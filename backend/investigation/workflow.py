"""
Investigation LangGraph workflow.

Graph topology:
  START
    → classify          (heuristic-only: greetings get instant answer, no LLM/DB)
        ↓ GREETING      → synthesize (instant canned response)
        ↓ NOT GREETING
    → retrieve          (HybridRetriever: Neo4j + ChromaDB context)
    → plan              (Orchestrator LLM: decides DIRECT or FULL, now has DB context)
        ↓ DIRECT        → synthesize (orchestrator answers from retrieved data)
        ↓ FULL
    → graph_agent   ┐   (parallel fan-out)
    → incident_agent├   (parallel fan-out)
    → risk_agent    ┘   (parallel fan-out)
    → synthesize        (fan-in barrier)
    → END

Each node:
  - receives the full InvestigationState
  - returns a partial state dict (only the keys it updates)
  - appends its completion step to `steps` (Annotated list reducer)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx
from langgraph.graph import StateGraph, START, END

from backend.investigation.state import InvestigationState
from backend.investigation.prompts import (
    ORCHESTRATOR_PLAN_PROMPT,
    GRAPH_AGENT_PROMPT,
    INCIDENT_AGENT_PROMPT,
    RISK_AGENT_PROMPT,
    ORCHESTRATOR_SYNTHESIZE_PROMPT,
)
from retrieval.retrieval.hybrid_retriever import get_retriever
from retrieval.config import settings as retrieval_settings

log = logging.getLogger(__name__)

# ── Model assignments ─────────────────────────────────────────────────────────

AGENT_MODELS: dict[str, str] = {
    "orchestrator": "llama3.1:8b",
    "graph":        "qwen2.5:7b",
    "incident":     "llama3.1:8b",
    # qwen2.5:7b is faster than gemma3:12b and produces cleaner structured output
    "risk":         "qwen2.5:7b",
    # JSON synthesis needs a model that reliably follows strict schema
    "synthesize":   "qwen2.5:7b",
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── InvestigationWorkflow ─────────────────────────────────────────────────────

class InvestigationWorkflow:
    """
    LangGraph-powered multi-agent investigation engine.

    Create once per process and reuse:
        workflow = InvestigationWorkflow()
        async for event in workflow.stream(query):
            ...
    """

    def __init__(self) -> None:
        self._ollama = retrieval_settings.ollama_host.rstrip("/")
        self._retriever = get_retriever()
        self._graph = self._compile()

    # ── Ollama helper ─────────────────────────────────────────────────────────

    async def _chat(
        self,
        model: str,
        system: str,
        user: str,
        timeout: float = 120.0,
        num_predict: int = 600,
        temperature: float = 0.1,
    ) -> str:
        """Single non-streaming Ollama /api/chat call."""
        payload = {
            "model":  model,
            "stream": False,
            "options": {
                "num_predict": num_predict,   # hard cap on tokens generated
                "temperature": temperature,
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self._ollama}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")

    # ── Node: classify (heuristic-only, no LLM, no DB) ─────────────────────

    # Keywords that strongly suggest a technical investigation is needed
    _TECH_KEYWORDS = (
        "incident", "outage", "error", "failure", "deploy", "service", "latency",
        "crash", "alert", "spike", "ticket", "jira", "commit", "rollback",
        "database", "cpu", "memory", "timeout", "nexus", "api", "pod", "k8s",
        "kubernetes", "dependency", "downstream", "upstream", "team",
    )

    def _is_greeting(self, query: str) -> tuple[bool, str]:
        """Returns (True, answer) only for unambiguous greetings — nothing else."""
        q = query.strip().lower().rstrip("!?.")
        greetings = {
            "hello": "Hello! I'm the NexusIQ Investigation AI. Ask me about incidents, service outages, deployments, or any technical investigation.",
            "hi": "Hi there! How can I help with your investigation today?",
            "hey": "Hey! What would you like to investigate?",
            "thanks": "You're welcome! Let me know if you have more questions.",
            "thank you": "You're welcome! Anything else I can help investigate?",
            "ok": "Got it. What else would you like to know?",
            "okay": "Understood. What else can I help with?",
            "bye": "Goodbye! Come back if you need another investigation.",
            "who are you": "I'm NexusIQ, an AI investigation engine that correlates incidents, deployments, and service topology to debug production issues.",
            "what can you do": "I can investigate incidents, correlate deployments with outages, analyze service blast radius, and trace root causes across your engineering systems.",
            "what is nexusiq": "NexusIQ is a multi-agent investigation platform using Graph RAG (Neo4j + ChromaDB) to correlate incidents, code changes, and service dependencies.",
        }
        for key, answer in greetings.items():
            if q == key or q.startswith(key + " ") or q.endswith(" " + key):
                return True, answer
        return False, ""

    async def _classify(self, state: InvestigationState) -> dict:
        """Fast heuristic node — no LLM, no DB. Only handles greetings."""
        is_greeting, answer = self._is_greeting(state["query"])
        if is_greeting:
            log.info("[classify] greeting detected — skipping retrieval and agents")
            return {
                "decision":      "direct",
                "direct_answer": answer,
                "plan":          "Greeting — no investigation needed",
                "steps": [_step("orchestrator", "completed", "Direct response — no investigation needed")],
            }
        # Everything else: proceed to retrieve → plan
        return {"decision": "full", "direct_answer": "", "plan": ""}

    # ── Node: retrieve ────────────────────────────────────────────────────────

    async def _retrieve(self, state: InvestigationState) -> dict:
        query = state["query"]
        log.info("[retrieve] %s", query[:80])
        try:
            fused = await self._retriever.query(query, top_k=6)
            return {
                "retrieved_context": fused.context,
                "entities":          fused.entities,
                "sources":           fused.sources,
                "steps": [_step("retrieve", "completed",
                    f"Retrieved {len(fused.sources)} sources from Neo4j + ChromaDB")],
            }
        except Exception as exc:
            log.warning("[retrieve] %s", exc)
            return {
                "retrieved_context": "Context retrieval unavailable.",
                "entities":          {},
                "sources":           [],
                "steps": [_step("retrieve", "error", str(exc))],
            }

    # ── Node: plan (runs after retrieve, so LLM has DB context) ──────────────

    async def _plan(self, state: InvestigationState) -> dict:
        log.info("[plan] formulating investigation plan")
        history_text = ""
        if state.get("history"):
            turns = state["history"][-6:]
            history_text = "\n".join(
                f"{t['role'].upper()}: {t['content'][:300]}" for t in turns
            )
        user_msg = (
            f"CONVERSATION HISTORY:\n{history_text or '(none)'}\n\n"
            f"CURRENT QUERY: {state['query']}\n\n"
            f"DETECTED ENTITIES: {', '.join(list(state['entities'].keys())[:10]) or 'none'}\n\n"
            f"CONTEXT PREVIEW:\n{state['retrieved_context'][:1200]}"
        )
        try:
            raw = await self._chat(
                AGENT_MODELS["orchestrator"], ORCHESTRATOR_PLAN_PROMPT, user_msg,
                timeout=60.0, num_predict=400, temperature=0.1,
            )
            decision = "full"
            direct_answer = ""
            for line in raw.splitlines():
                if line.startswith("DECISION:"):
                    decision = "direct" if "DIRECT" in line.upper() else "full"
                elif line.startswith("DIRECT_ANSWER:"):
                    direct_answer = line.split(":", 1)[1].strip()
            log.info("[plan] decision=%s", decision)
            return {
                "plan":          raw,
                "decision":      decision,
                "direct_answer": direct_answer,
                "steps": [_step("orchestrator", "completed",
                    f"Decision: {decision.upper()} — plan formulated")],
            }
        except Exception as exc:
            log.warning("[plan] %s", exc)
            return {
                "plan":          f"Direct investigation of: {state['query']}",
                "decision":      "full",
                "direct_answer": "",
                "steps": [_step("orchestrator", "error", f"Planning failed: {exc}")],
            }

    # ── Node: graph agent ─────────────────────────────────────────────────────

    async def _graph_agent(self, state: InvestigationState) -> dict:
        log.info("[graph_agent] analyzing service topology")
        user_msg = _agent_prompt(state)
        try:
            analysis = await self._chat(
                AGENT_MODELS["graph"], GRAPH_AGENT_PROMPT, user_msg,
                timeout=90.0, num_predict=500,
            )
            return {
                "graph_analysis": analysis,
                "steps": [_step("graph_agent", "completed",
                    "Service dependency and topology analysis complete")],
            }
        except Exception as exc:
            log.warning("[graph_agent] %s", exc)
            return {
                "graph_analysis": f"Graph analysis unavailable: {exc}",
                "steps": [_step("graph_agent", "error", str(exc))],
            }

    # ── Node: incident agent ──────────────────────────────────────────────────

    async def _incident_agent(self, state: InvestigationState) -> dict:
        log.info("[incident_agent] reconstructing incident timeline")
        user_msg = _agent_prompt(state)
        try:
            analysis = await self._chat(
                AGENT_MODELS["incident"], INCIDENT_AGENT_PROMPT, user_msg,
                timeout=90.0, num_predict=500,
            )
            return {
                "incident_analysis": analysis,
                "steps": [_step("incident_agent", "completed",
                    "Incident timeline and deployment analysis complete")],
            }
        except Exception as exc:
            log.warning("[incident_agent] %s", exc)
            return {
                "incident_analysis": f"Incident analysis unavailable: {exc}",
                "steps": [_step("incident_agent", "error", str(exc))],
            }

    # ── Node: risk agent ──────────────────────────────────────────────────────

    async def _risk_agent(self, state: InvestigationState) -> dict:
        log.info("[risk_agent] assessing cascading failure risk")
        user_msg = _agent_prompt(state)
        try:
            analysis = await self._chat(
                AGENT_MODELS["risk"], RISK_AGENT_PROMPT, user_msg,
                timeout=90.0, num_predict=500,
            )
            return {
                "risk_analysis": analysis,
                "steps": [_step("risk_agent", "completed",
                    "Cascading failure and risk assessment complete")],
            }
        except Exception as exc:
            log.warning("[risk_agent] %s", exc)
            return {
                "risk_analysis": f"Risk analysis unavailable: {exc}",
                "steps": [_step("risk_agent", "error", str(exc))],
            }

    # ── Node: synthesize ──────────────────────────────────────────────────────

    async def _synthesize(self, state: InvestigationState) -> dict:
        log.info("[synthesize] generating final investigation report")

        # ── Fast path: orchestrator answered directly ─────────────────────────
        if state.get("decision") == "direct" and state.get("direct_answer"):
            report = {
                "query":             state["query"],
                "risk_level":        "LOW",
                "summary":           state["direct_answer"],
                "synthesis":         state["direct_answer"],
                "graph_analysis":    "",
                "incident_analysis": "",
                "risk_analysis":     "",
                "affected_services": [],
                "timeline":          [],
                "evidence":          [],
                "recommendations":   [],
                "sources":           state["sources"],
            }
            return {
                "report": report,
                "steps":  [_step("orchestrator", "completed", "Direct answer — no specialist agents needed")],
            }

        # ── Full path: synthesize all three agent analyses ────────────────────
        user_msg = (
            f"ORIGINAL QUERY: {state['query']}\n\n"
            f"INVESTIGATION PLAN:\n{state['plan'][:400]}\n\n"
            f"GRAPH ANALYSIS:\n{state['graph_analysis'][:700]}\n\n"
            f"INCIDENT ANALYSIS:\n{state['incident_analysis'][:700]}\n\n"
            f"RISK ANALYSIS:\n{state['risk_analysis'][:700]}\n\n"
            f"KEY CONTEXT:\n{state['retrieved_context'][:1500]}"
        )
        try:
            raw = await self._chat(
                AGENT_MODELS["synthesize"], ORCHESTRATOR_SYNTHESIZE_PROMPT, user_msg,
                timeout=120.0, num_predict=1200, temperature=0.05,
            )
            report = _parse_json(raw)
            report.update({
                "query":            state["query"],
                "graph_analysis":   state["graph_analysis"],
                "incident_analysis":state["incident_analysis"],
                "risk_analysis":    state["risk_analysis"],
                "sources":          state["sources"],
            })
            return {
                "report": report,
                "steps": [_step("orchestrator", "completed", "Investigation report synthesised")],
            }
        except Exception as exc:
            log.error("[synthesize] %s", exc)
            fallback = _fallback_report(state, str(exc))
            return {
                "report": fallback,
                "error":  str(exc),
                "steps":  [_step("orchestrator", "error", f"Synthesis error: {exc}")],
            }

    # ── LangGraph compilation ─────────────────────────────────────────────────

    def _route_after_classify(self, state: InvestigationState) -> list[str]:
        """After heuristic classify: greetings go straight to synthesize, rest retrieve."""
        if state.get("decision") == "direct":
            return ["synthesize"]
        return ["retrieve"]

    def _route_after_plan(self, state: InvestigationState) -> list[str]:
        """After plan (which has DB context): DIRECT → synthesize, FULL → agents."""
        if state.get("decision") == "direct":
            return ["synthesize"]
        return ["graph_agent", "incident_agent", "risk_agent"]

    def _compile(self):
        wf = StateGraph(InvestigationState)

        wf.add_node("classify",      self._classify)
        wf.add_node("retrieve",       self._retrieve)
        wf.add_node("plan",           self._plan)
        wf.add_node("graph_agent",    self._graph_agent)
        wf.add_node("incident_agent", self._incident_agent)
        wf.add_node("risk_agent",     self._risk_agent)
        wf.add_node("synthesize",     self._synthesize)

        # classify: instant heuristic check (no LLM, no DB)
        wf.add_edge(START, "classify")
        wf.add_conditional_edges(
            "classify",
            self._route_after_classify,
            ["retrieve", "synthesize"],
        )

        # retrieve → plan (plan LLM now has retrieved context to answer DIRECT or FULL)
        wf.add_edge("retrieve", "plan")
        wf.add_conditional_edges(
            "plan",
            self._route_after_plan,
            ["graph_agent", "incident_agent", "risk_agent", "synthesize"],
        )

        # Fan-in: all three specialists converge on synthesize
        wf.add_edge("graph_agent",    "synthesize")
        wf.add_edge("incident_agent", "synthesize")
        wf.add_edge("risk_agent",     "synthesize")

        wf.add_edge("synthesize", END)

        return wf.compile()

    # ── Public streaming interface ────────────────────────────────────────────

    async def stream(self, query: str, history: list[dict] | None = None) -> AsyncIterator[dict]:
        """
        Execute the full investigation and yield SSE-ready event dicts.

        history: list of {"role": "user"|"assistant", "content": str} from prior turns.
        """
        initial: InvestigationState = {
            "query":              query,
            "history":            history or [],
            "retrieved_context":  "",
            "entities":           {},
            "sources":            [],
            "plan":               "",
            "decision":           "full",
            "direct_answer":      "",
            "graph_analysis":     "",
            "incident_analysis":  "",
            "risk_analysis":      "",
            "steps":              [],
            "report":             None,
            "error":              None,
        }

        yield {"type": "investigation-start", "data": {
            "query":   query,
            "message": "Investigation initiated — activating agent pipeline",
        }}

        async for chunk in self._graph.astream(initial, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                # Re-emit each step the node recorded
                for step in node_output.get("steps", []):
                    yield {"type": "step-update", "data": {
                        **step,
                        "node": node_name,
                    }}

                # When synthesize finishes, emit the complete report
                if node_name == "synthesize" and node_output.get("report"):
                    yield {"type": "investigation-complete", "data": {
                        "report": node_output["report"],
                    }}


# ── Helper functions ──────────────────────────────────────────────────────────

def _step(agent: str, status: str, summary: str) -> dict:
    return {"agent": agent, "status": status, "summary": summary, "timestamp": _ts()}


# Context budget per specialist agent — enough to capture key facts without overloading
_AGENT_CONTEXT_CHARS = 2500


def _agent_prompt(state: InvestigationState) -> str:
    """Standard user message for all three specialist agents."""
    return (
        f"INVESTIGATION PLAN:\n{state['plan'][:350]}\n\n"
        f"RETRIEVED CONTEXT:\n{state['retrieved_context'][:_AGENT_CONTEXT_CHARS]}\n\n"
        f"QUERY: {state['query']}"
    )


def _parse_json(raw: str) -> dict:
    """Extract JSON from Ollama's response, tolerating markdown fences and prose."""
    raw = raw.strip()

    # 1. Strip ```json ... ``` or ``` ... ``` fences
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()

    # 2. Find the outermost matching { ... } block
    start = raw.find("{")
    if start < 0:
        raise ValueError("No JSON object found in response")

    depth, end = 0, -1
    for i, ch in enumerate(raw[start:], start):
        if ch == "{":   depth += 1
        elif ch == "}": depth -= 1
        if depth == 0:
            end = i + 1
            break

    if end < 0:
        raise ValueError("Unmatched braces in JSON response")

    candidate = raw[start:end]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Last resort: let Python's json try to fix minor issues by stripping
        # common LLM artifacts (trailing commas, unquoted keys)
        cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)   # trailing commas
        return json.loads(cleaned)


def _fallback_report(state: InvestigationState, error: str) -> dict:
    return {
        "query":             state["query"],
        "risk_level":        "UNKNOWN",
        "summary":           "Investigation complete — synthesis unavailable.",
        "synthesis":         (
            f"**Graph analysis**\n{state['graph_analysis'][:800]}\n\n"
            f"**Incident analysis**\n{state['incident_analysis'][:800]}\n\n"
            f"**Risk analysis**\n{state['risk_analysis'][:800]}"
        ),
        "graph_analysis":    state["graph_analysis"],
        "incident_analysis": state["incident_analysis"],
        "risk_analysis":     state["risk_analysis"],
        "affected_services": [],
        "timeline":          [],
        "evidence":          [],
        "recommendations":   [],
        "sources":           state["sources"],
    }


# ── Module singleton ──────────────────────────────────────────────────────────

_workflow: InvestigationWorkflow | None = None


def get_workflow() -> InvestigationWorkflow:
    global _workflow
    if _workflow is None:
        _workflow = InvestigationWorkflow()
    return _workflow

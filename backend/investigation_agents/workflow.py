"""
Evidence-driven GraphRAG investigation workflow.

Architecture (query-analyzer-first, graph-aware):

  START
    -> query_analyzer    (qwen2.5:1.5b: lookup on Neo4j graph cache — NO extra DB call)
                          • reads from shared GraphCache populated by /graph/visualization
                          • query decomposition, entity extraction, intent classification
                          • graph lookup planning + retrieval routing
        | conversational (routing=NO_RETRIEVAL, no graph match) -> synthesize
        | graph match OR retrieve needed                        -> shared_retrieve
    -> shared_retrieve   (SharedLightweightRetriever: 1 embedding + 1-hop graph, cached)
    -> evaluate          (EvidenceEvaluator: heuristic gate, NO LLM call)
        | DIRECT_RESPONSE -> synthesize (lightweight: context already sufficient)
        | PARTIAL        -> graph_agent + incident_agent + risk_agent (filtered slices)
        | DEEP           -> plan (LLM: only for complex RCA, enriched with graph insights)
                           -> graph_agent + incident_agent + risk_agent
    -> synthesize        (lightweight merge)
    -> END

Key design guarantees:
  - query_analyzer runs FIRST: reads shared GraphCache (populated by /graph/visualization — same Neo4j fetch)
  - graph_insights from the Neo4j cache flow into orchestrator planning
  - Shared retrieval runs EXACTLY ONCE per query
  - Embedding computation cached (1 hour TTL)
  - Graph results cached per entity (2 min TTL)
  - Context object cached per query (5 min TTL)
  - Agents receive FILTERED slices, not duplicated full context
  - Selective expanders fetch ONLY missing evidence
  - FAST queries never reach agents
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Any

import httpx
from langgraph.graph import StateGraph, START, END

from backend.investigation_agents.state import InvestigationState
from backend.investigation_agents.prompts import (
    QUERY_ANALYZER_PROMPT,
    ORCHESTRATOR_PLAN_PROMPT,
    GRAPH_AGENT_PROMPT,
    INCIDENT_AGENT_PROMPT,
    RISK_AGENT_PROMPT,
    ORCHESTRATOR_SYNTHESIZE_PROMPT,
)
from backend.investigation_agents.graph_inspector import get_graph_inspector
from backend.retrieval.shared_retriever import get_shared_retriever
from backend.investigation.shared_context import SharedInvestigationContext
from backend.investigation.evidence_evaluator import (
    get_evaluator,
    EvidenceDecision,
)
from backend.retrieval.context_expanders.graph_expander import get_graph_expander
from backend.retrieval.context_expanders.incident_expander import get_incident_expander
from backend.retrieval.context_expanders.risk_expander import get_risk_expander
from retrieval.config import settings as retrieval_settings

log = logging.getLogger(__name__)

# -- Model assignments ---------------------------------------------------------

AGENT_MODELS: dict[str, str] = {
    "query_analyzer": "qwen2.5:1.5b",
    "orchestrator":   "llama3.1:8b",
    "graph":          "qwen2.5:7b",
    "incident":       "llama3.1:8b",
    "risk":           "qwen2.5:7b",
    "synthesize":     "qwen2.5:7b",
}

# Token budgets
_FAST_SYNTHESIZE_TOKENS = 512    # DIRECT_RESPONSE path (conversational)
_AGENT_TOKENS           = 600    # per specialist agent
_PLAN_TOKENS            = 400    # orchestrator plan
_SYNTHESIZE_TOKENS      = 2000   # final synthesis — needs room for full narrative
_AGENT_CONTEXT_CHARS    = 2500   # context slice per agent

_FAST_SYSTEM_PROMPT = (
    "You are a NexusIQ investigator. Answer the query directly and concisely "
    "using only the provided context. Do not speculate beyond the evidence."
)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step(agent: str, status: str, summary: str) -> dict:
    return {"agent": agent, "status": status, "summary": summary, "timestamp": _ts()}


# -- InvestigationWorkflow ----------------------------------------------------

class InvestigationWorkflow:
    """
    Evidence-driven multi-agent investigation engine.

    Create once per process and reuse:
        workflow = InvestigationWorkflow()
        async for event in workflow.stream(query):
            ...
    """

    def __init__(self) -> None:
        self._ollama    = retrieval_settings.ollama_host.rstrip("/")
        self._retriever = get_shared_retriever()
        self._evaluator = get_evaluator()
        self._inspector = get_graph_inspector()
        self._graph     = self._compile()

    # -- Ollama helper ---------------------------------------------------------

    async def _chat(
        self,
        model: str,
        system: str,
        user: str,
        timeout: float = 120.0,
        num_predict: int = 400,
        temperature: float = 0.1,
    ) -> str:
        payload = {
            "model":  model,
            "stream": False,
            "options": {"num_predict": num_predict, "temperature": temperature},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self._ollama}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")

    # -- Node: query_analyzer --------------------------------------------------

    async def _query_analyze(self, state: InvestigationState) -> dict:
        """
        First node: qwen2.5:1.5b reads from the shared GraphCache (same data
        already fetched from Neo4j by /graph/visualization — zero extra DB calls)
        to perform query decomposition, entity extraction, intent classification,
        graph lookup planning, and retrieval routing.

        If the graph cache has relevant entities/relationships the insights are
        stored in state and forwarded to the orchestrator planning step.
        """
        query = state["query"]
        log.info("[query_analyzer] analyzing query against visualization graph")

        # Build conversation history for the LLM (pronoun/reference resolution)
        history: list[dict] = state.get("history") or []
        history_text = ""
        if history:
            history_text = "\n".join(
                f"{t['role'].upper()}: {str(t.get('content', ''))[:300]}"
                for t in history[-6:]
            )

        # 1. Fast keyword lookup on the CURRENT query only (no history injection)
        #    History is given to the LLM below — it resolves "it"/"that"/etc. itself.
        keywords = self._inspector.extract_keywords(query)
        log.info("[query_analyzer] keywords=%s", keywords)

        # 2. In-memory graph lookup (no DB call) ───────────────────────────────
        lookup = self._inspector.lookup(keywords)
        graph_ctx_text = self._inspector.format_for_llm(lookup)
        has_match = lookup["matched"]

        log.info(
            "[query_analyzer] graph_match=%s entities=%d rels=%d",
            has_match, len(lookup["entities"]), len(lookup["relationships"]),
        )

        # 3. LLM analysis (qwen2.5:1.5b) ───────────────────────────────────────
        user_msg = (
            f"CONVERSATION HISTORY:\n{history_text or '(none)'}\n\n"
            f"CURRENT QUERY: {query}\n\n"
            f"{graph_ctx_text}"
        )
        try:
            raw = await self._chat(
                AGENT_MODELS["query_analyzer"],
                QUERY_ANALYZER_PROMPT,
                user_msg,
                timeout=45.0,
                num_predict=250,
                temperature=0.0,
            )

            # Ground-truth entities from the lookup — independent of the LLM.
            # The small model (1.5b) often returns NONE even when matches exist,
            # so we always trust the keyword-lookup result first.
            lookup_entity_titles = [
                str(e.get("title", "")) for e in lookup["entities"] if e.get("title")
            ]

            # Parse structured LLM output
            intent   = "GENERAL"
            llm_entities: list[str] = []
            routing  = "NO_RETRIEVAL" if not has_match else "GRAPH_SUFFICIENT"
            insights = "NONE"

            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("INTENT:"):
                    val = line.split(":", 1)[1].strip().upper()
                    if val in {"TOPOLOGY", "INCIDENT", "RISK", "PERFORMANCE", "GENERAL"}:
                        intent = val
                elif line.startswith("ENTITIES:"):
                    raw_ents = line.split(":", 1)[1].strip()
                    if raw_ents.upper() != "NONE":
                        llm_entities = [e.strip() for e in raw_ents.split(",") if e.strip()]
                elif line.startswith("ROUTING:"):
                    val = line.split(":", 1)[1].strip().upper()
                    if val in {"GRAPH_SUFFICIENT", "RETRIEVE_MORE", "NO_RETRIEVAL"}:
                        # Only allow the model to *upgrade* routing (ask for more),
                        # never downgrade a confirmed graph match to NO_RETRIEVAL.
                        if has_match and val == "NO_RETRIEVAL":
                            pass  # ignore — we have a real match
                        else:
                            routing = val
                elif line.startswith("GRAPH_INSIGHTS:"):
                    insights = line.split(":", 1)[1].strip()

            # Merge: lookup titles are authoritative; LLM extras appended if new
            lookup_set = {t.lower() for t in lookup_entity_titles}
            extra = [e for e in llm_entities if e.lower() not in lookup_set]
            entities_out = lookup_entity_titles + extra

            # ── Investigation-intent safety-net ────────────────────────────────
            # Queries that contain action/topology words or a named service/agent
            # should always be routed to retrieval, even if the small LLM
            # misclassifies them as conversational.
            _INVESTIGATION_WORDS = {
                # incidents / failures
                "incident", "incidents", "investigate", "investigation",
                "outage", "failure", "failures", "issue", "issues",
                "problem", "problems", "error", "errors", "crash", "crashes",
                "alert", "alerts", "fix", "solve", "root cause", "debug",
                "diagnose", "analyse", "analyze",
                # topology / ownership
                "owns", "own", "owner", "owned", "ownership",
                "team", "teams", "responsible", "manages", "managed",
                "depends", "dependency", "dependencies", "upstream", "downstream",
                "topology", "architecture", "graph", "connected", "connects",
                "calls", "calls-into", "service", "services",
                # general investigation verbs
                "why", "how", "point",
            }
            import re as _re
            _query_words = set(_re.findall(r'\w+', query.lower()))
            # Also flag queries that mention a specific named service/agent by suffix
            _has_named_service = bool(_re.search(r'\b\w+-(service|agent|api|worker|sidecar)\b', query, _re.I))
            has_investigation_intent = bool(_query_words & _INVESTIGATION_WORDS) or _has_named_service

            if routing == "NO_RETRIEVAL" and has_investigation_intent:
                routing = "RETRIEVE_MORE"
                log.info(
                    "[query_analyzer] routing upgraded NO_RETRIEVAL→RETRIEVE_MORE "
                    "due to investigation-intent keywords or named service in query"
                )

            # Secondary lookup: if the current query had no keyword match but the
            # LLM resolved entity names from history (e.g. "it" → "ADAS project"),
            # run a second graph lookup with those LLM-extracted names.
            # Also try extracting entities from history text directly when the
            # query uses pronouns ("this", "it", "that") and has no entity match.
            if not has_match and routing != "NO_RETRIEVAL":
                candidate_text = " ".join(llm_entities)
                # Fallback: mine entities from recent history if LLM found none
                if not llm_entities and history_text:
                    candidate_text = history_text
                if candidate_text.strip():
                    llm_kw = self._inspector.extract_keywords(candidate_text)
                    if llm_kw:
                        secondary = self._inspector.lookup(llm_kw)
                        if secondary["matched"]:
                            lookup        = secondary
                            graph_ctx_text = self._inspector.format_for_llm(secondary)
                            has_match     = True
                            lookup_entity_titles = [
                                str(e.get("title", "")) for e in secondary["entities"] if e.get("title")
                            ]
                            entities_out = lookup_entity_titles + extra
                            log.info("[query_analyzer] secondary lookup matched %d entities", len(lookup_entity_titles))

            # Build final insights block
            if has_match and insights and insights.upper() != "NONE":
                full_insights = f"{insights}\n\n{graph_ctx_text}"
            elif has_match:
                full_insights = graph_ctx_text
            else:
                full_insights = ""

            # Build routing state for downstream nodes.
            # Only treat as conversational for genuine greetings/small-talk —
            # never when investigation-intent words are present in the query.
            is_conversational = (
                routing == "NO_RETRIEVAL"
                and not has_match
                and not has_investigation_intent
            )
            decision           = "direct" if is_conversational else "full"
            evidence_decision  = "DIRECT_RESPONSE" if is_conversational else "DEEP"
            investigation_depth = "FAST" if is_conversational else "DEEP"

            log.info(
                "[query_analyzer] intent=%s routing=%s entities=%s conversational=%s",
                intent, routing, entities_out, is_conversational,
            )
            return {
                "query_intent":        intent,
                "query_entities":      entities_out,
                "graph_insights":      full_insights,
                "has_graph_match":     has_match,
                "decision":            decision,
                "evidence_decision":   evidence_decision,
                "investigation_depth": investigation_depth,
                "steps": [_step("query_analyzer", "completed",
                    f"Graph-aware analysis: intent={intent} routing={routing} "
                    f"entities={len(entities_out)} graph_match={has_match}")],
            }

        except Exception as exc:
            log.warning("[query_analyzer] LLM call failed: %s", exc)
            fallback_entities = [
                str(e.get("title", "")) for e in lookup["entities"] if e.get("title")
            ]
            return {
                "query_intent":        "GENERAL",
                "query_entities":      fallback_entities,
                "graph_insights":      graph_ctx_text if has_match else "",
                "has_graph_match":     has_match,
                "decision":            "full" if has_match else "direct",
                "evidence_decision":   "DEEP" if has_match else "DIRECT_RESPONSE",
                "investigation_depth": "DEEP" if has_match else "FAST",
                "steps": [_step("query_analyzer", "error", str(exc))],
            }

    # -- Node: shared_retrieve -------------------------------------------------

    async def _shared_retrieve(self, state: InvestigationState) -> dict:
        """
        Run the shared lightweight retrieval pass -- ONCE per query.

        Optimizations vs old HybridRetriever:
          ChromaDB: top_k=4 (was 10), Neo4j: depth=1 (was 3), TTL cache.
        """
        query = state["query"]
        log.info("[shared_retrieve] %s", query[:80])
        try:
            ctx: SharedInvestigationContext = await self._retriever.retrieve(query)
            return {
                "shared_ctx":        ctx,
                "retrieved_context": ctx.formatted_context,
                "entities":          ctx.entities,
                "sources":           ctx.sources,
                "steps": [_step("retrieve", "completed",
                    f"Shared retrieval -- {ctx.quick_summary()}")],
            }
        except Exception as exc:
            log.warning("[shared_retrieve] %s", exc)
            from backend.investigation.shared_context import (
                SharedInvestigationContext as SIC,
                RetrievalSignal, SignalStrength, InvestigationDepth,
            )
            empty_ctx = SIC(
                query=query, entities={}, retrieved_documents=[],
                graph_neighbors={}, incidents=[], deployments=[],
                formatted_context="Context retrieval unavailable.", sources=[],
                signal=RetrievalSignal(
                    signal_strength=SignalStrength.LOW, evidence_density=0.0,
                    recommended_depth=InvestigationDepth.DEEP,
                ),
            )
            return {
                "shared_ctx":        empty_ctx,
                "retrieved_context": "Context retrieval unavailable.",
                "entities":          {},
                "sources":           [],
                "steps": [_step("retrieve", "error", str(exc))],
            }

    # -- Node: evaluate --------------------------------------------------------

    async def _evaluate(self, state: InvestigationState) -> dict:
        """
        Heuristic evidence evaluation -- zero LLM calls, runs in microseconds.

        DIRECT_RESPONSE: skip all agents (saves 3-4 LLM calls)
        PARTIAL:         1-2 targeted agents, skip plan LLM
        DEEP:            full orchestration via plan node
        """
        ctx: SharedInvestigationContext | None = state.get("shared_ctx")
        if ctx is None:
            log.warning("[evaluate] no shared_ctx -- defaulting to DEEP")
            return {
                "evidence_decision":   "DEEP",
                "investigation_depth": "DEEP",
                "active_agents":       ["graph", "incident", "risk"],
            }

        evaluation = self._evaluator.evaluate(ctx)
        log.info(
            "[evaluate] decision=%s agents=%s confidence=%.2f -- %s",
            evaluation.decision.value, evaluation.recommended_agents,
            evaluation.confidence, evaluation.reasoning,
        )

        if evaluation.decision == EvidenceDecision.DIRECT_RESPONSE:
            depth = "FAST"; decision = "direct"
        elif evaluation.decision == EvidenceDecision.PARTIAL:
            depth = "STANDARD"; decision = "full"
        else:
            depth = "DEEP"; decision = "full"

        return {
            "evidence_decision":   evaluation.decision.value,
            "investigation_depth": depth,
            "decision":            decision,
            "active_agents":       evaluation.recommended_agents or ["graph", "incident", "risk"],
            "steps": [_step("orchestrator", "completed",
                f"Evidence: {evaluation.decision.value} ({evaluation.reasoning[:80]})")],
        }

    # -- Node: plan ------------------------------------------------------------

    async def _plan(self, state: InvestigationState) -> dict:
        """LLM planning -- ONLY for DEEP path (complex RCA). Uses pre-retrieved context."""
        log.info("[plan] formulating deep investigation plan")
        ctx: SharedInvestigationContext | None = state.get("shared_ctx")
        context_preview = (
            ctx.formatted_context[:900] if ctx
            else state.get("retrieved_context", "")[:900]
        )
        entity_summary = ", ".join(
            f"{k}:{v}" for k, v in (ctx.entities if ctx else {}).items() if v
        )[:150] or "none"

        history_text = ""
        if state.get("history"):
            turns = state["history"][-4:]
            history_text = "\n".join(
                f"{t['role'].upper()}: {t['content'][:200]}" for t in turns
            )
        # Include graph insights from query_analyzer if available
        graph_insights = state.get("graph_insights", "")
        graph_insights_section = (
            f"\nVISUALIZATION GRAPH INSIGHTS:\n{graph_insights[:600]}\n"
            if graph_insights else ""
        )
        user_msg = (
            f"CONVERSATION HISTORY:\n{history_text or '(none)'}\n\n"
            f"CURRENT QUERY: {state['query']}\n"
            f"QUERY INTENT: {state.get('query_intent', 'GENERAL')}\n"
            f"KEY ENTITIES (from graph): {', '.join(state.get('query_entities', [])) or 'none'}\n"
            f"{graph_insights_section}\n"
            f"DETECTED ENTITIES: {entity_summary}\n\n"
            f"CONTEXT PREVIEW:\n{context_preview}"
        )
        try:
            raw = await self._chat(
                AGENT_MODELS["orchestrator"], ORCHESTRATOR_PLAN_PROMPT, user_msg,
                timeout=60.0, num_predict=_PLAN_TOKENS, temperature=0.1,
            )
            active_agents = state.get("active_agents", ["graph", "incident", "risk"])
            for line in raw.splitlines():
                if line.startswith("ACTIVE_AGENTS:"):
                    raw_agents = line.split(":", 1)[1].strip().lower()
                    parsed = [a.strip() for a in raw_agents.split(",") if a.strip()]
                    valid  = [a for a in parsed if a in {"graph", "incident", "risk"}]
                    if valid:
                        active_agents = valid
            log.info("[plan] active_agents=%s", active_agents)
            return {
                "plan":          raw,
                "active_agents": active_agents,
                "steps": [_step("orchestrator", "completed",
                    f"Plan -- agents: {', '.join(active_agents)}")],
            }
        except Exception as exc:
            log.warning("[plan] %s", exc)
            return {
                "plan":          f"Direct investigation of: {state['query']}",
                "active_agents": state.get("active_agents", ["graph", "incident", "risk"]),
                "steps": [_step("orchestrator", "error", f"Planning failed: {exc}")],
            }

    # -- Node: graph_agent -----------------------------------------------------

    async def _graph_agent(self, state: InvestigationState) -> dict:
        if "graph" not in state.get("active_agents", []):
            log.info("[graph_agent] skipped")
            return {"graph_analysis": "", "steps": []}

        ctx: SharedInvestigationContext | None = state.get("shared_ctx")
        log.info("[graph_agent] analyzing service topology")

        if ctx and state.get("investigation_depth") in ("STANDARD", "DEEP"):
            try:
                await get_graph_expander().expand(ctx)
            except Exception as exc:
                log.warning("[graph_agent] expansion failed: %s", exc)

        context_slice = (
            ctx.context_for_agent("graph", max_chars=_AGENT_CONTEXT_CHARS)
            if ctx else state.get("retrieved_context", "")[:_AGENT_CONTEXT_CHARS]
        )
        user_msg = (
            f"INVESTIGATION PLAN:\n{state.get('plan', '')[:250]}\n\n"
            f"RETRIEVED CONTEXT:\n{context_slice}\n\n"
            f"QUERY: {state['query']}"
        )
        try:
            analysis = await self._chat(
                AGENT_MODELS["graph"], GRAPH_AGENT_PROMPT, user_msg,
                timeout=90.0, num_predict=_AGENT_TOKENS,
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

    # -- Node: incident_agent --------------------------------------------------

    async def _incident_agent(self, state: InvestigationState) -> dict:
        if "incident" not in state.get("active_agents", []):
            log.info("[incident_agent] skipped")
            return {"incident_analysis": "", "steps": []}

        ctx: SharedInvestigationContext | None = state.get("shared_ctx")
        log.info("[incident_agent] reconstructing incident timeline")

        if ctx:
            try:
                await get_incident_expander().expand(ctx)
            except Exception as exc:
                log.warning("[incident_agent] expansion failed: %s", exc)

        context_slice = (
            ctx.context_for_agent("incident", max_chars=_AGENT_CONTEXT_CHARS)
            if ctx else state.get("retrieved_context", "")[:_AGENT_CONTEXT_CHARS]
        )
        user_msg = (
            f"INVESTIGATION PLAN:\n{state.get('plan', '')[:250]}\n\n"
            f"RETRIEVED CONTEXT:\n{context_slice}\n\n"
            f"QUERY: {state['query']}"
        )
        try:
            analysis = await self._chat(
                AGENT_MODELS["incident"], INCIDENT_AGENT_PROMPT, user_msg,
                timeout=90.0, num_predict=_AGENT_TOKENS,
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

    # -- Node: risk_agent ------------------------------------------------------

    async def _risk_agent(self, state: InvestigationState) -> dict:
        if "risk" not in state.get("active_agents", []):
            log.info("[risk_agent] skipped")
            return {"risk_analysis": "", "steps": []}

        ctx: SharedInvestigationContext | None = state.get("shared_ctx")
        log.info("[risk_agent] assessing cascading failure risk")

        if ctx:
            try:
                await get_risk_expander().expand(ctx)
            except Exception as exc:
                log.warning("[risk_agent] expansion failed: %s", exc)

        context_slice = (
            ctx.context_for_agent("risk", max_chars=_AGENT_CONTEXT_CHARS)
            if ctx else state.get("retrieved_context", "")[:_AGENT_CONTEXT_CHARS]
        )
        user_msg = (
            f"INVESTIGATION PLAN:\n{state.get('plan', '')[:250]}\n\n"
            f"RETRIEVED CONTEXT:\n{context_slice}\n\n"
            f"QUERY: {state['query']}"
        )
        try:
            analysis = await self._chat(
                AGENT_MODELS["risk"], RISK_AGENT_PROMPT, user_msg,
                timeout=90.0, num_predict=_AGENT_TOKENS,
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

    # -- Node: synthesize ------------------------------------------------------

    async def _synthesize(self, state: InvestigationState) -> dict:
        log.info("[synthesize] generating final report")

        # FAST path: evidence evaluator (or query_analyzer) found context is sufficient
        if state.get("evidence_decision") == "DIRECT_RESPONSE":
            ctx: SharedInvestigationContext | None = state.get("shared_ctx")
            retrieved_text = (
                ctx.formatted_context[:1200] if ctx
                else state.get("retrieved_context", "")[:1200]
            )
            graph_insights = state.get("graph_insights", "")
            # Always prepend graph_insights when the graph cache had a match —
            # retrieved docs may not contain the entity's profile data.
            if graph_insights and state.get("has_graph_match"):
                context_text = (
                    f"GRAPH KNOWLEDGE BASE:\n{graph_insights[:800]}\n\n"
                    f"RETRIEVED DOCUMENTS:\n{retrieved_text}"
                ).strip()
            else:
                context_text = retrieved_text or graph_insights[:1000]

            is_conversational = state.get("decision") == "direct" and not context_text.strip()

            # Guard: if the query names a specific service/agent or uses topology
            # words but we have no context, it means retrieval found nothing —
            # do NOT hallucinate. Tell the user we have no data.
            import re as _re2
            _no_context_factual = (
                not context_text.strip()
                and not is_conversational
            )
            if _no_context_factual:
                return {
                    "report": {
                        "query":             state["query"],
                        "risk_level":        "UNKNOWN",
                        "summary":           "No information found in the knowledge base for this query.",
                        "synthesis":         (
                            f"I couldn't find any data about **{state['query'].strip()}** "
                            "in the graph or retrieved documents.\n\n"
                            "This may mean the service or entity is not yet indexed. "
                            "Try rephrasing with the exact service name, or check that "
                            "the knowledge base has been populated."
                        ),
                        "graph_analysis":    "",
                        "incident_analysis": "",
                        "risk_analysis":     "",
                        "affected_services": [],
                        "timeline":          [],
                        "evidence":          [],
                        "recommendations":   [],
                        "sources":           state.get("sources", []),
                    },
                    "steps": [_step("orchestrator", "completed",
                        "No data found in knowledge base for this query")],
                }
            # Build history snippet for both paths
            chat_history: list[dict] = state.get("history") or []
            history_snippet = ""
            if chat_history:
                history_snippet = "\n".join(
                    f"{t['role'].upper()}: {str(t.get('content', ''))[:400]}"
                    for t in chat_history[-6:]
                )
            if is_conversational:
                # Pure greeting / small-talk path — no investigation context.
                # DO NOT repeat the user's question or ask clarifying questions.
                # Respond briefly and invite the user to describe what to investigate.
                user_msg = (
                    f"CONVERSATION HISTORY:\n{history_snippet or '(none)'}\n\n"
                    f"USER: {state['query']}\n\n"
                    "You are the NexusIQ AI assistant for a system observability platform.\n"
                    "This is a greeting or casual message — respond briefly and warmly.\n"
                    "Do NOT repeat or paraphrase the user's message back to them.\n"
                    "Do NOT ask what they want to investigate — just let them know you're ready."
                )
            else:
                user_msg = (
                    f"CONVERSATION HISTORY:\n{history_snippet or '(none)'}\n\n"
                    f"QUERY: {state['query']}\n\n"
                    f"CONTEXT:\n{context_text}\n\n"
                    "Answer the query using the provided context and conversation history. "
                    "Prefer GRAPH KNOWLEDGE BASE information for entity/person details. "
                    "Be direct and factual."
                )
            try:
                answer = await self._chat(
                    AGENT_MODELS["orchestrator"], _FAST_SYSTEM_PROMPT, user_msg,
                    timeout=30.0, num_predict=_FAST_SYNTHESIZE_TOKENS, temperature=0.05,
                )
                return {
                    "report": {
                        "query":             state["query"],
                        "risk_level":        "LOW",
                        "summary":           answer,
                        "synthesis":         answer,
                        "graph_analysis":    "",
                        "incident_analysis": "",
                        "risk_analysis":     "",
                        "affected_services": [],
                        "timeline":          [],
                        "evidence":          [],
                        "recommendations":   [],
                        "sources":           state.get("sources", []),
                    },
                    "steps": [_step("orchestrator", "completed",
                        "Fast synthesis -- lightweight retrieval sufficient")],
                }
            except Exception as exc:
                log.warning("[synthesize] fast path failed: %s", exc)
                return {
                    "report": _fallback_report(state, str(exc)),
                    "error":  str(exc),
                    "steps":  [_step("orchestrator", "error", str(exc))],
                }

        # Full synthesis: merge agent outputs
        ctx = state.get("shared_ctx")
        key_context = (
            ctx.formatted_context[:700] if ctx
            else state.get("retrieved_context", "")[:700]
        )
        graph_insights = state.get("graph_insights", "")
        graph_kb_section = (
            f"GRAPH KNOWLEDGE BASE:\n{graph_insights[:600]}\n\n"
            if graph_insights and state.get("has_graph_match") else ""
        )
        user_msg = (
            f"ORIGINAL QUERY: {state['query']}\n\n"
            f"{graph_kb_section}"
            f"GRAPH ANALYSIS:\n{state.get('graph_analysis', '')[:550]}\n\n"
            f"INCIDENT ANALYSIS:\n{state.get('incident_analysis', '')[:550]}\n\n"
            f"RISK ANALYSIS:\n{state.get('risk_analysis', '')[:550]}\n\n"
            f"KEY EVIDENCE:\n{key_context}"
        )
        try:
            raw = await self._chat(
                AGENT_MODELS["synthesize"], ORCHESTRATOR_SYNTHESIZE_PROMPT, user_msg,
                timeout=150.0, num_predict=_SYNTHESIZE_TOKENS, temperature=0.05,
            )
            report = _parse_json(raw)
            # Normalise: LLM returns {synthesis, risk_level, timeline}
            synthesis = (
                report.get("synthesis")
                or report.get("executive_summary", "")
                or raw[:800]  # last-resort: use raw text if JSON failed to parse
            )
            report.update({
                "query":             state["query"],
                "summary":           synthesis,
                "synthesis":         synthesis,
                "graph_analysis":    state.get("graph_analysis", ""),
                "incident_analysis": state.get("incident_analysis", ""),
                "risk_analysis":     state.get("risk_analysis", ""),
                "sources":           state.get("sources", []),
            })
            return {
                "report": report,
                "steps":  [_step("orchestrator", "completed", "Investigation report synthesised")],
            }
        except Exception as exc:
            log.error("[synthesize] %s", exc)
            return {
                "report": _fallback_report(state, str(exc)),
                "error":  str(exc),
                "steps":  [_step("orchestrator", "error", f"Synthesis error: {exc}")],
            }

    # -- Routing ---------------------------------------------------------------

    def _route_after_query_analyze(self, state: InvestigationState) -> list[str]:
        """
        Route after query_analyzer — classify node is gone.
        Graph match or any retrieval need → shared_retrieve.
        Pure conversational (no match, NO_RETRIEVAL) → synthesize directly.
        """
        if state.get("has_graph_match") or state.get("decision") != "direct":
            log.info(
                "[route] query_analyzer → shared_retrieve (match=%s decision=%s)",
                state.get("has_graph_match"), state.get("decision"),
            )
            return ["shared_retrieve"]
        log.info("[route] query_analyzer → synthesize (conversational, no graph match)")
        return ["synthesize"]

    def _route_after_evaluate(self, state: InvestigationState) -> list[str]:
        """
        Critical optimization gate.

        DIRECT_RESPONSE: saves 3-4 LLM calls (all agents + plan)
        PARTIAL:         saves 1 LLM call (plan) + skipped agent calls
        DEEP:            full orchestration
        """
        decision = state.get("evidence_decision", "DEEP")
        if decision == "DIRECT_RESPONSE":
            log.info("[route] DIRECT_RESPONSE -- skipping all agents")
            return ["synthesize"]
        if decision == "PARTIAL":
            log.info("[route] PARTIAL -- direct fan-out agents=%s", state.get("active_agents"))
            return ["graph_agent", "incident_agent", "risk_agent"]
        log.info("[route] DEEP -- plan + full orchestration")
        return ["plan"]

    def _route_after_plan(self, state: InvestigationState) -> list[str]:
        return ["graph_agent", "incident_agent", "risk_agent"]

    # -- Graph compilation -----------------------------------------------------

    def _compile(self):
        wf = StateGraph(InvestigationState)

        wf.add_node("query_analyzer",  self._query_analyze)
        wf.add_node("shared_retrieve", self._shared_retrieve)
        wf.add_node("evaluate",        self._evaluate)
        wf.add_node("plan",            self._plan)
        wf.add_node("graph_agent",     self._graph_agent)
        wf.add_node("incident_agent",  self._incident_agent)
        wf.add_node("risk_agent",      self._risk_agent)
        wf.add_node("synthesize",      self._synthesize)

        # query_analyzer runs first, routes directly — no classify node
        wf.add_edge(START, "query_analyzer")
        wf.add_conditional_edges(
            "query_analyzer",
            self._route_after_query_analyze,
            ["shared_retrieve", "synthesize"],
        )
        wf.add_edge("shared_retrieve", "evaluate")
        wf.add_conditional_edges(
            "evaluate",
            self._route_after_evaluate,
            ["plan", "graph_agent", "incident_agent", "risk_agent", "synthesize"],
        )
        wf.add_conditional_edges(
            "plan",
            self._route_after_plan,
            ["graph_agent", "incident_agent", "risk_agent"],
        )
        wf.add_edge("graph_agent",    "synthesize")
        wf.add_edge("incident_agent", "synthesize")
        wf.add_edge("risk_agent",     "synthesize")
        wf.add_edge("synthesize", END)

        return wf.compile()

    # -- Public streaming interface --------------------------------------------

    async def stream(self, query: str, history: list[dict] | None = None) -> AsyncIterator[dict]:
        """Execute the investigation and yield SSE-ready event dicts."""
        initial: InvestigationState = {
            "query":               query,
            "history":             history or [],
            # query_analyzer fields (populated by first node)
            "query_intent":        "GENERAL",
            "query_entities":      [],
            "graph_insights":      "",
            "has_graph_match":     False,
            # retrieval
            "shared_ctx":          None,
            "retrieved_context":   "",
            "entities":            {},
            "sources":             [],
            "evidence_decision":   "DEEP",
            "investigation_depth": "DEEP",
            "plan":                "",
            "decision":            "full",
            "active_agents":       ["graph", "incident", "risk"],
            "graph_analysis":      "",
            "incident_analysis":   "",
            "risk_analysis":       "",
            "steps":               [],
            "report":              None,
            "error":               None,
        }

        yield {"type": "investigation-start", "data": {
            "query":   query,
            "message": "Investigation initiated -- evidence-driven pipeline",
        }}

        async for chunk in self._graph.astream(initial, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                for step in node_output.get("steps", []):
                    yield {"type": "step-update", "data": {**step, "node": node_name}}

                if node_name == "query_analyzer":
                    yield {"type": "graph-analysis-signal", "data": {
                        "intent":       node_output.get("query_intent", "GENERAL"),
                        "entities":     node_output.get("query_entities", []),
                        "has_match":    node_output.get("has_graph_match", False),
                        "message":      (
                            f"Visualization graph lookup: "
                            f"intent={node_output.get('query_intent', 'GENERAL')} "
                            f"match={node_output.get('has_graph_match', False)}"
                        ),
                    }}

                if node_name == "evaluate":
                    depth    = node_output.get("investigation_depth", "DEEP")
                    decision = node_output.get("evidence_decision", "DEEP")
                    yield {"type": "investigation-signal", "data": {
                        "depth":    depth,
                        "decision": decision,
                        "message":  f"Evidence: {decision} ({depth} mode)",
                    }}

                if node_name == "synthesize" and node_output.get("report"):
                    yield {"type": "investigation-complete", "data": {
                        "report": node_output["report"],
                    }}


# -- Helper functions ---------------------------------------------------------

def _fallback_report(state: InvestigationState, error: str) -> dict:
    return {
        "query":             state.get("query", ""),
        "risk_level":        "UNKNOWN",
        "summary":           f"Investigation encountered an error: {error}",
        "synthesis":         "",
        "graph_analysis":    state.get("graph_analysis", ""),
        "incident_analysis": state.get("incident_analysis", ""),
        "risk_analysis":     state.get("risk_analysis", ""),
        "affected_services": [],
        "timeline":          [],
        "evidence":          [],
        "recommendations":   ["Retry the investigation", "Check system logs"],
        "sources":           state.get("sources", []),
    }


def _parse_json(raw: str) -> dict:
    """Extract JSON from Ollama response, tolerating markdown fences."""
    raw = raw.strip()
    for fence in ("```json", "```"):
        if fence in raw:
            start = raw.find(fence) + len(fence)
            end   = raw.rfind("```")
            if end > start:
                raw = raw[start:end].strip()
                break
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("[parse_json] could not parse JSON response")
        return {}


# -- Module singleton ---------------------------------------------------------

_workflow: InvestigationWorkflow | None = None


def get_workflow() -> InvestigationWorkflow:
    global _workflow
    if _workflow is None:
        _workflow = InvestigationWorkflow()
    return _workflow

"""
Evidence-driven GraphRAG investigation workflow.

Architecture (persisted-session-context, graph-aware):

  START
    -> query_analyzer    (qwen2.5:1.5b: reads conversation_context from state + in-memory
                          GraphCache populated from Neo4j — NO extra DB call)
                          • query decomposition, entity extraction, intent classification
                          • graph lookup planning + retrieval routing
        | conversational (routing=NO_RETRIEVAL, no graph match) -> synthesize
        | graph match OR retrieve needed                        -> shared_retrieve
    -> shared_retrieve   (SharedLightweightRetriever: Neo4j graph + ChromaDB semantic search, cached)
    -> evaluate          (EvidenceEvaluator: heuristic gate, NO LLM call)
        | DIRECT_RESPONSE -> synthesize (lightweight: context already sufficient)
        | PARTIAL        -> graph_agent + incident_agent + risk_agent (filtered slices)
        | DEEP           -> plan (LLM: only for complex RCA, enriched with graph insights)
                           -> graph_agent + incident_agent + risk_agent
    -> synthesize        (lightweight merge)
        -> context_agent     (qwen2.5:7b: compacts the full session context AFTER the answer,
                                                    merging the prior compact context with the latest exchange)
    -> END

Key design guarantees:
    - query_analyzer reads persisted conversation_context, NOT raw history turns
    - GraphCache populated from Neo4j (no local data folder access)
    - ChromaDB provides semantic search for document content (no local files)
    - Shared retrieval runs EXACTLY ONCE per query
    - Embedding computation cached (1 hour TTL)
    - Graph results cached per entity (2 min TTL)
    - Context object cached per query (5 min TTL)
    - Agents receive FILTERED slices, not duplicated full context
    - Selective expanders fetch ONLY missing evidence from Neo4j/ChromaDB
    - FAST queries never reach agents
"""
from __future__ import annotations

from copy import deepcopy
import json
import logging
import re
from datetime import datetime, timezone
from typing import AsyncIterator, Any

from google import genai
from google.genai import types
from langgraph.graph import StateGraph, START, END

from backend.investigation_agents.state import InvestigationState
from backend.investigation_agents.prompts import (
    CONTEXT_AGENT_PROMPT,
    QUERY_ANALYZER_PROMPT,
    ORCHESTRATOR_PLAN_PROMPT,
    GRAPH_AGENT_PROMPT,
    INCIDENT_AGENT_PROMPT,
    RISK_AGENT_PROMPT,
    ORCHESTRATOR_SYNTHESIZE_PROMPT,
)
from backend.investigation_agents.graph_inspector import get_graph_inspector
from backend.retrieval.shared_retriever import get_shared_retriever
from backend.retrieval.workforce_catalog import get_workforce_catalog
from backend.investigation.shared_context import SharedInvestigationContext
from backend.investigation.evidence_evaluator import (
    get_evaluator,
    EvidenceDecision,
)
from backend.retrieval.context_expanders.graph_expander import get_graph_expander
from backend.retrieval.context_expanders.incident_expander import get_incident_expander
from backend.retrieval.context_expanders.risk_expander import get_risk_expander
from retrieval.config import settings as retrieval_settings
from backend.config import settings as backend_settings

log = logging.getLogger(__name__)

# -- Model assignments ---------------------------------------------------------

AGENT_MODELS: dict[str, str] = {
    "context_agent":  "gemini-2.5-pro",
    "query_analyzer": "gemini-2.5-pro",
    "orchestrator":   "gemini-2.5-pro",
    "graph":          "gemini-2.5-flash",
    "incident":       "gemini-2.5-flash",
    "risk":           "gemini-2.5-pro",
    "synthesize":     "gemini-2.5-pro",
}

# Token budgets
_FAST_SYNTHESIZE_TOKENS = 2200     # DIRECT_RESPONSE path (conversational/fact answer)
_QUERY_ANALYZER_TOKENS  = 450    # query analysis structure extraction
_AGENT_TOKENS           = 800    # per specialist agent
_PLAN_TOKENS            = 600    # orchestrator plan
_SYNTHESIZE_TOKENS      = 2400    # final synthesis
_AGENT_CONTEXT_CHARS    = 3200   # context slice per agent
_FAST_RETRIEVED_CONTEXT_CHARS = 2200
_FAST_GRAPH_CONTEXT_CHARS = 2800
_FAST_COMBINED_CONTEXT_CHARS = 4200
_FULL_SYNTHESIS_GRAPH_ONLY_CHARS = 1800
_FULL_SYNTHESIS_KEY_CONTEXT_CHARS = 1400
_FULL_SYNTHESIS_ANALYSIS_CHARS = 1100
_FULL_SYNTHESIS_GRAPH_KB_CHARS = 1200
_RAW_SYNTHESIS_FALLBACK_CHARS = 1600

_DETAIL_QUERY_MARKERS = (
    "tell me about",
    "tell me more",
    "more about",
    "details on",
    "details about",
    "detail on",
    "detail about",
    "expand on",
    "explain more",
    "drill into",
)

_COMPARISON_QUERY_MARKERS = (
    "most ",
    "least ",
    "highest ",
    "lowest ",
    "compare ",
    "comparison",
    " versus ",
    " vs ",
    "rank ",
    "top ",
)

_RISK_QUERY_MARKERS = (
    "risk",
    "at risk",
    "blast radius",
    "impact",
    "deployment",
    "deployments",
    "failed deploy",
    "failed deployment",
)

_STATUS_QUERY_MARKERS = (
    "progress",
    "status",
    "current state",
    "update on",
    "updates on",
    "how is",
    "how are",
    "contribution",
    "contributions",
)

_PERFORMANCE_QUERY_MARKERS = (
    "latency",
    "throughput",
    "p95",
    "p99",
    "slow",
    "slowness",
    "spike",
    "regression",
    "performance",
)

_CAUSAL_QUERY_MARKERS = (
    "what caused",
    "cause of",
    "caused",
    "why did",
    "why was",
    "why is",
    "root cause",
    "reason for",
)

_COMMIT_QUERY_MARKERS = (
    "commit ",
    "commit#",
    "changeset",
)

_DEPLOYMENT_QUERY_MARKERS = (
    "deployment",
    "deployments",
    "rollout",
    "release",
    "rollback",
    "dep-",
)

_CONTEXT_ENTITY_STOPWORDS = {
    "context",
    "entities",
    "facts",
    "summary",
    "user",
    "assistant",
    "query",
    "answer",
    "latest",
    "recent",
    "history",
    "provided",
    "conversation",
    "current",
    "none",
}

_FOLLOWUP_QUERY_MARKERS = (
    "tell me more",
    "more about",
    "what about",
    "how about",
    "go on",
    "continue",
    "expand on",
    "who owns that",
    "who owns it",
)

_FOLLOWUP_PRONOUNS = {
    "it", "its", "they", "them", "their", "theirs",
    "he", "him", "his", "she", "her", "hers",
    "that", "those", "this", "these",
}

_FAST_SYSTEM_PROMPT = (
    "You are a NexusIQ answer agent. Answer the user's exact question directly "
    "using only the provided evidence from retrieved documents and graph results. "
    "Conversation context is reference-only for pronouns and topic continuity, "
    "never factual evidence. Give the answer in the first sentence. "
    "If the question asks for a count, state the number explicitly. Ignore "
    "unrelated incidents or background details. If evidence is insufficient, "
    "say exactly what is known and what is missing. For superlatives or "
    "comparisons such as busiest/most active/most important, do not infer from "
    "incidents, failures, or ownership alone unless the evidence explicitly "
    "supports that comparison."
)

_GRAPH_SUFFICIENCY_CHECK_PROMPT = """
You are a strict evidence sufficiency checker.

Decide whether the provided graph context ALONE can fully answer the current query.
Do not infer missing facts.

Return ONLY valid JSON in this schema:
{
    "sufficient": true|false,
    "confidence": 0.0,
    "reason": "short reason"
}

Rules:
- sufficient=true ONLY when the graph context explicitly contains the final answer.
- If the query asks for counts, names, ownership, status, timeline, or root cause and
    the required facts are not explicit, return sufficient=false.
- If the graph context appears semantically related but lacks direct answer facts,
    return sufficient=false.
- Be conservative: when uncertain, return sufficient=false.
"""


def _extract_finish_reason(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return "UNKNOWN"
    finish_reason = getattr(candidates[0], "finish_reason", None)
    if finish_reason is None:
        return "UNKNOWN"
    return str(getattr(finish_reason, "name", finish_reason) or "UNKNOWN")


def _extract_candidate_token_count(response: Any) -> int | None:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return None
    for attr in ("candidates_token_count", "candidate_token_count", "output_token_count"):
        value = getattr(usage, attr, None)
        if isinstance(value, int):
            return value
    return None


def _is_detail_query(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _DETAIL_QUERY_MARKERS)


def _is_comparison_query(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _COMPARISON_QUERY_MARKERS)


def _is_risk_query(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _RISK_QUERY_MARKERS)


def _is_status_query(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _STATUS_QUERY_MARKERS)


def _is_performance_query(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _PERFORMANCE_QUERY_MARKERS)


def _is_causal_query(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _CAUSAL_QUERY_MARKERS)


def _is_commit_query(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _COMMIT_QUERY_MARKERS)


def _is_deployment_query(query: str) -> bool:
    lowered = query.lower()
    return any(marker in lowered for marker in _DEPLOYMENT_QUERY_MARKERS)


def _clean_context_entities(raw_entities: str) -> str:
    cleaned_entities: list[str] = []
    seen: set[str] = set()
    for part in raw_entities.split(","):
        cleaned = re.sub(r"<[^>]+>", " ", part)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\n\r-:;,.`")
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in _CONTEXT_ENTITY_STOPWORDS:
            continue
        if len(re.findall(r"[a-z0-9]", lowered)) < 2:
            continue
        if lowered not in seen:
            seen.add(lowered)
            cleaned_entities.append(cleaned)
    return ", ".join(cleaned_entities) if cleaned_entities else "NONE"


def _extract_context_entities(context: str) -> list[str]:
    if not context.strip():
        return []
    match = re.search(r"<entities>(.*?)</entities>", context, re.DOTALL | re.IGNORECASE)
    if not match:
        return []
    raw = match.group(1).strip()
    if not raw or raw.upper() == "NONE":
        return []
    return [entity.strip() for entity in raw.split(",") if entity.strip()]


def _is_followup_query(query: str) -> bool:
    lowered = query.lower().strip()
    if not lowered:
        return False
    if any(marker in lowered for marker in _FOLLOWUP_QUERY_MARKERS):
        return True
    tokens = re.findall(r"[a-z]+", lowered)
    return any(token in _FOLLOWUP_PRONOUNS for token in tokens)


def _should_carry_context(
    inspector: Any,
    query: str,
    conversation_context: str,
) -> bool:
    context_entities = _extract_context_entities(conversation_context)
    if not context_entities:
        return False
    if _is_followup_query(query):
        return True

    query_keywords = {kw.lower() for kw in inspector.extract_keywords(query)}
    context_keywords = {kw.lower() for kw in inspector.extract_keywords(" ".join(context_entities))}
    return bool(query_keywords & context_keywords)


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
        self._gemini_client = genai.Client(
            vertexai=True,
            project="knudc-khang-buiphuoc",
            location="us-central1",
        )
        self._retriever = get_shared_retriever()
        self._evaluator = get_evaluator()
        self._inspector = get_graph_inspector()
        self._graph     = self._compile()

    # -- Gemini helper ---------------------------------------------------------

    async def _chat(
        self,
        model: str,
        system: str,
        user: str,
        timeout: float = 120.0,
        num_predict: int = 400,
        temperature: float = 0.1,
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=temperature,
            max_output_tokens=num_predict,
        )
        response = await self._gemini_client.aio.models.generate_content(
            model=model,
            contents=user,
            config=config,
        )
        text = response.text or ""
        finish_reason = _extract_finish_reason(response)
        candidate_tokens = _extract_candidate_token_count(response)
        log.info(
            "[llm] model=%s finish_reason=%s candidate_tokens=%s chars=%d max_output_tokens=%d",
            model,
            finish_reason,
            candidate_tokens,
            len(text),
            num_predict,
        )
        if finish_reason.upper() not in {"STOP", "FINISH_REASON_STOP", "UNKNOWN"}:
            log.warning(
                "[llm] non-stop finish reason for model=%s: %s (chars=%d max_output_tokens=%d)",
                model,
                finish_reason,
                len(text),
                num_predict,
            )
        return text

    async def _verify_graph_sufficiency(
        self,
        *,
        query: str,
        answer_goal: str,
        answer_type: str,
        intent: str,
        conversation_context: str,
        graph_context: str,
    ) -> tuple[bool, float, str]:
        """
        LLM guardrail for GRAPH_SUFFICIENT routing.
        Returns: (is_sufficient, confidence, reason).
        """
        user_msg = (
            f"QUERY: {query}\n"
            f"ANSWER_GOAL: {answer_goal}\n"
            f"ANSWER_TYPE: {answer_type}\n"
            f"INTENT: {intent}\n\n"
            f"CONVERSATION_CONTEXT:\n{conversation_context or '(none)'}\n\n"
            f"GRAPH_CONTEXT:\n{graph_context or '(none)'}"
        )
        try:
            raw = await self._chat(
                AGENT_MODELS["query_analyzer"],
                _GRAPH_SUFFICIENCY_CHECK_PROMPT,
                user_msg,
                timeout=25.0,
                num_predict=120,
                temperature=0.0,
            )
            parsed = _parse_json(raw)
            sufficient = bool(parsed.get("sufficient", False))
            confidence = float(parsed.get("confidence", 0.0) or 0.0)
            reason = str(parsed.get("reason", "no reason provided"))[:200]
            return sufficient, confidence, reason
        except Exception as exc:
            # Fail-safe: prefer retrieval over direct answer when verifier fails.
            return False, 0.0, f"sufficiency-check-failed: {exc}"

    # -- Node: context_agent ---------------------------------------------------

    async def _context_agent(self, state: InvestigationState) -> dict:
        """
        Session context compactor — runs AFTER synthesize.

        Merges the persisted compact session context with the latest user query,
        the final assistant answer, and a small backfill window of recent raw turns.
        The refreshed XML block is persisted by the client for the next turn.
        """
        existing_context = state.get("conversation_context") or ""
        history: list[dict] = state.get("history") or []
        report = state.get("report") or {}
        latest_answer = ""
        if isinstance(report, dict):
            latest_answer = str(report.get("synthesis") or report.get("summary") or "").strip()

        if not (existing_context.strip() or history or state.get("query", "").strip() or latest_answer):
            log.info("[context_agent] no session material — skipping")
            return {
                "conversation_context": "",
                "steps": [_step("context_agent", "completed", "Session context unchanged — no history to compact")],
            }

        formatted = "\n".join(
            f"{t['role'].upper()}: {str(t.get('content', ''))[:400]}"
            for t in history[-12:]
        )
        current_query: str = state.get("query", "")
        carry_context = _should_carry_context(self._inspector, current_query, existing_context)
        existing_context_input = existing_context if carry_context else ""
        formatted_input = formatted if carry_context else ""
        log.info(
            "[context_agent] compacting session context: turns=%d existing=%s carry_context=%s",
            len(history),
            bool(existing_context.strip()),
            carry_context,
        )

        try:
            raw = await self._chat(
                AGENT_MODELS["context_agent"],
                CONTEXT_AGENT_PROMPT,
                (
                    f"EXISTING SESSION CONTEXT:\n{existing_context_input or 'NONE'}\n\n"
                    f"RECENT SESSION HISTORY:\n{formatted_input or '(none)'}\n\n"
                    f"LATEST USER QUERY: {current_query or 'NONE'}\n\n"
                    f"LATEST ASSISTANT ANSWER:\n{latest_answer or 'NONE'}"
                ),
                timeout=60.0,
                num_predict=400,
                temperature=0.0,
            )

            def _tag(text: str, tag: str, default: str = "NONE") -> str:
                m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
                return m.group(1).strip() if m else default

            entities_val = _tag(raw, "entities")
            facts_val    = _tag(raw, "facts")
            summary_val  = _tag(raw, "summary")

            # Heuristic fallback: if the LLM returned NONE for entities, extract
            # keywords directly from the session context + latest exchange.
            if entities_val.upper() == "NONE":
                sanitized_existing_context = re.sub(r"<[^>]+>", " ", existing_context_input)
                fallback_text = " ".join([
                    sanitized_existing_context,
                    formatted_input,
                    current_query,
                    latest_answer,
                ])
                kw = self._inspector.extract_keywords(fallback_text)
                if kw:
                    entities_val = ", ".join(kw[:12])
                    log.info(
                        "[context_agent] LLM returned NONE entities — heuristic fallback: %s",
                        entities_val,
                    )

            entities_val = _clean_context_entities(entities_val)

            context_block = (
                "<context>\n"
                f"  <entities>{entities_val}</entities>\n"
                f"  <facts>{facts_val}</facts>\n"
                f"  <summary>{summary_val}</summary>\n"
                "</context>"
            )
            log.info("[context_agent] context_block=%r", context_block[:120])
            return {
                "conversation_context": context_block,
                "steps": [_step("context_agent", "completed",
                    (
                        f"Session context compacted — entities={entities_val[:60]}"
                        if carry_context else
                        f"Session context refreshed for new topic — entities={entities_val[:60]}"
                    ))],
            }

        except Exception as exc:
            log.warning("[context_agent] LLM call failed: %s — using session fallback", exc)
            fallback_summary = latest_answer[:400] or current_query[:400] or "NONE"
            if existing_context.strip():
                return {
                    "conversation_context": existing_context,
                    "steps": [_step("context_agent", "error", f"Compaction failed — kept prior session context: {exc}")],
                }
            return {
                "conversation_context": (
                    "<context>\n  <entities>NONE</entities>\n"
                    f"  <facts>Latest query: {current_query[:250] or 'NONE'}.</facts>\n"
                    f"  <summary>{fallback_summary}</summary>\n</context>"
                ),
                "steps": [_step("context_agent", "error", f"Compaction failed, using minimal fallback: {exc}")],
            }

    # -- Node: query_analyzer --------------------------------------------------

    async def _query_analyze(self, state: InvestigationState) -> dict:
        """
        First node: qwen2.5:1.5b reads lightweight graph matches directly from
        Neo4j so query routing is not limited by the visualization cache.
        to perform query decomposition, entity extraction, intent classification,
        graph lookup planning, and retrieval routing.

        If graph lookup has relevant entities/relationships the insights are
        stored in state and forwarded to the orchestrator planning step.
        """
        query = state["query"]
        query_lower = query.lower()
        log.info("[query_analyzer] analyzing query against visualization graph")

        # Structured session context persisted from the previous turn.
        conversation_context: str = state.get("conversation_context") or ""
        carry_context = _should_carry_context(self._inspector, query, conversation_context)

        # 1. Graph lookup using keywords from the current query PLUS entities that
        #    the context_agent already extracted from conversation history.
        #    This ensures follow-up queries ("Tell me more", "Who owns that?") get
        #    meaningful graph context even when the query itself is short.
        query_keywords = self._inspector.extract_keywords(query)

        context_entity_keywords: list[str] = []
        if carry_context:
            context_entities = _extract_context_entities(conversation_context)
            if context_entities:
                context_entity_keywords = self._inspector.extract_keywords(", ".join(context_entities))

        combined_keywords = list(dict.fromkeys(query_keywords + context_entity_keywords))
        log.info(
            "[query_analyzer] keywords=%s (query=%s ctx=%s carry_context=%s)",
            combined_keywords, query_keywords, context_entity_keywords, carry_context,
        )

        # 2. In-memory graph lookup (no DB call) ─────────────────────────────
        lookup = await self._inspector.lookup(combined_keywords)
        graph_ctx_text = self._inspector.format_for_llm(lookup)
        has_match = lookup["matched"]

        log.info(
            "[query_analyzer] graph_match=%s entities=%d rels=%d",
            has_match, len(lookup["entities"]), len(lookup["relationships"]),
        )

        # 3. LLM analysis (qwen2.5:1.5b) ───────────────────────────────────────
        user_msg = (
            f"CONVERSATION CONTEXT:\n{conversation_context or '(none)'}\n\n"
            f"CURRENT QUERY: {query}\n\n"
            f"{graph_ctx_text}"
        )
        try:
            raw = await self._chat(
                AGENT_MODELS["query_analyzer"],
                QUERY_ANALYZER_PROMPT,
                user_msg,
                timeout=60.0,
                num_predict=_QUERY_ANALYZER_TOKENS,
                temperature=0.0,
            )

            # Ground-truth entities from the lookup — independent of the LLM.
            # The small model (1.5b) often returns NONE even when matches exist,
            # so we always trust the keyword-lookup result first.
            lookup_entity_titles = [
                str(e.get("title", "")) for e in lookup["entities"] if e.get("title")
            ]

            # Parse structured LLM output
            answer_goal = query
            answer_type = "SUMMARY"
            intent   = "GENERAL"
            llm_entities: list[str] = []
            recommended_agents: list[str] = []
            routing  = "NO_RETRIEVAL" if not has_match else "GRAPH_SUFFICIENT"
            insights = "NONE"

            # Parse XML tags from the LLM response
            def _tag(text: str, tag: str, default: str = "") -> str:
                m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
                return m.group(1).strip() if m else default

            raw_goal     = _tag(raw, "answer_goal",   query)
            raw_answer_type = _tag(raw, "answer_type", "SUMMARY").upper()
            raw_intent   = _tag(raw, "intent",        "GENERAL").upper()
            raw_entities = _tag(raw, "entities",      "NONE")
            raw_agents   = _tag(raw, "recommended_agents", "NONE")
            raw_routing  = _tag(raw, "routing",
                                "NO_RETRIEVAL" if not has_match else "GRAPH_SUFFICIENT").upper()
            insights     = _tag(raw, "graph_insights", "NONE")

            if raw_goal:
                answer_goal = raw_goal
            if raw_answer_type in {"PEOPLE", "PROFILE", "STATUS", "DEPENDENCY", "INCIDENT", "RISK", "PERFORMANCE", "SUMMARY", "GENERAL"}:
                answer_type = raw_answer_type
            if raw_intent in {"TOPOLOGY", "INCIDENT", "RISK", "PERFORMANCE", "GENERAL"}:
                intent = raw_intent
            if raw_entities.upper() != "NONE":
                llm_entities = [e.strip() for e in raw_entities.split(",") if e.strip()]

            workforce_catalog = await get_workforce_catalog()
            resolved_employee_names = workforce_catalog.resolve_employee_names(
                query,
                answer_goal,
                *llm_entities,
            )
            if resolved_employee_names:
                existing_entities = {entity.lower() for entity in llm_entities}
                for employee_name in resolved_employee_names:
                    if employee_name.lower() not in existing_entities:
                        llm_entities.append(employee_name)
                        existing_entities.add(employee_name.lower())

                if answer_type in {"SUMMARY", "GENERAL"}:
                    log.info(
                        "[query_analyzer] forcing answer_type SUMMARY/GENERAL→PROFILE for employees=%s",
                        resolved_employee_names,
                    )
                    answer_type = "PROFILE"

                if routing == "NO_RETRIEVAL":
                    log.info(
                        "[query_analyzer] forcing routing NO_RETRIEVAL→RETRIEVE_MORE for employees=%s",
                        resolved_employee_names,
                    )
                    routing = "RETRIEVE_MORE"

            if raw_agents.upper() != "NONE":
                recommended_agents = [
                    agent.strip()
                    for agent in raw_agents.split(",")
                    if agent.strip() in {"graph", "incident", "risk"}
                ]
            if raw_routing in {"GRAPH_SUFFICIENT", "RETRIEVE_MORE", "NO_RETRIEVAL"}:
                # Never downgrade a confirmed graph match to NO_RETRIEVAL.
                if not (has_match and raw_routing == "NO_RETRIEVAL"):
                    routing = raw_routing

            # Post-LLM Guardrail: prevent routing to NO_RETRIEVAL if the query is factual.
            if routing == "NO_RETRIEVAL":
                has_context_entities = False
                if conversation_context.strip():
                    _m_check = re.search(r"<entities>(.*?)</entities>", conversation_context, re.DOTALL | re.IGNORECASE)
                    if _m_check and _m_check.group(1).strip().upper() != "NONE":
                        has_context_entities = True
                
                # Check for any non-greeting keywords in the combined keywords
                non_greeting_keywords = [
                    kw for kw in combined_keywords
                    if kw.lower() not in {"hello", "hi", "hey", "thanks", "thank", "greetings", "bye", "goodbye", "please", "yes", "no"}
                ]
                
                if has_context_entities or non_greeting_keywords:
                    log.info(
                        "[query_analyzer] guard: NO_RETRIEVAL→RETRIEVE_MORE "
                        "(has_context_entities=%s, non_greeting_keywords=%s)",
                        has_context_entities, non_greeting_keywords,
                    )
                    routing = "RETRIEVE_MORE"

            # PEOPLE/PROFILE/STATUS answers usually need shared retrieval even when
            # the graph matched, because workforce and document evidence live there.
            if answer_type in {"PEOPLE", "PROFILE", "STATUS"}:
                if routing != "RETRIEVE_MORE":
                    log.info(
                        "[query_analyzer] routing forced to RETRIEVE_MORE for answer_type=%s",
                        answer_type,
                    )
                    routing = "RETRIEVE_MORE"

            # Enforce internal consistency: if specialist agents are required,
            # the answer is not graph-sufficient yet.
            if routing == "GRAPH_SUFFICIENT" and recommended_agents:
                log.info(
                    "[query_analyzer] routing downgraded GRAPH_SUFFICIENT→RETRIEVE_MORE "
                    "because recommended_agents=%s",
                    recommended_agents,
                )
                routing = "RETRIEVE_MORE"

            # Merge: lookup titles are authoritative; LLM extras appended if new
            lookup_set = {t.lower() for t in lookup_entity_titles}
            extra = [e for e in llm_entities if e.lower() not in lookup_set]
            entities_out = lookup_entity_titles + extra

            detail_query = _is_detail_query(query)
            comparison_query = _is_comparison_query(query)
            risk_query = _is_risk_query(query)
            status_query = _is_status_query(query)
            performance_query = _is_performance_query(query)
            causal_query = _is_causal_query(query)
            commit_query = _is_commit_query(query)
            deployment_query = _is_deployment_query(query)
            followup_query = _is_followup_query(query)

            if intent == "GENERAL" and risk_query:
                log.info("[query_analyzer] forcing intent GENERAL→RISK for query=%s", query[:120])
                intent = "RISK"

            if intent == "GENERAL" and (performance_query or causal_query):
                log.info(
                    "[query_analyzer] forcing intent GENERAL→PERFORMANCE for performance/causal query"
                )
                intent = "PERFORMANCE"

            if performance_query and answer_type in {"GENERAL", "SUMMARY"}:
                log.info(
                    "[query_analyzer] forcing answer_type %s→PERFORMANCE for performance query",
                    answer_type,
                )
                answer_type = "PERFORMANCE"

            if causal_query and answer_type in {"GENERAL", "SUMMARY", "PERFORMANCE"}:
                log.info(
                    "[query_analyzer] forcing answer_type %s→INCIDENT for causal query",
                    answer_type,
                )
                answer_type = "INCIDENT"

            if (performance_query or causal_query) and routing == "GRAPH_SUFFICIENT":
                log.info(
                    "[query_analyzer] forcing routing GRAPH_SUFFICIENT→RETRIEVE_MORE for performance/causal query"
                )
                routing = "RETRIEVE_MORE"

            if causal_query and not recommended_agents:
                recommended_agents = ["incident"]
                log.info(
                    "[query_analyzer] forcing recommended_agents=incident for causal query"
                )
            elif performance_query and not recommended_agents:
                recommended_agents = ["incident"]
                log.info(
                    "[query_analyzer] forcing recommended_agents=incident for performance query"
                )

            deployment_investigation_query = (
                deployment_query and (
                    detail_query
                    or causal_query
                    or followup_query
                    or "failed" in query_lower
                    or "failure" in query_lower
                    or "what happened" in query_lower
                    or "how did" in query_lower
                    or "why did" in query_lower
                    or "when did" in query_lower
                )
            )
            if deployment_investigation_query:
                if intent != "INCIDENT":
                    log.info(
                        "[query_analyzer] forcing intent %s→INCIDENT for deployment investigation query",
                        intent,
                    )
                    intent = "INCIDENT"
                if answer_type != "INCIDENT":
                    log.info(
                        "[query_analyzer] forcing answer_type %s→INCIDENT for deployment investigation query",
                        answer_type,
                    )
                    answer_type = "INCIDENT"
                if routing != "RETRIEVE_MORE":
                    log.info(
                        "[query_analyzer] forcing routing %s→RETRIEVE_MORE for deployment investigation query",
                        routing,
                    )
                    routing = "RETRIEVE_MORE"
                if "incident" not in recommended_agents:
                    recommended_agents = ["incident"]
                    log.info(
                        "[query_analyzer] forcing recommended_agents=incident for deployment investigation query"
                    )

            if status_query and answer_type in {"GENERAL", "SUMMARY", "PROFILE"}:
                log.info(
                    "[query_analyzer] forcing answer_type %s→STATUS for status/progress query",
                    answer_type,
                )
                answer_type = "STATUS"

            if status_query and routing == "GRAPH_SUFFICIENT":
                log.info(
                    "[query_analyzer] forcing routing GRAPH_SUFFICIENT→RETRIEVE_MORE for status/progress query"
                )
                routing = "RETRIEVE_MORE"

            if status_query and has_match and not recommended_agents:
                recommended_agents = ["graph"]
                log.info(
                    "[query_analyzer] forcing recommended_agents=graph for status/progress query"
                )

            if commit_query and answer_type in {"GENERAL", "SUMMARY"}:
                log.info(
                    "[query_analyzer] forcing answer_type %s→INCIDENT for explicit commit query",
                    answer_type,
                )
                answer_type = "INCIDENT"

            if commit_query and routing == "GRAPH_SUFFICIENT":
                log.info(
                    "[query_analyzer] forcing routing GRAPH_SUFFICIENT→RETRIEVE_MORE for explicit commit query"
                )
                routing = "RETRIEVE_MORE"

            if commit_query and not recommended_agents:
                recommended_agents = ["incident"]
                log.info(
                    "[query_analyzer] forcing recommended_agents=incident for explicit commit query"
                )

            if causal_query and not recommended_agents:
                recommended_agents = ["graph", "incident"] if has_match else ["incident"]
                log.info(
                    "[query_analyzer] forcing recommended_agents=%s for causal query",
                    recommended_agents,
                )
            elif performance_query and not recommended_agents:
                recommended_agents = ["graph", "incident"] if has_match else ["incident"]
                log.info(
                    "[query_analyzer] forcing recommended_agents=%s for performance query",
                    recommended_agents,
                )

            if has_match and (detail_query or comparison_query):
                if routing == "GRAPH_SUFFICIENT":
                    log.info(
                        "[query_analyzer] forcing routing GRAPH_SUFFICIENT→RETRIEVE_MORE for detail/comparison query"
                    )
                    routing = "RETRIEVE_MORE"

                if not recommended_agents:
                    recommended_agents = ["risk"] if risk_query or comparison_query else ["graph"]
                    log.info(
                        "[query_analyzer] forcing recommended_agents=%s for detail/comparison query",
                        recommended_agents,
                    )

                if answer_type == "GENERAL":
                    answer_type = "RISK" if risk_query else "SUMMARY"

            if (
                has_match
                and routing == "RETRIEVE_MORE"
                and not recommended_agents
                and len(entities_out) >= 2
                and (detail_query or comparison_query or "more" in query_lower)
            ):
                recommended_agents = ["graph"]
                log.info(
                    "[query_analyzer] forcing recommended_agents=graph for multi-entity follow-up query"
                )

            # Secondary lookup: if the LLM extracted entity names that weren't in
            # the initial combined lookup, run a targeted pass on them.
            if llm_entities and not has_match:
                llm_kw = self._inspector.extract_keywords(" ".join(llm_entities))
                if llm_kw:
                    secondary = await self._inspector.lookup(llm_kw)
                    if secondary["matched"]:
                        lookup           = secondary
                        graph_ctx_text   = self._inspector.format_for_llm(secondary)
                        has_match        = True
                        lookup_entity_titles = [
                            str(e.get("title", "")) for e in secondary["entities"] if e.get("title")
                        ]
                        entities_out = lookup_entity_titles + extra
                        log.info(
                            "[query_analyzer] LLM-entity secondary lookup matched %d entities",
                            len(lookup_entity_titles),
                        )

            # Build final insights block
            if has_match and insights and insights.upper() != "NONE":
                full_insights = f"{insights}\n\n{graph_ctx_text}"
            elif has_match:
                full_insights = graph_ctx_text
            else:
                full_insights = ""

            # Second-stage LLM verification for GRAPH_SUFFICIENT.
            # This prevents false-direct answers when graph matches are stale/irrelevant.
            if routing == "GRAPH_SUFFICIENT" and has_match:
                ok, conf, reason = await self._verify_graph_sufficiency(
                    query=query,
                    answer_goal=answer_goal,
                    answer_type=answer_type,
                    intent=intent,
                    conversation_context=conversation_context,
                    graph_context=full_insights,
                )
                if not ok or conf < 0.55:
                    log.info(
                        "[query_analyzer] GRAPH_SUFFICIENT→RETRIEVE_MORE by verifier "
                        "(ok=%s conf=%.2f reason=%s)",
                        ok,
                        conf,
                        reason,
                    )
                    routing = "RETRIEVE_MORE"

            # Final routing to execution mode.
            is_conversational  = routing == "NO_RETRIEVAL" and not has_match
            is_graph_sufficient = routing == "GRAPH_SUFFICIENT" and has_match
            is_direct_answer   = is_conversational or is_graph_sufficient
            decision           = "direct" if is_direct_answer else "full"
            evidence_decision  = "DIRECT_RESPONSE" if is_direct_answer else "DEEP"
            investigation_depth = "FAST" if is_direct_answer else "DEEP"

            log.info(
                "[query_analyzer] intent=%s routing=%s entities=%s conversational=%s",
                intent, routing, entities_out, is_conversational,
            )
            return {
                "answer_goal":         answer_goal,
                "answer_type":         answer_type,
                "query_intent":        intent,
                "query_entities":      entities_out,
                "recommended_agents":  recommended_agents,
                "graph_insights":      full_insights,
                "has_graph_match":     has_match,
                "llm_routing":         routing,
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
                "answer_goal":         query,
                "answer_type":         "SUMMARY",
                "query_intent":        "GENERAL",
                "query_entities":      fallback_entities,
                "recommended_agents":  ["graph"] if has_match else [],
                "graph_insights":      graph_ctx_text if has_match else "",
                "has_graph_match":     has_match,
                "llm_routing":         "RETRIEVE_MORE" if has_match else "NO_RETRIEVAL",
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
            ctx: SharedInvestigationContext = deepcopy(await self._retriever.retrieve(query))
            if state.get("answer_type") in {"PEOPLE", "PROFILE"}:
                workforce_catalog = await get_workforce_catalog()
                workforce_docs = await workforce_catalog.build_people_documents(
                    query=query,
                    answer_goal=state.get("answer_goal", query),
                    query_entities=state.get("query_entities", []),
                )
                if workforce_docs:
                    ctx = _inject_context_documents(ctx, workforce_docs, section_name="WORKFORCE")
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

        evaluation = self._evaluator.evaluate(
            ctx,
            intent=state.get("query_intent", "GENERAL"),
            routing=state.get("llm_routing", "RETRIEVE_MORE"),
            recommended_agents=state.get("recommended_agents", []),
            answer_type=state.get("answer_type", "SUMMARY"),
            query_entities=state.get("query_entities", []),
        )
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

        # Include graph insights from query_analyzer if available
        graph_insights = state.get("graph_insights", "")
        graph_insights_section = (
            f"\nVISUALIZATION GRAPH INSIGHTS:\n{graph_insights[:600]}\n"
            if graph_insights else ""
        )
        conv_ctx = state.get("conversation_context") or ""
        user_msg = (
            f"CONVERSATION CONTEXT:\n{conv_ctx or '(none)'}\n\n"
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
        log.info("[graph_agent] answering graph-focused query")

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
            f"ANSWER GOAL: {state.get('answer_goal', state['query'])}\n"
            f"QUERY INTENT: {state.get('query_intent', 'GENERAL')}\n\n"
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
                    "Graph-grounded answer analysis complete")],
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
                ctx.formatted_context[:_FAST_RETRIEVED_CONTEXT_CHARS] if ctx
                else state.get("retrieved_context", "")[:_FAST_RETRIEVED_CONTEXT_CHARS]
            )

            # Keep direct-response cheap, but never drop explicitly requested
            # incident evidence (for example "INC-001") due to context truncation.
            incident_refs = {
                inc.upper() for inc in re.findall(r"\bINC-\d+\b", state.get("query", ""), re.IGNORECASE)
            }
            if ctx and incident_refs:
                focused_docs: list[str] = []
                for doc in ctx.retrieved_documents:
                    doc_id = str(doc.get("id", "")).upper()
                    doc_content = str(doc.get("content", ""))
                    upper_content = doc_content.upper()
                    if doc_id in incident_refs or any(ref in upper_content for ref in incident_refs):
                        focused_docs.append(
                            f"[INCIDENT MATCH: {doc.get('id', 'unknown')}]\n{doc_content[:520]}"
                        )
                if focused_docs:
                    focus_block = "\n\n".join(focused_docs[:3])
                    retrieved_text = (
                        f"=== INCIDENT-FOCUSED EVIDENCE ===\n{focus_block}\n\n"
                        f"=== RETRIEVED CONTEXT (TRUNCATED) ===\n{retrieved_text}"
                    )[:_FAST_COMBINED_CONTEXT_CHARS]

            graph_insights = state.get("graph_insights", "")
            # Always prepend graph_insights when the graph cache had a match —
            # retrieved docs may not contain the entity's profile data.
            if graph_insights and state.get("has_graph_match"):
                context_text = (
                    f"GRAPH KNOWLEDGE BASE:\n{graph_insights[:_FAST_GRAPH_CONTEXT_CHARS]}\n\n"
                    f"RETRIEVED DOCUMENTS:\n{retrieved_text}"
                ).strip()[:_FAST_COMBINED_CONTEXT_CHARS]
            else:
                context_text = (retrieved_text or graph_insights[:_FAST_GRAPH_CONTEXT_CHARS])[:_FAST_COMBINED_CONTEXT_CHARS]

            is_conversational = state.get("decision") == "direct" and not context_text.strip()

            # Guard: if the query names a specific service/agent or uses topology
            # words but we have no context, it means retrieval found nothing —
            # do NOT hallucinate. Tell the user we have no data.
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
            conv_ctx = state.get("conversation_context") or ""
            if is_conversational:
                # Pure greeting / small-talk path — no investigation context.
                # DO NOT repeat the user's question or ask clarifying questions.
                # Respond briefly and invite the user to describe what to investigate.
                user_msg = (
                    f"CONVERSATION CONTEXT:\n{conv_ctx or '(none)'}\n\n"
                    f"USER: {state['query']}\n\n"
                    "You are the NexusIQ AI assistant for a system observability platform.\n"
                    "This is a greeting or casual message — respond briefly and warmly.\n"
                    "Do NOT repeat or paraphrase the user's message back to them.\n"
                    "Do NOT ask what they want to investigate — just let them know you're ready."
                )
            else:
                user_msg = (
                    f"REFERENCE CONTEXT (for pronoun/topic resolution only; not evidence):\n{conv_ctx or '(none)'}\n\n"
                    f"ANSWER TYPE: {state.get('answer_type', 'SUMMARY')}\n"
                    f"QUERY INTENT: {state.get('query_intent', 'GENERAL')}\n"
                    f"ANSWER GOAL: {state.get('answer_goal', state['query'])}\n\n"
                    f"QUERY: {state['query']}\n\n"
                    f"EVIDENCE:\n{context_text}\n\n"
                    "Answer the query using only the EVIDENCE block. Use REFERENCE CONTEXT "
                    "only to resolve what the user is referring to. If a fact is not present "
                    "in EVIDENCE, say the evidence does not show it. Answer the user's exact "
                    "question first. Prefer GRAPH KNOWLEDGE BASE information for entity/person "
                    "details. Ignore unrelated incident details."
                )
            try:
                answer = await self._chat(
                    AGENT_MODELS["orchestrator"], _FAST_SYSTEM_PROMPT, user_msg,
                    timeout=30.0, num_predict=_FAST_SYNTHESIZE_TOKENS, temperature=0.05,
                )
                return {
                    "report": {
                        "query":             state["query"],
                        "risk_level":        "UNKNOWN",
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
        active_agents = state.get("active_agents", [])
        if ctx and active_agents == ["graph"]:
            key_context = ctx.context_for_agent("graph", max_chars=_FULL_SYNTHESIS_GRAPH_ONLY_CHARS)
        else:
            key_context = (
                ctx.formatted_context[:_FULL_SYNTHESIS_KEY_CONTEXT_CHARS] if ctx
                else state.get("retrieved_context", "")[:_FULL_SYNTHESIS_KEY_CONTEXT_CHARS]
            )
        graph_insights = state.get("graph_insights", "")
        graph_kb_section = (
            f"GRAPH KNOWLEDGE BASE:\n{graph_insights[:_FULL_SYNTHESIS_GRAPH_KB_CHARS]}\n\n"
            if graph_insights and state.get("has_graph_match") else ""
        )
        user_msg = (
            f"ORIGINAL QUERY: {state['query']}\n\n"
            f"ANSWER GOAL: {state.get('answer_goal', state['query'])}\n"
            f"ANSWER TYPE: {state.get('answer_type', 'SUMMARY')}\n"
            f"QUERY INTENT: {state.get('query_intent', 'GENERAL')}\n"
            f"ACTIVE AGENTS: {', '.join(active_agents) or 'none'}\n\n"
            f"{graph_kb_section}"
            f"GRAPH ANALYSIS:\n{state.get('graph_analysis', '')[:_FULL_SYNTHESIS_ANALYSIS_CHARS]}\n\n"
            f"INCIDENT ANALYSIS:\n{state.get('incident_analysis', '')[:_FULL_SYNTHESIS_ANALYSIS_CHARS]}\n\n"
            f"RISK ANALYSIS:\n{state.get('risk_analysis', '')[:_FULL_SYNTHESIS_ANALYSIS_CHARS]}\n\n"
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
                or raw[:_RAW_SYNTHESIS_FALLBACK_CHARS]  # last-resort: use raw text if JSON failed to parse
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
        Route after query_analyzer.
        Direct-answer routes (GRAPH_SUFFICIENT or conversational NO_RETRIEVAL)
        go straight to synthesize. Only RETRIEVE_MORE goes through shared_retrieve.
        """
        if state.get("decision") != "direct":
            log.info(
                "[route] query_analyzer → shared_retrieve (routing=%s decision=%s)",
                state.get("llm_routing"), state.get("decision"),
            )
            return ["shared_retrieve"]
        log.info(
            "[route] query_analyzer → synthesize (routing=%s decision=%s)",
            state.get("llm_routing"), state.get("decision"),
        )
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
        wf.add_node("context_agent",   self._context_agent)

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
        wf.add_edge("synthesize", "context_agent")
        wf.add_edge("context_agent", END)

        return wf.compile()

    # -- Public streaming interface --------------------------------------------

    async def stream(
        self,
        query: str,
        history: list[dict] | None = None,
        conversation_context: str = "",
    ) -> AsyncIterator[dict]:
        """Execute the investigation and yield SSE-ready event dicts."""
        initial: InvestigationState = {
            "query":                query,
            "history":              history or [],
            # persisted session context supplied by the caller
            "conversation_context": conversation_context or "",
            # query_analyzer fields (populated by second node)
            "answer_goal":          query,
            "answer_type":          "SUMMARY",
            "query_intent":         "GENERAL",
            "query_entities":       [],
            "recommended_agents":   [],
            "graph_insights":       "",
            "has_graph_match":      False,
            "llm_routing":          "RETRIEVE_MORE",
            # retrieval
            "shared_ctx":           None,
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

                if node_name == "context_agent" and node_output.get("conversation_context") is not None:
                    yield {"type": "session-context-updated", "data": {
                        "conversation_context": node_output.get("conversation_context", ""),
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


def _inject_context_documents(
    ctx: SharedInvestigationContext,
    docs: list[dict[str, Any]],
    section_name: str,
) -> SharedInvestigationContext:
    existing_ids = {str(doc.get("id", "")) for doc in ctx.retrieved_documents}
    fresh_docs = [doc for doc in docs if str(doc.get("id", "")) not in existing_ids]
    if not fresh_docs:
        return ctx

    ctx.retrieved_documents = fresh_docs + ctx.retrieved_documents

    section_lines = [f"=== {section_name} EVIDENCE ==="]
    fresh_sources: list[dict[str, Any]] = []
    for idx, doc in enumerate(fresh_docs, 1):
        section_lines.append(f"[{section_name} #{idx}] {doc.get('content', '')}")
        fresh_sources.append({
            "rank": idx,
            "id": doc.get("id", ""),
            "source": doc.get("source", ""),
            "collection": doc.get("collection", ""),
            "rrf_score": round(float(doc.get("rrf_score", 1.0)), 4),
        })
    section_lines.append(f"=== END {section_name} EVIDENCE ===")

    block = "\n\n".join(section_lines)
    if ctx.formatted_context and ctx.formatted_context != "No relevant context found.":
        ctx.formatted_context = f"{block}\n\n{ctx.formatted_context}"
    else:
        ctx.formatted_context = block

    ctx.sources = fresh_sources + ctx.sources
    return ctx


# -- Module singleton ---------------------------------------------------------

_workflow: InvestigationWorkflow | None = None


def get_workflow() -> InvestigationWorkflow:
    global _workflow
    if _workflow is None:
        _workflow = InvestigationWorkflow()
    return _workflow

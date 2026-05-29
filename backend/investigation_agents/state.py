"""
Investigation workflow shared state and output models.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, Field


# ── Output models (serialised in the final report) ────────────────────────────

class EvidenceItem(BaseModel):
    type: str           # incident | commit | deployment | jira | slack | service
    id: str
    title: str
    timestamp: str | None = None
    snippet: str | None = None


class TimelineEntry(BaseModel):
    timestamp: str
    event: str
    type: str = "event"   # incident | deployment | commit | alert | recovery
    service: str | None = None


class ServiceRisk(BaseModel):
    name: str
    risk_level: str       # CRITICAL | HIGH | MEDIUM | LOW
    reason: str


class InvestigationReport(BaseModel):
    """Structured output from the full investigation workflow."""
    query: str
    risk_level: str = "UNKNOWN"
    summary: str = ""
    synthesis: str = ""
    graph_analysis: str = ""
    incident_analysis: str = ""
    risk_analysis: str = ""
    affected_services: list[ServiceRisk] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)


# ── LangGraph shared state ────────────────────────────────────────────────────

class InvestigationState(TypedDict):
    # ── Input ─────────────────────────────────────────────────────────────────
    query: str
    # Prior turns: list of {"role": "user"|"assistant", "content": str}
    history: list[dict]

    # ── Query analyzer outputs (set by query_analyzer node — runs first) ──────
    # qwen2.5:1.5b reads from shared GraphCache (same Neo4j data as visualization)
    query_intent: str          # "TOPOLOGY" | "INCIDENT" | "RISK" | "PERFORMANCE" | "GENERAL"
    query_entities: list[str]  # entity names found in the Neo4j graph cache
    graph_insights: str        # insights from the Neo4j graph cache lookup
    has_graph_match: bool      # True if the cache had relevant entities

    # ── Shared investigation context (set by shared_retrieve node) ───────────
    # SharedInvestigationContext object — reused by all agents (no re-retrieval)
    shared_ctx: Any
    retrieved_context: str     # formatted string (extracted from shared_ctx)
    entities: dict
    sources: list[dict]

    # ── Evidence evaluation (set by evaluate node, heuristic — no LLM) ───────
    investigation_depth: str   # "FAST" | "STANDARD" | "DEEP"
    evidence_decision: str     # "DIRECT_RESPONSE" | "PARTIAL" | "DEEP"

    # ── Orchestrator plan (set by plan node — DEEP path only) ─────────────────
    plan: str
    # "direct" → orchestrator answers alone; "full" → fan-out to specialist agents
    decision: str
    # Subset of ["graph", "incident", "risk"] to actually run
    active_agents: list[str]

    # ── Parallel specialist outputs (each writes its own key) ─────────────────
    graph_analysis: str
    incident_analysis: str
    risk_analysis: str

    # ── Aggregated execution steps — reducer concatenates lists ───────────────
    steps: Annotated[list[dict], operator.add]

    # ── Final output ──────────────────────────────────────────────────────────
    report: dict | None
    error: str | None

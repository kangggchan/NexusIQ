"""
Investigation workflow shared state and output models.
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

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

    # ── Context retrieval (set by retrieve node) ──────────────────────────────
    retrieved_context: str
    entities: dict
    sources: list[dict]

    # ── Orchestrator plan (set by plan node) ──────────────────────────────────
    plan: str
    # "direct" → orchestrator answers alone; "full" → fan-out to specialist agents
    decision: str
    direct_answer: str
    # Subset of ["graph", "incident", "risk"] to actually run; empty = all three
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

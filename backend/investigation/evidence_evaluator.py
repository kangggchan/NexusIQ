"""
Evidence Evaluator — answer-contract-driven determination of investigation depth.

DESIGN PRINCIPLE:
Do not infer user intent again. The query_analyzer LLM already determines:
    - query intent
    - routing decision
    - the exact answer goal
    - the recommended specialist agents needed

This evaluator uses that LLM contract plus retrieval signal quality to decide:

    DIRECT_RESPONSE   → graph/retrieval context is already sufficient
    PARTIAL           → run the specific 1-2 agents recommended by the LLM
    DEEP              → run full orchestration when signal is weak or all agents are needed
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from backend.investigation.shared_context import SharedInvestigationContext, SignalStrength

log = logging.getLogger(__name__)


def _primary_agent_for_intent(intent: str, agents: list[str]) -> str | None:
    """Choose the most relevant specialist for the detected intent."""
    if not agents:
        return None
    preferred_by_intent = {
        "RISK": "risk",
        "INCIDENT": "incident",
        "TOPOLOGY": "graph",
        "PERFORMANCE": "risk",
    }
    preferred = preferred_by_intent.get(intent)
    if preferred in agents:
        return preferred
    for candidate in ("risk", "incident", "graph"):
        if candidate in agents:
            return candidate
    return agents[0]


class EvidenceDecision(str, Enum):
    DIRECT_RESPONSE = "DIRECT_RESPONSE"
    PARTIAL         = "PARTIAL"
    DEEP            = "DEEP"


@dataclass
class EvaluationResult:
    decision: EvidenceDecision
    recommended_agents: list[str]
    needs_graph_expansion: bool = False
    needs_incident_expansion: bool = False
    needs_risk_expansion: bool = False
    confidence: float = 0.0
    reasoning: str = ""

    def needs_any_expansion(self) -> bool:
        return (
            self.needs_graph_expansion
            or self.needs_incident_expansion
            or self.needs_risk_expansion
        )


# ── EvidenceEvaluator ─────────────────────────────────────────────────────────

class EvidenceEvaluator:
    """
    Answer-contract-driven evidence evaluator. Zero LLM calls, zero regex.
    Relies on the query_analyzer LLM's routing + recommended agent set.
    """

    def evaluate(
        self,
        ctx: SharedInvestigationContext,
        intent: str = "GENERAL",
        routing: str = "RETRIEVE_MORE",
        recommended_agents: list[str] | None = None,
    ) -> EvaluationResult:
        """
        Determine investigation depth from the LLM answer contract + retrieval signal.

        Args:
            ctx:     Shared retrieval context (signal, entities, incidents).
            intent:  LLM-classified intent from query_analyzer
                     (TOPOLOGY|INCIDENT|RISK|PERFORMANCE|GENERAL).
            routing: LLM routing decision from query_analyzer
                     (GRAPH_SUFFICIENT|RETRIEVE_MORE|NO_RETRIEVAL).
            recommended_agents: LLM-selected specialist agents needed for the answer.
        """
        signal  = ctx.signal
        intent  = (intent  or "GENERAL").upper()
        routing = (routing or "RETRIEVE_MORE").upper()
        valid_agents = {"graph", "incident", "risk"}
        agents = [agent for agent in (recommended_agents or []) if agent in valid_agents]

        log.info(
            "[evaluator] intent=%s routing=%s agents=%s signal=%s density=%.2f incidents=%d",
            intent, routing, agents,
            signal.signal_strength.value, signal.evidence_density, len(ctx.incidents),
        )

        # ── Graph cache already answered it — no agents needed ────────────
        if routing == "GRAPH_SUFFICIENT":
            return EvaluationResult(
                decision=EvidenceDecision.DIRECT_RESPONSE,
                recommended_agents=[],
                confidence=signal.evidence_density,
                reasoning="LLM routing=GRAPH_SUFFICIENT — existing graph/retrieval context answered the query",
            )

        # ── LOW signal — surface hidden evidence with full investigation ──
        if signal.signal_strength == SignalStrength.LOW:
            return EvaluationResult(
                decision=EvidenceDecision.DEEP,
                recommended_agents=["graph", "incident", "risk"],
                needs_graph_expansion=True,
                needs_incident_expansion=True,
                needs_risk_expansion=True,
                confidence=signal.evidence_density,
                reasoning=f"Low retrieval signal (density={signal.evidence_density:.2f}) — full investigation",
            )

        # If the LLM did not request any specialist, shared retrieval alone should
        # answer the query directly after evidence is gathered.
        # Exception: incident-intent queries with explicit incident entities should
        # still run the incident specialist to reconstruct timeline/root-cause details.
        if (
            not agents
            and intent == "INCIDENT"
            and routing == "RETRIEVE_MORE"
            and bool((ctx.entities or {}).get("incidents"))
        ):
            return EvaluationResult(
                decision=EvidenceDecision.PARTIAL,
                recommended_agents=["incident"],
                needs_incident_expansion=True,
                confidence=signal.evidence_density,
                reasoning=(
                    "Incident intent with explicit incident entity detected "
                    "— forcing incident specialist for timeline fidelity"
                ),
            )

        if not agents:
            return EvaluationResult(
                decision=EvidenceDecision.DIRECT_RESPONSE,
                recommended_agents=[],
                confidence=signal.evidence_density,
                reasoning=(
                    f"No specialist agents requested by LLM contract after retrieval "
                    f"(intent={intent}, routing={routing})"
                ),
            )

        # Three-agent fan-out is expensive enough to justify full orchestration.
        if len(agents) == 3:
            return EvaluationResult(
                decision=EvidenceDecision.DEEP,
                recommended_agents=agents,
                needs_graph_expansion=True,
                needs_incident_expansion="incident" in agents,
                needs_risk_expansion="risk" in agents,
                confidence=signal.evidence_density,
                reasoning=f"LLM requested full multi-agent analysis — agents={agents}",
            )

        selected_agents = agents
        reasoning_suffix = ""

        # High-confidence retrieval usually needs one specialist only.
        if signal.signal_strength == SignalStrength.HIGH and len(agents) > 1:
            primary = _primary_agent_for_intent(intent, agents)
            selected_agents = [primary] if primary else agents[:1]

            # For risk questions with no incident evidence yet, keep incident as fallback.
            if primary == "risk" and "incident" in agents and len(ctx.incidents) == 0:
                selected_agents = ["risk", "incident"]
                reasoning_suffix = " + incident fallback enabled (no incident evidence found)"
            else:
                reasoning_suffix = " (high-signal partial path: primary specialist only)"

        return EvaluationResult(
            decision=EvidenceDecision.PARTIAL,
            recommended_agents=selected_agents,
            needs_graph_expansion="graph" in selected_agents,
            needs_incident_expansion="incident" in selected_agents,
            needs_risk_expansion="risk" in selected_agents,
            confidence=signal.evidence_density,
            reasoning=(
                f"LLM-recommended targeted analysis — intent={intent} "
                f"agents={selected_agents}{reasoning_suffix}"
            ),
        )


# ── Module-level singleton ────────────────────────────────────────────────────

_evaluator: EvidenceEvaluator | None = None


def get_evaluator() -> EvidenceEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = EvidenceEvaluator()
    return _evaluator

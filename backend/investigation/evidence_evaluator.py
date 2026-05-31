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

        return EvaluationResult(
            decision=EvidenceDecision.PARTIAL,
            recommended_agents=agents,
            needs_graph_expansion="graph" in agents,
            needs_incident_expansion="incident" in agents,
            needs_risk_expansion="risk" in agents,
            confidence=signal.evidence_density,
            reasoning=f"LLM-recommended targeted analysis — intent={intent} agents={agents}",
        )


# ── Module-level singleton ────────────────────────────────────────────────────

_evaluator: EvidenceEvaluator | None = None


def get_evaluator() -> EvidenceEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = EvidenceEvaluator()
    return _evaluator

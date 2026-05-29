"""
Evidence Evaluator — heuristic-only determination of investigation depth.

CRITICAL DESIGN PRINCIPLE:
This evaluator uses NO LLM calls. It evaluates the shared retrieval signal
using fast heuristics to determine whether:

  DIRECT_RESPONSE   → lightweight retrieval has sufficient evidence
                       → skip agents, produce immediate answer (~0 extra latency)

  PARTIAL           → partial evidence found
                       → run 1–2 selective agents with targeted expansion

  DEEP              → weak signal or complex multi-entity query
                       → full multi-agent orchestration with all expanders

This gate prevents 3 unnecessary LLM agent calls for simple queries like:
  "Who owns telemetry-service?" → DIRECT_RESPONSE in ~2s total
  "What caused INC-042?"        → PARTIAL (incident agent only)
  "Why did cascade fail?"       → DEEP (all agents + expanders)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

from backend.investigation.shared_context import (
    SharedInvestigationContext,
    InvestigationDepth,
    SignalStrength,
    RetrievalSignal,
)

log = logging.getLogger(__name__)


class EvidenceDecision(str, Enum):
    DIRECT_RESPONSE = "DIRECT_RESPONSE"
    PARTIAL         = "PARTIAL"
    DEEP            = "DEEP"


@dataclass
class EvaluationResult:
    decision: EvidenceDecision
    recommended_agents: list[str]       # subset of ["graph", "incident", "risk"]
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


# ── Query complexity signals ──────────────────────────────────────────────────

# Patterns that indicate simple ownership/status/info lookups → DIRECT_RESPONSE
_SIMPLE_PATTERNS = [
    re.compile(r"\bwho owns?\b", re.I),
    re.compile(r"\bwho is (the )?owner\b", re.I),
    re.compile(r"\bwhat team\b", re.I),
    re.compile(r"\bwhat is the status of\b", re.I),
    re.compile(r"\blist (all )?services?\b", re.I),
    re.compile(r"\bshow me\b.*\bservice\b", re.I),
    re.compile(r"\bwhat does\b.*\bdo\b", re.I),
    re.compile(r"\btell me about\b", re.I),
    re.compile(r"\bdescribe\b.*\bservice\b", re.I),
    re.compile(r"\bcontact\b.*\bteam\b", re.I),
    # Person / entity info lookups
    re.compile(r"\bwho is\b", re.I),
    re.compile(r"\bwhat is\b.{0,40}\b(role|email|contact|phone|title|department)\b", re.I),
    re.compile(r"\btell me (more )?about\b", re.I),
    re.compile(r"\binfo(rmation)? (on|about)\b", re.I),
    re.compile(r"\bdetails? (on|about|for)\b", re.I),
    re.compile(r"\bwho (manages?|leads?|is responsible for)\b", re.I),
]

# Patterns that indicate incident/timeline analysis → PARTIAL or DEEP
_INCIDENT_PATTERNS = [
    re.compile(r"\bINC-\d+\b", re.I),
    re.compile(r"\boutage\b", re.I),
    re.compile(r"\bincident\b", re.I),
    re.compile(r"\bfailed?\b", re.I),
    re.compile(r"\balert\b", re.I),
    re.compile(r"\bdown\b", re.I),
    re.compile(r"\blatency spike\b", re.I),
    re.compile(r"\berror rate\b", re.I),
]

# Patterns that indicate causal / cascading analysis → DEEP
_DEEP_PATTERNS = [
    re.compile(r"\broot cause\b", re.I),
    re.compile(r"\bwhy did\b", re.I),
    re.compile(r"\bcascad\b", re.I),
    re.compile(r"\bblast radius\b", re.I),
    re.compile(r"\bdownstream\b", re.I),
    re.compile(r"\bimpact analysis\b", re.I),
    re.compile(r"\bRCA\b"),
    re.compile(r"\bfailure propagat\b", re.I),
    re.compile(r"\bpostmortem\b", re.I),
]

# Patterns that force graph agent → dependency / ownership analysis
_GRAPH_PATTERNS = [
    re.compile(r"\bdepend\b", re.I),
    re.compile(r"\bupstream\b", re.I),
    re.compile(r"\bdownstream\b", re.I),
    re.compile(r"\btopology\b", re.I),
    re.compile(r"\bservice graph\b", re.I),
    re.compile(r"\bownership\b", re.I),
    re.compile(r"\bblast radius\b", re.I),
]

# Patterns that force risk agent
_RISK_PATTERNS = [
    re.compile(r"\brisk\b", re.I),
    re.compile(r"\bhow dangerous\b", re.I),
    re.compile(r"\bcritical\b", re.I),
    re.compile(r"\bcascad\b", re.I),
    re.compile(r"\bmitigat\b", re.I),
    re.compile(r"\bvulnerab\b", re.I),
]


def _matches_any(query: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(query) for p in patterns)


# ── EvidenceEvaluator ─────────────────────────────────────────────────────────

class EvidenceEvaluator:
    """
    Heuristic evidence evaluator.
    Zero LLM calls. Runs in microseconds.
    """

    def evaluate(
        self,
        ctx: SharedInvestigationContext,
    ) -> EvaluationResult:
        """
        Evaluate the shared context and determine investigation depth.

        Decision logic (in priority order):
          1. Deep patterns in query → always DEEP
          2. Simple pattern + MEDIUM/HIGH signal → DIRECT_RESPONSE  (before entity count)
          3. Multiple entities (≥3) → DEEP
          4. Single service + HIGH signal → DIRECT_RESPONSE
          5. Incident patterns + MEDIUM/HIGH signal → PARTIAL (incident agent)
          6. Anything else → DEEP (conservative default)
        """
        query = ctx.query
        signal = ctx.signal
        entities = ctx.entities
        entity_count = sum(
            len(v) for v in entities.values() if isinstance(v, list)
        )

        is_simple    = _matches_any(query, _SIMPLE_PATTERNS)
        is_incident  = _matches_any(query, _INCIDENT_PATTERNS)
        is_deep      = _matches_any(query, _DEEP_PATTERNS)
        needs_graph  = _matches_any(query, _GRAPH_PATTERNS)
        needs_risk   = _matches_any(query, _RISK_PATTERNS)

        log.info(
            "[evaluator] simple=%s incident=%s deep=%s entities=%d signal=%s density=%.2f",
            is_simple, is_incident, is_deep, entity_count,
            signal.signal_strength.value, signal.evidence_density,
        )

        # ── Rule 1: explicit deep/RCA query → always DEEP ─────────────────
        if is_deep:
            agents = ["graph", "incident", "risk"]
            return EvaluationResult(
                decision=EvidenceDecision.DEEP,
                recommended_agents=agents,
                needs_graph_expansion=True,
                needs_incident_expansion=True,
                needs_risk_expansion=True,
                confidence=signal.evidence_density,
                reasoning="Deep/RCA query detected — full orchestration required",
            )

        # ── Rule 2: simple query + good evidence → DIRECT (checked before entity count)
        # This must fire before entity-count checks so that simple person/info
        # lookups returning multiple entity types still get a fast response.
        if (
            is_simple
            and signal.signal_strength in (SignalStrength.HIGH, SignalStrength.MEDIUM)
            and signal.evidence_density >= 0.4
            and not is_incident
        ):
            return EvaluationResult(
                decision=EvidenceDecision.DIRECT_RESPONSE,
                recommended_agents=[],
                confidence=signal.evidence_density,
                reasoning=(
                    f"Simple query + {signal.signal_strength.value} signal "
                    f"(density={signal.evidence_density:.2f}) — direct answer sufficient"
                ),
            )

        # ── Rule 3: high entity count → multi-agent needed ─────────────────
        if entity_count >= 3:
            agents = ["graph", "incident"]
            if needs_risk:
                agents.append("risk")
            return EvaluationResult(
                decision=EvidenceDecision.DEEP,
                recommended_agents=agents,
                needs_graph_expansion=True,
                needs_incident_expansion=len(ctx.incidents) > 0,
                needs_risk_expansion=needs_risk,
                confidence=signal.evidence_density,
                reasoning=f"High entity count ({entity_count}) — multi-agent needed",
            )

        # ── Rule 4: single specific entity + HIGH signal → DIRECT ──────────
        if (
            entity_count == 1
            and signal.signal_strength == SignalStrength.HIGH
            and signal.evidence_density >= 0.65
            and not is_incident
            and not is_deep
        ):
            # Only need graph if explicit dependency question
            agents = ["graph"] if needs_graph else []
            if not agents:
                return EvaluationResult(
                    decision=EvidenceDecision.DIRECT_RESPONSE,
                    recommended_agents=[],
                    confidence=signal.evidence_density,
                    reasoning=(
                        f"Single entity + HIGH signal (density={signal.evidence_density:.2f}) "
                        "— lightweight retrieval sufficient"
                    ),
                )

        # ── Rule 5: incident query + evidence → PARTIAL (incident agent) ───
        if is_incident and signal.signal_strength != SignalStrength.LOW:
            agents = ["incident"]
            if needs_graph or entity_count >= 2:
                agents.insert(0, "graph")
            if needs_risk:
                agents.append("risk")
            return EvaluationResult(
                decision=EvidenceDecision.PARTIAL,
                recommended_agents=agents,
                needs_graph_expansion="graph" in agents,
                needs_incident_expansion=True,
                needs_risk_expansion=needs_risk,
                confidence=signal.evidence_density,
                reasoning=(
                    f"Incident query + {signal.signal_strength.value} signal "
                    f"— selective expansion: {agents}"
                ),
            )

        # ── Rule 6: graph-only question with good evidence → PARTIAL ───────
        if needs_graph and not is_incident and signal.signal_strength != SignalStrength.LOW:
            agents = ["graph"]
            if needs_risk:
                agents.append("risk")
            return EvaluationResult(
                decision=EvidenceDecision.PARTIAL,
                recommended_agents=agents,
                needs_graph_expansion=True,
                needs_incident_expansion=False,
                needs_risk_expansion=needs_risk,
                confidence=signal.evidence_density,
                reasoning=f"Graph-focus query — selective expansion: {agents}",
            )

        # ── Rule 7: LOW signal → full investigation ─────────────────────────
        if signal.signal_strength == SignalStrength.LOW:
            return EvaluationResult(
                decision=EvidenceDecision.DEEP,
                recommended_agents=["graph", "incident", "risk"],
                needs_graph_expansion=True,
                needs_incident_expansion=True,
                needs_risk_expansion=True,
                confidence=signal.evidence_density,
                reasoning="Low signal strength — full investigation to surface evidence",
            )

        # ── Default: conservative PARTIAL ──────────────────────────────────
        agents = []
        if needs_graph or entity_count >= 1:
            agents.append("graph")
        if is_incident:
            agents.append("incident")
        if needs_risk:
            agents.append("risk")
        if not agents:
            agents = ["graph", "incident"]

        return EvaluationResult(
            decision=EvidenceDecision.PARTIAL,
            recommended_agents=agents,
            needs_graph_expansion="graph" in agents,
            needs_incident_expansion="incident" in agents,
            needs_risk_expansion="risk" in agents,
            confidence=signal.evidence_density,
            reasoning=f"Conservative partial investigation — agents: {agents}",
        )


# ── Module-level singleton ────────────────────────────────────────────────────

_evaluator: EvidenceEvaluator | None = None


def get_evaluator() -> EvidenceEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = EvidenceEvaluator()
    return _evaluator

"""
Risk Context Expander — expands downstream blast radius and risk topology.

This expander is called ONLY when:
  - The evidence evaluator recommends risk expansion
  - The risk agent needs cascade failure analysis

It REUSES topology data from SharedInvestigationContext and adds:
  - 2-hop downstream blast radius
  - Service risk scores
  - Cascade failure paths

NEVER re-runs full graph traversal. Uses graph_expander for topology.
"""
from __future__ import annotations

import logging

from backend.investigation.shared_context import SharedInvestigationContext
from backend.retrieval.context_expanders.graph_expander import get_graph_expander

log = logging.getLogger(__name__)

# Risk level thresholds based on hop count and service metadata
_CRITICAL_STATUSES = {"degraded", "incident", "down", "critical"}


class RiskExpander:
    """
    Expands risk context by analyzing blast radius topology.

    Delegates graph expansion to GraphExpander (reuses its cache),
    then enriches with risk scoring based on service metadata.
    """

    async def expand(self, ctx: SharedInvestigationContext) -> None:
        """
        Expand risk context in-place.
        Fetches blast radius, then computes risk levels from topology.
        """
        graph_expander = get_graph_expander()

        # Reuse graph expander for blast radius (avoids duplicate Neo4j calls)
        if not ctx.expanded_risk.get("blast_radius"):
            await graph_expander.expand_blast_radius(ctx)

        # Also ensure 2-hop topology is available for cascade analysis
        if not ctx.expanded_graph:
            await graph_expander.expand(ctx)

        # Compute risk scores from expanded topology
        blast_radius = ctx.expanded_risk.get("blast_radius", [])
        risk_scores  = _compute_risk_scores(blast_radius, ctx)

        ctx.expanded_risk["risk_scores"]      = risk_scores
        ctx.expanded_risk["cascade_paths"]    = _find_cascade_paths(ctx)
        ctx.expanded_risk["critical_services"] = [
            r for r in risk_scores if r.get("risk_level") == "CRITICAL"
        ]

        log.info(
            "[risk_expander] blast_radius=%d risk_scores=%d critical=%d",
            len(blast_radius),
            len(risk_scores),
            len(ctx.expanded_risk["critical_services"]),
        )


def _compute_risk_scores(
    blast_radius: list[dict],
    ctx: SharedInvestigationContext,
) -> list[dict]:
    """
    Assign risk levels to blast-radius services based on:
    - Hop distance (closer = higher risk)
    - Service status (degraded/incident = higher risk)
    - Whether the service itself had incidents
    """
    incident_services: set[str] = set()
    for inc in ctx.incidents:
        # Gather service names from incident metadata
        for svc in inc.get("affected_services", []):
            name = svc.get("name", "") if isinstance(svc, dict) else svc
            if name:
                incident_services.add(name.lower())

    scores = []
    for svc in blast_radius:
        name   = svc.get("dep_name", svc.get("name", ""))
        hops   = svc.get("hops", 999)
        status = (svc.get("dep_status", svc.get("status", "")) or "").lower()
        is_incident_service = name.lower() in incident_services

        if hops == 1 or is_incident_service or status in _CRITICAL_STATUSES:
            level = "CRITICAL"
        elif hops == 2:
            level = "HIGH"
        else:
            level = "MEDIUM"

        reason_parts = []
        if hops <= 2:
            reason_parts.append(f"directly affected ({hops}-hop)")
        if is_incident_service:
            reason_parts.append("involved in active incidents")
        if status in _CRITICAL_STATUSES:
            reason_parts.append(f"status={status}")

        scores.append({
            "name": name,
            "risk_level": level,
            "hops": hops,
            "status": status,
            "reason": "; ".join(reason_parts) or f"{hops}-hop dependent",
            "team": svc.get("dep_team", svc.get("team", "")),
        })

    # Sort: CRITICAL first, then by hops
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    scores.sort(key=lambda x: (order.get(x["risk_level"], 4), x.get("hops", 999)))
    return scores


def _find_cascade_paths(ctx: SharedInvestigationContext) -> list[str]:
    """
    Identify potential cascade failure paths from expanded topology.
    Returns human-readable path strings.
    """
    paths = []
    services = ctx.entities.get("services", [])

    for svc in services[:3]:
        neighbors = ctx.expanded_graph.get(svc, [])
        if neighbors:
            path_services = [n.get("dep_name", "") for n in neighbors[:4] if n.get("dep_name")]
            if path_services:
                paths.append(f"{svc} → {' → '.join(path_services)}")

    return paths


# ── Singleton ─────────────────────────────────────────────────────────────────

_expander: RiskExpander | None = None


def get_risk_expander() -> RiskExpander:
    global _expander
    if _expander is None:
        _expander = RiskExpander()
    return _expander

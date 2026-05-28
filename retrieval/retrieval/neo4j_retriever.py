"""
Graph retriever — runs targeted Cypher queries based on detected entities.
Returns structured GraphResult objects for downstream fusion.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from retrieval.graph.neo4j_client import get_session
from retrieval.graph import cypher_queries as q
from retrieval.retrieval.entity_detector import DetectedEntities
from retrieval.config import settings

log = logging.getLogger(__name__)


@dataclass
class GraphResult:
    id: str
    type: str               # "incident" | "service" | "deployment" | etc.
    content: str            # human-readable summary
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 1.0      # raw graph score (≥1 for known entities, 0.5 otherwise)


class Neo4jRetriever:
    """
    Dispatches Neo4j queries based on detected entity types
    and returns a flat list of GraphResult objects.
    """

    async def retrieve(
        self,
        entities: DetectedEntities,
        query: str,
    ) -> list[GraphResult]:
        results: list[GraphResult] = []

        async with get_session() as session:
            # ── Incidents ─────────────────────────────────────────────────────
            for inc_id in entities.incidents:
                ctx = await q.get_incident_full_context(session, inc_id.upper())
                if ctx and ctx.get("incident"):
                    results.append(_incident_result(ctx))

            # ── Services ──────────────────────────────────────────────────────
            for svc_name in entities.services:
                svc = await q.get_service_by_name(session, svc_name)
                if svc:
                    results.extend(await _service_results(session, svc))

            # ── Employees ─────────────────────────────────────────────────────
            for emp_id in entities.employees:
                svcs = await q.get_employee_services(session, emp_id.upper())
                if svcs:
                    results.append(GraphResult(
                        id=emp_id,
                        type="employee",
                        content=(
                            f"Employee {emp_id} owns services: "
                            + ", ".join(s.get("name", "") for s in svcs)
                        ),
                        metadata={"employee_id": emp_id, "services": svcs},
                    ))

            # ── Deployments ───────────────────────────────────────────────────
            # (Deployment-specific queries handled via service context above)

            # ── Fallback: broad service search when no entities detected ──────
            if entities.is_empty():
                results.extend(await _broad_search(session, query))

        log.debug("Graph retriever returned %d results", len(results))
        return results


# ── Result builders ───────────────────────────────────────────────────────────

def _incident_result(ctx: dict) -> GraphResult:
    inc = ctx["incident"]
    affected = ", ".join(
        s.get("name", "") for s in ctx.get("affected_services", []) if s.get("name")
    )
    deployments = ctx.get("deployments", [])
    commits = ctx.get("commits", [])

    content = (
        f"[INCIDENT {inc.get('incident_id', '')}] {inc.get('title', '')}\n"
        f"Severity: {inc.get('severity', '')} | "
        f"Started: {inc.get('started_at', '')} | Ended: {inc.get('ended_at', '')}\n"
        f"Affected services: {affected}\n"
        f"Root cause: {inc.get('root_cause', '')}\n"
    )
    if deployments:
        dep_summary = ", ".join(
            f"{d.get('id', '')} ({d.get('service', '')} {d.get('version', '')} {d.get('status', '')})"
            for d in deployments[:3]
        )
        content += f"Nearby deployments: {dep_summary}\n"
    if commits:
        commit_summary = ", ".join(
            f"{c.get('id', '')[:8]}: {c.get('msg', '')[:60]}"
            for c in commits[:3]
        )
        content += f"Nearby commits: {commit_summary}\n"

    return GraphResult(
        id=inc.get("incident_id", ""),
        type="incident",
        content=content,
        metadata=ctx,
        score=1.0,
    )


async def _service_results(session, svc: dict) -> list[GraphResult]:
    results = []
    name = svc.get("name", "")

    # Service node itself
    results.append(GraphResult(
        id=svc.get("service_id", name),
        type="service",
        content=(
            f"[SERVICE] {name} (team: {svc.get('team', '')}, "
            f"project: {svc.get('project', '')})\n"
            f"Description: {svc.get('description', '')}"
        ),
        metadata=svc,
        score=1.0,
    ))

    # Dependencies
    deps = await q.get_service_dependencies(session, name, depth=settings.graph_max_depth)
    if deps:
        dep_list = ", ".join(d.get("dep_name", "") for d in deps)
        results.append(GraphResult(
            id=f"{name}_deps",
            type="service_dependency",
            content=f"[DEPENDENCIES] {name} depends on: {dep_list}",
            metadata={"service": name, "dependencies": deps},
            score=0.9,
        ))

    # Blast radius
    dependents = await q.get_service_dependents(session, name, depth=settings.graph_max_depth)
    if dependents:
        dep_list = ", ".join(d.get("dep_name", "") for d in dependents)
        results.append(GraphResult(
            id=f"{name}_dependents",
            type="service_blast_radius",
            content=f"[BLAST RADIUS] Services depending on {name}: {dep_list}",
            metadata={"service": name, "dependents": dependents},
            score=0.9,
        ))

    # Recent incidents
    incidents = await q.get_incidents_for_service(session, name)
    for inc in incidents[:3]:
        results.append(GraphResult(
            id=inc.get("id", ""),
            type="incident_ref",
            content=(
                f"[INCIDENT {inc.get('id', '')}] {inc.get('title', '')} "
                f"({inc.get('severity', '')}) affecting {name}"
            ),
            metadata=inc,
            score=0.8,
        ))

    return results


async def _broad_search(session, query: str) -> list[GraphResult]:
    """No specific entities — return recent deployments across services."""
    result = await session.run(
        """
        MATCH (d:Deployment)
        WHERE d.status IN ['failed', 'rolled_back']
        RETURN d.deployment_id AS id, d.service AS service,
               d.status AS status, d.timestamp AS ts
        ORDER BY d.timestamp DESC LIMIT 5
        """
    )
    rows = [dict(r) async for r in result]
    results = []
    for row in rows:
        results.append(GraphResult(
            id=row.get("id", ""),
            type="deployment",
            content=(
                f"[DEPLOYMENT] {row.get('id', '')} — "
                f"{row.get('service', '')} status={row.get('status', '')} at {row.get('ts', '')}"
            ),
            metadata=row,
            score=0.5,
        ))
    return results

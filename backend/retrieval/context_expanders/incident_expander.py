"""
Incident Context Expander — expands timeline data beyond base incident records.

This expander is called ONLY when:
  - The evidence evaluator recommends incident expansion
  - The incident agent needs full timeline reconstruction

It REUSES existing incidents and deployments from SharedInvestigationContext
and fetches ONLY missing timeline data (commits, Jira tickets, extended deployments).

NEVER re-fetches incident records already in ctx.incidents.
"""
from __future__ import annotations

import asyncio
import logging

from retrieval.graph.neo4j_client import get_session
from retrieval.graph import cypher_queries as q

from backend.cache.retrieval_cache import get_graph_cache, graph_key, GRAPH_TTL
from backend.investigation.shared_context import SharedInvestigationContext

log = logging.getLogger(__name__)


class IncidentExpander:
    """
    Selectively expands incident timeline data.

    Strategy:
      - Base retrieval already has: incidents, deployments (from incident_full_context)
      - Expansion adds: commits, Jira tickets, extended deployment history
      - Each expansion is cached per service/incident
    """

    def __init__(self) -> None:
        self._cache = get_graph_cache()

    async def expand(self, ctx: SharedInvestigationContext) -> None:
        """
        Expand incident timeline context in-place.
        Fetches commits and Jira tickets for detected services/incidents.
        """
        services  = ctx.entities.get("services", [])
        incidents = ctx.entities.get("incidents", [])

        if not services and not incidents:
            log.debug("[incident_expander] no services or incidents to expand")
            return

        # Already have: ctx.incidents (incident records), ctx.deployments
        # Need: commits per service, Jira tickets, extended deployment history

        timeline_entries: list[dict] = []

        tasks = []
        # Fetch commits for detected services (missing from base retrieval)
        for svc in services[:4]:
            tasks.append(self._expand_service_commits(svc))
            tasks.append(self._expand_service_jira(svc))

        # Fetch extended deployment history for services
        for svc in services[:4]:
            tasks.append(self._expand_service_deployments(svc))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                log.warning("[incident_expander] expansion failed: %s", result)
            elif isinstance(result, list):
                timeline_entries.extend(result)

        ctx.expanded_incidents = timeline_entries
        log.info(
            "[incident_expander] expanded %d timeline entries",
            len(timeline_entries),
        )

    async def _expand_service_commits(self, svc_name: str) -> list[dict]:
        k = graph_key(svc_name, 0, "commits")
        cached = await self._cache.get(k)
        if cached is not None:
            return cached

        async with get_session() as session:
            commits = await q.get_commits_for_service(session, svc_name, limit=8)

        entries = [
            {
                "type": "commit",
                "service": svc_name,
                "timestamp": c.get("ts", ""),
                "event": f"Commit: {c.get('message', '')[:80]} (by {c.get('author', 'unknown')})",
            }
            for c in commits
        ]
        await self._cache.set(k, entries, ttl=GRAPH_TTL)
        return entries

    async def _expand_service_jira(self, svc_name: str) -> list[dict]:
        k = graph_key(svc_name, 0, "jira")
        cached = await self._cache.get(k)
        if cached is not None:
            return cached

        async with get_session() as session:
            tickets = await q.get_jira_tickets_for_service(session, svc_name)

        entries = [
            {
                "type": "jira",
                "service": svc_name,
                "timestamp": "",
                "event": (
                    f"Jira [{t.get('id', '')}] {t.get('summary', '')[:80]} "
                    f"[{t.get('priority', '')} / {t.get('status', '')}]"
                ),
            }
            for t in tickets[:6]
        ]
        await self._cache.set(k, entries, ttl=GRAPH_TTL)
        return entries

    async def _expand_service_deployments(self, svc_name: str) -> list[dict]:
        k = graph_key(svc_name, 0, "deploys_extended")
        cached = await self._cache.get(k)
        if cached is not None:
            return cached

        async with get_session() as session:
            deploys = await q.get_recent_deployments(session, svc_name, limit=6)

        entries = [
            {
                "type": "deployment",
                "service": svc_name,
                "timestamp": d.get("ts", ""),
                "event": (
                    f"Deploy [{d.get('id', '')}] {svc_name} v{d.get('version', '')} "
                    f"→ {d.get('env', '')} [{d.get('status', '')}]"
                    + (f" by {d.get('deployed_by', '')}" if d.get("deployed_by") else "")
                ),
            }
            for d in deploys
        ]
        await self._cache.set(k, entries, ttl=GRAPH_TTL)
        return entries


# ── Singleton ─────────────────────────────────────────────────────────────────

_expander: IncidentExpander | None = None


def get_incident_expander() -> IncidentExpander:
    global _expander
    if _expander is None:
        _expander = IncidentExpander()
    return _expander

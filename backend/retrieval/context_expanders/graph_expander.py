"""
Graph Context Expander — incrementally expands graph topology from base context.

This expander is called ONLY when:
  - The evidence evaluator recommends graph expansion
  - The graph agent needs 2-hop topology or blast radius

It REUSES the SharedInvestigationContext's existing 1-hop data and
extends it with targeted 2-hop traversal for specific entities only.

NEVER re-runs full retrieval. Only fetches MISSING evidence.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from retrieval.graph.neo4j_client import get_session
from retrieval.graph import cypher_queries as q

from backend.cache.retrieval_cache import get_graph_cache, graph_key, GRAPH_TTL
from backend.investigation.shared_context import SharedInvestigationContext

log = logging.getLogger(__name__)

# 2-hop expansion — used only when evaluator requires it
EXPANSION_DEPTH = 2


class GraphExpander:
    """
    Selectively expands graph topology beyond the 1-hop base retrieval.

    Expansion strategy:
      - Check which services are NOT yet in graph_neighbors
      - Fetch 2-hop dependencies for those services only
      - Cache each expansion result individually
      - Append to ctx.expanded_graph in-place
    """

    def __init__(self) -> None:
        self._cache = get_graph_cache()

    async def expand(self, ctx: SharedInvestigationContext) -> None:
        """
        Expand graph context in-place on the SharedInvestigationContext.
        Returns immediately if no services to expand.
        """
        services = ctx.entities.get("services", [])
        if not services:
            log.debug("[graph_expander] no services to expand")
            return

        # Only expand services not already in base neighbors
        to_expand = [
            svc for svc in services
            if svc not in ctx.expanded_graph and svc not in ctx.graph_neighbors
        ]
        # Also expand services that are in base but only have 1-hop
        # (graph_neighbors has 1-hop; we need 2-hop for risk analysis)
        already_shallow = [
            svc for svc in services
            if svc in ctx.graph_neighbors and svc not in ctx.expanded_graph
        ]

        if not to_expand and not already_shallow:
            log.debug("[graph_expander] all services already expanded")
            return

        log.info(
            "[graph_expander] expanding %d new + %d shallow services to 2-hop",
            len(to_expand), len(already_shallow),
        )

        all_to_expand = list(set(to_expand + already_shallow))

        results = await asyncio.gather(
            *[self._expand_service(svc) for svc in all_to_expand[:6]],
            return_exceptions=True,
        )

        for svc, result in zip(all_to_expand, results):
            if isinstance(result, Exception):
                log.warning("[graph_expander] failed for %s: %s", svc, result)
            elif result:
                ctx.expanded_graph[svc] = result
                ctx.expanded_entities.add(svc)

        log.info("[graph_expander] expanded %d services", len(ctx.expanded_graph))

    async def expand_blast_radius(self, ctx: SharedInvestigationContext) -> None:
        """
        Fetch downstream blast radius for all detected services.
        Appends to ctx.expanded_risk.
        """
        services = ctx.entities.get("services", [])
        if not services:
            return

        blast_radius: list[dict] = []
        for svc in services[:4]:
            k = graph_key(svc, EXPANSION_DEPTH, "blast_radius")
            cached = await self._cache.get(k)
            if cached is not None:
                blast_radius.extend(cached)
                continue
            async with get_session() as session:
                deps = await q.get_service_dependents(session, svc, depth=EXPANSION_DEPTH)
                for d in deps:
                    d["source_service"] = svc
                blast_radius.extend(deps)
                await self._cache.set(k, deps, ttl=GRAPH_TTL)

        ctx.expanded_risk["blast_radius"] = blast_radius
        log.info("[graph_expander] blast radius: %d affected services", len(blast_radius))

    async def _expand_service(self, svc_name: str) -> list[dict]:
        """Fetch 2-hop dependencies for a service (cached)."""
        k = graph_key(svc_name, EXPANSION_DEPTH, "deps")
        cached = await self._cache.get(k)
        if cached is not None:
            return cached

        async with get_session() as session:
            deps = await q.get_service_dependencies(session, svc_name, depth=EXPANSION_DEPTH)

        await self._cache.set(k, deps, ttl=GRAPH_TTL)
        return deps


# ── Singleton ─────────────────────────────────────────────────────────────────

_expander: GraphExpander | None = None


def get_graph_expander() -> GraphExpander:
    global _expander
    if _expander is None:
        _expander = GraphExpander()
    return _expander

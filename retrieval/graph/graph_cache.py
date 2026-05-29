"""
Shared in-memory graph cache.

The /graph/visualization endpoint populates this cache once after
fetching from Neo4j.  The graph inspector (and any other consumer)
reads from it — no second Neo4j round-trip.

Thread/task safety: asyncio is single-threaded; writes happen only from
the visualization endpoint so no locking is needed.
"""
from __future__ import annotations

import time
import logging
from typing import Any

log = logging.getLogger(__name__)

# Cache TTL mirrors the Next.js revalidate interval (60 s) — keep them aligned.
_CACHE_TTL = 60.0


class GraphCache:
    """
    Holds the last successful result of /graph/visualization.

    Fields mirror the entity/relationship dicts produced by graph_api.py:
      entity:       { id, human_readable_id, title, type, description, degree, ... }
      relationship: { id, source, target, description, weight, ... }
    """

    def __init__(self) -> None:
        self._entities:      list[dict[str, Any]] = []
        self._relationships: list[dict[str, Any]] = []
        self._populated_at:  float = 0.0

    # ── Write (called by /graph/visualization after Neo4j fetch) ─────────────

    def populate(
        self,
        entities:      list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> None:
        self._entities      = entities
        self._relationships = relationships
        self._populated_at  = time.monotonic()
        log.info(
            "[graph_cache] populated: %d entities, %d relationships",
            len(entities), len(relationships),
        )

    # ── Read ──────────────────────────────────────────────────────────────────

    @property
    def entities(self) -> list[dict[str, Any]]:
        return self._entities

    @property
    def relationships(self) -> list[dict[str, Any]]:
        return self._relationships

    @property
    def is_populated(self) -> bool:
        return bool(self._entities)

    @property
    def is_stale(self) -> bool:
        """True if cache is older than TTL (used for optional background refresh)."""
        return (time.monotonic() - self._populated_at) > _CACHE_TTL

    def stats(self) -> dict[str, Any]:
        age = time.monotonic() - self._populated_at if self._populated_at else None
        return {
            "entities":      len(self._entities),
            "relationships": len(self._relationships),
            "age_seconds":   round(age, 1) if age is not None else None,
            "is_stale":      self.is_stale,
        }


# Module singleton — imported by both graph_api.py and graph_inspector.py
_cache = GraphCache()


def get_graph_cache() -> GraphCache:
    return _cache

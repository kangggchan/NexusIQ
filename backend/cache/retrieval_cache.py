"""
Retrieval cache — in-memory TTL cache for shared investigation context.

Caches:
  - SharedInvestigationContext keyed by (query_hash, entity_hash)
  - Embedding vectors keyed by text
  - Graph traversal results keyed by (service_name, depth)

Design principles:
  - Thread-safe via asyncio.Lock
  - TTL-based expiry (default 5 minutes)
  - LRU eviction when capacity exceeded
  - No external dependencies (no Redis required)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

# Default TTLs (seconds)
CONTEXT_TTL   = 300   # 5 min — investigation context
EMBEDDING_TTL = 3600  # 1 hour — embeddings change only when model changes
GRAPH_TTL     = 120   # 2 min — graph data can change more frequently


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    hits: int = 0

    def is_valid(self) -> bool:
        return time.monotonic() < self.expires_at


class TTLCache:
    """
    Async-safe TTL LRU cache.
    All public methods are coroutine-safe via a single asyncio.Lock.
    """

    def __init__(self, max_size: int = 256, default_ttl: float = 300.0) -> None:
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max_size = max_size
        self._default_ttl = default_ttl

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if not entry.is_valid():
                del self._store[key]
                log.debug("Cache miss (expired): %s", key[:40])
                return None
            # Move to end (LRU update)
            self._store.move_to_end(key)
            entry.hits += 1
            log.debug("Cache hit (%dx): %s", entry.hits, key[:40])
            return entry.value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        async with self._lock:
            ttl = ttl if ttl is not None else self._default_ttl
            self._store[key] = CacheEntry(
                value=value,
                expires_at=time.monotonic() + ttl,
            )
            self._store.move_to_end(key)
            # Evict oldest if over capacity
            while len(self._store) > self._max_size:
                evicted_key, _ = self._store.popitem(last=False)
                log.debug("Cache evict (LRU): %s", evicted_key[:40])

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def stats(self) -> dict:
        async with self._lock:
            now = time.monotonic()
            valid = sum(1 for e in self._store.values() if e.is_valid())
            total_hits = sum(e.hits for e in self._store.values())
            return {
                "size": len(self._store),
                "valid": valid,
                "expired": len(self._store) - valid,
                "total_hits": total_hits,
                "max_size": self._max_size,
            }


# ── Key builders ──────────────────────────────────────────────────────────────

def context_key(query: str, entity_fingerprint: str = "") -> str:
    """Cache key for SharedInvestigationContext."""
    raw = f"ctx:{query.lower().strip()}:{entity_fingerprint}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def embedding_key(text: str) -> str:
    """Cache key for embedding vectors."""
    raw = f"emb:{text.lower().strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def graph_key(entity: str, depth: int, query_type: str = "") -> str:
    """Cache key for graph traversal results."""
    raw = f"graph:{entity.lower()}:{depth}:{query_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Module-level singletons ───────────────────────────────────────────────────

_context_cache:   TTLCache | None = None
_embedding_cache: TTLCache | None = None
_graph_cache:     TTLCache | None = None


def get_context_cache() -> TTLCache:
    global _context_cache
    if _context_cache is None:
        _context_cache = TTLCache(max_size=128, default_ttl=CONTEXT_TTL)
    return _context_cache


def get_embedding_cache() -> TTLCache:
    global _embedding_cache
    if _embedding_cache is None:
        _embedding_cache = TTLCache(max_size=512, default_ttl=EMBEDDING_TTL)
    return _embedding_cache


def get_graph_cache() -> TTLCache:
    global _graph_cache
    if _graph_cache is None:
        _graph_cache = TTLCache(max_size=256, default_ttl=GRAPH_TTL)
    return _graph_cache

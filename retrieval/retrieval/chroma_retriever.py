"""
ChromaDB semantic retriever.
Embeds the query, searches across all (or specified) collections, returns VectorResult objects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from retrieval.vector.chroma_client import get_or_create_collection
from retrieval.ingestion.embedding_pipeline import EmbeddingPipeline
from retrieval.retrieval.entity_detector import DetectedEntities
from retrieval.schema.chroma_schema import COLLECTIONS, ALL_COLLECTION_NAMES
from retrieval.config import settings

log = logging.getLogger(__name__)


@dataclass
class VectorResult:
    id: str
    collection: str
    document: str
    metadata: dict[str, Any] = field(default_factory=dict)
    distance: float = 0.0    # lower = more similar (cosine distance)

    @property
    def score(self) -> float:
        """Similarity score in [0, 1]: 1 = identical."""
        return max(0.0, 1.0 - self.distance)


class ChromaRetriever:
    """
    Semantic search across ChromaDB collections.
    Optionally restricts which collections are queried based on detected entities.
    """

    def __init__(self) -> None:
        self._embedder = EmbeddingPipeline()

    async def search(
        self,
        query: str,
        entities: DetectedEntities | None = None,
        collections: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[VectorResult]:
        """
        Search ChromaDB.

        :param query: Natural language query string.
        :param entities: Detected entities — used to infer relevant collections.
        :param collections: Explicit list of collection *keys* (from chroma_schema.COLLECTIONS).
        :param top_k: Number of results per collection (defaults to settings.vector_top_k).
        """
        k = top_k or settings.vector_top_k
        target_keys = collections or _infer_collections(entities)

        query_embedding = await self._embedder.embed(query)

        all_results: list[VectorResult] = []
        for col_key in target_keys:
            col_def = COLLECTIONS.get(col_key)
            if col_def is None:
                log.warning("Unknown collection key: %s", col_key)
                continue
            try:
                results = await self._query_collection(
                    col_def.name, query_embedding, k
                )
                all_results.extend(results)
            except Exception as exc:
                log.warning("ChromaDB query failed for %s: %s", col_key, exc)

        log.debug("ChromaDB retriever returned %d results", len(all_results))
        return all_results

    async def _query_collection(
        self,
        collection_name: str,
        embedding: list[float],
        top_k: int,
    ) -> list[VectorResult]:
        collection = await get_or_create_collection(collection_name)
        response = await collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        results = []
        ids       = (response.get("ids") or [[]])[0]
        docs      = (response.get("documents") or [[]])[0]
        metas     = (response.get("metadatas") or [[]])[0]
        distances = (response.get("distances") or [[]])[0]

        for doc_id, doc, meta, dist in zip(ids, docs, metas, distances):
            results.append(VectorResult(
                id=doc_id,
                collection=collection_name,
                document=doc or "",
                metadata=meta or {},
                distance=float(dist),
            ))
        return results


# ── Collection selection heuristic ───────────────────────────────────────────

def _infer_collections(entities: DetectedEntities | None) -> list[str]:
    """
    Choose relevant collections based on which entity types were detected.
    Falls back to all collections when no entities are found.
    """
    if entities is None or entities.is_empty():
        return list(COLLECTIONS.keys())

    keys: list[str] = []
    if entities.incidents:
        keys.extend(["incidents", "slack", "jira", "deployments", "commits"])
    if entities.services:
        keys.extend(["incidents", "deployments", "commits", "jira"])
    if entities.jira_tickets:
        keys.extend(["jira", "commits", "slack"])
    if entities.commits:
        keys.extend(["commits", "deployments"])
    if entities.deployments:
        keys.extend(["deployments", "commits", "incidents"])

    # Always include documents for contextual understanding
    keys.extend(["tech_docs", "meeting_notes"])

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result

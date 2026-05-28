"""
Hybrid retriever — orchestrates the full retrieval pipeline:

  Query → Entity Detection → [Neo4j Graph + ChromaDB Vector] (parallel)
        → RRF Reranking → Context Fusion → FusedContext
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from retrieval.retrieval.entity_detector import get_detector, DetectedEntities
from retrieval.retrieval.neo4j_retriever import Neo4jRetriever
from retrieval.retrieval.chroma_retriever import ChromaRetriever
from retrieval.retrieval.reranker import rrf_fuse
from retrieval.retrieval.context_fusion import fuse_context, FusedContext
from retrieval.config import settings

log = logging.getLogger(__name__)


class HybridRetriever:
    """
    Async-safe hybrid retriever.
    Create once and reuse across requests.
    """

    def __init__(self) -> None:
        self._graph  = Neo4jRetriever()
        self._vector = ChromaRetriever()

    async def query(
        self,
        user_query: str,
        top_k: int | None = None,
    ) -> FusedContext:
        """
        Run the full hybrid retrieval pipeline.

        :param user_query: Raw user query string.
        :param top_k: Number of final fused results (defaults to settings.rerank_top_k).
        :returns: FusedContext with formatted context + source metadata.
        """
        _top_k = top_k or settings.rerank_top_k

        # 1. Entity detection
        detector = get_detector()
        entities: DetectedEntities = detector.detect(user_query)
        log.info(
            "Entities detected — incidents: %s, services: %s, jira: %s, commits: %s",
            entities.incidents, entities.services, entities.jira_tickets, entities.commits,
        )

        # 2. Parallel graph + vector retrieval
        graph_task  = asyncio.create_task(self._graph.retrieve(entities, user_query))
        vector_task = asyncio.create_task(self._vector.search(user_query, entities))

        graph_results, vector_results = await asyncio.gather(
            graph_task, vector_task, return_exceptions=True
        )

        # Graceful degradation if one retriever fails
        if isinstance(graph_results, Exception):
            log.warning("Graph retrieval failed: %s", graph_results)
            graph_results = []

        if isinstance(vector_results, Exception):
            log.warning("Vector retrieval failed: %s", vector_results)
            vector_results = []

        log.info(
            "Retrieval: %d graph results, %d vector results",
            len(graph_results), len(vector_results),
        )

        # 3. RRF re-ranking
        fused = rrf_fuse(graph_results, vector_results, top_k=_top_k)

        # 4. Context fusion
        context = fuse_context(fused, entities_dict=entities.to_dict())
        log.info("Fused context: %d results, %d sources", len(fused), len(context.sources))

        return context


# ── Module-level singleton ────────────────────────────────────────────────────

_retriever: HybridRetriever | None = None


def get_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever

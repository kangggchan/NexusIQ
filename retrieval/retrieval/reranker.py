"""
Reciprocal Rank Fusion (RRF) re-ranker.
Merges graph results + vector results into a single ranked list.

Formula: score(d) = Σ_i  1 / (k + rank_i + 1)
where k is the smoothing constant (default 60) and rank_i is 0-indexed rank
in result list i.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from retrieval.config import settings


@dataclass
class RankedResult:
    id: str
    source: str          # "graph" | "vector"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    rrf_score: float = 0.0
    original_score: float = 0.0
    collection: str = ""  # for vector results


def rrf_fuse(
    graph_results: list,    # list[GraphResult]
    vector_results: list,   # list[VectorResult]
    top_k: int | None = None,
    k: int | None = None,
) -> list[RankedResult]:
    """
    Fuse graph and vector result lists using RRF.

    :param graph_results: Ordered list of GraphResult (best-first).
    :param vector_results: Ordered list of VectorResult (best-first by cosine similarity).
    :param top_k: Maximum results to return (defaults to settings.rerank_top_k).
    :param k: RRF smoothing constant (defaults to settings.rrf_k).
    :returns: Merged list of RankedResult sorted by rrf_score descending.
    """
    _k = k if k is not None else settings.rrf_k
    _top_k = top_k if top_k is not None else settings.rerank_top_k

    scores: dict[str, float] = {}
    ranked: dict[str, RankedResult] = {}

    # ── Graph results ─────────────────────────────────────────────────────────
    for rank, gr in enumerate(graph_results):
        doc_id = f"graph::{gr.id}"
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_k + rank + 1)
        if doc_id not in ranked:
            ranked[doc_id] = RankedResult(
                id=gr.id,
                source="graph",
                content=gr.content,
                metadata=gr.metadata,
                original_score=gr.score,
            )

    # ── Vector results ────────────────────────────────────────────────────────
    for rank, vr in enumerate(vector_results):
        doc_id = f"vector::{vr.id}"
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_k + rank + 1)
        if doc_id not in ranked:
            ranked[doc_id] = RankedResult(
                id=vr.id,
                source="vector",
                content=vr.document,
                metadata=vr.metadata,
                original_score=vr.score,
                collection=vr.collection,
            )

    # ── Sort by RRF score and attach ──────────────────────────────────────────
    for doc_id, rrf_score in scores.items():
        if doc_id in ranked:
            ranked[doc_id].rrf_score = rrf_score

    sorted_results = sorted(ranked.values(), key=lambda r: r.rrf_score, reverse=True)
    return sorted_results[:_top_k]

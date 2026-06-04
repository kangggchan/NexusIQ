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


def _normalize_id(value: Any) -> str:
    text = str(value or "").strip()
    return text.upper()


def _fusion_key_from_graph(result: Any) -> str:
    item_type = str(getattr(result, "type", "") or "").lower()
    item_id = _normalize_id(getattr(result, "id", ""))
    if not item_id:
        return f"graph::{id(result)}"
    if item_type:
        return f"{item_type}::{item_id}"
    return f"graph::{item_id}"


def _fusion_key_from_vector(result: Any) -> str:
    metadata = getattr(result, "metadata", {}) or {}
    for field_name, item_type in (
        ("incident_id", "incident"),
        ("deployment_id", "deployment"),
        ("commit_id", "commit"),
        ("ticket_id", "jira"),
        ("doc_id", "tech_doc"),
        ("note_id", "meeting_note"),
        ("message_id", "slack"),
    ):
        value = metadata.get(field_name)
        if value:
            return f"{item_type}::{_normalize_id(value)}"

    collection = _normalize_id(getattr(result, "collection", ""))
    item_id = _normalize_id(getattr(result, "id", ""))
    if collection and item_id:
        return f"{collection}::{item_id}"
    if item_id:
        return f"vector::{item_id}"
    return f"vector::{id(result)}"


def _merge_metadata(existing: dict[str, Any], incoming: dict[str, Any], source: str) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value

    sources = list(merged.get("sources") or [])
    if existing.get("source"):
        sources.append(existing["source"])
    if source:
        sources.append(source)
    if sources:
        merged["sources"] = sorted(set(sources))
    return merged


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
        doc_id = _fusion_key_from_graph(gr)
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_k + rank + 1)
        existing = ranked.get(doc_id)
        if existing is None:
            ranked[doc_id] = RankedResult(
                id=gr.id,
                source="graph",
                content=gr.content,
                metadata={**gr.metadata, "source": "graph"},
                original_score=gr.score,
            )
        else:
            existing.original_score = max(existing.original_score, gr.score)
            existing.metadata = _merge_metadata(existing.metadata, gr.metadata, "graph")

    # ── Vector results ────────────────────────────────────────────────────────
    for rank, vr in enumerate(vector_results):
        doc_id = _fusion_key_from_vector(vr)
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (_k + rank + 1)
        existing = ranked.get(doc_id)
        if existing is None:
            ranked[doc_id] = RankedResult(
                id=vr.id,
                source="vector",
                content=vr.document,
                metadata={**vr.metadata, "source": "vector"},
                original_score=vr.score,
                collection=vr.collection,
            )
        else:
            existing.original_score = max(existing.original_score, vr.score)
            existing.collection = existing.collection or vr.collection
            existing.metadata = _merge_metadata(existing.metadata, vr.metadata, "vector")

    # ── Sort by RRF score and attach ──────────────────────────────────────────
    for doc_id, rrf_score in scores.items():
        if doc_id in ranked:
            ranked[doc_id].rrf_score = rrf_score

    sorted_results = sorted(ranked.values(), key=lambda r: r.rrf_score, reverse=True)
    return sorted_results[:_top_k]

"""
Context fusion — formats merged RRF results into a structured agent context string.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from retrieval.retrieval.reranker import RankedResult


@dataclass
class FusedContext:
    context: str                        # Formatted text injected into agent prompt
    sources: list[dict[str, Any]] = field(default_factory=list)  # Structured source refs
    entities: dict = field(default_factory=dict)  # Detected entities for transparency


def fuse_context(
    results: list[RankedResult],
    entities_dict: dict | None = None,
) -> FusedContext:
    """
    Convert ranked results into a structured context string suitable for
    injection into an LLM system prompt.
    """
    if not results:
        return FusedContext(
            context="No relevant context found in the knowledge base.",
            sources=[],
            entities=entities_dict or {},
        )

    sections: list[str] = []
    sources: list[dict] = []

    sections.append("=== RETRIEVED CONTEXT ===")

    for i, result in enumerate(results, 1):
        tag = f"[{result.source.upper()} #{i}]"
        if result.collection:
            tag = f"[{result.collection.replace('nexusiq_', '').upper()} #{i}]"

        section = f"{tag} (relevance: {result.rrf_score:.3f})\n{result.content}"
        sections.append(section)

        sources.append({
            "rank": i,
            "id": result.id,
            "source": result.source,
            "collection": result.collection,
            "rrf_score": round(result.rrf_score, 4),
        })

    sections.append("=== END CONTEXT ===")

    context_text = "\n\n".join(sections)

    return FusedContext(
        context=context_text,
        sources=sources,
        entities=entities_dict or {},
    )

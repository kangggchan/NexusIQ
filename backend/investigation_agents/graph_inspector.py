"""
Visualization Graph Inspector.

Reads from the shared in-memory GraphCache that is populated by the
/graph/visualization endpoint after its single Neo4j fetch.

No direct Neo4j or ChromaDB calls are made here — this module is
purely a fast keyword-lookup layer on top of already-cached data.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from retrieval.graph.graph_cache import get_graph_cache

log = logging.getLogger(__name__)

_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "on", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "from", "up", "down", "out", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "what", "which", "who", "whom", "this", "that",
    "these", "those", "and", "but", "if", "or", "because", "as", "until",
    "while", "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves", "he", "him", "his",
    "himself", "she", "her", "hers", "herself", "it", "its", "itself",
    "they", "them", "their", "theirs", "themselves", "show", "get", "tell",
    "find", "give", "list", "explain", "describe", "what", "why", "how",
    "did", "does", "happen", "happened", "going", "went", "look", "like",
})


class VisualizationGraphInspector:
    """
    Fast in-memory keyword lookup against the visualization graph.

    Data source: GraphCache singleton populated by /graph/visualization.
    No database calls are ever made from this class.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """True if the cache has been populated (i.e. /graph/visualization was called)."""
        return get_graph_cache().is_populated

    def extract_keywords(self, query: str) -> list[str]:
        """
        Fast keyword extraction — no LLM, no external deps.
        Returns meaningful tokens with stopwords removed.
        """
        tokens = re.findall(r"[a-zA-Z0-9_\-]+", query)
        keywords = [t for t in tokens if t.lower() not in _STOPWORDS and len(t) > 2]
        return list(dict.fromkeys(keywords))  # deduplicate, preserve order

    def lookup(self, keywords: list[str], max_entities: int = 15) -> dict[str, Any]:
        """
        Return entities and relationships matching keywords from the
        shared graph cache.  No Neo4j call is made.

        Scoring (case-insensitive):
          +10 — exact title match
          +7  — title starts-with keyword or keyword starts-with title
          +5  — keyword contained in title
          +3  — keyword contained in entity type
          +1  — keyword contained in description
        """
        cache = get_graph_cache()
        entities      = cache.entities
        relationships = cache.relationships

        if not keywords or not entities:
            return {"entities": [], "relationships": [], "matched": False}

        kw_lower = [k.lower() for k in keywords if k and len(k) > 2]
        if not kw_lower:
            return {"entities": [], "relationships": [], "matched": False}

        # Score every entity
        scored: list[tuple[int, dict]] = []
        for entity in entities:
            title = str(entity.get("title", "")).lower()
            etype = str(entity.get("type", "")).lower()
            desc  = str(entity.get("description", "")).lower()
            score = 0
            for kw in kw_lower:
                if title == kw:
                    score += 10
                elif title.startswith(kw) or kw.startswith(title):
                    score += 7
                elif kw in title:
                    score += 5
                if kw in etype:
                    score += 3
                if kw in desc:
                    score += 1
            if score > 0:
                scored.append((score, entity))

        scored.sort(key=lambda x: x[0], reverse=True)
        matched_entities = [e for _, e in scored[:max_entities]]

        if not matched_entities:
            return {"entities": [], "relationships": [], "matched": False}

        # Collect relationships that touch any matched entity (by id or title)
        matched_ids    = {str(e.get("id", ""))            for e in matched_entities}
        matched_titles = {str(e.get("title", "")).lower() for e in matched_entities}

        related_rels: list[dict] = []
        for rel in relationships:
            src = str(rel.get("source", ""))
            tgt = str(rel.get("target", ""))
            if src in matched_ids or tgt in matched_ids \
                    or src.lower() in matched_titles or tgt.lower() in matched_titles:
                related_rels.append(rel)
            if len(related_rels) >= 30:
                break

        return {
            "entities":      matched_entities,
            "relationships": related_rels,
            "matched":       True,
        }

    def format_for_llm(self, lookup_result: dict, max_chars: int = 1500) -> str:
        """Format lookup results into a concise text block for the LLM."""
        if not lookup_result.get("matched"):
            return "No matching entities found in the visualization graph."

        lines: list[str] = ["=== NEO4J GRAPH CONTEXT (visualization cache) ==="]

        entities = lookup_result["entities"]
        if entities:
            lines.append(f"\nMATCHED ENTITIES ({len(entities)}):")
            for e in entities[:10]:
                title = e.get("title", "?")
                etype = e.get("type", "?")
                desc  = str(e.get("description", ""))[:120]
                lines.append(f"  [{etype}] {title}: {desc}")

        rels = lookup_result["relationships"]
        if rels:
            lines.append(f"\nRELATIONSHIPS ({len(rels)}):")
            for r in rels[:15]:
                src  = r.get("source", "?")
                tgt  = r.get("target", "?")
                desc = str(r.get("description", ""))[:80]
                lines.append(f"  {src} → {tgt}: {desc}")

        return "\n".join(lines)[:max_chars]

    def stats(self) -> dict[str, Any]:
        return get_graph_cache().stats()


# Module singleton
_inspector: VisualizationGraphInspector | None = None


def get_graph_inspector() -> VisualizationGraphInspector:
    global _inspector
    if _inspector is None:
        _inspector = VisualizationGraphInspector()
    return _inspector


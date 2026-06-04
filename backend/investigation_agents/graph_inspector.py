"""
Visualization Graph Inspector.

Performs lightweight Neo4j lookups for the query analyzer.

Unlike the UI visualization cache, this path queries Neo4j directly so
entity matches are not limited by the visualization endpoint's sampling
budget.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from retrieval.graph.neo4j_client import get_session

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
    "some", "such", "no", "nor", "not", "only", "same", "so", "than",
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
        """Inspector is always available when the backend can reach Neo4j."""
        return True

    def extract_keywords(self, query: str) -> list[str]:
        """
        Fast keyword extraction — no LLM, no external deps.
        Returns meaningful tokens with stopwords removed.
        """
        tokens = re.findall(r"[a-zA-Z0-9_\-]+", query)
        keywords = [t for t in tokens if t.lower() not in _STOPWORDS and len(t) > 2]
        return list(dict.fromkeys(keywords))  # deduplicate, preserve order

    async def lookup(self, keywords: list[str], max_entities: int = 15) -> dict[str, Any]:
        """
        Return entities and relationships matching keywords from Neo4j.

        Scoring (case-insensitive):
          +10 — exact title match
          +7  — title starts-with keyword or keyword starts-with title
          +5  — keyword contained in title
          +3  — keyword contained in entity type
          +1  — keyword contained in description
        """
        if not keywords:
            return {"entities": [], "relationships": [], "matched": False}

        kw_lower = [k.lower() for k in keywords if k and len(k) > 2]
        if not kw_lower:
            return {"entities": [], "relationships": [], "matched": False}

        async with get_session() as session:
            node_result = await session.run(
                """
                MATCH (n)
                WHERE any(kw in $keywords WHERE
                    toLower(coalesce(n.name, '')) CONTAINS kw OR
                    toLower(coalesce(n.employee_id, '')) CONTAINS kw OR
                    toLower(coalesce(n.incident_id, '')) CONTAINS kw OR
                    toLower(coalesce(n.deployment_id, '')) CONTAINS kw OR
                    toLower(coalesce(n.commit_sha, '')) CONTAINS kw OR
                    toLower(coalesce(n.ticket_id, '')) CONTAINS kw OR
                    toLower(coalesce(n.channel, '')) CONTAINS kw OR
                    toLower(coalesce(n.id, '')) CONTAINS kw OR
                    toLower(coalesce(n.team, '')) CONTAINS kw OR
                    toLower(coalesce(n.project, '')) CONTAINS kw OR
                    toLower(coalesce(n.role, '')) CONTAINS kw OR
                    toLower(coalesce(n.description, '')) CONTAINS kw OR
                    toLower(coalesce(n.summary, '')) CONTAINS kw OR
                    toLower(coalesce(n.status, '')) CONTAINS kw
                )
                RETURN
                    coalesce(n.id, toString(id(n))) AS id,
                    labels(n)[0] AS label,
                    COALESCE(
                        n.name,
                        n.employee_id,
                        n.incident_id,
                        n.deployment_id,
                        n.commit_sha,
                        n.ticket_id,
                        n.channel,
                        n.id,
                        toString(id(n))
                    ) AS title,
                    COALESCE(n.description, n.summary, n.status, n.role, '') AS description,
                    n.name AS name,
                    n.employee_id AS employee_id,
                    n.team AS team,
                    n.project AS project,
                    n.role AS role,
                    n.email AS email
                LIMIT 100
                """,
                keywords=kw_lower,
            )
            raw_entities = [dict(record) async for record in node_result]

        scored: list[tuple[int, dict]] = []
        for entity in raw_entities:
            title = str(entity.get("title", "")).lower()
            etype = str(entity.get("label") or "NODE").lower()
            desc  = str(entity.get("description", "")).lower()
            aliases = [
                str(entity.get("name", "")).lower(),
                str(entity.get("employee_id", "")).lower(),
                str(entity.get("team", "")).lower(),
                str(entity.get("project", "")).lower(),
                str(entity.get("role", "")).lower(),
                str(entity.get("email", "")).lower(),
            ]
            score = 0
            for kw in kw_lower:
                if title == kw:
                    score += 10
                elif title.startswith(kw) or kw.startswith(title):
                    score += 7
                elif kw in title:
                    score += 5
                for alias in aliases:
                    if not alias:
                        continue
                    if alias == kw:
                        score += 8
                    elif alias.startswith(kw) or kw.startswith(alias):
                        score += 6
                    elif kw in alias:
                        score += 4
                if kw in etype:
                    score += 3
                if kw in desc:
                    score += 1
            if score > 0:
                entity["type"] = str(entity.get("label") or "NODE")
                scored.append((score, entity))

        scored.sort(key=lambda x: x[0], reverse=True)
        matched_entities = [e for _, e in scored[:max_entities]]

        if not matched_entities:
            return {"entities": [], "relationships": [], "matched": False}

        matched_ids = [str(e.get("id", "")) for e in matched_entities if e.get("id")]

        async with get_session() as session:
            rel_result = await session.run(
                """
                MATCH (a)-[r]-(b)
                WHERE coalesce(a.id, toString(id(a))) IN $entity_ids
                RETURN DISTINCT
                    toString(id(r)) AS id,
                    coalesce(a.id, toString(id(a))) AS source,
                    coalesce(b.id, toString(id(b))) AS target,
                    type(r) AS rel_type,
                    COALESCE(
                        a.name,
                        a.employee_id,
                        a.incident_id,
                        a.deployment_id,
                        a.commit_sha,
                        a.ticket_id,
                        a.channel,
                        a.id,
                        toString(id(a))
                    ) AS source_title,
                    COALESCE(
                        b.name,
                        b.employee_id,
                        b.incident_id,
                        b.deployment_id,
                        b.commit_sha,
                        b.ticket_id,
                        b.channel,
                        b.id,
                        toString(id(b))
                    ) AS target_title,
                    coalesce(r.description, replace(type(r), '_', ' ')) AS description
                LIMIT 30
                """,
                entity_ids=matched_ids,
            )
            related_rels = [
                {
                    "id": str(record["id"]),
                    "source": str(record["source"]),
                    "target": str(record["target"]),
                    "source_title": str(record["source_title"]),
                    "target_title": str(record["target_title"]),
                    "description": str(record["description"]).replace("_", " ").lower(),
                }
                async for record in rel_result
            ]

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
                src  = r.get("source_title") or r.get("source", "?")
                tgt  = r.get("target_title") or r.get("target", "?")
                desc = str(r.get("description", ""))[:80]
                lines.append(f"  {src} → {tgt}: {desc}")

        return "\n".join(lines)[:max_chars]

    def stats(self) -> dict[str, Any]:
        return {"source": "neo4j"}


# Module singleton
_inspector: VisualizationGraphInspector | None = None


def get_graph_inspector() -> VisualizationGraphInspector:
    global _inspector
    if _inspector is None:
        _inspector = VisualizationGraphInspector()
    return _inspector


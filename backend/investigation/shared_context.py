"""
Shared investigation context — the central evidence memory shared across all agents.

This object is built ONCE by the SharedLightweightRetriever and then passed
(by reference) to every downstream agent. Agents read from it and may request
selective expansion via ContextExpanders, but they NEVER re-run full retrieval.

Design principles:
  - Built once, read many
  - Agents receive filtered slices, not the whole object
  - Expanders extend the context in-place (append-only)
  - Immutable core fields; mutable expansion fields
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


_QUERY_TERM_STOPWORDS = {
    "about",
    "after",
    "before",
    "caused",
    "cause",
    "current",
    "from",
    "have",
    "latency",
    "most",
    "recent",
    "risk",
    "services",
    "spike",
    "that",
    "their",
    "them",
    "what",
    "which",
    "with",
    "why",
}


class InvestigationDepth(str, Enum):
    FAST     = "FAST"      # lightweight retrieval only — no agents
    STANDARD = "STANDARD"  # lightweight + 1-2 selective agents
    DEEP     = "DEEP"      # full multi-agent orchestration


class SignalStrength(str, Enum):
    HIGH   = "HIGH"    # strong evidence found — high confidence
    MEDIUM = "MEDIUM"  # partial evidence — needs expansion
    LOW    = "LOW"     # weak evidence — deep investigation required


@dataclass
class RetrievalSignal:
    """Confidence metadata produced by the shared retrieval pass."""
    signal_strength: SignalStrength = SignalStrength.LOW
    evidence_density: float = 0.0         # 0.0 – 1.0
    related_entities_found: bool = False
    entity_match_count: int = 0
    top_score: float = 0.0
    recommended_depth: InvestigationDepth = InvestigationDepth.DEEP

    def to_dict(self) -> dict:
        return {
            "signal_strength": self.signal_strength.value,
            "evidence_density": round(self.evidence_density, 3),
            "related_entities_found": self.related_entities_found,
            "entity_match_count": self.entity_match_count,
            "top_score": round(self.top_score, 3),
            "recommended_depth": self.recommended_depth.value,
        }


@dataclass
class SharedInvestigationContext:
    """
    Central investigation memory object.

    Lifecycle:
      1. Created by SharedLightweightRetriever with base evidence.
      2. EvidenceEvaluator reads signal metadata to decide depth.
      3. ContextExpanders optionally append incremental evidence.
      4. Agents read filtered slices from context_for_agent().
    """

    # ── Immutable core (set at creation) ─────────────────────────────────────
    query: str
    entities: dict                          # DetectedEntities.to_dict()
    retrieved_documents: list[dict]         # ranked fused results (serializable)
    graph_neighbors: dict[str, list]        # service_name → neighbor list (1-hop)
    incidents: list[dict]                   # raw incident records
    deployments: list[dict]                 # raw deployment records
    formatted_context: str                  # pre-formatted LLM-ready context string
    sources: list[dict]                     # source metadata for citation
    signal: RetrievalSignal = field(default_factory=RetrievalSignal)
    created_at: float = field(default_factory=time.monotonic)

    # ── Mutable expansion fields (populated by ContextExpanders) ─────────────
    expanded_graph: dict[str, list] = field(default_factory=dict)       # 2-hop neighbors
    expanded_incidents: list[dict] = field(default_factory=list)        # extended timelines
    expanded_risk: dict[str, Any] = field(default_factory=dict)         # blast radius data
    expanded_entities: set[str] = field(default_factory=set)            # expansion tracking

    # ── Agent output slots (populated during parallel execution) ──────────────
    graph_analysis: str = ""
    incident_analysis: str = ""
    risk_analysis: str = ""

    def context_for_agent(self, agent: str, max_chars: int = 2000) -> str:
        """
        Return a filtered context slice appropriate for the given agent.
        Agents receive ONLY the evidence relevant to their domain.
        This prevents token waste and keeps prompts focused.
        """
        base = self.formatted_context

        if agent == "graph":
            # Graph agent: graph-derived evidence only, plus topology expansions.
            graph_docs = [
                str(doc.get("content", ""))
                for doc in self.retrieved_documents
                if doc.get("source") in {"graph", "workforce"} and doc.get("content")
            ]
            if graph_docs:
                parts = ["[GRAPH RESULTS]\n" + "\n\n".join(graph_docs[:6])]
            else:
                parts = [base[:max_chars]]
            if self.graph_neighbors or self.expanded_graph:
                neighbors = {**self.graph_neighbors, **self.expanded_graph}
                neighbor_text = "\n".join(
                    f"  {svc}: {', '.join(str(n) for n in neighbors[:5])}"
                    for svc, neighbors in list(neighbors.items())[:6]
                )
                parts.append(f"\n[GRAPH TOPOLOGY]\n{neighbor_text}")
            return "\n".join(parts)[:max_chars + 500]

        elif agent == "incident":
            # Incident agent: incidents + deployments + timeline
            parts: list[str] = []

            query_terms = {
                term.lower()
                for term in re.findall(r"[a-z0-9-]+", self.query or "")
                if len(term) >= 3 and term.lower() not in _QUERY_TERM_STOPWORDS
            }
            if query_terms:
                scored_docs: list[tuple[float, dict]] = []
                for doc in self.retrieved_documents:
                    content = str(doc.get("content", ""))
                    if not content:
                        continue
                    collection = str(doc.get("collection", "") or "").lower()
                    source = str(doc.get("source", "") or "").lower()
                    haystack = f"{doc.get('id', '')} {content}".lower()
                    overlap = sum(1 for term in query_terms if term in haystack)
                    if overlap == 0:
                        continue
                    source_bonus = 0.0
                    if source == "vector":
                        source_bonus += 0.25
                    if any(key in collection for key in ("incident", "jira", "deployment", "commit", "slack")):
                        source_bonus += 0.25
                    scored_docs.append((overlap + source_bonus, doc))
                scored_docs.sort(key=lambda item: item[0], reverse=True)
                if scored_docs:
                    focused_docs = [
                        f"  [{doc.get('id', 'unknown')}] {str(doc.get('content', ''))[:420]}"
                        for _, doc in scored_docs[:4]
                    ]
                    parts.append("[QUERY-ALIGNED EVIDENCE]\n" + "\n\n".join(focused_docs))

            # Promote documents that match explicitly requested incident IDs
            # (for example INC-001) so the incident agent can reconstruct the
            # timeline even when graph-derived incident rows are empty.
            target_incidents = [
                str(i).upper() for i in (self.entities or {}).get("incidents", []) if i
            ]
            if target_incidents:
                focused_docs: list[str] = []
                for doc in self.retrieved_documents:
                    doc_id = str(doc.get("id", "")).upper()
                    content = str(doc.get("content", ""))
                    upper_content = content.upper()
                    if doc_id in target_incidents or any(ref in upper_content for ref in target_incidents):
                        focused_docs.append(f"  [{doc.get('id', 'unknown')}] {content[:420]}")
                if focused_docs:
                    parts.append("[TARGET INCIDENT DOCUMENTS]\n" + "\n\n".join(focused_docs[:4]))

            parts.append(base[:max_chars])
            if self.incidents:
                inc_text = "\n".join(
                    f"  [{i.get('incident_id', '')}] {i.get('title', '')} "
                    f"({i.get('severity', '')})"
                    for i in self.incidents[:5]
                )
                parts.append(f"\n[INCIDENTS]\n{inc_text}")
            if self.deployments:
                dep_text = "\n".join(
                    f"  [{d.get('id', '')}] {d.get('service', '')} "
                    f"v{d.get('version', '')} — {d.get('status', '')}"
                    for d in self.deployments[:5]
                )
                parts.append(f"\n[DEPLOYMENTS]\n{dep_text}")
            if self.expanded_incidents:
                exp_text = "\n".join(
                    f"  {e.get('timestamp', '')} | {e.get('event', '')}"
                    for e in self.expanded_incidents[:8]
                )
                parts.append(f"\n[EXTENDED TIMELINE]\n{exp_text}")
            return "\n".join(parts)[:max_chars + 600]

        elif agent == "risk":
            # Risk agent: topology + blast radius
            parts = [base[:max_chars]]
            if self.expanded_risk:
                blast = self.expanded_risk.get("blast_radius", [])
                if blast:
                    risk_text = "\n".join(
                        f"  {s.get('name', '')} (hops={s.get('hops', '?')}, "
                        f"team={s.get('team', '')})"
                        for s in blast[:8]
                    )
                    parts.append(f"\n[BLAST RADIUS]\n{risk_text}")
            return "\n".join(parts)[:max_chars + 400]

        # Default: return base context
        return base[:max_chars]

    def quick_summary(self) -> str:
        """One-line summary for logging / step events."""
        return (
            f"signal={self.signal.signal_strength.value} "
            f"density={self.signal.evidence_density:.2f} "
            f"docs={len(self.retrieved_documents)} "
            f"incidents={len(self.incidents)} "
            f"depth={self.signal.recommended_depth.value}"
        )

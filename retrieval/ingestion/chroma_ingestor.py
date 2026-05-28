"""
ChromaDB ingestion pipeline.
Reads NexusIQ dataset, embeds documents via Ollama, and upserts to ChromaDB Cloud.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from retrieval.config import DATASET_DIR
from retrieval.vector.chroma_client import get_or_create_collection
from retrieval.ingestion.embedding_pipeline import EmbeddingPipeline
from retrieval.schema.chroma_schema import COLLECTIONS

log = logging.getLogger(__name__)


def _load(filename: str) -> dict:
    path = DATASET_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def ingest_all() -> dict[str, int]:
    embedder = EmbeddingPipeline()
    counts: dict[str, int] = {}

    counts["incidents"]    = await _ingest_incidents(embedder)
    counts["commits"]      = await _ingest_commits(embedder)
    counts["slack"]        = await _ingest_slack(embedder)
    counts["jira"]         = await _ingest_jira(embedder)
    counts["tech_docs"]    = await _ingest_tech_docs(embedder)
    counts["meeting_notes"]= await _ingest_meeting_notes(embedder)
    counts["deployments"]  = await _ingest_deployments(embedder)

    log.info("ChromaDB ingestion complete: %s", counts)
    return counts


async def _upsert(
    collection_key: str,
    embedder: EmbeddingPipeline,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    chunk_size: int = 250,  # ChromaDB free tier: 300 records/upsert
) -> int:
    col_def = COLLECTIONS[collection_key]
    collection = await get_or_create_collection(col_def.name)
    embeddings = await embedder.embed_batch(documents)
    safe_meta = [_safe_metadata(m) for m in metadatas]

    # Chunk to stay within quota
    total = len(ids)
    for start in range(0, total, chunk_size):
        end = start + chunk_size
        await collection.upsert(
            ids=ids[start:end],
            embeddings=embeddings[start:end],
            documents=documents[start:end],
            metadatas=safe_meta[start:end],
        )

    log.info("  ✓ %d → %s", total, col_def.name)
    return total


def _safe_metadata(meta: dict) -> dict[str, str | int | float | bool]:
    """Ensure all metadata values are ChromaDB-compatible scalars."""
    result = {}
    for k, v in meta.items():
        if v is None:
            result[k] = ""
        elif isinstance(v, (list, dict)):
            result[k] = json.dumps(v)
        else:
            result[k] = v
    return result


# ── Ingestion functions ───────────────────────────────────────────────────────

async def _ingest_incidents(embedder: EmbeddingPipeline) -> int:
    data = _load("incidents.json")
    incidents = data.get("incidents", [])
    ids, docs, metas = [], [], []
    for inc in incidents:
        timeline = " | ".join(
            f"{e['timestamp']}: {e['event']}"
            for e in inc.get("timeline", [])
        )
        doc = (
            f"Incident: {inc.get('title', '')}\n"
            f"Severity: {inc.get('severity', '')}\n"
            f"Started: {inc.get('started_at', '')} | Ended: {inc.get('ended_at', '')}\n"
            f"Affected: {', '.join(inc.get('affected_services', []))}\n"
            f"Root cause: {inc.get('root_cause', '')}\n"
            f"Timeline: {timeline}"
        )
        ids.append(inc["incident_id"])
        docs.append(doc)
        metas.append({
            "incident_id": inc["incident_id"],
            "severity": inc.get("severity", ""),
            "started_at": inc.get("started_at", ""),
            "ended_at": inc.get("ended_at", ""),
            "affected_services": inc.get("affected_services", []),
        })
    return await _upsert("incidents", embedder, ids, docs, metas)


async def _ingest_commits(embedder: EmbeddingPipeline) -> int:
    data = _load("github_commits.json")
    commits = data.get("commits", [])
    ids, docs, metas = [], [], []
    for c in commits:
        doc = (
            f"Commit: {c.get('short_commit_id', c['commit_id'][:8])}\n"
            f"Author: {c.get('author_name', '')}\n"
            f"Branch: {c.get('branch', '')}\n"
            f"Message: {c.get('message', '')}\n"
            f"Services modified: {', '.join(c.get('services_modified', []))}\n"
            f"Jira tickets: {', '.join(c.get('jira_ticket_ids', []))}"
        )
        ids.append(c["commit_id"])
        docs.append(doc)
        metas.append({
            "commit_id": c["commit_id"],
            "short_id": c.get("short_commit_id", ""),
            "author": c.get("author_name", ""),
            "timestamp": c.get("timestamp", ""),
            "branch": c.get("branch", ""),
            "services_modified": c.get("services_modified", []),
            "jira_tickets": c.get("jira_ticket_ids", []),
        })
    return await _upsert("commits", embedder, ids, docs, metas)


async def _ingest_slack(embedder: EmbeddingPipeline) -> int:
    slack_dir = DATASET_DIR / "slack_logs"
    ids, docs, metas = [], [], []
    counter = 0
    for json_file in sorted(slack_dir.glob("*.json")):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        channel = data.get("channel", json_file.stem)
        for msg in data.get("messages", []):
            ts = msg.get("timestamp", "")
            author = msg.get("author", "unknown")
            # Include counter to guarantee uniqueness across all channels
            msg_id = f"{channel}_{ts}_{author}_{counter}"
            content = msg.get("content", msg.get("message", ""))
            doc = f"[{channel}] {author}: {content}"
            ids.append(msg_id)
            docs.append(doc)
            metas.append({
                "message_id": msg_id,
                "channel": channel,
                "author": author,
                "timestamp": ts,
            })
            counter += 1
    return await _upsert("slack", embedder, ids, docs, metas)


async def _ingest_jira(embedder: EmbeddingPipeline) -> int:
    data = _load("jira_tickets.json")
    tickets = data.get("tickets", [])
    ids, docs, metas = [], [], []
    for t in tickets:
        comments = " | ".join(
            c.get("text", "") for c in t.get("comments", [])
        )
        doc = (
            f"Ticket: {t['ticket_id']} [{t.get('type', '')} / {t.get('priority', '')}]\n"
            f"Summary: {t.get('summary', '')}\n"
            f"Description: {t.get('description', '')}\n"
            f"Status: {t.get('status', '')}\n"
            f"Services: {', '.join(t.get('related_services', []))}\n"
            f"Comments: {comments}"
        )
        ids.append(t["ticket_id"])
        docs.append(doc)
        metas.append({
            "ticket_id": t["ticket_id"],
            "type": t.get("type", ""),
            "priority": t.get("priority", ""),
            "status": t.get("status", ""),
            "related_services": t.get("related_services", []),
            "assignee": t.get("assignee_employee_id", ""),
            "created_at": t.get("created_at", ""),
        })
    return await _upsert("jira", embedder, ids, docs, metas)


async def _ingest_tech_docs(embedder: EmbeddingPipeline) -> int:
    docs_dir = DATASET_DIR / "technical_documents"
    ids, docs, metas = [], [], []
    for md_file in sorted(docs_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        doc_id = f"TDOC-{md_file.stem}"
        title = _extract_md_title(content, md_file.stem)
        ids.append(doc_id)
        docs.append(content)
        metas.append({
            "doc_id": doc_id,
            "title": title,
            "filename": md_file.name,
        })
    return await _upsert("tech_docs", embedder, ids, docs, metas)


async def _ingest_meeting_notes(embedder: EmbeddingPipeline) -> int:
    notes_dir = DATASET_DIR / "meeting_notes"
    ids, docs, metas = [], [], []
    for md_file in sorted(notes_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        note_id = f"MTG-{md_file.stem}"
        title = _extract_md_title(content, md_file.stem)
        ids.append(note_id)
        docs.append(content)
        metas.append({
            "note_id": note_id,
            "title": title,
            "filename": md_file.name,
        })
    return await _upsert("meeting_notes", embedder, ids, docs, metas)


async def _ingest_deployments(embedder: EmbeddingPipeline) -> int:
    data = _load("deployment_logs.json")
    deployments = data.get("deployments", [])
    ids, docs, metas = [], [], []
    for d in deployments:
        doc = (
            f"Deployment: {d['deployment_id']}\n"
            f"Service: {d.get('service', '')} v{d.get('service_version', '')}\n"
            f"Environment: {d.get('environment', '')} / {d.get('target', '')}\n"
            f"Status: {d.get('status', '')}\n"
            f"When: {d.get('timestamp', '')}\n"
            f"Notes: {d.get('notes', '')}"
        )
        ids.append(d["deployment_id"])
        docs.append(doc)
        metas.append({
            "deployment_id": d["deployment_id"],
            "service": d.get("service", ""),
            "environment": d.get("environment", ""),
            "status": d.get("status", ""),
            "timestamp": d.get("timestamp", ""),
            "deployed_by": d.get("initiated_by_employee_id", ""),
        })
    return await _upsert("deployments", embedder, ids, docs, metas)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_md_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback.replace("-", " ").replace("_", " ").title()

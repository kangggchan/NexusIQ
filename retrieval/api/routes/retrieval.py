from __future__ import annotations

import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from retrieval.retrieval.hybrid_retriever import get_retriever
from retrieval.ingestion import neo4j_ingestor, chroma_ingestor

log = logging.getLogger(__name__)
router = APIRouter(prefix="/retrieval", tags=["retrieval"])


# ── Request / Response models ─────────────────────────────────────────────────

class RetrievalRequest(BaseModel):
    query: str
    top_k: int = 8


class RetrievalResponse(BaseModel):
    context: str
    sources: list[dict]
    entities: dict


class IngestRequest(BaseModel):
    target: str = "all"   # "neo4j" | "chroma" | "all"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/query", response_model=RetrievalResponse)
async def retrieval_query(req: RetrievalRequest) -> RetrievalResponse:
    """
    Hybrid GraphRAG retrieval: entity detect → graph + vector parallel → RRF → context.
    """
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    try:
        retriever = get_retriever()
        fused = await retriever.query(req.query, top_k=req.top_k)
        return RetrievalResponse(
            context=fused.context,
            sources=fused.sources,
            entities=fused.entities,
        )
    except Exception as exc:
        log.exception("Retrieval failed for query: %s", req.query)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ingest")
async def ingest(req: IngestRequest) -> dict:
    """
    Trigger data ingestion into Neo4j and/or ChromaDB.
    This is a long-running operation — consider running via CLI for production.
    """
    counts: dict[str, dict] = {}
    try:
        if req.target in ("neo4j", "all"):
            counts["neo4j"] = await neo4j_ingestor.ingest_all()
        if req.target in ("chroma", "all"):
            counts["chroma"] = await chroma_ingestor.ingest_all()
        return {"status": "ok", "counts": counts}
    except Exception as exc:
        log.exception("Ingestion failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

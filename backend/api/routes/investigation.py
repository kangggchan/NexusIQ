"""
FastAPI route for the multi-agent investigation workflow.

POST /investigation/run  — starts a streaming investigation
GET  /investigation/health — sanity-checks Ollama connectivity
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.investigation_agents.workflow import get_workflow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/investigation", tags=["investigation"])

SSE_HEADERS = {
    "Cache-Control":    "no-cache",
    "X-Accel-Buffering": "no",     # prevent nginx buffering
    "Connection":       "keep-alive",
}


class InvestigationRequest(BaseModel):
    query: str
    history: list[dict] = []   # prior conversation turns: [{role, content}, ...]


# ── POST /investigation/run ───────────────────────────────────────────────────

@router.post("/run")
async def run_investigation(req: InvestigationRequest):
    """
    Start a multi-agent investigation and stream SSE events back.

    Event types:
      investigation-start     — workflow kicked off
      step-update             — one agent node completed
      investigation-complete  — final InvestigationReport attached
      error                   — unrecoverable failure
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    async def event_stream():
        try:
            workflow = get_workflow()
            async for event in workflow.stream(req.query, history=req.history):
                payload = json.dumps(event["data"], ensure_ascii=False)
                yield f"event: {event['type']}\ndata: {payload}\n\n"
        except Exception as exc:
            log.exception("Investigation pipeline failed: %s", req.query)
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ── GET /investigation/health ─────────────────────────────────────────────────

@router.get("/health")
async def investigation_health():
    """Quick check that the workflow can be instantiated."""
    try:
        get_workflow()
        return {"status": "ok", "message": "Investigation workflow ready"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

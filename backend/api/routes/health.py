"""
GET /health            – liveness probe
GET /health/gemini     – Vertex AI Gemini connectivity check
GET /models/status     – per-agent model configuration
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness():
    """Basic liveness probe – always returns 200 if the server is running."""
    return {"status": "ok", "timestamp": int(time.time() * 1000)}


@router.get("/health/gemini")
async def gemini_health(request: Request):
    """
    Check that Vertex AI / Gemini is reachable.
    Returns 503 if the API cannot be contacted.
    """
    svc = request.app.state.gemini
    try:
        info = await svc.health_check()
        return {"status": "ok", **info}
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": str(exc)},
        )


@router.get("/models/status")
async def models_status(request: Request):
    """
    Return per-agent model name and provider configuration.
    Gemini models are always available via API – no local pull required.
    """
    router_obj = request.app.state.model_router

    statuses = []
    for cfg in router_obj.all_configs():
        statuses.append(
            {
                "agent_id": cfg.agent_id,
                "model": cfg.model,
                "description": cfg.description,
                "tags": cfg.tags,
                "provider": "vertex-ai",
            }
        )

    return {"models": statuses}

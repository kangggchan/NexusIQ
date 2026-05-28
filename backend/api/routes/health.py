"""
GET /health            – liveness probe
GET /health/ollama     – Ollama connectivity check
GET /models/status     – per-agent model availability
"""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness():
    """Basic liveness probe – always returns 200 if the server is running."""
    return {"status": "ok", "timestamp": int(time.time() * 1000)}


@router.get("/health/ollama")
async def ollama_health(request: Request):
    """
    Check that Ollama is reachable and list available models.
    Returns 503 if Ollama cannot be contacted.
    """
    svc = request.app.state.ollama
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
    Return per-agent model name and whether the model is already pulled locally.
    """
    svc = request.app.state.ollama
    router_obj = request.app.state.model_router

    available = await svc.list_models()
    available_set = set(available)

    statuses = []
    for cfg in router_obj.all_configs():
        # Fuzzy match: "llama3.1:8b" matches "llama3.1:8b" or "llama3.1"
        base = cfg.model.split(":")[0]
        pulled = any(m == cfg.model or m.startswith(base) for m in available_set)
        statuses.append(
            {
                "agent_id": cfg.agent_id,
                "model": cfg.model,
                "description": cfg.description,
                "tags": cfg.tags,
                "pulled": pulled,
            }
        )

    return {"models": statuses, "available_count": len(available)}

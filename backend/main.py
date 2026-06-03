"""
NexusIQ FastAPI Backend – main application entry point.

Startup sequence:
  1. Create GeminiService (Vertex AI)
  2. Create ModelRouter
  3. Create EmbeddingService
  4. Instantiate all four agent classes
  5. Mount API routers

Run with::

    cd graphrag-workbench
    uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.services.ollama_service import GeminiService, GeminiServiceError
from backend.services.embedding_service import EmbeddingService

from backend.api.routes import health, embeddings
from backend.api.routes import investigation as investigation_routes
from retrieval.api.routes import retrieval as retrieval_routes
from retrieval.api.routes import graph_api as graph_routes

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    origins = [o.strip() for o in settings.backend_cors_origins.split(",") if o.strip()]
    if origins:
        return origins
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: initialise services and inject them into app.state.
    Shutdown: clean up.
    """
    log.info("NexusIQ backend starting…")

    # Services
    gemini = GeminiService()
    embedding_svc = EmbeddingService(gemini)

    # Verify Vertex AI connectivity (non-fatal — requests will fail gracefully at runtime)
    try:
        info = await gemini.health_check()
        log.info("Vertex AI connected. Project=%s location=%s", info.get("project"), info.get("location"))
    except GeminiServiceError as exc:
        log.warning(
            "Vertex AI not reachable at startup: %s — LLM calls will fail until credentials are configured.",
            exc,
        )

    # Inject into app state so routes can access them via request.app.state.*
    app.state.gemini = gemini
    app.state.ollama = gemini  # backward-compat alias for any route using app.state.ollama
    app.state.embedding_service = embedding_svc

    log.info("NexusIQ backend ready on http://%s:%d", settings.backend_host, settings.backend_port)
    yield

    log.info("NexusIQ backend shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="NexusIQ Backend",
    description="Multi-agent Vertex AI Gemini investigation service for NexusIQ operational intelligence.",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow requests from the Next.js dev server and production origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(embeddings.router)

# Hybrid GraphRAG retrieval routes
app.include_router(retrieval_routes.router)
app.include_router(graph_routes.router)

# Multi-agent investigation workflow
app.include_router(investigation_routes.router)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=settings.backend_reload,
        log_level=settings.log_level.lower(),
    )

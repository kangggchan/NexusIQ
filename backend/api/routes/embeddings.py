"""
POST /embeddings       – embed one or more texts
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["embeddings"])


class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, description="Texts to embed")


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    count: int


@router.post("/embeddings", response_model=EmbedResponse)
async def embed_texts(body: EmbedRequest, request: Request):
    """
    Embed one or more texts using the configured embedding model (nomic-embed-text).
    Returns a list of float vectors, one per input text.
    """
    emb_svc = request.app.state.embedding_service

    if not body.texts:
        raise HTTPException(status_code=422, detail="texts must be non-empty")

    try:
        vectors = await emb_svc.embed_batch(body.texts)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {exc}") from exc

    return EmbedResponse(
        embeddings=vectors,
        model=request.app.state.model_router.get_model("embedding"),
        count=len(vectors),
    )

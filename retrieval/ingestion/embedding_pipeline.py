"""
Embedding pipeline — batch text embedding via Ollama nomic-embed-text.
Uses httpx directly so the retrieval module stays independent of the backend module.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Sequence

import httpx

from retrieval.config import settings

log = logging.getLogger(__name__)


class EmbeddingPipeline:
    """
    Async batch embedding pipeline backed by Ollama.

    Usage::

        pipeline = EmbeddingPipeline()
        vecs = await pipeline.embed_batch(["text a", "text b"])
    """

    def __init__(self) -> None:
        self._base_url = settings.ollama_host.rstrip("/")
        self._model = settings.embedding_model
        self._batch_size = settings.embedding_batch_size
        self._timeout = settings.embedding_timeout

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        vecs = await self.embed_batch([text])
        return vecs[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed a list of texts, chunked into batches to avoid overloading Ollama.
        Each text is truncated to MAX_CHARS to stay within the model's context window.
        Returns embeddings in the same order as input.
        """
        MAX_CHARS = 8192  # nomic-embed-text context window ~8192 tokens ≈ 8192 chars
        texts = [t[:MAX_CHARS] for t in texts if t and t.strip()]
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for i in range(0, len(texts), self._batch_size):
                chunk = list(texts[i : i + self._batch_size])
                vecs = await self._call_ollama(client, chunk)
                all_embeddings.extend(vecs)

        return all_embeddings

    async def _call_ollama(
        self, client: httpx.AsyncClient, texts: list[str]
    ) -> list[list[float]]:
        """Single Ollama /api/embed call for a list of texts."""
        payload = {"model": self._model, "input": texts}
        response = await client.post(
            f"{self._base_url}/api/embed",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        embeddings = data.get("embeddings", [])
        if len(embeddings) != len(texts):
            raise ValueError(
                f"Ollama returned {len(embeddings)} embeddings for {len(texts)} inputs"
            )
        return embeddings

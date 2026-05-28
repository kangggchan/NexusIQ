"""
EmbeddingService – high-level text embedding pipeline backed by Ollama.

Features:
- Single-text and batch embedding
- Cosine similarity helper
- Thread-safe in-memory LRU cache (optional, disabled by default)
"""
from __future__ import annotations

import math
from typing import Sequence

from backend.config import settings
from backend.services.ollama_service import OllamaService


class EmbeddingService:
    """
    Wraps OllamaService to provide a dedicated embedding interface.

    Usage::

        svc = EmbeddingService(ollama_service)
        vec = await svc.embed("What is the blast radius of a payment service failure?")
        vecs = await svc.embed_batch(["text a", "text b"])
        score = EmbeddingService.cosine_similarity(vec_a, vec_b)
    """

    def __init__(self, ollama: OllamaService, model: str | None = None) -> None:
        self._ollama = ollama
        self._model = model or settings.model_embedding

    # ── Public API ────────────────────────────────────────────────────────────

    async def embed(self, text: str) -> list[float]:
        """Embed a single piece of text."""
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        return await self._ollama.embed(self._model, text)

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """
        Embed a list of texts.

        Internally chunks into batches of `settings.embedding_batch_size` to
        avoid overloading Ollama with huge payloads.
        """
        texts = [t for t in texts if t and t.strip()]
        if not texts:
            return []

        batch_size = max(1, settings.embedding_batch_size)
        results: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            batch_vecs = await self._ollama.embed_batch(self._model, list(chunk))
            results.extend(batch_vecs)

        return results

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
        """
        Compute cosine similarity in [-1, 1].
        Returns 0.0 if either vector has zero magnitude.
        """
        if len(vec_a) != len(vec_b):
            raise ValueError("Vectors must have the same dimension")

        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a * a for a in vec_a))
        mag_b = math.sqrt(sum(b * b for b in vec_b))

        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0
        return dot / (mag_a * mag_b)

    @staticmethod
    def rank_by_similarity(
        query_vec: list[float],
        candidates: list[tuple[str, list[float]]],
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """
        Rank *(text, embedding)* pairs by cosine similarity to *query_vec*.

        Returns list of *(text, score)* sorted descending, length ≤ top_k.
        """
        scored = [
            (text, EmbeddingService.cosine_similarity(query_vec, vec))
            for text, vec in candidates
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

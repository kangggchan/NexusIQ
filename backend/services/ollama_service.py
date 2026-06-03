"""
GeminiService – Vertex AI / Gemini inference client.

Drop-in replacement for the previous OllamaService – same public interface,
Vertex AI Gemini backend.  OllamaService and OllamaServiceError are kept as
aliases so any import that has not yet been updated continues to work.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Sequence

from google import genai
from google.genai import types

from backend.config import settings

log = logging.getLogger(__name__)


class GeminiServiceError(RuntimeError):
    """Raised when the Gemini / Vertex AI API is unreachable or returns an error."""


class GeminiService:
    """
    Async Vertex AI Gemini client.

    Provides chat, streaming chat, and text embedding via the google-genai SDK.
    Instantiate once and reuse across requests – the underlying HTTP session is
    shared automatically by the SDK.

    Authentication uses Application Default Credentials (ADC).  On Cloud Run
    the service-account attached to the revision is used automatically; locally
    run ``gcloud auth application-default login`` once.
    """

    def __init__(self) -> None:
        self._client = genai.Client(
            vertexai=True,
            project="knudc-khang-buiphuoc",
            location="us-central1",
        )

    # ── Health ────────────────────────────────────────────────────────────────

    async def health_check(self) -> dict:
        """
        Verify Vertex AI connectivity with a minimal generate call.
        Raises GeminiServiceError on failure.
        """
        try:
            response = await self._client.aio.models.generate_content(
                model="gemini-2.0-flash-lite",
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=1),
            )
            _ = response.text  # confirm we can read the response
            return {
                "status": "ok",
                "provider": "vertex-ai",
                "project": settings.google_cloud_project,
                "location": settings.google_cloud_location,
            }
        except Exception as exc:
            raise GeminiServiceError(f"Vertex AI unreachable: {exc}") from exc

    async def list_models(self) -> list[str]:
        """
        Return the names of the configured agent models.
        (Gemini models are always available via API — no local pull needed.)
        """
        return [
            settings.model_orchestrator,
            settings.model_graph,
            settings.model_incident,
            settings.model_risk,
            settings.model_embedding,
        ]

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def chat(
        self,
        model: str,
        messages: Sequence[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **_kwargs,  # absorb legacy keep_alive / other Ollama-only params
    ) -> str:
        """
        Blocking (non-streaming) chat completion.

        :param model: Gemini model name, e.g. ``"gemini-2.5-flash"``.
        :param messages: List of ``{"role": "system"|"user"|"assistant", "content": str}``.
        :returns: Assistant reply as a plain string.
        """
        try:
            system_text, contents = _split_messages(list(messages))
            config = types.GenerateContentConfig(
                system_instruction=system_text or None,
                temperature=temperature if temperature is not None else settings.default_temperature,
                max_output_tokens=max_tokens or settings.default_max_tokens,
            )
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            return response.text or ""
        except GeminiServiceError:
            raise
        except Exception as exc:
            raise GeminiServiceError(f"chat failed: {exc}") from exc

    async def stream_chat(
        self,
        model: str,
        messages: Sequence[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **_kwargs,
    ) -> AsyncIterator[str]:
        """
        Async generator that yields text chunks as they arrive from Gemini.

        Example::

            async for chunk in svc.stream_chat("gemini-2.5-flash", messages):
                sys.stdout.write(chunk)
        """
        try:
            system_text, contents = _split_messages(list(messages))
            config = types.GenerateContentConfig(
                system_instruction=system_text or None,
                temperature=temperature if temperature is not None else settings.default_temperature,
                max_output_tokens=max_tokens or settings.default_max_tokens,
            )
            async for chunk in self._client.aio.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            ):
                if chunk.text:
                    yield chunk.text
        except GeminiServiceError:
            raise
        except Exception as exc:
            raise GeminiServiceError(f"stream_chat failed: {exc}") from exc

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Convenience wrapper – single prompt string, no chat format."""
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        return await self.chat(model, msgs, temperature=temperature, max_tokens=max_tokens)

    # ── Embeddings ────────────────────────────────────────────────────────────

    async def embed(self, model: str, text: str) -> list[float]:
        """Return the embedding vector for *text*."""
        vecs = await self.embed_batch(model, [text])
        return vecs[0]

    async def embed_batch(self, model: str, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts via Vertex AI text-embedding.

        Vertex AI ``text-embedding-005`` accepts up to 250 inputs per call.
        Inputs are chunked automatically.
        """
        if not texts:
            return []

        MAX_BATCH = 250
        all_vectors: list[list[float]] = []

        try:
            for i in range(0, len(texts), MAX_BATCH):
                chunk = texts[i : i + MAX_BATCH]
                response = await self._client.aio.models.embed_content(
                    model=model,
                    contents=chunk,
                    config=types.EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT",
                    ),
                )
                all_vectors.extend(e.values for e in response.embeddings)
            return all_vectors
        except GeminiServiceError:
            raise
        except Exception as exc:
            raise GeminiServiceError(f"embed_batch failed: {exc}") from exc


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_messages(messages: list[dict]) -> tuple[str, object]:
    """
    Separate the system turn from the conversation.

    Returns ``(system_text, contents)`` where *contents* is either a plain
    string (single-turn) or a ``list[types.Content]`` (multi-turn).
    """
    system_parts: list[str] = []
    conversation: list[dict] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(content)
        else:
            conversation.append({
                "role": "model" if role == "assistant" else "user",
                "content": content,
            })

    system_text = "\n\n".join(system_parts)

    if len(conversation) == 1:
        return system_text, conversation[0]["content"]

    contents = [
        types.Content(
            role=msg["role"],
            parts=[types.Part(text=msg["content"])],
        )
        for msg in conversation
    ]
    return system_text, contents


# ── Backward-compat aliases ───────────────────────────────────────────────────
# Keeps existing ``from backend.services.ollama_service import OllamaService``
# imports working without requiring a simultaneous rename everywhere.
OllamaService = GeminiService
OllamaServiceError = GeminiServiceError

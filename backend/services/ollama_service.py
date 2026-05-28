"""
OllamaService – Centralized Ollama connection manager.

Responsibilities:
- Health checking & readiness probing
- Lazy model pulling (first-use pull if not present)
- Streaming and non-streaming inference via ollama-python
- Retry with exponential back-off via tenacity
- Async-first; all public methods are coroutines
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Sequence

import ollama
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.config import settings

log = logging.getLogger(__name__)

# Models that have already been verified as present in this session
_pulled_models: set[str] = set()
_pull_locks: dict[str, asyncio.Lock] = {}


class OllamaServiceError(RuntimeError):
    """Raised when Ollama is unreachable or returns an unexpected error."""


class OllamaService:
    """
    Thin async wrapper around the ollama-python AsyncClient.

    Usage::

        svc = OllamaService()
        await svc.ensure_model("llama3.1:8b")
        async for chunk in svc.stream_chat("llama3.1:8b", messages=[...]):
            print(chunk, end="", flush=True)
    """

    def __init__(self) -> None:
        self._client = ollama.AsyncClient(host=settings.ollama_host)
        self._timeout = settings.ollama_timeout

    # ── Health ────────────────────────────────────────────────────────────────

    async def health_check(self) -> dict:
        """Return server info dict or raise OllamaServiceError."""
        try:
            result = await asyncio.wait_for(
                self._client.list(),
                timeout=5.0,
            )
            return {"status": "ok", "models": [m.model for m in result.models]}
        except Exception as exc:
            raise OllamaServiceError(f"Ollama unreachable at {settings.ollama_host}: {exc}") from exc

    async def list_models(self) -> list[str]:
        """Return names of all locally available models."""
        try:
            result = await self._client.list()
            return [m.model for m in result.models]
        except Exception as exc:
            log.warning("Could not list Ollama models: %s", exc)
            return []

    # ── Lazy model loading ────────────────────────────────────────────────────

    async def ensure_model(self, model: str) -> None:
        """
        Pull *model* if it is not already present locally.
        Only one pull per model name runs at a time (lock-guarded).
        Subsequent callers wait for the first pull to finish.
        """
        if model in _pulled_models:
            return

        if model not in _pull_locks:
            _pull_locks[model] = asyncio.Lock()

        async with _pull_locks[model]:
            # Re-check inside lock in case another coroutine just finished pulling
            if model in _pulled_models:
                return

            available = await self.list_models()
            # Ollama stores names like "llama3.1:8b" – exact or prefix match
            if any(m == model or m.startswith(model.split(":")[0]) for m in available):
                _pulled_models.add(model)
                log.info("Model '%s' already available.", model)
                return

            log.info("Pulling model '%s' from Ollama registry…", model)
            try:
                # ollama.pull streams progress; we consume it silently
                async for _ in await self._client.pull(model, stream=True):
                    pass
                _pulled_models.add(model)
                log.info("Model '%s' pulled successfully.", model)
            except Exception as exc:
                log.error("Failed to pull model '%s': %s", model, exc)
                raise OllamaServiceError(f"Cannot pull model '{model}': {exc}") from exc

    # ── Inference ─────────────────────────────────────────────────────────────

    async def chat(
        self,
        model: str,
        messages: Sequence[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        keep_alive: str | None = None,
    ) -> str:
        """
        Blocking (non-streaming) chat completion.
        Returns the assistant's reply as a plain string.
        """
        await self.ensure_model(model)
        options = self._build_options(temperature, max_tokens)

        async def _call() -> str:
            response = await self._client.chat(
                model=model,
                messages=list(messages),
                stream=False,
                options=options,
                keep_alive=keep_alive or settings.ollama_keep_alive,
            )
            return response.message.content or ""

        return await self._with_retry(_call)

    async def stream_chat(
        self,
        model: str,
        messages: Sequence[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        keep_alive: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Async generator that yields text chunks as they arrive from Ollama.

        Example::

            async for chunk in svc.stream_chat("llama3.1:8b", messages):
                sys.stdout.write(chunk)
        """
        await self.ensure_model(model)
        options = self._build_options(temperature, max_tokens)

        # We cannot wrap a generator in tenacity easily, so we do a single
        # attempt here; callers that need retry should wrap at a higher level.
        async_stream = await self._client.chat(
            model=model,
            messages=list(messages),
            stream=True,
            options=options,
            keep_alive=keep_alive or settings.ollama_keep_alive,
        )
        async for chunk in async_stream:
            content = chunk.message.content
            if content:
                yield content

    async def generate(
        self,
        model: str,
        prompt: str,
        system: str = "",
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Raw generate (no chat format). Returns complete response string."""
        await self.ensure_model(model)
        options = self._build_options(temperature, max_tokens)

        async def _call() -> str:
            response = await self._client.generate(
                model=model,
                prompt=prompt,
                system=system,
                stream=False,
                options=options,
                keep_alive=settings.ollama_keep_alive,
            )
            return response.response or ""

        return await self._with_retry(_call)

    async def embed(self, model: str, text: str) -> list[float]:
        """Return embedding vector for *text* using *model*."""
        await self.ensure_model(model)

        async def _call() -> list[float]:
            response = await self._client.embed(model=model, input=text)
            # ollama-python returns embeddings as list[list[float]]
            embeddings = response.embeddings
            if not embeddings:
                raise OllamaServiceError("Ollama returned empty embeddings")
            return embeddings[0]

        return await self._with_retry(_call)

    async def embed_batch(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts. Uses a single Ollama call per batch."""
        await self.ensure_model(model)

        async def _call() -> list[list[float]]:
            response = await self._client.embed(model=model, input=texts)
            return response.embeddings

        return await self._with_retry(_call)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _build_options(temperature: float | None, max_tokens: int | None) -> dict:
        opts: dict = {}
        if temperature is not None:
            opts["temperature"] = temperature
        else:
            opts["temperature"] = settings.default_temperature
        if max_tokens is not None:
            opts["num_predict"] = max_tokens
        else:
            opts["num_predict"] = settings.default_max_tokens
        return opts

    async def _with_retry(self, coro_factory):
        """Run *coro_factory* with exponential back-off retry."""
        last_exc: Exception | None = None
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(settings.max_retries),
            wait=wait_exponential(
                min=settings.retry_wait_min,
                max=settings.retry_wait_max,
            ),
            retry=retry_if_exception_type((OSError, ConnectionError, TimeoutError)),
            reraise=False,
        ):
            with attempt:
                try:
                    return await coro_factory()
                except OllamaServiceError:
                    raise
                except Exception as exc:
                    last_exc = exc
                    log.warning("Ollama call failed (attempt %d): %s", attempt.retry_state.attempt_number, exc)
                    raise

        raise OllamaServiceError(f"All retries exhausted: {last_exc}") from last_exc

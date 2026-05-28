"""
BaseAgent – Abstract base class for all NexusIQ agents.

Each concrete agent must implement:
  - ``AGENT_ID``: one of the AgentId literals
  - ``system_prompt``: the system message injected before every conversation

Public interface:
  - ``invoke(messages, context)``  → str          (blocking)
  - ``stream(messages, context)``  → AsyncIterator[str] (streaming)
"""
from __future__ import annotations

import abc
import logging
from collections.abc import AsyncIterator
from typing import Sequence

from backend.services.model_router import AgentId, ModelRouter
from backend.services.ollama_service import OllamaService

log = logging.getLogger(__name__)

# Chat message shape accepted by Ollama
Message = dict  # {"role": "system"|"user"|"assistant", "content": str}


class BaseAgent(abc.ABC):
    """Abstract base for all NexusIQ investigation agents."""

    AGENT_ID: AgentId = NotImplemented  # Must be overridden

    def __init__(self, ollama: OllamaService, router: ModelRouter) -> None:
        self._ollama = ollama
        self._router = router
        self._config = router.get_config(self.AGENT_ID)

    # ── Subclass must provide ─────────────────────────────────────────────────

    @property
    @abc.abstractmethod
    def system_prompt(self) -> str:
        """The system message injected at the start of every conversation."""

    # ── Public API ────────────────────────────────────────────────────────────

    async def invoke(
        self,
        messages: Sequence[Message],
        context: str = "",
    ) -> str:
        """
        Run a non-streaming inference and return the full reply string.

        *context* is prepended to the last user message as additional
        knowledge-graph or dataset context.
        """
        prepared = self._prepare_messages(messages, context)
        log.info(
            "[%s] invoke – model=%s tokens~=%d",
            self.AGENT_ID,
            self._config.model,
            _estimate_tokens(prepared),
        )
        return await self._ollama.chat(
            model=self._config.model,
            messages=prepared,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )

    async def stream(
        self,
        messages: Sequence[Message],
        context: str = "",
    ) -> AsyncIterator[str]:
        """
        Async generator that yields text chunks as they arrive from Ollama.
        """
        prepared = self._prepare_messages(messages, context)
        log.info(
            "[%s] stream – model=%s tokens~=%d",
            self.AGENT_ID,
            self._config.model,
            _estimate_tokens(prepared),
        )
        async for chunk in self._ollama.stream_chat(
            model=self._config.model,
            messages=prepared,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        ):
            yield chunk

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _prepare_messages(
        self,
        messages: Sequence[Message],
        context: str,
    ) -> list[Message]:
        """
        Build the final message list:

        1. System message (this agent's prompt)
        2. All user/assistant turns
        3. If *context* is provided, prepend it to the last user message
        """
        msgs: list[Message] = [{"role": "system", "content": self.system_prompt}]

        turns = list(messages)
        if not turns:
            return msgs

        if context and turns:
            # Find the last user message and inject context above it
            for i in range(len(turns) - 1, -1, -1):
                if turns[i].get("role") == "user":
                    original_content = turns[i]["content"]
                    turns = list(turns)
                    turns[i] = {
                        "role": "user",
                        "content": (
                            f"[Context]\n{context}\n\n"
                            f"[Question]\n{original_content}"
                        ),
                    }
                    break

        msgs.extend(turns)
        return msgs

    @property
    def config(self):
        return self._config


def _estimate_tokens(messages: list[Message]) -> int:
    """Very rough token estimate: ~4 characters per token."""
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return total_chars // 4

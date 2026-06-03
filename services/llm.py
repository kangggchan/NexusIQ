"""
Standalone Gemini / Vertex AI service.

Model recommendations for this workbench:
  - gemini-2.5-flash   : Best all-rounder — fast, cost-effective, strong reasoning.
                         Use for orchestrator, graph, incident, context, and synthesize agents.
  - gemini-2.5-pro     : Deepest reasoning — ideal for the risk agent (blast radius / SLO).
  - gemini-2.0-flash   : Slightly faster / cheaper than 2.5-flash; use if latency is critical.
  - text-embedding-005 : Google's best embedding model (up to 3072 dims); replaces nomic-embed-text.

Authentication uses Application Default Credentials (ADC):
  - Cloud Run: service-account attached to the revision is used automatically.
  - Local dev: run  ``gcloud auth application-default login``  once.
"""
from __future__ import annotations

import os

from google import genai
from google.genai import types


class GeminiService:
    """
    Thin Vertex AI Gemini wrapper for standalone / scripted use.

    For the FastAPI backend use ``backend.services.ollama_service.GeminiService``
    which provides the same interface with async support.
    """

    def __init__(
        self,
        project: str | None = None,
        location: str = "us-central1",
        default_model: str = "gemini-2.5-flash",
    ) -> None:
        self.client = genai.Client(
            vertexai=True,
            project="knudc-khang-buiphuoc",
            location="us-central1",
        )
        self.default_model = default_model

    # ── Synchronous ───────────────────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Generate a completion for *prompt* and return the text."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        response = self.client.models.generate_content(
            model=model or self.default_model,
            contents=prompt,
            config=config,
        )
        return response.text or ""

    # ── Async ─────────────────────────────────────────────────────────────────

    async def generate_async(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Async version of generate()."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        response = await self.client.aio.models.generate_content(
            model=model or self.default_model,
            contents=prompt,
            config=config,
        )
        return response.text or ""
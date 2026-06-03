"""
NexusIQ Backend – Central Configuration
All environment-driven settings with sensible defaults.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Google Cloud / Vertex AI ─────────────────────────────────────────────
    google_cloud_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = Field(default="us-central1", alias="GOOGLE_CLOUD_LOCATION")

    # ── Agent model assignments ──────────────────────────────────────────────
    model_orchestrator: str = Field(default="gemini-2.5-flash", alias="MODEL_ORCHESTRATOR")
    model_graph: str = Field(default="gemini-2.5-flash", alias="MODEL_GRAPH")
    model_incident: str = Field(default="gemini-2.5-flash", alias="MODEL_INCIDENT")
    model_risk: str = Field(default="gemini-2.5-pro", alias="MODEL_RISK")
    model_embedding: str = Field(default="text-embedding-005", alias="MODEL_EMBEDDING")

    # ── Server ────────────────────────────────────────────────────────────────
    backend_host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    backend_reload: bool = Field(default=False, alias="BACKEND_RELOAD")
    log_level: str = Field(default="info", alias="LOG_LEVEL")
    backend_cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        alias="BACKEND_CORS_ORIGINS",
    )

    # ── Retry / resilience ───────────────────────────────────────────────────
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    retry_wait_min: float = Field(default=1.0, alias="RETRY_WAIT_MIN")
    retry_wait_max: float = Field(default=8.0, alias="RETRY_WAIT_MAX")

    # ── Inference defaults ───────────────────────────────────────────────────
    default_temperature: float = Field(default=0.7, alias="DEFAULT_TEMPERATURE")
    default_max_tokens: int = Field(default=2048, alias="DEFAULT_MAX_TOKENS")
    embedding_batch_size: int = Field(default=100, alias="EMBEDDING_BATCH_SIZE")


# Singleton – import this everywhere
settings = Settings()

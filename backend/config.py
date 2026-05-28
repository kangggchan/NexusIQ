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

    # ── Ollama ───────────────────────────────────────────────────────────────
    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    ollama_timeout: float = Field(default=120.0, alias="OLLAMA_TIMEOUT")
    ollama_keep_alive: str = Field(default="5m", alias="OLLAMA_KEEP_ALIVE")

    # ── Agent model assignments ──────────────────────────────────────────────
    model_orchestrator: str = Field(default="llama3.1:8b", alias="MODEL_ORCHESTRATOR")
    model_graph: str = Field(default="qwen2.5:7b", alias="MODEL_GRAPH")
    model_incident: str = Field(default="llama3.1:8b", alias="MODEL_INCIDENT")
    model_risk: str = Field(default="gemma3:12b", alias="MODEL_RISK")
    model_embedding: str = Field(default="nomic-embed-text", alias="MODEL_EMBEDDING")

    # ── Server ────────────────────────────────────────────────────────────────
    backend_host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    backend_reload: bool = Field(default=False, alias="BACKEND_RELOAD")
    log_level: str = Field(default="info", alias="LOG_LEVEL")

    # ── Retry / resilience ───────────────────────────────────────────────────
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    retry_wait_min: float = Field(default=1.0, alias="RETRY_WAIT_MIN")
    retry_wait_max: float = Field(default=8.0, alias="RETRY_WAIT_MAX")

    # ── Inference defaults ───────────────────────────────────────────────────
    default_temperature: float = Field(default=0.7, alias="DEFAULT_TEMPERATURE")
    default_max_tokens: int = Field(default=2048, alias="DEFAULT_MAX_TOKENS")
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE")


# Singleton – import this everywhere
settings = Settings()

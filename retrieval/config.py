"""
Retrieval module configuration.
All settings are environment-driven with sensible defaults.
"""
from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Resolve project root so we can find the dataset and .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = PROJECT_ROOT / "data" / "nexusiq_dataset"


class RetrievalSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    neo4j_username: str = Field(default="neo4j", alias="NEO4J_USERNAME")
    neo4j_password: str = Field(default="", alias="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", alias="NEO4J_DATABASE")
    neo4j_max_connection_pool: int = Field(default=20, alias="NEO4J_MAX_POOL")

    # ── ChromaDB Cloud ────────────────────────────────────────────────────────
    chroma_cloud_host: str = Field(default="localhost", alias="CHROMA_CLOUD_HOST")
    chroma_api_key: str = Field(default="", alias="CHROMA_API_KEY")
    chroma_tenant: str = Field(default="default_tenant", alias="CHROMA_TENANT")
    chroma_database: str = Field(default="nexusiq", alias="CHROMA_DATABASE")

    # ── Ollama embeddings ─────────────────────────────────────────────────────
    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    embedding_model: str = Field(default="nomic-embed-text", alias="MODEL_EMBEDDING")
    embedding_batch_size: int = Field(default=16, alias="EMBEDDING_BATCH_SIZE")
    embedding_timeout: float = Field(default=60.0, alias="EMBEDDING_TIMEOUT")

    # ── Retrieval tuning ──────────────────────────────────────────────────────
    vector_top_k: int = Field(default=10, alias="VECTOR_TOP_K")
    graph_max_depth: int = Field(default=3, alias="GRAPH_MAX_DEPTH")
    rerank_top_k: int = Field(default=8, alias="RERANK_TOP_K")
    rrf_k: int = Field(default=60, alias="RRF_K")  # RRF smoothing constant


# Singleton
settings = RetrievalSettings()

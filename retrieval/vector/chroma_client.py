"""
ChromaDB Cloud client — singleton with lazy async initialization.

chromadb.AsyncHttpClient(...) is itself a coroutine, so we must await it
before the client can be used.  Use `await get_client()` everywhere.
"""
from __future__ import annotations

import logging
import chromadb

from retrieval.config import settings

log = logging.getLogger(__name__)

_client: chromadb.AsyncClientAPI | None = None


async def get_client() -> chromadb.AsyncClientAPI:
    """Return (and lazily create) the singleton async ChromaDB client."""
    global _client
    if _client is None:
        _client = await chromadb.AsyncHttpClient(
            host=settings.chroma_cloud_host,
            port=443,
            ssl=True,
            headers={"x-chroma-token": settings.chroma_api_key},
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
        )
        log.info(
            "ChromaDB client created → %s / %s",
            settings.chroma_cloud_host,
            settings.chroma_database,
        )
    return _client


async def get_or_create_collection(name: str) -> chromadb.AsyncCollection:
    """Get or create a collection by name."""
    client = await get_client()
    return await client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


async def health_check() -> dict:
    """Verify ChromaDB connectivity."""
    client = await get_client()
    version = await client.get_version()
    collections = await client.list_collections()
    return {
        "status": "ok",
        "version": version,
        "collection_count": len(collections),
    }

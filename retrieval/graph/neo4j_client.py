"""
Neo4j async connection manager with lazy initialization.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession

from retrieval.config import settings

log = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    """Return the singleton AsyncDriver, creating it on first call."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
            max_connection_pool_size=settings.neo4j_max_connection_pool,
        )
        log.info("Neo4j driver created → %s", settings.neo4j_uri)
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        log.info("Neo4j driver closed.")


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager that yields a Neo4j session."""
    driver = get_driver()
    async with driver.session(database=settings.neo4j_database) as session:
        yield session


async def health_check() -> dict:
    """Verify connectivity and return server info."""
    async with get_session() as session:
        result = await session.run("RETURN 1 AS ok")
        record = await result.single()
        return {"status": "ok", "uri": settings.neo4j_uri, "result": record["ok"]}

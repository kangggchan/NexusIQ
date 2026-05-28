"""
CLI ingestion runner.

Usage::

    # Ingest everything
    python -m retrieval.ingestion.run_ingestion

    # Only Neo4j
    python -m retrieval.ingestion.run_ingestion --target neo4j

    # Only ChromaDB
    python -m retrieval.ingestion.run_ingestion --target chroma
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)

log = logging.getLogger("run_ingestion")


async def main(target: str) -> None:
    if target in ("neo4j", "all"):
        from retrieval.ingestion.neo4j_ingestor import ingest_all as neo4j_ingest
        log.info("=== Neo4j ingestion ===")
        counts = await neo4j_ingest()
        log.info("Neo4j totals: %s", counts)

    if target in ("chroma", "all"):
        from retrieval.ingestion.chroma_ingestor import ingest_all as chroma_ingest
        log.info("=== ChromaDB ingestion ===")
        counts = await chroma_ingest()
        log.info("ChromaDB totals: %s", counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NexusIQ dataset ingestion")
    parser.add_argument(
        "--target",
        choices=["neo4j", "chroma", "all"],
        default="all",
        help="Which store(s) to ingest into",
    )
    args = parser.parse_args()
    asyncio.run(main(args.target))

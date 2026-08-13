"""Shared Neo4j Aura driver, loading NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD
from the repo-root .env -- the same convention used for the Langfuse
credentials in agent/tracing.py. Both scripts/ingest_graph.py and
agent/tools.py use get_driver() instead of each creating their own.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        )
    return _driver

"""Neo4j Aura access via the HTTPS Query API rather than the Bolt driver.

Bolt (port 7687, raw TCP) doesn't route through this network's HTTP(S)-only
proxy, so the official `neo4j` driver can't reach Aura here -- but Aura also
exposes Cypher over plain HTTPS specifically for networks like this one, and
that does work through the proxy. NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD load
from the repo-root .env, the same convention used for the Langfuse
credentials in agent/tracing.py. NEO4J_DATABASE defaults to "neo4j" but on
this Aura Free instance the database is named after the instance ID, same
as NEO4J_USER -- set NEO4J_DATABASE explicitly if that's the case for you.

A single connection reused across calls (rather than a fresh one per query)
cuts down on proxy CONNECT handshakes, which this corporate proxy has shown
to occasionally drop mid-batch; a couple of retries on top of that absorbs
the rest.
"""

import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30,
        )
    return _client


def _query_api_url() -> str:
    host = os.environ["NEO4J_URI"].split("://", 1)[1]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    return f"https://{host}/db/{database}/query/v2"


def run_query(statement: str, retries: int = 3, **parameters) -> list[dict]:
    """Run a single Cypher statement and return its rows as dicts."""
    url = _query_api_url()
    payload = {"statement": statement, "parameters": parameters}

    for attempt in range(retries):
        try:
            response = _get_client().post(url, json=payload)
            break
        except httpx.TransportError:
            if attempt == retries - 1:
                raise
            time.sleep(0.5 * (attempt + 1))

    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    fields = body["data"]["fields"]
    values = body["data"]["values"]
    return [dict(zip(fields, row)) for row in values]

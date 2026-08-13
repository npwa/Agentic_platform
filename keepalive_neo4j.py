#!/usr/bin/env python3
"""Tiny KeepAlive node so the Aura Free instance does not
auto-pause after ~72 hours of read-only activity.

Usage:
    python keepalive_neo4j.py

Requires NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in the environment (or in
the repo-root .env, loaded automatically via agent.graph_db). Runs over
Aura's HTTPS Query API rather than the Bolt driver -- see agent/graph_db.py
for why (Bolt doesn't traverse an HTTP(S)-only proxy).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from agent.graph_db import run_query


def main() -> int:
    if not os.getenv("NEO4J_URI") or not os.getenv("NEO4J_PASSWORD"):
        print(
            "Missing NEO4J_URI or NEO4J_PASSWORD. "
            "Set them in the environment or in the repo-root .env.",
            file=sys.stderr,
        )
        return 1

    now = datetime.now(timezone.utc).isoformat()

    rows = run_query(
        """
        MERGE (k:KeepAlive {id: 'agentic_platform_poc'})
        SET k.last_seen = datetime($ts),
            k.source    = 'keepalive_neo4j.py'
        RETURN k.id AS id, k.last_seen AS last_seen
        """,
        ts=now,
    )
    rec = rows[0]
    print(f"Keep-alive written: id={rec['id']} last_seen={rec['last_seen']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

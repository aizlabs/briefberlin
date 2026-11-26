"""Host commands for editorial discovery."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .db import connect
from .inventory import DEFAULT_REGISTRY
from .registry import sync_registry


def coverage(conn: sqlite3.Connection) -> dict:
    """Report lookup resources and configured adapters, including unverified endpoints."""
    sources = conn.execute("SELECT count(*) FROM sources WHERE present=1").fetchone()[0]
    adapters = dict(conn.execute("""
        SELECT adapter,count(*) FROM endpoints WHERE active=1 GROUP BY adapter ORDER BY adapter
    """))
    lookups = [dict(row) for row in conn.execute("""
        SELECT s.id,r.field,r.purpose,r.url FROM sources s
        JOIN source_resources r ON r.source_id=s.id AND r.current=1
        WHERE s.present=1 AND r.purpose IN ('reference','example','contact','subscription')
        ORDER BY s.id,r.field
    """)]
    endpoints = [dict(row) for row in conn.execute("""
        SELECT s.id AS source_id,e.id AS endpoint_id,e.adapter,e.url,s.scope,s.active,
               p.last_success,p.failures,p.last_failure
        FROM sources s JOIN source_endpoints se ON se.source_id=s.id AND se.current=1
        JOIN endpoints e ON e.id=se.endpoint_id
        JOIN poll_state p ON p.endpoint_id=e.id AND p.generation=e.generation
        WHERE s.present=1 ORDER BY s.id
    """)]
    return {"sources": sources, "active_poll_endpoints": adapters, "endpoints": endpoints,
            "lookup_resources": lookups}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="host database (default: BRIEFBERLIN_EDITORIAL_DB or XDG state)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create or migrate the database")
    sync = commands.add_parser("registry-sync", help="validate and atomically reload the directory")
    sync.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    commands.add_parser("coverage", help="show configured discovery and lookup endpoints")
    args = parser.parse_args(argv)
    try:
        with closing(connect(args.db)) as conn:
            if args.command == "registry-sync":
                sync_registry(conn, args.registry)
            if args.command == "coverage":
                print(json.dumps(coverage(conn), ensure_ascii=False))
            else:
                print(json.dumps({"command": args.command, "schema_version":
                                  conn.execute("PRAGMA user_version").fetchone()[0]}))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

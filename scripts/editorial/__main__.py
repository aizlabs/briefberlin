"""Host commands for editorial discovery."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from . import triage_cli
from .collection import collect, paused, set_paused
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
    gaps = [dict(row) for row in conn.execute("""
        SELECT g.* FROM collection_gaps g JOIN endpoints e
        ON e.id=g.endpoint_id AND e.generation=g.generation WHERE e.active=1
        ORDER BY g.endpoint_id,g.category
    """)]
    return {"collection_paused": paused(conn), "collection_gaps": gaps, "sources": sources, "active_poll_endpoints": adapters, "endpoints": endpoints,
            "lookup_resources": lookups}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="host database (default: BRIEFBERLIN_EDITORIAL_DB or XDG state)")
    commands = parser.add_subparsers(dest="command", required=True)
    triage_cli.add_commands(commands)
    commands.add_parser("init", help="create or migrate the database")
    sync = commands.add_parser("registry-sync", help="validate and atomically reload the directory")
    sync.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    commands.add_parser("coverage", help="show configured discovery and lookup endpoints")
    run = commands.add_parser("collect", help="poll due endpoints and report per-source results")
    run.add_argument("--limit", type=int, default=20)
    run.add_argument("--lookback-hours", type=int, default=0)
    run.add_argument("--children", type=int, default=4)
    commands.add_parser("collection-pause", help="pause collection and discard in-flight batches")
    commands.add_parser("collection-resume", help="resume collection on the regular due schedule")
    args = parser.parse_args(argv)
    try:
        with closing(connect(args.db)) as conn:
            if args.command == "registry-sync":
                sync_registry(conn, args.registry)
            if args.command == "collect":
                print(json.dumps(collect(conn, limit=args.limit, children=args.children,
                                         lookback_hours=args.lookback_hours)))
            elif args.command in {"collection-pause", "collection-resume"}:
                set_paused(conn, args.command == "collection-pause")
                print(json.dumps({"collection_paused": paused(conn)}))
            elif args.command == "coverage":
                print(json.dumps(coverage(conn), ensure_ascii=False))
            elif args.command.startswith(("triage-", "archive-")):
                result = triage_cli.execute(conn, args)
                print(json.dumps(result, ensure_ascii=False))
                if args.command == "archive-sync" and not result["ready"]:
                    return 1
            else:
                print(json.dumps({"command": args.command, "schema_version":
                                  conn.execute("PRAGMA user_version").fetchone()[0]}))
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f"{parser.prog}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

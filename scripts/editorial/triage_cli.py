"""Host command arguments for archive reconciliation and model work."""

import argparse
import sqlite3
import sys
from pathlib import Path

from . import triage
from .archive import resolve_archive, sync_archive


def add_commands(commands: argparse._SubParsersAction) -> None:
    sync = commands.add_parser("archive-sync", help="reconcile public editions with the live sitemap")
    sync.add_argument("--output", type=Path, default=Path("output"))
    sync.add_argument("--sitemap-fixture", type=Path, help="offline host test XML, use a disposable DB")
    sync.add_argument("--bootstrap-epoch", type=int, help="known last live epoch or explicit initial clock")
    sync.add_argument("--known-live-story", help="story ID with independently established last live time")
    sync.add_argument("--known-live-epoch", type=int)
    resolve = commands.add_parser("archive-resolve", help="identify or dismiss a possible live duplicate")
    resolve.add_argument("--live", required=True)
    resolve.add_argument("--candidate", required=True)
    resolve.add_argument("--outcome", required=True, choices=["same", "distinct"])
    resolve.add_argument("--actor", required=True)
    for command in ("triage-claim", "triage-resolve"):
        claim = commands.add_parser(command)
        claim.add_argument("--owner", required=True)
        claim.add_argument("--lease-seconds", type=int, default=600)
        if command == "triage-resolve":
            held = claim.add_mutually_exclusive_group(required=True)
            held.add_argument("--revision", type=int)
            held.add_argument("--story", help="reassess this insufficient story with its latest evidence")
            claim.add_argument("--compare", help="include this known story in the editor's shortlist")
    decide = commands.add_parser("triage-decide", help="submit bounded JSON on stdin")
    decide.add_argument("--token", required=True)
    decide.add_argument("--model", required=True)
    commands.add_parser("triage-status")
    rate = commands.add_parser("triage-rate")
    rate.add_argument("--actor", required=True)
    rate.add_argument("--action-id", required=True)
    rate.add_argument("--story", required=True)
    rate.add_argument("--rating", type=int, required=True)
    rate.add_argument("--note", required=True)


def execute(conn: sqlite3.Connection, args: argparse.Namespace) -> dict:
    if args.command == "archive-sync":
        return sync_archive(conn, output=args.output, fixture=args.sitemap_fixture,
                            bootstrap_epoch=args.bootstrap_epoch, known_live_story=args.known_live_story,
                            known_live_epoch=args.known_live_epoch)
    if args.command == "archive-resolve":
        return resolve_archive(conn, live_id=args.live, candidate_id=args.candidate, outcome=args.outcome,
                               actor=args.actor)
    if args.command == "triage-status":
        return triage.status(conn)
    if args.command in {"triage-claim", "triage-resolve"}:
        return triage.claim(conn, owner=args.owner, lease_seconds=args.lease_seconds,
                            held_revision=getattr(args, "revision", None), compare=getattr(args, "compare", None),
                            held_story=getattr(args, "story", None))
    if args.command == "triage-decide":
        return triage.decide(conn, token=args.token, model=args.model, raw=sys.stdin.read(64001))
    if args.command == "triage-rate":
        return triage.rate(conn, actor=args.actor, action_id=args.action_id, story_id=args.story,
                           rating=args.rating, note=args.note)
    raise ValueError("unknown triage command")

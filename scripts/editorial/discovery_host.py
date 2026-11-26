"""Installed host operations and the two-operation OpenClaw triage capability."""

import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from . import (
    collection,
    dispatch,
    publication_host,
    publication_worker,
    review,
    review_telegram,
    triage,
)
from .archive import setting
from .db import connect
from .inventory import DEFAULT_REGISTRY
from .registry import sync_registry

MAX_REQUEST = 256_000


def wake(conn):
    # PathExists coalesces concurrent decisions. The five-minute timer also retries after a crash.
    (publication_host.state_dir(conn) / "dispatch.wake").touch(mode=0o600)


def poll(conn):
    path = Path(os.environ.get("BB_SOURCE_REGISTRY", DEFAULT_REGISTRY))
    sync_registry(conn, path)
    return collection.collect(conn, limit=10, children=3)


def dispatch_cycle(conn):
    root = publication_host.state_dir(conn)
    (root / "dispatch.wake").unlink(missing_ok=True)
    result = publication_worker.cycle(conn, root)
    if result["state"] in {"review", "awaiting-editor"}:
        result["outbox"] = review_telegram.send_pending(conn)
    return result


def first_story(conn, story, version):
    """Pin the observed winner and run at most its authorized work. Never advance the general queue."""
    root = publication_host.state_dir(conn)
    publication_host.check_legacy(conn)
    policy = dispatch.Policy.load()
    review_telegram.route(policy)
    review.callback_key()
    target = [story, version]
    pinned = json.loads(setting(conn, "launch_target") or "null")
    if pinned and pinned != target:
        raise ValueError("a different launch is pinned")
    if not pinned:
        if not publication_host.refresh_archive(conn, root)["ready"]:
            return {"state": "archive-block"}
        dispatch.configure(conn, mode="live", launch_target=target)
    prior = conn.execute("""SELECT id,state,commit_sha FROM dispatch_work WHERE story_id=? AND version=?
        AND commit_sha IS NOT NULL ORDER BY rowid DESC LIMIT 1""", (story, version)).fetchone()
    if prior:
        return {"state": "recover-only", "work_id": prior["id"], "commit": prior["commit_sha"]}
    if not publication_host.refresh_archive(conn, root)["ready"]:
        return {"state": "archive-block"}
    decision = dispatch.tick(conn)
    if (decision["state"] == "requested" and decision["kind"] != "manual"
            and [decision["story_id"], decision["version"]] == target):
        return publication_worker.send_work(conn, root, decision["work_id"])
    if decision["state"] in {"review", "awaiting-editor"}:
        decision["outbox"] = review_telegram.send_pending(conn)
    return decision


def handle(conn, request):
    if not isinstance(request, dict):
        raise ValueError("expected a scoped triage request")
    model = os.environ.get("BB_TRIAGE_MODEL", "")
    if len(model) > 160 or not re.fullmatch(r"[a-zA-Z0-9._-]+/[^\s]+", model):
        raise ValueError("configure the scheduled OpenClaw provider/model identifier")
    if set(request) == {"op", "owner"} and request["op"] == "claim":
        owner = request["owner"]
        if not isinstance(owner, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", owner):
            raise ValueError("invalid triage invocation identifier")
        return triage.claim(conn, owner="openclaw:" + owner)
    if set(request) == {"op", "token", "decision"} and request["op"] == "decide":
        token = request["token"]
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("invalid triage token")
        lease = conn.execute("SELECT owner FROM triage_leases WHERE token=?", (token,)).fetchone()
        if not lease or not lease[0].startswith("openclaw:"):
            raise ValueError("unknown triage capability")
        result = triage.decide(conn, token=token, model="requested:" + model,
                               raw=json.dumps(request["decision"], ensure_ascii=False))
        if result["state"] == "done":
            wake(conn)
        return result
    raise ValueError("unsupported triage operation")


def rpc():
    os.umask(0o077)
    try:
        raw = sys.stdin.buffer.readline(MAX_REQUEST + 1)
        if not raw.endswith(b"\n") or len(raw) > MAX_REQUEST:
            raise ValueError("invalid request framing or size")
        with closing(connect()) as conn:
            reply = {"ok": True, "result": handle(conn, json.loads(raw))}
    except (OSError, ValueError, KeyError, RecursionError, sqlite3.Error) as exc:
        reply = {"ok": False, "error": str(exc)[:500]}
    print(json.dumps(reply))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("poll")
    commands.add_parser("dispatch")
    launch = commands.add_parser("first-story", help="authorize only this observed story and evidence version")
    launch.add_argument("story")
    launch.add_argument("version", type=int)
    args = parser.parse_args()
    os.umask(0o077)
    with closing(connect()) as conn:
        if args.command == "first-story":
            result = first_story(conn, args.story, args.version)
        else:
            result = poll(conn) if args.command == "poll" else dispatch_cycle(conn)
    print(json.dumps(result, ensure_ascii=False))

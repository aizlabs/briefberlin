"""One group-authenticated Unix socket request, served by systemd Accept=yes."""

import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from . import manual_drafts, publication_host
from .db import connect
from .publication_cli import manual

MAX_REQUEST = 1_100_000
ARITY = {
    "status": {0}, "received": {0}, "generate": {0}, "match": {2}, "preview": {0},
    "stories": {0}, "illustrate": {3}, "add-image": {2, 3}, "publish": {0, 1},
    "discard": {0, 1}, "cancel": {0},
}


def handle(conn, request):
    if not isinstance(request, dict) or set(request) - {"action", "args", "content"}:
        raise ValueError("invalid manual request")
    action, args = request.get("action"), request.get("args", [])
    if (not isinstance(action, str) or action not in ARITY or not isinstance(args, list)
            or len(args) not in ARITY[action] or any(
                not isinstance(a, str) or len(a) > 4000 or a == "--" or "\x00" in a for a in args)):
        raise ValueError("invalid scoped manual operation or arguments")
    content = request.get("content")
    if content is not None:
        if action not in {"received", "generate", "add-image"} or not isinstance(content, str):
            raise ValueError("unexpected attachment")
        content = base64.b64decode(content, validate=True)
        if len(content) > (800_000 if action == "add-image" else 256_000):
            raise ValueError("attachment too large")
    if action in {"received", "add-image"} and not content:
        raise ValueError("attachment required")
    root = publication_host.state_dir(conn)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        uploaded = None
        if content is not None:
            uploaded = Path(tmp) / ("image" if action == "add-image" else "article.source.txt")
            uploaded.write_bytes(content)
        if action == "add-image":
            args = [args[0], str(uploaded), *args[1:]]
        result = manual(conn, root, action, args, remote=True, uploaded=uploaded)
        draft = manual_drafts.pending(conn)
        return {"ok": True, "result": result,
                "source_hash": draft["source_hash"] if action == "generate" and draft else None}


def main():
    os.umask(0o077)
    try:
        raw = sys.stdin.buffer.readline(MAX_REQUEST + 1)
        if len(raw) > MAX_REQUEST:
            raise ValueError("oversized request")
        with closing(connect()) as conn:
            reply = handle(conn, json.loads(raw))
    except (ValueError, KeyError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        reply = {"ok": False, "result": str(exc)[:3000]}
    print(json.dumps(reply))


if __name__ == "__main__":
    main()

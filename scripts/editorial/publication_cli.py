"""Trusted host publisher commands and the scoped bb manual workflow."""

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from . import dispatch
from . import manual_drafts as drafts
from . import publication_host as host
from . import publication_worker as worker
from .db import connect
from .publication_files import artifacts, ensure_private, protect_text


def inbox():
    return Path(os.environ.get("BB_INBOX", "/opt/openclaw/work/inbox")) / "article.txt"


def manual(conn, root, action, args, *, remote=False, uploaded=None):
    # Keep the manual editing lock independent of generation for unrelated dispatch work.
    # Release it before running the sender; approved artifacts are immutable.
    with host.locked(root, "manual"):
        worker.finish_drafts(conn)
        draft = drafts.pending(conn)
        host.prune(root, "manual", (draft["id"],) if draft else ())
        if action != "legacy-import":
            host.check_legacy(conn)
        if action == "status":
            return drafts.status(conn)
        if action == "received":
            if draft or (not remote and (len(args) != 1 or Path(args[0]).resolve() != inbox().resolve())):
                raise ValueError("a draft is already waiting or the source is outside the configured inbox")
            path = uploaded if remote else inbox()
            if not path or path.is_symlink() or not path.is_file() or path.stat().st_size > 256_000:
                raise ValueError("invalid inbox file")
            count = len(path.read_text().split())
            sent = host.telegram(f"Article received (~{count} words). Send any remaining parts, then Generate or Cancel.",
                                 [("Generate", "bb-generate"), ("Cancel", "bb-cancel")])
            return f"BUTTONS SENT ({count} words)" if sent else f"RECEIVED: {count} words"
        if action in {"generate", "stage", "legacy-import"} and not draft:
            importing = action == "legacy-import"
            path = host.legacy() if importing else Path(args[0]) if len(args) == 1 else None
            if remote:
                path = uploaded
            if path is None or (action == "generate" and not remote and path.resolve() != inbox().resolve()):
                raise ValueError("provide the current private source")
            if action == "stage" and (path.resolve() != path.absolute() or not (
                path.is_relative_to(host.REPO / "private-input") or path.is_relative_to(host.REPO / "input/private")
                or path.name.endswith(".source.txt")
            )):
                raise ValueError("operator staging requires a regular private-input source")
            draft = drafts.stage(conn, root, path, importing=importing)
            if action == "generate" and not remote:
                # Only consume the known inbox file after saving the exact bytes durably.
                if hashlib.sha256(path.read_bytes()).hexdigest() == draft["source_hash"]:
                    path.unlink()
        elif action in {"legacy-import", "stage"}:
            raise ValueError("a draft is already waiting")
        if not draft:
            if action == "cancel":
                if not remote:
                    inbox().unlink(missing_ok=True)
                return "Cancelled."
            if action in {"publish", "discard"} and args:
                return prior_receipt(conn, action, args[0])
            raise ValueError("no waiting manual draft")
        directory = host.area(root, "manual", draft["id"])
        tree = directory / "checkout"
        if action == "match" and len(args) == 2 and args[0] == draft["id"] and draft["state"] == "matching":
            result = drafts.match(conn, draft, args[1], drafts.source_data(directory / "evidence.source.txt"))
            if result:
                return result
            draft = drafts.pending(conn)
            action = "generate"
        if action in {"generate", "stage", "legacy-import"}:
            return drafts.generate(conn, root, draft)
        if action == "preview":
            return drafts.preview(conn, root, draft)
        if action in {"stories", "illustrate", "add-image"} and draft["state"] == "waiting":
            manifest, posts = artifacts(tree, draft["story_id"])
            evidence = (directory / "evidence.source.txt").read_text()
            ensure_private(tree, manifest, evidence)
            if action == "stories":
                return host.helper(tree, "bb_images.py", "stories", *posts.values())
            if not args or args[0] != draft["story_id"]:
                raise ValueError("use the waiting story identifier")
            if action == "add-image":
                image = Path(args[1])
                if not image.is_file() or image.is_symlink() or image.stat().st_size > 800_000:
                    raise ValueError("invalid or oversized image")
                protect_text(image.read_bytes().decode(errors="ignore"), evidence, tree)
            for value in (args[1:] if action == "illustrate" else args[2:]):
                protect_text(value, evidence, tree)
            conn.execute("UPDATE publication_drafts SET display_id=NULL,message_id=NULL,snapshot=NULL WHERE id=?",
                         (draft["id"],))
            result = host.helper(tree, "bb_images.py", "add" if action == "add-image" else action,
                               *args, "--", *posts.values())
            ensure_private(tree, artifacts(tree, draft["story_id"])[0], evidence)
            return result
        if action in {"publish", "discard"} and args and args != [draft["display_id"]]:
            return prior_receipt(conn, action, args[0])
        if (action == "cancel" and draft["state"] not in {"ready", "failed", "matching", "generating"}
                and not (draft["state"] == "waiting" and not draft["display_id"])):
            raise ValueError("use the delivered Discard control for a completed draft")
        if action in {"cancel", "discard"}:
            if action == "discard" and draft["state"] != "withdraw":
                raise ValueError("explicit discard of the delivered draft is required")
            dispatch.release_manual_preview(conn, preview_id=draft["id"])
            conn.execute("UPDATE publication_drafts SET state='discarded' WHERE id=?", (draft["id"],))
            host.cleanup(directory)
            host.telegram("Discarded: the saved draft and source were deleted.")
            return "DISCARDED"
        if action != "publish" or draft["state"] != "approved":
            raise ValueError("action unavailable; check bb status or authenticate the exact preview decision")
        preview_id, version = draft["id"], draft["version"]
    decision = dispatch.reserve_manual(conn, preview_id=preview_id, version=version)
    if decision["state"] == "requested":
        decision = worker.send_work(conn, root, decision["work_id"])
    worker.deliver_notices(conn)
    return json.dumps(decision)


def prior_receipt(conn, action, display_id):
    row = conn.execute("""SELECT d.state FROM manual_actions a JOIN publication_drafts d ON a.draft_id=d.id
        WHERE a.display_id=? AND a.verb=?""", (display_id, action)).fetchone()
    if not row:
        raise ValueError("button belongs to an older or unapproved preview")
    return "RECORDED: " + row["state"]


def operator_absent(conn, root, work_id, sha, evidence):
    if len(evidence.strip()) < 20:
        raise ValueError("document definitive remote-side evidence and sender fencing")
    with host.locked(root, "sender"):
        remote = host.fetch()
        # An exit code of 1 means conclusively 'not an ancestor' in the fetched history.
        probe = subprocess.run(["git", "merge-base", "--is-ancestor", sha, remote], cwd=host.REPO,
                               capture_output=True, timeout=30)
        if probe.returncode != 1:
            raise ValueError("expected commit is reachable or ancestry cannot be established")
        return dispatch.reconcile(conn, work_id=work_id, commit=sha, outcome="absent",
                                  evidence="operator verified terminated sender and definitive absence: " + evidence)


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    sub = parser.add_subparsers(dest="op", required=True)
    bb = sub.add_parser("manual")
    bb.add_argument("action", nargs="?", default="status", choices=[
        "status", "received", "generate", "match", "preview", "stories", "illustrate",
        "add-image", "publish", "discard", "cancel", "legacy-import", "stage"])
    bb.add_argument("args", nargs="*")
    sub.add_parser("telegram-event", help="trusted authenticated Telegram adapter only; read update JSON on stdin")
    sub.add_parser("cycle", help="recover, synchronize live archive, service eligible manual or scheduled work")
    sub.add_parser("recover", help="read-only external verification and local ledger reconciliation")
    run = sub.add_parser("work")
    run.add_argument("work_id")
    absent = sub.add_parser("confirmed-absent")
    absent.add_argument("work_id")
    absent.add_argument("commit")
    absent.add_argument("--evidence", required=True)
    args = parser.parse_args(argv)
    try:
        with closing(connect(args.db, recovery=args.op == "confirmed-absent")) as conn:
            root = host.state_dir(conn)
            if args.op == "manual":
                print(manual(conn, root, args.action, args.args))
                return 0
            host.check_legacy(conn)
            if args.op == "telegram-event":
                raw = sys.stdin.buffer.read(65_537)
                if len(raw) > 65_536:
                    raise ValueError("oversized Telegram update")
                with host.locked(root, "manual"):
                    result = drafts.receive_update(conn, json.loads(raw), os.environ["BB_TELEGRAM_ACCOUNT"])
            elif args.op == "confirmed-absent":
                result = operator_absent(conn, root, args.work_id, args.commit, args.evidence)
            elif args.op == "work":
                result = worker.send_work(conn, root, args.work_id)
            elif args.op == "cycle":
                result = worker.cycle(conn, root)
            else:
                result = worker.recover(conn, root)
                worker.housekeep(conn, root)
            if args.op != "cycle":
                worker.deliver_notices(conn)
            print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

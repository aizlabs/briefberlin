"""Private online snapshots, non-overwriting restore staging and fenced reconciliation."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
from contextlib import ExitStack, closing
from pathlib import Path

from . import collection, dispatch, publication_verify, publication_worker
from . import publication_host as host
from .archive import set_setting, setting
from .db import connect, transaction
from .publication_files import git


def integrity(conn):
    if [r[0] for r in conn.execute("PRAGMA integrity_check")] != ["ok"]:
        raise ValueError("SQLite integrity_check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("SQLite foreign_key_check failed")


def files(directory):
    hashes = {}
    for name in sorted(directory.rglob("*")):
        path = str(name.relative_to(directory))
        mode = name.lstat().st_mode
        if name.is_symlink():
            hashes[path] = ["link", os.readlink(name)]
        elif stat.S_ISREG(mode):
            with name.open("rb") as stream:
                hashes[path] = ["file", stat.S_IMODE(mode), hashlib.file_digest(stream, "sha256").hexdigest()]
        elif not stat.S_ISDIR(mode):
            raise ValueError(f"unsupported private backup entry {path}")
    return hashes


def target_for(path, forbidden):
    path = path.absolute()
    if path != path.resolve() or os.path.lexists(path):
        raise ValueError("destination must be new and use resolved paths")
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise ValueError("use an existing owner-only destination parent")
    if any(path.is_relative_to(source) or source.is_relative_to(path) for source in forbidden):
        raise ValueError("destination overlaps protected source state")
    return path


def write_snapshot(conn, destination):
    db = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    root = host.state_dir(conn)
    repo = host.REPO
    if db.is_relative_to(repo) or repo.is_relative_to(db.parent):
        raise ValueError("backup requires separate state and repository directories")
    dest = target_for(destination, [db.parent, repo])
    with tempfile.TemporaryDirectory(dir=dest.parent) as temporary, ExitStack() as locks:
        stage = Path(temporary) / "snapshot"
        stage.mkdir(mode=0o700)
        # Match sender -> archive nesting in publication_worker. Fail cleanly if a job is running.
        for name in ("sender", "manual", "archive"):
            locks.enter_context(host.locked(root, name, blocking=False))
        if ((repo / ".git").resolve() != repo / ".git" or not (repo / ".git").is_dir()
                or (repo / ".git/objects/info/alternates").exists() or (repo / ".git/commondir").exists()
                or os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")):
            raise ValueError("use a standalone, full non-shared Git clone for the private publisher")
        roots = [Path(field[9:].decode()) for field in git(repo, "worktree", "list", "--porcelain", "-z").split(b"\0")
                 if field.startswith(b"worktree ")]
        if not roots or any(tree != repo and not tree.is_relative_to(root) for tree in roots):
            raise ValueError("publisher clone has worktrees outside its private state")
        snapshot_id = uuid.uuid4().hex
        with closing(sqlite3.connect(stage / "database")) as snapshot:
            conn.backup(snapshot)
            set_setting(snapshot, "restore_quarantine", "1")
            set_setting(snapshot, "restore_snapshot", snapshot_id)
            snapshot.commit()
            snapshot.execute("PRAGMA journal_mode=DELETE")
            integrity(snapshot)
        (stage / "database").chmod(0o600)
        shutil.copytree(root, stage / "publisher", symlinks=True)
        # Store the worktrees' common .git directory and objects together with their main checkout.
        shutil.copytree(repo, stage / "repo", symlinks=True,
                        ignore=lambda directory, names: {".venv"} if Path(directory) == repo else set())
        record = {"format": 1, "snapshot_id": snapshot_id, "db": str(db), "repo": str(repo), "time": int(time.time()),
                  "head": git(repo, "rev-parse", "HEAD").decode().strip(),
                  "main": git(repo, "rev-parse", "origin/main").decode().strip(),
                  "worktrees": [str(tree) for tree in roots], "files": files(stage)}
        (stage / "manifest.json").write_text(json.dumps(record, sort_keys=True))
        if os.path.lexists(dest):
            raise ValueError("destination created concurrently")
        stage.rename(dest)
    return dest


def check(bundle):
    if bundle.resolve() != bundle.absolute() or bundle.stat().st_mode & 0o077 or bundle.stat().st_uid != os.getuid():
        raise ValueError("expected trusted service-owned private backup directory")
    record = json.loads((bundle / "manifest.json").read_text())
    if record.get("format") != 1:
        raise ValueError("unknown backup format")
    actual = files(bundle)
    del actual["manifest.json"]
    if record["files"] != actual:
        raise ValueError("private backup contents do not match manifest")
    with closing(sqlite3.connect((bundle / "database").resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        integrity(conn)
        if setting(conn, "restore_quarantine") != "1":
            raise ValueError("snapshot lacks the restore fence")
    return record


def stage_restore(bundle, destination):
    record = check(bundle)
    db = Path(record["db"])
    dest = target_for(destination, [bundle, db.parent, Path(record["repo"]), host.REPO])
    with tempfile.TemporaryDirectory(dir=dest.parent) as temporary:
        stage = Path(temporary) / "restore"
        shutil.copytree(bundle, stage, symlinks=True)
        check(stage)
        (stage / "database").rename(stage / db.name)
        (stage / "publisher").rename(stage / (db.name + ".publisher"))
        if os.path.lexists(dest):
            raise ValueError("restore destination created concurrently")
        stage.rename(dest)
    return {"staged": str(dest), "original_db": str(db), "original_repo": record["repo"]}


def reconcile(conn, record, expected, audit):
    db = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    if setting(conn, "restore_quarantine") != "1" or record["repo"] != str(host.REPO) or record["db"] != str(db):
        raise ValueError("reconcile only quarantined state at both original absolute paths")
    if len(audit.strip()) < 30:
        raise ValueError("record the operator's post-snapshot remote and editor reconciliation")
    if setting(conn, "restore_snapshot") != record["snapshot_id"]:
        raise ValueError("backup does not identify this restored database")
    root = host.state_dir(conn)
    with host.locked(root, "maintenance"):
        remote = host.fetch()
        if expected != remote or publication_verify.public("/briefberlin-deployment.txt").strip() != remote:
            raise ValueError("wait for the reviewed remote tip to be deployed by Pages")
        git(host.REPO, "merge-base", "--is-ancestor", record["main"], remote)
        work = publication_worker.recover(conn, root)
        if work["state"] not in {"live", "idle"}:
            raise ValueError("outstanding publisher receipt needs definitive reconciliation")
        publication_worker.finish_drafts(conn)
        dispatch.configure(conn, mode="observe", paused=True)
        collection.set_paused(conn, True)
        with transaction(conn):
            # Even if the snapshot was already paused, expire pre-snapshot authorizations.
            job = dispatch.active(conn)
            if job:
                dispatch.transition(conn, job["id"], "superseded", "restore requires fresh approval", int(time.time()))
            conn.execute("UPDATE review_requests SET state='superseded' WHERE state IN ('pending','approved')")
            conn.execute("UPDATE triage_leases SET state='stale' WHERE state='active'")
            conn.execute("""UPDATE publication_drafts SET state='waiting',approved_event=NULL,
                display_id=NULL,snapshot=NULL,message_id=NULL WHERE state IN ('approved','waiting')""")
        archive = host.refresh_archive(conn, root)
        if not archive["ready"] or host.fetch() != remote:
            raise ValueError("archive or current main requires reconciliation: " + str(archive.get("issues", []))[:1500])
        integrity(conn)
        with transaction(conn):
            set_setting(conn, "restore_audit", json.dumps({"main": remote, "at": int(time.time()), "note": audit}))
            conn.execute("DELETE FROM settings WHERE key='restore_quarantine'")
        return {"state": "reconciled", "main": remote, "mode": "observe", "publish_paused": True, "collection_paused": True}


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="op", required=True)
    for name in ("create", "check", "stage", "reconcile"):
        action = sub.add_parser(name)
        action.add_argument("bundle", type=Path)
        if name == "stage":
            action.add_argument("new_directory", type=Path)
        if name == "reconcile":
            action.add_argument("--verified-main", required=True)
            action.add_argument("--audit", required=True)
    args = parser.parse_args()
    if args.op == "stage":
        result = stage_restore(args.bundle, args.new_directory)
    elif args.op == "create":
        with closing(connect()) as conn:
            result = {"created": str(write_snapshot(conn, args.bundle))}
    elif args.op == "check":
        result = {k: v for k, v in check(args.bundle).items() if k != "files"}
    else:
        record = check(args.bundle)
        with closing(connect(recovery=True)) as conn:
            result = reconcile(conn, record, args.verified_main, args.audit)
    print(json.dumps(result))

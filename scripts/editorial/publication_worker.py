"""Single fenced sender for scheduled stories and explicitly approved manual drafts."""

import hashlib
import json
import os
import subprocess
from datetime import datetime

from scripts.publisher import PUBLICATION_ZONE

from . import dispatch, manual_drafts, publication_host as host
from .publication_files import artifacts, changes, check_story_in_base, ensure_private, git, read_artifact, restamp, verify_commit
from .publication_verify import SITE, verify

ERRORS = (ValueError, OSError, KeyError, subprocess.SubprocessError)


def recover(conn, root):
    if (dispatch.status(conn)["work"] or {}).get("state") not in dispatch.EXTERNAL:
        return {"state": "idle"}
    with host.locked(root, "sender"):
        status = dispatch.status(conn)
        work, commit = status["work"], status["expected_commit"]
        if not work or work["state"] not in dispatch.EXTERNAL:
            return {"state": "idle"}
        try:
            evidence = verify(host.REPO, commit, status["manifest"])
        except ERRORS as exc:
            return dispatch.reconcile(conn, work_id=work["id"], commit=commit, outcome="unknown",
                                      evidence=f"awaiting verification: {type(exc).__name__} {str(exc)[:250]}")
        result = dispatch.reconcile(conn, work_id=work["id"], commit=commit, outcome="live", evidence=evidence)
        return result


def deliver_notices(conn):
    """At-least-once human notifications; a lost send receipt cannot repeat publication."""
    rows = conn.execute("""SELECT w.* FROM dispatch_work w WHERE w.kind='manual'
        AND w.state IN ('live','push-authorized','external-uncertain') AND NOT EXISTS
        (SELECT 1 FROM publication_notices n WHERE n.work_id=w.id AND n.state=CASE WHEN
        w.state='live' THEN 'live' ELSE 'deploying' END) ORDER BY w.created_at LIMIT 10""").fetchall()
    for row in rows:
        state = "live" if row["state"] == "live" else "deploying"
        note = ("Live on briefberlin.de" if state == "live" else
                "Publication submitted for verification. I will message again when both articles are live.")
        links = "\n".join(SITE + p for p in json.loads(row["manifest"])["editions"].values())
        if host.telegram(f"{note}\nCommit {row['commit_sha'][:12]}\n{links}"):
            conn.execute("INSERT OR IGNORE INTO publication_notices VALUES(?,?)", (row["id"], state))


def finish_drafts(conn):
    # Recover a crash after the ledger transaction and before private file cleanup.
    conn.execute("""UPDATE publication_drafts SET state='live' WHERE state='approved'
        AND EXISTS(SELECT 1 FROM dispatch_work w WHERE w.manual_preview_id=publication_drafts.id AND w.state='live')""")


def housekeep(conn, root):
    # An unrelated manual generation may be using its own worktree for several minutes.
    # Cleanup can wait until the next cycle without delaying dispatch.
    try:
        with host.locked(root, "manual", blocking=False):
            finish_drafts(conn)
            draft = manual_drafts.pending(conn)
            if draft and draft["state"] == "withdraw":
                dispatch.release_manual_preview(conn, preview_id=draft["id"])
                conn.execute("UPDATE publication_drafts SET state='discarded' WHERE id=?", (draft["id"],))
                draft = None
            host.prune(root, "manual", (draft["id"],) if draft else ())
    except BlockingIOError:
        pass


def frozen(conn, work):
    story = conn.execute("SELECT title,summary FROM stories WHERE id=? AND evidence_version=?",
                         (work["story_id"], work["version"])).fetchone()
    rows = conn.execute("""SELECT e.fact,e.quote,e.attribution,e.wire_origin,e.url,
        i.published_at,i.observed_at FROM story_evidence e JOIN editorial_inputs i USING(revision_id)
        WHERE e.story_id=? AND e.evidence_version BETWEEN 1 AND ? ORDER BY e.evidence_version,e.revision_id
        LIMIT 101""", (work["story_id"], work["version"])).fetchall()
    if not story or not 1 <= len(rows) <= 100:
        raise ValueError("missing, stale or oversized frozen evidence")
    text = "\n\n".join([story["title"], story["summary"], *(json.dumps(dict(r), ensure_ascii=False) for r in rows)])
    if len(text.encode()) > 256_000:
        raise ValueError("evidence packet too large")
    return text


def copy_approved(conn, root, work, tree):
    draft = conn.execute("""SELECT d.* FROM publication_drafts d JOIN manual_actions a
        ON a.event_key=d.approved_event AND a.draft_id=d.id AND a.display_id=d.display_id AND a.verb='publish'
        WHERE d.id=? AND d.story_id=? AND d.version=? AND d.state='approved'""",
                         (work["preview_id"], work["story_id"], work["version"])).fetchone()
    if not draft:
        raise ValueError("no exact authenticated draft approval")
    directory = host.area(root, "manual", draft["id"])
    source = directory / "evidence.source.txt"
    data = manual_drafts.source_data(source)
    if hashlib.sha256(data).hexdigest() != draft["source_hash"]:
        raise ValueError("approved source changed")
    snapshot = json.loads(draft["snapshot"])
    original = directory / "checkout"
    if artifacts(original, work["story_id"])[0] != snapshot:
        raise ValueError("draft changed after preview")
    for path, digest in snapshot["files"].items():
        contents = read_artifact(original, path)
        if hashlib.sha256(contents).hexdigest() != digest:
            raise ValueError("approved artifact changed during copy")
        dest = tree / path
        if dest.resolve() != dest or dest.exists():
            raise ValueError("approved file collides with new base")
        dest.parent.mkdir(exist_ok=True, parents=True)
        dest.write_bytes(contents)
    return data.decode()


class ReservationLost(ValueError):
    pass


def optional_media(tree, story, evidence, command, log, heartbeat, limit):
    manifest, _ = artifacts(tree, story)
    ensure_private(tree, manifest, evidence)
    before = {path: read_artifact(tree, path) for path in manifest["files"]}
    try:
        if host.child(tree, command, log, heartbeat=heartbeat, limit=limit):
            raise ValueError("media helper failed")
        current, _ = artifacts(tree, story)
        ensure_private(tree, current, evidence)
        return True
    except ReservationLost:
        raise
    except ERRORS:
        # Revert partial optional writes in this dedicated worktree only.
        for path in changes(tree) - before.keys():
            file = tree / path
            if (not path.startswith("output/") or file.parent.resolve() != file.parent or
                    git(tree, "ls-tree", "-z", "HEAD", "--", path)):
                raise ValueError("unexpected tracked or unrelated change during media preparation")
            file.unlink(missing_ok=True)
        for path, data in before.items():
            dest = tree / path
            if dest.resolve() != dest:
                raise ValueError("unsafe artifact path after media failure")
            dest.write_bytes(data)
        if artifacts(tree, story)[0] != manifest:
            raise ValueError("unable to restore article after optional media failure")
        return False


def prepare(conn, root, work):
    token = work["token"]

    def heartbeat():
        result = dispatch.refresh(conn, token=token)
        if result["state"] != "preparing":
            raise ReservationLost("publication reservation superseded")
        return result

    directory = host.area(root, "worker", work["id"])
    tree = host.checkout(directory)
    if work["kind"] == "manual":
        evidence = copy_approved(conn, root, work, tree)
    else:
        evidence = frozen(conn, work)
        src = directory / "evidence.source.txt"
        src.write_text(evidence)
        host.generate(tree, work["story_id"], src, directory / "generation.log", heartbeat)
    manifest, posts = artifacts(tree, work["story_id"])
    ensure_private(tree, manifest, evidence)
    failures = []
    if work["kind"] != "manual" and os.environ.get("BB_ILLUSTRATE", "1") == "1":
        command = [str(host.helpers() / "bb_images.py"), "auto", work["story_id"], *posts.values()]
        if not optional_media(tree, work["story_id"], evidence, command, directory / "illustration.log", heartbeat, 600):
            failures.append("illustration")
    for level, path in posts.items():
        heartbeat()
        if os.environ.get("BB_AUDIO", "1") == "1":
            command = ["-m", "scripts.post_audio", path, "--environment", "production", "--upload",
                       "--public-base-url", "https://media.briefberlin.de", "--s3-bucket",
                       "briefberlin-audio-prod", "--s3-region", "eu-central-1", "--s3-prefix", "articles"]
            if not optional_media(tree, work["story_id"], evidence, command, directory / "audio.log", heartbeat, 1800):
                failures.append(level + " audio")
    return tree, evidence, failures


def commit_story(tree, story_id, evidence):
    # At this point every artifact is a validated addition. Checkout preserves untracked
    # files or fails on a collision; Git must never overwrite an editor's approved draft.
    latest = host.fetch()
    git(tree, "checkout", "--no-overwrite-ignore", "--detach", latest)
    check_story_in_base(tree, story_id)
    manifest, posts = artifacts(tree, story_id)
    when = datetime.now(PUBLICATION_ZONE)
    restamp(tree, manifest, posts, when)
    manifest, _ = artifacts(tree, story_id)
    ensure_private(tree, manifest, evidence)
    git(tree, "add", "--", *sorted(manifest["files"]))
    git(tree, "commit", "-m", "Generate articles - " + when.strftime("%Y-%m-%d %H:%M %Z"))
    sha = git(tree, "rev-parse", "HEAD").decode().strip()
    verify_commit(tree, sha, manifest, delta=True)
    return sha, manifest


def send_work(conn, root, work_id):
    with host.locked(root, "sender") as lock_fd:
        host.check_legacy(conn)
        claim = dispatch.claim(conn, work_id=work_id, owner="host-publisher")
        if claim["state"] != "preparing":
            return claim
        try:
            host.prune(root, "worker")
            tree, evidence, failures = prepare(conn, root, claim)
            fresh = dispatch.refresh(conn, token=claim["token"])
            if fresh["state"] != "preparing":
                return fresh
            if fresh.get("blocked"):
                host.refresh_archive(conn, root)
            sha, manifest = commit_story(tree, claim["story_id"], evidence)
            for _ in range(3):
                tip = host.fetch()
                if git(tree, "rev-parse", "HEAD^").decode().strip() == tip:
                    break
                # This checkout contains only this worker's verified additions. Reapply
                # them to the latest main, rerunning canonical, file and clock checks.
                git(tree, "reset", "--mixed", "HEAD^")
                sha, manifest = commit_story(tree, claim["story_id"], evidence)
            else:
                raise ValueError("origin/main changed repeatedly during preparation")
            result = dispatch.authorize_push(conn, token=claim["token"], commit=sha, manifest=manifest)
            if not result["push_once"]:
                if result.get("blocked"):
                    dispatch.fail_preparation(conn, token=claim["token"], reason="archive blocked final authorization")
                return result
        except ERRORS as exc:
            dispatch.fail_preparation(conn, token=claim["token"], reason=str(exc)[:900] or type(exc).__name__)
            raise
        try:
            # Pass the flock descriptor through the sender process so a parent crash cannot
            # release the fence while a surviving Git push is still running.
            git(tree, "push", "--porcelain", "origin", f"{sha}:refs/heads/main", pass_fds=(lock_fd,))
            note = "push returned success; awaiting deployment"
        except ERRORS:
            note = "push response unavailable; read-only verification required"
        result = dispatch.reconcile(conn, work_id=work_id, commit=sha, outcome="unknown", evidence=note)
        if failures:
            result["media_unavailable"] = failures
            if claim["kind"] == "manual":
                host.telegram("Optional media unavailable: " + ", ".join(failures) + ". Verifying article deployment.")
        return result


def advance(conn, root, *, manual_only=False):
    finish_drafts(conn)
    draft = manual_drafts.pending(conn)
    if draft and draft["state"] == "approved":
        decision = dispatch.reserve_manual(conn, preview_id=draft["id"], version=draft["version"])
        if decision["state"] == "requested":
            return send_work(conn, root, decision["work_id"])
        if manual_only:
            return decision
    if manual_only:
        raise ValueError("explicit approval of the delivered draft is required")
    decision = dispatch.tick(conn)
    if decision["state"] == "requested":
        return send_work(conn, root, decision["work_id"])
    return decision

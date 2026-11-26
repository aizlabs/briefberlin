"""Single-writer selection and publication fencing for the host dispatcher."""

import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from .archive import article_path, record_publication_tx, set_setting, setting
from .db import ROOT, transaction

ACTIVE = "('requested','preparing','push-authorized','external-uncertain')"
EXTERNAL = {"push-authorized", "external-uncertain"}


@dataclass(frozen=True)
class Policy:
    tick_seconds: int = 300
    slot_seconds: int = 43200
    review_interval_seconds: int = 43200
    archive_max_age_seconds: int = 600
    lease_seconds: int = 900
    hold_seconds: int = 43200
    retry_seconds: int = 600
    max_retry_seconds: int = 21600
    editor_allowlist: tuple[str, ...] = ()

    def __post_init__(self):
        for name, value in vars(self).items():
            if name == "editor_allowlist":
                if not isinstance(value, (tuple, list)) or any(
                    not isinstance(actor, str) or not actor.strip() for actor in value
                ):
                    raise ValueError("editor_allowlist must contain exact transport identifiers")
            elif type(value) is not int or not 1 <= value <= 7 * 86400:
                raise ValueError(f"{name} must be a positive bounded number of seconds")
        if self.max_retry_seconds < self.retry_seconds:
            raise ValueError("max_retry_seconds must cover retry_seconds")

    @classmethod
    def load(cls):
        repo_path = ROOT / "config/editorial_policy.yaml"
        path = os.environ.get("BRIEFBERLIN_EDITORIAL_POLICY") or (
            repo_path if repo_path.exists() else Path(__file__).with_name("editorial_policy.yaml"))
        data = yaml.safe_load(Path(path).read_text())
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("incomplete or unknown editorial policy fields")
        return cls(**data)


def clock(now):
    return int(time.time()) if now is None else now


def archive_block(conn, now, p, *, automatic=True):
    checked = int(setting(conn, "archive_checked_at") or 0)
    epoch = int(setting(conn, "fallback_epoch") or 0)
    if (setting(conn, "archive_ready") != "1" or not 0 < epoch <= now
            or not conn.execute("SELECT 1 FROM live_publications LIMIT 1").fetchone()):
        return "archive-not-ready"
    if not 0 <= now - checked <= p.archive_max_age_seconds:
        return "archive-stale"
    if automatic and setting(conn, "dispatch_requires_archive") == "1":
        return "reconcile-after-control-change"
    return None


def active(conn):
    return conn.execute(f"SELECT * FROM dispatch_work WHERE state IN {ACTIVE}").fetchone()


def transition(conn, work_id, state, reason, now):
    conn.execute("UPDATE dispatch_work SET state=?,reason=? WHERE id=?", (state, reason, work_id))
    conn.execute("INSERT INTO dispatch_transitions(work_id,state,reason,recorded_at) VALUES(?,?,?,?)",
                 (work_id, state, reason, now))


def defer(conn, story_id, now, p):
    row = conn.execute("SELECT failures FROM dispatch_deferrals WHERE story_id=?", (story_id,)).fetchone()
    failures = (row[0] if row else 0) + 1
    delay = min(p.max_retry_seconds, p.retry_seconds * 2 ** min(failures - 1, 16))
    conn.execute("""INSERT INTO dispatch_deferrals(story_id,failures,retry_at) VALUES(?,?,?)
        ON CONFLICT(story_id) DO UPDATE SET failures=excluded.failures,retry_at=excluded.retry_at""",
                 (story_id, failures, now + delay))


RANKED_QUEUE = """WITH scored AS (
    SELECT q.*, coalesce(o.rating,q.score) AS dispatch_score,coalesce(o.hold_until,0) AS observed_hold
    FROM editorial_queue q LEFT JOIN observation_decisions o
    ON :mode='observe' AND o.story_id=q.id AND o.version=q.evidence_version
), ranked AS (
    SELECT q.*, CASE WHEN q.dispatch_score IS NULL OR q.dispatch_score<4 THEN 3
        WHEN q.dispatch_score<7 OR q.model_score BETWEEN 4 AND 6 OR EXISTS(
            SELECT 1 FROM review_requests r WHERE r.story_id=q.id AND r.mode IN ('live',:mode)
            AND (r.version=q.evidence_version OR (q.editor_score IS NOT NULL AND q.model_score<7))
        ) THEN 2 WHEN q.dispatch_score<9 THEN 1 ELSE 0 END AS dispatch_tier
    FROM scored q)"""


def candidates(conn, now, mode, *, include_retries=False):
    """Read current, attributed evidence. A rating cannot promote a review past its gate."""
    return conn.execute(RANKED_QUEUE + """, eligible AS (
        SELECT q.*,
        (SELECT max(CASE WHEN n.revision_id IS NOT NULL THEN i.observed_at
                         ELSE coalesce(i.published_at,i.observed_at) END)
         FROM story_evidence e JOIN editorial_inputs i USING(revision_id)
         LEFT JOIN notice_changes n USING(revision_id)
         WHERE e.story_id=q.id AND e.evidence_version=q.evidence_version AND i.eligible=1) AS freshness
        FROM ranked q LEFT JOIN dispatch_deferrals d ON d.story_id=q.id
        WHERE q.status IN ('pending','review') AND q.sufficient=1 AND q.needs_review=0
        AND q.dispatch_tier<3 AND q.expires_at>:now AND (q.deadline IS NULL OR q.deadline>:now)
        AND (:include_retries OR coalesce(d.retry_at,0)<=:now) AND coalesce(d.hold_until,0)<=:now
        AND q.observed_hold<=:now
        AND NOT EXISTS(SELECT 1 FROM manual_previews m WHERE m.story_id=q.id AND m.version=q.evidence_version)
        AND NOT EXISTS(SELECT 1 FROM manual_match_candidates m JOIN publication_drafts d ON d.id=m.draft_id
            WHERE d.state='matching' AND m.priority>0 AND d.created_at+300>:now
            AND m.story_id=q.id AND m.version=q.evidence_version)
        AND NOT EXISTS(SELECT 1 FROM live_publications l WHERE l.story_id=q.id)
        AND NOT EXISTS(SELECT 1 FROM evidence_holds h WHERE h.story_id=q.id))
        SELECT * FROM eligible WHERE freshness IS NOT NULL ORDER BY dispatch_tier,dispatch_score DESC,
        CASE WHEN dispatch_tier!=0 THEN coalesce(deadline,253402300799) END,freshness DESC,id""",
                        {"mode": mode, "now": now, "include_retries": include_retries}).fetchall()


def review_row(conn, mode):
    return conn.execute("""SELECT * FROM review_requests WHERE mode=? AND state IN ('pending','approved')""",
                        (mode,)).fetchone()


def close_review(conn, request_id, state):
    conn.execute("UPDATE review_requests SET state=? WHERE id=?", (state, request_id))


def reserve(conn, story, kind, slot, review_id, now, preview=None):
    work_id = uuid.uuid4().hex
    conn.execute("""INSERT INTO dispatch_work(id,story_id,version,kind,slot,request_id,state,created_at,
        manual_preview_id) VALUES(?,?,?,?,?,?,'requested',?,?)""",
                 (work_id, story["id"], story["evidence_version"], kind, slot, review_id, now, preview))
    transition(conn, work_id, "requested", kind, now)
    return reservation(active(conn))


def make_review(conn, story, slot, mode, now):
    revision = conn.execute("""SELECT e.url,i.published_at,i.observed_at,e.fact,e.attribution,
        e.revision_id,m.response FROM story_evidence e JOIN editorial_inputs i USING(revision_id)
        LEFT JOIN model_decisions m ON m.story_id=e.story_id AND m.revision_id=e.revision_id
          AND m.evidence_version=e.evidence_version WHERE e.story_id=? AND e.evidence_version=?
        ORDER BY m.id DESC,e.revision_id DESC LIMIT 1""", (story["id"], story["evidence_version"])).fetchone()
    event = json.loads(revision["response"]) if revision["response"] else {}
    request_id = uuid.uuid4().hex
    card = dict(request_id=request_id, story_id=story["id"], evidence_version=story["evidence_version"],
                headline=story["title"], score=story["dispatch_score"], rationale=event.get("rationale", revision["fact"]),
                berlin_impact=event.get("berlin_consequence", story["summary"]), date=story["event_date"],
                source_date=revision["published_at"], observed_at=revision["observed_at"],
                source_url=revision["url"], attribution=revision["attribution"], revision_id=revision["revision_id"],
                expires_at=story["expires_at"], slot=slot, mode=mode)
    conn.execute("""INSERT INTO review_requests(id,story_id,version,slot,mode,state,card,created_at)
        VALUES(?,?,?,?,?,'pending',?,?)""", (request_id, story["id"], story["evidence_version"], slot, mode,
                                            json.dumps(card), now))
    return {"state": "review", "card": card}


def current_work(conn, now, p):
    work = active(conn)
    if work and work["state"] == "preparing" and work["expires_at"] <= now:
        transition(conn, work["id"], "abandoned", "worker lease expired before push", now)
        defer(conn, work["story_id"], now, p)
        return None
    return work


def reservation(work):
    result = {"state": work["state"], "work_id": work["id"], "story_id": work["story_id"], "kind": work["kind"]}
    if work["kind"] == "manual":
        result.update(preview_id=work["manual_preview_id"], version=work["version"])
    return result


def manual_story(conn, preview_id, version, now):
    return conn.execute("""SELECT s.* FROM manual_previews m JOIN stories s ON s.id=m.story_id
        WHERE m.preview_id=? AND m.version=? AND s.evidence_version=m.version
        AND s.status NOT IN ('live','covered','deploying','expired') AND s.needs_review=0
        AND (s.expires_at IS NULL OR s.expires_at>?) AND (s.deadline IS NULL OR s.deadline>?)
        AND NOT EXISTS(SELECT 1 FROM live_publications WHERE story_id=s.id)
        AND NOT EXISTS(SELECT 1 FROM evidence_holds WHERE story_id=s.id)""", (preview_id, version, now, now)).fetchone()


def choose(conn, now, p):
    """Decide under BEGIN IMMEDIATE. Also revalidate a previously requested/preparing worker."""
    mode = setting(conn, "dispatch_mode")
    work = current_work(conn, now, p)
    if work and work["state"] in EXTERNAL:
        return {"state": "reconcile", "work_id": work["id"]}
    manual = work is not None and work["kind"] == "manual"
    if manual and not manual_story(conn, work["manual_preview_id"], work["version"], now):
        transition(conn, work["id"], "superseded", "manual preview is stale", now)
        work = None
        manual = False
    blocked = archive_block(conn, now, p, automatic=not manual)
    if blocked:
        return {"state": "blocked", "reason": blocked}
    if manual:
        return reservation(work)
    if setting(conn, "publish_paused") == "1":
        return {"state": "blocked", "reason": "paused"}

    slot = int(setting(conn, "fallback_epoch"))
    opened = now >= slot + p.slot_seconds
    queue = candidates(conn, now, mode)
    by_id = {row["id"]: row for row in queue}
    auto = next((s for s in queue if s["dispatch_tier"] == 0 or (opened and s["dispatch_tier"] == 1)), None)
    if work and work["state"] == "preparing" and work["kind"] == "immediate":
        current = by_id.get(work["story_id"])
        if current and current["dispatch_tier"] == 0 and current["evidence_version"] == work["version"]:
            auto = current
    review = review_row(conn, mode)
    if review:
        candidate = by_id.get(review["story_id"])
        if candidate is None and review["state"] == "approved":
            candidate = next((s for s in candidates(conn, now, mode, include_retries=True)
                              if s["id"] == review["story_id"]), None)
            # Let another reviewable story use the slot after repeated preparation failures.
            since = review["response_at"] or review["created_at"]
            if now >= since + p.review_interval_seconds and any(s["dispatch_tier"] == 2 for s in queue):
                candidate = None
        if (not opened or slot != review["slot"] or candidate is None
                or candidate["evidence_version"] != review["version"] or auto is not None):
            close_review(conn, review["id"], "superseded")
            review = None
    selected = auto
    kind = None
    if auto:
        kind = "immediate" if auto["dispatch_tier"] == 0 else "fallback"
    elif review and review["state"] == "approved" and review["story_id"] in by_id:
        selected = by_id[review["story_id"]]
        kind = "approved"

    if work:
        valid = (selected is not None and selected["id"] == work["story_id"]
                 and selected["evidence_version"] == work["version"] and work["kind"] == kind
                 and (kind == "immediate" or slot == work["slot"]))
        if valid:
            return reservation(work)
        transition(conn, work["id"], "superseded", "eligibility, priority or slot changed", now)

    if selected is not None:
        if mode == "observe":
            return {"state": "would-publish", "kind": kind, "story_id": selected["id"]}
        return reserve(conn, selected, kind, slot if kind != "immediate" else None,
                       review["id"] if review else None, now)
    if review:
        if review["state"] == "approved":
            return {"state": "deferred", "story_id": review["story_id"], "request_id": review["id"]}
        return {"state": "awaiting-editor", "card": json.loads(review["card"])}
    if opened:
        recent = conn.execute("""SELECT max(coalesce(response_at,created_at)) FROM review_requests
            WHERE mode=? AND slot=?""", (mode, slot)).fetchone()[0]
        declined = {tuple(row) for row in conn.execute("""SELECT story_id,version FROM review_requests
            WHERE mode=? AND state='declined'""", (mode,))}
        suggestion = next((s for s in queue if s["dispatch_tier"] == 2
                           and (s["id"], s["evidence_version"]) not in declined), None)
        if suggestion is not None and (recent is None or now >= recent + p.review_interval_seconds):
            return make_review(conn, suggestion, slot, mode, now)
    return {"state": "idle", "next_fallback_at": slot + p.slot_seconds}


def tick(conn, *, policy=None, now=None):
    p = policy or Policy.load()
    with transaction(conn):
        return choose(conn, clock(now), p)


def configure(conn, *, mode=None, paused=None, now=None):
    if mode is not None and mode not in {"observe", "live"}:
        raise ValueError("unknown dispatch mode")
    with transaction(conn):
        now = clock(now)
        if ((mode is not None and mode != setting(conn, "dispatch_mode"))
                or (paused is not None and paused != (setting(conn, "publish_paused") == "1"))):
            work = active(conn)
            if work and work["kind"] != "manual" and work["state"] not in EXTERNAL:
                transition(conn, work["id"], "superseded", "dispatch controls changed", now)
            conn.execute("UPDATE review_requests SET state='superseded' WHERE state IN ('approved','pending')")
            if mode is not None:
                set_setting(conn, "dispatch_mode", mode)
            if paused is not None:
                set_setting(conn, "publish_paused", int(paused))
            set_setting(conn, "dispatch_requires_archive", 1)
            set_setting(conn, "dispatch_control_generation", uuid.uuid4().hex)
        return {"mode": setting(conn, "dispatch_mode"), "paused": setting(conn, "publish_paused") == "1"}


def work_result(work):
    result = {key: work[key] for key in ("id", "state", "story_id", "version", "kind", "expires_at")}
    if work["kind"] == "manual":
        result["preview_id"] = work["manual_preview_id"]
    return result


def claim(conn, *, work_id, owner, policy=None, now=None):
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 256:
        raise ValueError("bounded worker identity required")
    p = policy or Policy.load()
    with transaction(conn):
        now = clock(now)
        result = choose(conn, now, p)
        if result.get("work_id") != work_id or result["state"] != "requested":
            return {"state": "unavailable", "dispatch": result}
        token = uuid.uuid4().hex
        conn.execute("UPDATE dispatch_work SET worker=?,token=?,expires_at=? WHERE id=?",
                     (owner, token, now + p.lease_seconds, work_id))
        transition(conn, work_id, "preparing", "claimed by " + owner, now)
        work = active(conn)
        return {**work_result(work), "token": token}


def owned(conn, token):
    row = conn.execute("SELECT * FROM dispatch_work WHERE token=?", (token,)).fetchone()
    if not row:
        raise ValueError("unknown publication lease")
    return row


def prepare(conn, token, now, p):
    row = owned(conn, token)
    blocked = None
    if row["state"] == "preparing":
        result = choose(conn, now, p)
        if result["state"] == "blocked":
            blocked = result["reason"]
        row = owned(conn, token)
    return row, blocked


def refresh(conn, *, token, policy=None, now=None):
    p = policy or Policy.load()
    with transaction(conn):
        now = clock(now)
        row, blocked = prepare(conn, token, now, p)
        if row["state"] == "preparing":
            conn.execute("UPDATE dispatch_work SET expires_at=? WHERE id=?", (now + p.lease_seconds, row["id"]))
        result = work_result(owned(conn, token))
        if blocked:
            result["blocked"] = blocked
        return result


def fail_preparation(conn, *, token, reason, policy=None, now=None):
    p = policy or Policy.load()
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ValueError("brief failure reason required")
    with transaction(conn):
        row = owned(conn, token)
        if row["state"] == "preparing":
            now = clock(now)
            transition(conn, row["id"], "failed", reason, now)
            defer(conn, row["story_id"], now, p)
        return work_result(owned(conn, token))


def validate_manifest(commit, manifest, story_id):
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("full lowercase Git commit SHA required")
    if not isinstance(manifest, dict) or set(manifest) != {"story_id", "files", "editions"}:
        raise ValueError("expected story_id, files and editions")
    files, editions = manifest["files"], manifest["editions"]
    if manifest["story_id"] != story_id or not isinstance(files, dict) or not 2 <= len(files) <= 4096:
        raise ValueError("story-scoped file digest mapping required")
    for path, digest in files.items():
        if (not isinstance(path, str) or not path.startswith("output/") or len(path) > 1024
                or PurePosixPath(path).as_posix() != path or ".." in PurePosixPath(path).parts
                or any(ord(c) < 32 or c == "\\" for c in path)
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError("invalid repository artifact path or SHA256")
    if not isinstance(editions, dict) or set(editions) != {"A2", "B1"}:
        raise ValueError("expected both German edition paths")
    for path in editions.values():
        if not isinstance(path, str) or article_path(path) != path or len(path.strip("/").split("/")) != 2:
            raise ValueError("invalid canonical German edition path")
    if editions["A2"] == editions["B1"]:
        raise ValueError("distinct A2 and B1 paths required")
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def authorize_push(conn, *, token, commit, manifest, policy=None, now=None):
    p = policy or Policy.load()
    with transaction(conn):
        now = clock(now)
        row, blocked = prepare(conn, token, now, p)
        if blocked:
            return {**work_result(row), "push_once": False, "blocked": blocked}
        if row["state"] != "preparing":
            return {**work_result(row), "push_once": False}
        frozen = validate_manifest(commit, manifest, row["story_id"])
        prior = conn.execute("SELECT status FROM stories WHERE id=?", (row["story_id"],)).fetchone()[0]
        conn.execute("UPDATE dispatch_work SET commit_sha=?,manifest=?,prior_status=? WHERE id=?",
                     (commit, frozen, prior, row["id"]))
        conn.execute("UPDATE stories SET status='deploying' WHERE id=?", (row["story_id"],))
        transition(conn, row["id"], "push-authorized", "manifest frozen before external call", now)
        return {**work_result(owned(conn, token)), "push_once": True}


def reconcile(conn, *, work_id, commit, outcome, evidence, policy=None, now=None):
    """Trusted stage 5 verifier supplies the outcome after examining the remote and live pages."""
    if outcome not in {"unknown", "live", "absent"} or not isinstance(evidence, str) or not 1 <= len(evidence.strip()) <= 2000:
        raise ValueError("verified outcome and bounded reconciliation evidence required")
    p = policy or Policy.load()
    with transaction(conn):
        now = clock(now)
        row = conn.execute("SELECT * FROM dispatch_work WHERE id=?", (work_id,)).fetchone()
        if not row or not commit or row["commit_sha"] != commit:
            raise ValueError("expected commit does not match work")
        if row["state"] in {"live", "absent"}:
            if outcome != row["state"]:
                raise ValueError("conflicting final outcome")
            return work_result(row)
        if row["state"] not in EXTERNAL:
            raise ValueError("work did not reach external authorization")
        if outcome == "live":
            record_publication_tx(conn, story_id=row["story_id"], publication_key=commit, verified_at=now,
                                  origin="manual" if row["kind"] == "manual" else "automatic")
            conn.execute("DELETE FROM manual_previews WHERE story_id=?", (row["story_id"],))
            if row["request_id"]:
                close_review(conn, row["request_id"], "published")
        elif outcome == "absent":
            conn.execute("UPDATE stories SET status=? WHERE id=? AND status='deploying'",
                         (row["prior_status"], row["story_id"]))
            correction = conn.execute("""SELECT e.revision_id FROM story_evidence e
                JOIN stories s ON s.id=e.story_id WHERE s.id=? AND s.needs_review=1 AND e.evidence_version IS NULL
                AND e.recorded_at >= (SELECT min(recorded_at) FROM dispatch_transitions
                    WHERE work_id=? AND state='push-authorized')
                AND EXISTS(SELECT 1 FROM model_decisions m WHERE m.story_id=s.id
                    AND m.revision_id=e.revision_id AND json_extract(m.response,'$.material')=1)
                ORDER BY e.recorded_at DESC,e.revision_id DESC LIMIT 1""", (row["story_id"], work_id)).fetchone()
            if correction:
                conn.execute("UPDATE stories SET status='held' WHERE id=?", (row["story_id"],))
                conn.execute("""INSERT OR REPLACE INTO evidence_holds VALUES(?,?,
                    'Reassess material evidence received during external publication')""",
                             (row["story_id"], correction[0]))
            defer(conn, row["story_id"], now, p)
        transition(conn, work_id, "external-uncertain" if outcome == "unknown" else outcome, evidence, now)
        return work_result(conn.execute("SELECT * FROM dispatch_work WHERE id=?", (work_id,)).fetchone())


def attach_manual_preview(conn, *, story_id, version, preview_id, now=None):
    """Trusted manual workflow attaches a single identified draft, prior to editor approval."""
    if not isinstance(preview_id, str) or not 1 <= len(preview_id.strip()) <= 256:
        raise ValueError("immutable preview identity required")
    with transaction(conn):
        return attach_manual_tx(conn, story_id, version, preview_id, clock(now))


def attach_manual_tx(conn, story_id, version, preview_id, now):
    """Attach within the same short transaction as the publisher's matching decision."""
    row = conn.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()
    if not row or row["evidence_version"] != version or row["status"] in {"live", "covered", "deploying"}:
        raise ValueError("story is stale, live or already deploying")
    previous = conn.execute("SELECT * FROM manual_previews WHERE story_id=?", (story_id,)).fetchone()
    if previous and previous["version"] == version and previous["preview_id"] != preview_id:
        raise ValueError("release the superseded preview first")
    if not previous or (previous["preview_id"], previous["version"]) != (preview_id, version):
        if conn.execute("SELECT 1 FROM manual_preview_history WHERE preview_id=?", (preview_id,)).fetchone():
            raise ValueError("preview identity already used")
        conn.execute("INSERT INTO manual_preview_history VALUES(?,?,?)", (preview_id, story_id, version))
        conn.execute("""INSERT INTO manual_previews VALUES(?,?,?) ON CONFLICT(story_id)
            DO UPDATE SET version=excluded.version,preview_id=excluded.preview_id""", (story_id, version, preview_id))
    work = active(conn)
    if work and work["story_id"] == story_id and work["manual_preview_id"] != preview_id:
        if work["state"] in EXTERNAL:
            raise ValueError("reconcile outstanding push first")
        transition(conn, work["id"], "superseded", "manual preview attached", clock(now))
    conn.execute("""UPDATE review_requests SET state='superseded' WHERE story_id=?
        AND state IN ('pending','approved')""", (story_id,))
    return {"state": "preview", "preview_id": preview_id, "story_id": story_id, "version": version}


def release_manual_preview(conn, *, preview_id, now=None):
    with transaction(conn):
        work = active(conn)
        if work and work["manual_preview_id"] == preview_id:
            if work["state"] in EXTERNAL:
                raise ValueError("reconcile outstanding manual push first")
            transition(conn, work["id"], "superseded", "manual preview withdrawn", clock(now))
        conn.execute("DELETE FROM manual_previews WHERE preview_id=?", (preview_id,))
        return {"state": "released", "preview_id": preview_id}


def reserve_manual(conn, *, preview_id, version, policy=None, now=None):
    """Stage 5 calls only after authenticated explicit approval of the exact manual preview."""
    p = policy or Policy.load()
    with transaction(conn):
        now = clock(now)
        work = current_work(conn, now, p)
        same = work is not None and work["manual_preview_id"] == preview_id and work["version"] == version
        if same and work["state"] in EXTERNAL:
            return {"state": "reconcile", "work_id": work["id"]}
        row = manual_story(conn, preview_id, version, now)
        if not row:
            if same:
                transition(conn, work["id"], "superseded", "manual preview is stale", now)
            return {"state": "stale"}
        blocked = archive_block(conn, now, p, automatic=False)
        if blocked:
            return {"state": "blocked", "reason": blocked}
        if same:
            return reservation(work)
        deferred = conn.execute("SELECT retry_at FROM dispatch_deferrals WHERE story_id=? AND retry_at>?",
                                (row["id"], now)).fetchone()
        if deferred:
            return {"state": "deferred", "retry_at": deferred[0]}
        if work:
            return {"state": "busy"}
        return reserve(conn, row, "manual", None, None, now, preview_id)


def status(conn, *, policy=None, now=None):
    p = policy or Policy.load()
    with transaction(conn):
        now = clock(now)
        mode = setting(conn, "dispatch_mode")
        work = active(conn)
        blocked = archive_block(conn, now, p)
        request = review_row(conn, mode)
        slot = int(setting(conn, "fallback_epoch") or 0)
        latest = conn.execute("""SELECT story_id,verified_at,origin FROM live_publications
            ORDER BY verified_at DESC,story_id LIMIT 1""").fetchone()
        return {"mode": mode, "publish_paused": setting(conn, "publish_paused") == "1",
                "archive_block": blocked, "archive_checked_at": setting(conn, "archive_checked_at"),
                "latest_publication": dict(latest) if latest else None, "fallback_epoch": slot or None,
                "next_fallback_at": slot + p.slot_seconds if slot else None,
                "queue": [dict(r) for r in conn.execute(RANKED_QUEUE + """
                    SELECT dispatch_tier AS tier,count(*) AS pending,min(first_seen) AS oldest
                    FROM ranked WHERE status IN ('pending','review') GROUP BY dispatch_tier ORDER BY dispatch_tier""",
                                                        {"mode": mode})],
                "work": work_result(work) if work else None,
                "expected_commit": work["commit_sha"] if work else None,
                "manifest": json.loads(work["manifest"]) if work and work["manifest"] else None,
                "review": {"state": request["state"], "card": json.loads(request["card"]),
                           "deliveries": request["delivery_count"]} if request else None,
                "deferred": [dict(row) for row in conn.execute("""SELECT * FROM dispatch_deferrals
                    WHERE retry_at>? OR hold_until>? ORDER BY story_id""", (now, now))]}

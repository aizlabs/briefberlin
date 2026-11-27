"""Offline host acceptance for dispatch and the stage 5 fencing contract."""

import hmac
import io
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest

from scripts.editorial import dispatch as d
from scripts.editorial import review, review_adapter
from scripts.editorial.__main__ import main
from scripts.editorial.archive import record_publication, set_setting, setting
from scripts.editorial.db import connect

NOW = 1_800_000_000
SLOT = 43200
META = {"transport": "telegram", "account": "desk", "conversation": "-123", "sender": "456"}
P = d.Policy(editor_allowlist=("telegram/desk/-123/456",))
COMMIT = "c" * 40
TEST_KEY = b"test" * 8


def archive(conn, now, *, epoch=None):
    set_setting(conn, "archive_ready", 1)
    set_setting(conn, "archive_checked_at", now)
    set_setting(conn, "dispatch_requires_archive", 0)
    if epoch is not None:
        set_setting(conn, "fallback_epoch", epoch)


def seed(conn, now=NOW, mode="live"):
    conn.execute("INSERT INTO stories(id,title,first_seen,updated_at) VALUES('ledger','Past',?,?)", (now, now))
    record_publication(conn, story_id="ledger", publication_key="old", verified_at=now-SLOT, origin="manual")
    d.configure(conn, mode=mode, now=now)
    archive(conn, now)


def story(conn, name, score, *, now=NOW, deadline=None, expiry=None):
    url = "https://example.org/" + name
    report = conn.execute("INSERT INTO reports(url,first_seen,last_seen) VALUES(?,?,?)",
                          (url, now, now)).lastrowid
    rev = conn.execute("""INSERT INTO report_revisions(report_id,content_hash,title,evidence,publisher,
        published_at,observed_at,eligible) VALUES(?,?,'Title','Evidence','Office',?,?,1)""",
                       (report, name, now, now)).lastrowid
    conn.execute("""INSERT INTO stories(id,title,summary,first_seen,updated_at,model_score,deadline,
        expires_at,sufficient) VALUES(?,?,'Berlin change',?,?,?,?,?,1)""",
                 (name, name, now, now, score, deadline, expiry or now+2*86400))
    conn.execute("""INSERT INTO story_evidence(story_id,revision_id,evidence_version,relationship,fact,
        quote,attribution,url,recorded_at) VALUES(?,?,1,'new','Changed','Quote','Office',?,?)""",
                 (name, rev, url, now))
    conn.execute("""INSERT INTO model_decisions(story_id,revision_id,evidence_version,token,rubric,model,
        score,outcome,response,recorded_at) VALUES(?,?,1,'token','v1','model',?,'new',?,?)""",
                 (name, rev, score, json.dumps({"rationale": "Why", "berlin_consequence": "Rent changes"}), now))


@pytest.fixture
def conn(tmp_path):
    with closing(connect(tmp_path / "dispatch.db")) as db:
        seed(db)
        yield db


@pytest.fixture(autouse=True)
def private_review_key(tmp_path, monkeypatch):
    path = tmp_path / "review.key"
    path.write_bytes(TEST_KEY)
    path.chmod(0o600)
    monkeypatch.setenv("BRIEFBERLIN_REVIEW_KEY_FILE", str(path))
    return path


def tick(conn, now=NOW):
    return d.tick(conn, policy=P, now=now)


def claim(conn, now=NOW):
    item = tick(conn, now)
    return d.claim(conn, work_id=item["work_id"], owner="worker", now=now, policy=P)


def manifest(name):
    return {"story_id": name, "files": {"output/_posts/a.md": "0"*64, "output/_posts/b.md": "1"*64},
            "editions": {"A2": "/articles/a/", "B1": "/articles/b/"}}


def push(conn, task, now=NOW):
    return d.authorize_push(conn, token=task["token"], commit=COMMIT, manifest=manifest(task["story_id"]),
                            policy=P, now=now)


def envelope(card, verb, event="cb1", **kwargs):
    payload = dict(metadata=META, request_id=card["request_id"], story_id=card["story_id"],
                   version=card["evidence_version"], verb=verb, event_id=event)
    payload.update(kwargs)
    signed = b"briefberlin/review-action/v1\x00" + json.dumps(payload, sort_keys=True,
        ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return {"payload": payload, "signature": hmac.digest(TEST_KEY, signed, "sha256").hex()}


def reply(conn, card, verb, event="cb1", now=NOW, **kwargs):
    return review.signed_action(conn, envelope(card, verb, event, **kwargs), policy=P, now=now)


@pytest.mark.parametrize("month,day", [(3, 28), (10, 24)])
def test_elapsed_boundary_through_berlin_clock_change(tmp_path, month, day):
    zone = ZoneInfo("Europe/Berlin")
    epoch = int(datetime(2026, month, day, 21, tzinfo=zone).timestamp())
    now = epoch + SLOT
    with closing(connect(tmp_path / "dst")) as db:
        seed(db, now=now)
        archive(db, now-1, epoch=epoch)
        story(db, "early", 7, now=now-4000)
        story(db, "recent", 8, now=now-1800)
        assert tick(db, now-1)["state"] == "idle"
        assert tick(db, now)["story_id"] == "recent"
        assert setting(db, "fallback_epoch") == str(epoch)


def test_ties_deadline_evidence_and_expiry(conn):
    story(conn, "no-evidence", 10)
    conn.execute("DELETE FROM story_evidence WHERE story_id='no-evidence'")
    story(conn, "expired", 10, expiry=NOW)
    story(conn, "past-deadline", 10, deadline=NOW)
    story(conn, "under-review", 10)
    conn.execute("UPDATE stories SET needs_review=1 WHERE id='under-review'")
    story(conn, "fresh", 8)
    story(conn, "older", 8, now=NOW-60, deadline=NOW+60)
    story(conn, "earlier-id", 8, now=NOW-60, deadline=NOW+60)
    assert tick(conn)["story_id"] == "earlier-id"
    story(conn, "urgent", 9)
    assert tick(conn)["story_id"] == "urgent"


def test_two_ticks_and_one_lease(tmp_path):
    path = tmp_path / "concurrent"
    with closing(connect(path)) as db:
        seed(db)
        story(db, "one", 7)
    barrier = Barrier(2)

    def run(owner):
        with closing(connect(path)) as db:
            barrier.wait()
            work = tick(db)
            return work["work_id"], d.claim(db, work_id=work["work_id"], owner=owner, policy=P, now=NOW)["state"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, ["a", "b"]))
    assert len({x[0] for x in outcomes}) == 1
    assert sorted(x[1] for x in outcomes) == ["preparing", "unavailable"]


def test_pause_observe_and_archive_requirements(conn):
    story(conn, "trial", 5)
    d.configure(conn, mode="observe", now=NOW)
    assert tick(conn)["reason"] == "reconcile-after-control-change"
    archive(conn, NOW)
    card = tick(conn)["card"]
    assert not review.pending(conn, policy=P, now=NOW)["deliver"]
    assert reply(conn, card, "rate-and-publish", rating=10)["mode"] == "observe"
    assert tick(conn)["state"] == "would-publish"
    assert conn.execute("SELECT editor_score FROM stories WHERE id='trial'").fetchone()[0] is None
    assert d.active(conn) is None
    d.configure(conn, mode="live", now=NOW)
    d.configure(conn, paused=True, now=NOW)
    archive(conn, NOW)
    assert tick(conn)["reason"] == "paused"
    d.configure(conn, paused=False, now=NOW)
    assert tick(conn)["state"] == "blocked"
    archive(conn, NOW)
    assert tick(conn)["card"]["request_id"] != card["request_id"]
    assert tick(conn, NOW + P.archive_max_age_seconds + 1)["reason"] == "archive-stale"
    set_setting(conn, "archive_ready", 0)
    assert tick(conn)["reason"] == "archive-not-ready"
    archive(conn, NOW)
    conn.execute("DELETE FROM publication_keys")
    conn.execute("DELETE FROM live_publications")
    assert tick(conn)["reason"] == "archive-not-ready"


def test_immutable_card_authenticated_action_rating_does_not_approve(conn):
    story(conn, "small", 6)
    card = tick(conn)["card"]
    assert card["rationale"] == "Why" and card["berlin_impact"] == "Rent changes"
    assert tick(conn)["card"] == card
    with pytest.raises(ValueError, match="authorized"):
        reply(conn, card, "approve", metadata={**META, "conversation": "-999"})
    with pytest.raises(ValueError, match="identity"):
        reply(conn, {**card, "evidence_version": 2}, "approve")
    ack = review.delivered(conn, request_id=card["request_id"], receipt="message-1", policy=P, now=NOW)
    assert review.delivered(conn, request_id=card["request_id"], receipt="message-1", policy=P, now=NOW) == ack
    assert review.pending(conn, policy=P, now=NOW)["delivery_count"] == 1
    result = reply(conn, card, "rate", rating=9)
    assert reply(conn, card, "rate", rating=9) == result
    with pytest.raises(ValueError, match="reused"):
        reply(conn, card, "approve")
    assert tick(conn) == {"state": "awaiting-editor", "card": card}
    assert reply(conn, card, "approve", event="explicit")["state"] == "approved"
    assert claim(conn)["kind"] == "approved"
    assert conn.execute("SELECT count(*) FROM editor_feedback").fetchone()[0] == 2


def test_late_decline_and_hold_throttle_next_suggestion(conn):
    story(conn, "first", 6, expiry=NOW+5*SLOT)
    story(conn, "second", 5, expiry=NOW+5*SLOT)
    card = tick(conn)["card"]
    after = NOW + SLOT + 30
    archive(conn, after)
    reply(conn, card, "decline", now=after)
    assert tick(conn, after)["state"] == "idle"
    archive(conn, after+SLOT)
    next_card = tick(conn, after+SLOT)["card"]
    assert next_card["story_id"] == "second"
    reply(conn, next_card, "hold", event="hold", now=after+SLOT)
    assert tick(conn, after+SLOT)["state"] == "idle"
    archive(conn, after+2*SLOT)
    assert tick(conn, after+2*SLOT)["card"]["story_id"] == "second"


def test_material_evidence_and_manual_clock_invalidate_review(conn):
    story(conn, "minor", 5)
    card = tick(conn)["card"]
    conn.execute("UPDATE stories SET evidence_version=2 WHERE id='minor'")
    assert reply(conn, card, "approve")["request_state"] == "superseded"
    story(conn, "next", 6)
    archive(conn, NOW + SLOT)
    next_card = tick(conn, NOW + SLOT)["card"]
    story(conn, "manual", 7)
    record_publication(conn, story_id="manual", publication_key="manual-sha", verified_at=NOW+SLOT, origin="manual")
    assert reply(conn, next_card, "approve", event="manual-stale", now=NOW+SLOT)["state"] == "stale"
    assert tick(conn, NOW + SLOT)["state"] == "idle"


def test_stale_preparation_and_immediate_supersession(conn):
    story(conn, "fallback", 7)
    work = claim(conn)
    story(conn, "urgent", 9)
    assert not push(conn, work)["push_once"]
    urgent = claim(conn)
    assert urgent["story_id"] == "urgent"
    story(conn, "other-urgent", 10)
    assert d.refresh(conn, token=urgent["token"], policy=P, now=NOW+1)["state"] == "preparing"
    conn.execute("UPDATE stories SET evidence_version=2 WHERE id='urgent'")
    assert not push(conn, urgent)["push_once"]
    assert tick(conn)["story_id"] == "other-urgent"


def test_no_lease_recovery_after_external_authorization(conn):
    story(conn, "best", 9)
    story(conn, "second", 7)
    task = claim(conn)
    later = NOW + P.lease_seconds
    archive(conn, later)
    assert tick(conn, later)["story_id"] == "second"
    assert not push(conn, task, later)["push_once"]
    task = claim(conn, later)
    assert push(conn, task, later)["push_once"]
    assert not push(conn, task, later)["push_once"]
    future = later + 12 * P.lease_seconds
    assert tick(conn, future)["state"] == "reconcile"
    assert d.status(conn, policy=P, now=future)["manifest"] == manifest("second")
    rec = dict(work_id=task["id"], commit=COMMIT, policy=P, now=future)
    assert d.reconcile(conn, **rec, outcome="unknown", evidence="remote unavailable")["state"] == "external-uncertain"
    assert tick(conn, future)["state"] == "reconcile"
    assert d.reconcile(conn, **rec, outcome="live", evidence="both canonical pages verified")["state"] == "live"
    rec["now"] += 60
    assert d.reconcile(conn, **rec, outcome="live", evidence="duplicate verifier")["state"] == "live"
    assert int(setting(conn, "fallback_epoch")) == future
    archive(conn, future)
    assert tick(conn, future)["story_id"] == "best"


def test_waiting_manual_preview_releases_worker_and_closes_global_slot(conn):
    story(conn, "fallback", 8)
    story(conn, "manual", 9)
    d.attach_manual_preview(conn, story_id="manual", version=1, preview_id="draft1", now=NOW)
    story(conn, "urgent", 10)
    task = claim(conn)
    assert task["story_id"] == "urgent"
    assert d.reserve_manual(conn, preview_id="draft1", version=1, policy=P, now=NOW)["state"] == "busy"
    d.fail_preparation(conn, token=task["token"], reason="quality rejected", policy=P, now=NOW)
    manual = d.reserve_manual(conn, preview_id="draft1", version=1, policy=P, now=NOW)
    task = d.claim(conn, work_id=manual["work_id"], owner="manual-worker", policy=P, now=NOW)
    assert push(conn, task)["push_once"]
    d.reconcile(conn, work_id=task["id"], commit=COMMIT, outcome="live", evidence="manual pages checked",
                policy=P, now=NOW)
    assert tick(conn)["state"] == "idle"
    assert int(setting(conn, "fallback_epoch")) == NOW


def test_tier_zero_arrives_during_review_and_confirmed_absence_backoff(conn):
    story(conn, "review", 6)
    card = tick(conn)["card"]
    story(conn, "urgent", 10)
    assert reply(conn, card, "approve")["request_state"] == "superseded"
    task = claim(conn)
    with pytest.raises(ValueError, match="both"):
        d.authorize_push(conn, token=task["token"], commit=COMMIT, policy=P, now=NOW,
                         manifest={**manifest("urgent"), "editions": {"A2": "/articles/a/"}})
    assert push(conn, task)["push_once"]
    with pytest.raises(ValueError, match="commit"):
        d.reconcile(conn, work_id=task["id"], commit="d"*40, outcome="absent", evidence="checked", now=NOW)
    d.reconcile(conn, work_id=task["id"], commit=COMMIT, outcome="absent", evidence="fenced and absent", now=NOW)
    assert tick(conn)["state"] == "idle"
    archive(conn, NOW+P.retry_seconds)
    assert tick(conn, NOW+P.retry_seconds)["story_id"] == "urgent"


def test_manual_success_during_fallback_generation_fences_original_worker(conn):
    story(conn, "waiting", 8)
    task = claim(conn)
    story(conn, "manual", 5)
    record_publication(conn, story_id="manual", publication_key="manual-commit", verified_at=NOW, origin="manual")
    assert push(conn, task)["state"] == "superseded"
    assert tick(conn)["state"] == "idle"
    assert setting(conn, "fallback_epoch") == str(NOW)


def test_approved_fallback_failure_retains_revision_bound_approval_for_retry(conn):
    story(conn, "minor", 6)
    card = tick(conn)["card"]
    assert reply(conn, card, "rate-and-publish", rating=7)["state"] == "approved"
    task = claim(conn)
    d.fail_preparation(conn, token=task["token"], reason="temporary generation failure", policy=P, now=NOW)
    assert tick(conn)["state"] == "deferred"
    later = NOW + P.retry_seconds
    archive(conn, later)
    retried = claim(conn, later)
    assert retried["kind"] == "approved"
    assert push(conn, retried, later)["push_once"]
    d.configure(conn, paused=True, now=later)
    assert tick(conn, later)["state"] == "reconcile"


@pytest.mark.parametrize("paused", [False, True])
def test_explicit_manual_approval_fenced_in_observation_and_pause(tmp_path, paused):
    with closing(connect(tmp_path / "manual")) as db:
        seed(db, mode="observe")
        d.configure(db, paused=paused, now=NOW)
        story(db, "draft", 5)
        d.attach_manual_preview(db, story_id="draft", version=1, preview_id="approved", now=NOW)
        args = dict(preview_id="approved", version=1, policy=P, now=NOW)
        reserved = d.reserve_manual(db, **args)
        assert d.reserve_manual(db, **args) == reserved
        task = d.claim(db, work_id=reserved["work_id"], owner="manual", policy=P, now=NOW)
        d.configure(db, paused=not paused, mode="live", now=NOW)
        assert d.refresh(db, token=task["token"], policy=P, now=NOW)["state"] == "preparing"
        assert d.reserve_manual(db, **args)["work_id"] == task["id"]
        assert push(db, task)["push_once"] and not push(db, task)["push_once"]
        assert d.reserve_manual(db, **args) == {"state": "reconcile", "work_id": task["id"]}
        assert int(setting(db, "fallback_epoch")) == NOW-SLOT
        d.reconcile(db, work_id=task["id"], commit=COMMIT, outcome="live", evidence="verified editions",
                    policy=P, now=NOW)
        assert int(setting(db, "fallback_epoch")) == NOW
        assert d.reserve_manual(db, **args) == {"state": "stale"}


def test_manual_retry_is_scoped_and_honors_backoff(conn):
    story(conn, "draft", 5)
    story(conn, "urgent", 10)
    d.attach_manual_preview(conn, story_id="draft", version=1, preview_id="p", now=NOW)
    args = dict(preview_id="p", version=1, policy=P)
    first = d.reserve_manual(conn, **args, now=NOW)
    d.claim(conn, work_id=first["work_id"], owner="manual", policy=P, now=NOW)
    later = NOW + P.lease_seconds
    archive(conn, later)
    assert d.reserve_manual(conn, **args, now=later) == {"state": "deferred", "retry_at": later+P.retry_seconds}
    assert d.active(conn) is None
    automatic = tick(conn, later)
    assert automatic["story_id"] == "urgent"
    at_retry = later + P.retry_seconds
    archive(conn, at_retry)
    assert d.reserve_manual(conn, **args, now=at_retry) == {"state": "busy"}
    auto_worker = d.claim(conn, work_id=automatic["work_id"], owner="auto", policy=P, now=at_retry)
    d.fail_preparation(conn, token=auto_worker["token"], reason="failed quality", now=at_retry, policy=P)
    second = d.reserve_manual(conn, **args, now=at_retry)
    assert second["story_id"] == "draft" and second["work_id"] != first["work_id"]
    conn.execute("UPDATE stories SET needs_review=1 WHERE id='draft'")
    assert d.reserve_manual(conn, **args, now=at_retry) == {"state": "stale"}
    assert d.active(conn) is None


def test_stale_manual_preview_releases_current_revision(conn):
    story(conn, "changing", 10)
    d.attach_manual_preview(conn, story_id="changing", version=1, preview_id="old", now=NOW)
    d.reserve_manual(conn, preview_id="old", version=1, policy=P, now=NOW)
    conn.execute("UPDATE stories SET evidence_version=2 WHERE id='changing'")
    conn.execute("UPDATE story_evidence SET evidence_version=2 WHERE story_id='changing'")
    auto = tick(conn)
    assert auto["story_id"] == "changing" and auto["kind"] == "immediate"
    d.attach_manual_preview(conn, story_id="changing", version=2, preview_id="new", now=NOW)
    assert tick(conn)["state"] == "idle"
    assert d.reserve_manual(conn, preview_id="old", version=1, policy=P, now=NOW) == {"state": "stale"}
    assert d.reserve_manual(conn, preview_id="new", version=2, policy=P, now=NOW)["kind"] == "manual"
    d.release_manual_preview(conn, preview_id="new", now=NOW)
    with pytest.raises(ValueError, match="already used"):
        d.attach_manual_preview(conn, story_id="changing", version=2, preview_id="old", now=NOW)


def test_archive_refresh_retains_requested_and_preparing_work(conn):
    story(conn, "fallback", 8)
    work = tick(conn)
    set_setting(conn, "archive_ready", 0)
    assert d.claim(conn, work_id=work["work_id"], owner="w", policy=P, now=NOW)["state"] == "unavailable"
    assert d.active(conn)["id"] == work["work_id"]
    archive(conn, NOW)
    task = d.claim(conn, work_id=work["work_id"], owner="w", policy=P, now=NOW)
    set_setting(conn, "archive_ready", 0)
    assert d.refresh(conn, token=task["token"], policy=P, now=NOW+1)["state"] == "preparing"
    denied = push(conn, task, NOW+1)
    assert not denied["push_once"] and denied["blocked"] == "archive-not-ready"
    story(conn, "urgent", 10)
    archive(conn, NOW+2)
    assert push(conn, task, NOW+2)["state"] == "superseded"
    assert tick(conn, NOW+2)["story_id"] == "urgent"


def test_effective_tier_and_observation_score_hold_are_revision_scoped(conn):
    d.configure(conn, mode="observe", now=NOW)
    archive(conn, NOW)
    story(conn, "trial", 6)
    card = tick(conn)["card"]
    obs = replace(P, hold_seconds=2*SLOT)
    assert reply(conn, card, "rate", rating=10)["state"] == "pending"
    assert [(r["dispatch_score"], r["dispatch_tier"]) for r in d.candidates(conn, NOW, "observe")] == [(10, 2)]
    assert d.status(conn, policy=P, now=NOW)["queue"][0]["tier"] == 2
    assert review.signed_action(conn, envelope(card, "hold", "hold"), policy=obs, now=NOW)["state"] == "held"
    archive(conn, NOW+SLOT)
    assert d.tick(conn, policy=obs, now=NOW+SLOT)["state"] == "idle"
    assert not conn.execute("SELECT 1 FROM dispatch_deferrals").fetchone()
    assert not conn.execute("SELECT 1 FROM editor_feedback").fetchone()
    d.configure(conn, mode="live", now=NOW+SLOT)
    archive(conn, NOW+SLOT)
    live = tick(conn, NOW+SLOT)["card"]
    assert live["score"] == 6
    assert reply(conn, live, "rate", "real", now=NOW+SLOT, rating=9)["state"] == "pending"
    assert d.status(conn, policy=P, now=NOW+SLOT)["queue"][0]["tier"] == 2


def test_temporary_callback_retry_retains_bound_event(conn):
    story(conn, "review", 5)
    card = tick(conn)["card"]
    set_setting(conn, "archive_ready", 0)
    assert reply(conn, card, "approve")["state"] == "retry"
    archive(conn, NOW)
    with pytest.raises(ValueError, match="reused"):
        reply(conn, card, "decline")
    result = reply(conn, card, "approve")
    assert result["state"] == "approved" and reply(conn, card, "approve") == result


def test_signed_adapter_bound_fields_receipt_and_cli(conn, tmp_path, monkeypatch, private_review_key):
    story(conn, "review", 6)
    card = tick(conn)["card"]
    key = ("telegram", "desk", "-123", "message-1", "button-A")
    outbox = {key: review_adapter.Control(card["request_id"], "review", 1, "rate", 8)}
    args = dict(metadata=META, event_id="update-3", message_id="message-1", control_id="button-A",
                lookup_control=lambda *route: outbox.get(route))
    with pytest.raises(ValueError, match="unknown delivered"):
        review_adapter.signed_event(**{**args, "message_id": "wrong"})
    signed = review_adapter.signed_event(**args)
    cmd = ["--db", str(tmp_path / "dispatch.db"), "review-action"]
    monkeypatch.setattr(d.Policy, "load", lambda: P)
    monkeypatch.setattr(d.time, "time", lambda: NOW)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(signed["payload"])))
    with pytest.raises(SystemExit):
        main(cmd)
    for field, value in {"request_id": "x", "story_id": "x", "version": 2, "verb": "approve",
                         "event_id": "forged", "metadata": {**META, "sender": "0"},
                         "rating": 9, "note": "edited"}.items():
        tampered = {**signed, "payload": {**signed["payload"], field: value}}
        with pytest.raises(ValueError, match="signature"):
            review.signed_action(conn, tampered, policy=P, now=NOW)
    assert not conn.execute("SELECT 1 FROM review_receipts").fetchone()
    for _ in range(2):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(signed)))
        assert main(cmd) == 0
    assert conn.execute("SELECT count(*) FROM editor_feedback").fetchone()[0] == 1
    other = {**META, "sender": "789"}
    two = replace(P, editor_allowlist=(*P.editor_allowlist, review.identity(other)))
    with pytest.raises(ValueError, match="reused"):
        review.signed_action(conn, review_adapter.signed_event(**{**args, "metadata": other}), policy=two, now=NOW)
    private_review_key.chmod(0o644)
    with pytest.raises(ValueError, match="private regular"):
        review.signed_action(conn, signed, policy=P, now=NOW)
    monkeypatch.delenv("BRIEFBERLIN_REVIEW_KEY_FILE")
    with pytest.raises(SystemExit):
        main(["--db", str(tmp_path / "dispatch.db"), "dispatch-mode", "live"])

import hashlib
import json
from contextlib import closing

import pytest

from scripts.editorial import triage
from scripts.editorial.archive import record_publication, set_setting
from scripts.editorial.db import connect

NOW = 1_800_000_000


@pytest.fixture
def conn(tmp_path):
    with closing(connect(tmp_path / "host.db")) as db:
        set_setting(db, "archive_ready", 1)
        yield db


def ingest(db, number, *, url=None, publisher="District", text=None):
    text = text or f"Spandau housing update {number} at Havelufer."
    url = url or f"https://example.org/news/{number}"
    report = db.execute("SELECT id FROM reports WHERE url=?", (url,)).fetchone()
    report_id = report[0] if report else db.execute("INSERT INTO reports(url,first_seen,last_seen) VALUES(?,?,?)",
                                                     (url, NOW, NOW)).lastrowid
    return db.execute("""INSERT INTO report_revisions(report_id,content_hash,title,evidence,publisher,
        published_at,observed_at,eligible) VALUES(?,?,?,?,?,?,?,1)""",
                      (report_id, hashlib.sha256(text.encode()).hexdigest(), "Wohnheim Spandau Havelufer", text, publisher, NOW, NOW + number)).lastrowid


def event(packet, **changes):
    src = packet["source"]
    defaults = dict(relationship="new", candidate_id=None, title="Spandau housing restart",
                    change="Construction work has resumed at Havelufer.", place="Spandau",
                    entities=["Havelufer"], event_date="2026-11-24", score=8,
                    rationale="300 dwellings after a prolonged halt.", berlin_consequence="Local student housing.",
                    time_sensitivity="Work has resumed.", sufficient=True, unresolved="", material=True,
                    deadline=None, expires_at=None, evidence=dict(revision_id=src["revision_id"],
                    url=src["url"], quote=src["evidence"], attribution=src["publisher"], fact=src["evidence"]))
    defaults.update(changes)
    return defaults


def claim(db, **kwargs):
    return triage.claim(db, owner="worker", now=NOW + 10, **kwargs)


def submit(db, packet, *events):
    return triage.decide(db, token=packet["token"], model="model-v1", raw=json.dumps({"events": events}),
                         now=max(packet["evaluation_epoch"], NOW + 11))


def new_story(db):
    ingest(db, 1)
    p = claim(db)
    return submit(db, p, event(p))["stories"][0]


def test_replay_lease_cross_source_and_material_version(conn):
    ingest(conn, 1, text="dpa: Spandau restarts housing at Havelufer.")
    p = claim(conn)
    assert claim(conn)["token"] == p["token"]
    assert triage.claim(conn, owner="other", now=NOW + 11)["state"] == "busy"
    e = event(p)
    e["evidence"]["attribution"] = "dpa"
    answer = submit(conn, p, e)
    assert answer == submit(conn, p, e)
    story = answer["stories"][0]
    assert claim(conn)["state"] == "empty"
    triage.rate(conn, action_id="feedback-1", story_id=story, actor="editor", rating=7, note="local impact")
    ingest(conn, 2, publisher="Other", text="dpa: Spandau restarts housing at Havelufer.")
    q = claim(conn)
    assert q == {"state": "syndicated", "revision_id": 2, "original_revision": 1, "stories": [story]}
    assert conn.execute("SELECT wire_origin FROM story_evidence WHERE revision_id=2").fetchone()[0] == "dpa"
    original = conn.execute("SELECT * FROM editorial_queue WHERE id=?", (story,)).fetchone()
    assert (original["model_score"], original["score"], original["evidence_version"]) == (8, 7, 1)
    ingest(conn, 3, url="https://example.org/news/2", text="Spandau now confirms 400 homes at Havelufer.")
    r = claim(conn)
    submit(conn, r, event(r, relationship="same", candidate_id=story, score=9))
    latest = conn.execute("SELECT * FROM editorial_queue WHERE id=?", (story,)).fetchone()
    assert (latest["first_seen"], latest["model_score"], latest["score"], latest["evidence_version"]) == (
        original["first_seen"], 9, 7, 2)
    assert [r[0] for r in conn.execute("SELECT score FROM model_decisions ORDER BY id")] == [8, 9]
    assert conn.execute("SELECT count(*) FROM story_evidence WHERE attribution='dpa'").fetchone()[0] == 2


def test_stale_lease_cannot_mint_events_and_roundup_can(conn):
    ingest(conn, 1)
    packet = claim(conn, lease_seconds=30)
    fresh = triage.claim(conn, owner="next", now=NOW + 41)
    assert fresh["token"] != packet["token"]
    assert submit(conn, packet, event(packet))["state"] == "stale"
    result = triage.decide(conn, token=fresh["token"], model="m", now=NOW + 42,
                           raw=json.dumps({"events": [event(fresh), event(fresh, title="Separate event")]}))
    assert len(set(result["stories"])) == 2
    assert conn.execute("SELECT count(*) FROM story_evidence").fetchone()[0] == 2


@pytest.mark.parametrize("bad", [True, 8.0, -1, 11, "8"])
def test_invalid_model_scores_hold_and_human_resolution(conn, bad):
    revision = ingest(conn, 1)
    p = claim(conn)
    invalid = event(p, score=bad)
    assert submit(conn, p, invalid)["state"] == "retry"
    assert submit(conn, p, invalid)["state"] == "retry"
    assert conn.execute("SELECT invalid_count FROM triage_cases").fetchone()[0] == 1
    assert submit(conn, p, invalid | {"another_invalid_field": 1})["state"] == "held"
    assert claim(conn)["state"] == "empty"
    h = triage.claim(conn, held_revision=revision, owner="editor", now=NOW + 12)
    assert h["resolution"] and submit(conn, h, event(h))["state"] == "done"
    assert conn.execute("SELECT actor FROM editor_feedback WHERE action='resolve'").fetchone()[0] == "editor"


def test_uncertain_broken_json_and_unsupplied_or_uncited_claim(conn):
    revision = ingest(conn, 1)
    p = claim(conn)
    assert triage.decide(conn, token=p["token"], model="m", now=NOW + 11, raw="{")["state"] == "retry"
    result = triage.decide(conn, token=p["token"], model="m", now=NOW + 11, raw='{"uncertain":"Which site?"}')
    assert result["state"] == "held"
    assert triage.status(conn)["held_cases"][0]["revision_id"] == revision
    h = claim(conn, held_revision=revision)
    wrong = event(h, relationship="follow-up", candidate_id="invented")
    assert submit(conn, h, wrong)["state"] == "held"
    h = claim(conn, held_revision=revision)
    wrong = event(h)
    wrong["evidence"]["quote"] = "The model invented this."
    assert submit(conn, h, wrong)["state"] == "held"
    assert conn.execute("SELECT count(*) FROM stories").fetchone()[0] == 0


def test_live_observations_corrections_and_followups(conn):
    story = new_story(conn)
    record_publication(conn, story_id=story, publication_key="commit", origin="manual", verified_at=NOW)
    for n, relation in [(2, "same"), (3, "correction"), (4, "follow-up")]:
        ingest(conn, n)
        packet = claim(conn)
        result = submit(conn, packet, event(packet, relationship=relation, candidate_id=story,
                                             material=relation != "same"))
    assert conn.execute("SELECT status,needs_review,evidence_version FROM stories WHERE id=?",
                        (story,)).fetchone()[:] == ("live", 1, 1)
    child = result["stories"][0]
    assert child != story
    assert conn.execute("SELECT parent_id,relationship FROM stories WHERE id=?", (child,)).fetchone()[:] == (
        story, "follow-up")
    assert conn.execute("SELECT count(*) FROM live_publications").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM story_evidence WHERE story_id=? AND evidence_version IS NULL",
                        (story,)).fetchone()[0] == 2


@pytest.mark.parametrize("state", ["generating", "deploying", "declined", "expired", "skipped", "held"])
def test_frozen_content_and_explicit_dispositions_survive_material_reports(conn, state):
    story = new_story(conn)
    conn.execute("UPDATE stories SET status=? WHERE id=?", (state, story))
    ingest(conn, 2)
    p = claim(conn)
    submit(conn, p, event(p, relationship="same", candidate_id=story, score=10))
    row = conn.execute("SELECT status,model_score,evidence_version,needs_review FROM stories WHERE id=?",
                       (story,)).fetchone()
    assert tuple(row) == (state, 8, 1, int(state in {"generating", "deploying"}))


def test_context_changes_stale_packet_and_feedback_idempotency(conn):
    story = new_story(conn)
    ingest(conn, 2)
    p = claim(conn)
    kwargs = dict(story_id=story, actor="editor", action_id="vote", rating=9, note="changed assessment")
    assert triage.rate(conn, **kwargs) == triage.rate(conn, **kwargs)
    with pytest.raises(ValueError, match="reused"):
        triage.rate(conn, **(kwargs | {"rating": 10}))
    assert submit(conn, p, event(p))["state"] == "stale"
    assert claim(conn)["source"]["revision_id"] == p["source"]["revision_id"]
    assert conn.execute("SELECT count(*) FROM stories").fetchone()[0] == 1
    assert conn.execute("SELECT status,model_score,score,tier FROM editorial_queue").fetchone()[:] == (
        "pending", 8, 9, 0)


def test_expiry_sufficiency_and_old_distinctive_archive_match(conn):
    conn.execute("""INSERT INTO stories(id,title,first_seen,updated_at,status,entities)
        VALUES('years-old','Apartment project',?,?, 'live','["Havelufer"]')""", (NOW - 990 * 86400, NOW))
    ingest(conn, 1)
    p = claim(conn)
    assert "years-old" in [c["id"] for c in p["candidates"]]
    submit(conn, p, event(p, title="Expired story", score=10, deadline=NOW, expires_at=NOW),
           event(p, title="Incomplete proposal", sufficient=False, unresolved="Awaiting evidence."))
    assert dict(conn.execute("SELECT title,status FROM stories WHERE status!='live'")) == {
        "Expired story": "expired", "Incomplete proposal": "held"}


def test_insufficient_story_resolves_in_place_with_latest_material(conn):
    ingest(conn, 1)
    packet = claim(conn)
    story = submit(conn, packet, event(packet, sufficient=False, unresolved="Need the vote."))["stories"][0]
    first_seen = conn.execute("SELECT first_seen FROM stories").fetchone()[0]
    ingest(conn, 2, text="The district voted to fund the Spandau building.")
    updated = claim(conn)
    submit(conn, updated, event(updated, relationship="same", candidate_id=story))
    assert triage.status(conn)["evidence_holds"] == [{
        "story_id": story, "revision_id": 2, "reason": "Need the vote."}]
    h = triage.claim(conn, owner="editor", held_story=story, now=NOW + 12)
    assert submit(conn, h, event(h))["state"] == "held"
    h = triage.claim(conn, owner="editor", held_story=story, now=NOW + 13)
    result = submit(conn, h, event(h, relationship="same", candidate_id=story))
    assert result["stories"] == [story] and triage.status(conn)["evidence_holds"] == []
    assert conn.execute("SELECT id,first_seen,status,evidence_version FROM stories").fetchone()[:] == (
        story, first_seen, "pending", 2)
    assert conn.execute("SELECT story_id,revision_id FROM editor_feedback").fetchone()[:] == (story, 2)


def test_material_notice_uses_observed_time_and_extended_expiry_needs_date(conn):
    old = NOW - 12 * triage.DAY
    revision = ingest(conn, 1)
    conn.execute("UPDATE report_revisions SET published_at=?", (old,))
    packet = claim(conn)
    assert packet["source"]["freshness_epoch"] == old
    submit(conn, packet, event(packet))
    assert conn.execute("SELECT status FROM stories").fetchone()[0] == "expired"
    changed = ingest(conn, 2, url=packet["source"]["url"], text="Havelufer has a revised deadline.")
    conn.execute("UPDATE report_revisions SET published_at=? WHERE id=?", (old, changed))
    conn.execute("INSERT INTO notice_changes VALUES(?)", (changed,))
    packet = claim(conn)
    assert revision != changed and packet["source"]["freshness_epoch"] == NOW + 2
    assert submit(conn, packet, event(packet, expires_at=NOW + 3 * triage.DAY))["state"] == "retry"
    assert submit(conn, packet, event(packet))["state"] == "done"
    assert conn.execute("SELECT expires_at FROM stories WHERE status='pending'").fetchone()[0] == NOW + 2 + 2 * triage.DAY


def test_exact_roundup_records_all_wire_observations_without_a_model(conn):
    text = "dpa: Havelufer work resumed. Separately Spandau expanded classes."
    ingest(conn, 1, text=text)
    packet = claim(conn)
    original = submit(conn, packet, event(packet), event(packet, title="Classes expand"))
    revision = ingest(conn, 2, text=text, publisher="Local newspaper")
    copied = claim(conn)
    assert copied["state"] == "syndicated" and set(copied["stories"]) == set(original["stories"])
    outcomes = conn.execute("""SELECT relationship,wire_origin,e.url,r.publisher,e.evidence_version
        FROM story_evidence e JOIN report_revisions r ON r.id=e.revision_id WHERE r.id=?""", (revision,)).fetchall()
    assert len(outcomes) == 2 and all(tuple(r) == (
        "syndicated", "dpa", "https://example.org/news/2", "Local newspaper", None) for r in outcomes)
    assert claim(conn)["state"] == "empty"
    assert conn.execute("SELECT count(*) FROM model_decisions").fetchone()[0] == 2


def test_added_edition_alias_invalidates_matching_packet(conn):
    story = new_story(conn)
    ingest(conn, 2)
    packet = claim(conn)
    conn.execute("INSERT INTO editions VALUES('/articles/extra/',?,'de','B1','New title')", (story,))
    assert submit(conn, packet, event(packet))["state"] == "stale"


def test_quoted_service_end_can_extend_freshness(conn):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    end = NOW + 7 * triage.DAY
    date = datetime.fromtimestamp(end, ZoneInfo("Europe/Berlin")).date().isoformat()
    text = f"The Berlin application window ends on {date}."
    ingest(conn, 1, text=text)
    packet = claim(conn)
    assert submit(conn, packet, event(packet, deadline=end, expires_at=end,
                                      timing_quote=text))["state"] == "done"
    assert conn.execute("SELECT expires_at FROM stories").fetchone()[0] == end

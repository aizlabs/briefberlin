"""Lease one report revision and atomically apply a validated external judgment."""

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .archive import archive_comparisons, setting
from .db import transaction
from .matching import words

RUBRIC = "berlin-v1"
DAY = 86400
MODEL_STATES = {"pending", "review", "expired", "skipped"}
Short = Annotated[str, Field(min_length=1, max_length=300)]
Text = Annotated[str, Field(min_length=1, max_length=1200)]
Epoch = Annotated[int, Field(ge=1, le=253402300799)]
Score = Annotated[int, Field(ge=0, le=10)]


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)


class Evidence(Strict):
    revision_id: int
    url: Annotated[str, Field(min_length=1, max_length=4096)]
    quote: Annotated[str, Field(min_length=4, max_length=700)]
    attribution: Short
    wire_origin: Short | None = None
    fact: Text


class Event(Strict):
    relationship: Literal["new", "same", "follow-up", "correction"]
    candidate_id: Short | None
    title: Short
    change: Text
    place: Short
    entities: Annotated[list[Short], Field(max_length=12)]
    event_date: str | None
    score: Score
    rationale: Text
    berlin_consequence: Text
    time_sensitivity: Text
    sufficient: bool
    unresolved: Annotated[str, Field(max_length=600)]
    material: bool
    deadline: Epoch | None
    expires_at: Epoch | None
    timing_quote: Short | None = None
    evidence: Evidence


class Decision(Strict):
    events: Annotated[list[Event], Field(min_length=1, max_length=8)]


class Uncertain(Strict):
    uncertain: Text


def shortlist(conn: sqlite3.Connection, source: dict, extra: str | None = None) -> list[dict]:
    """Lexical retrieval across the whole archive, retaining rare long-running identifiers."""
    dated = source["freshness_epoch"]
    query_title = words(source["title"])
    query = query_title | words(source["evidence"])
    prior = {r[0] for r in conn.execute("""SELECT DISTINCT coalesce(a.live_id,e.story_id) FROM story_evidence e
        LEFT JOIN archive_comparisons a ON a.candidate_id=e.story_id AND a.outcome='same'
        JOIN report_revisions r ON r.id=e.revision_id WHERE r.report_id=?""", (source["report_id"],))}
    editions: dict[str, list[str]] = defaultdict(list)
    for row in conn.execute("SELECT story_id,title FROM editions WHERE lang='de' ORDER BY path"):
        editions[row[0]].append(row[1])
    corpus = []
    freq: Counter[str] = Counter()
    for row in conn.execute("""SELECT id,title,summary,place,entities,event_date,status,evidence_version,
                               first_seen,parent_id FROM stories WHERE status!='covered'"""):
        doc = dict(row)
        titles = words(" ".join([doc["title"], *editions[doc["id"]]]))
        tokens = titles | words(" ".join(str(doc[k] or "") for k in
                                         ("summary", "place", "entities", "event_date")))
        corpus.append((doc, titles, tokens))
        freq.update(tokens & query)
    ranked = []
    for doc, titles, tokens in corpus:
        overlap = query & tokens
        if not overlap and doc["id"] not in prior and doc["id"] != extra:
            continue
        strength = sum((1 + math.log((1 + len(corpus)) / (1 + freq[w])))
                       * (1 + (w in titles) + 2 * (w in query_title)) for w in overlap)
        delta = abs(dated - doc["first_seen"])
        strength += max(0, 2 - delta / DAY)
        # Same report and an editor's explicitly named comparison always take precedence.
        ranked.append(((doc["id"] == extra, doc["id"] in prior, strength, -delta, doc["id"]), doc))
    if extra and not any(doc["id"] == extra for _, doc in ranked):
        raise ValueError("unknown editor-specified comparison story")
    result = []
    for _, doc in sorted(ranked, key=lambda x: x[0], reverse=True)[:12]:
        doc["summary"] = doc["summary"][:600]
        doc["editions"] = [r[0] for r in conn.execute(
            "SELECT path FROM editions WHERE story_id=? AND lang='de' ORDER BY path LIMIT 2", (doc["id"],))]
        doc["previous_evidence"] = [dict(r) for r in conn.execute("""
            SELECT e.fact,e.attribution,e.wire_origin,e.url FROM story_evidence e WHERE story_id=?
            ORDER BY e.recorded_at DESC,e.revision_id DESC LIMIT 2""", (doc["id"],))]
        result.append(doc)
    return result


def packet_for(conn: sqlite3.Connection, revision: int, now: int, extra: str | None) -> dict:
    source = dict(conn.execute("SELECT * FROM editorial_inputs WHERE revision_id=?", (revision,)).fetchone())
    source["evidence"] = source["evidence"][:4000]
    source["observed_notice_change"] = bool(conn.execute(
        "SELECT 1 FROM notice_changes WHERE revision_id=?", (revision,)).fetchone())
    source["freshness_epoch"] = (source["observed_at"] if source["observed_notice_change"]
                                 else source["published_at"] or source["observed_at"])
    source["source_date"] = conn.execute("SELECT source_date FROM report_revisions WHERE id=?",
                                         (revision,)).fetchone()[0]
    source["issuers"] = [dict(row) for row in conn.execute("""
        SELECT DISTINCT s.id,s.publisher,s.scope FROM sources s JOIN source_sightings o
        ON o.source_id=s.id WHERE o.revision_id=? ORDER BY s.id LIMIT 20""", (revision,))]
    return {"rubric": RUBRIC, "evaluation_epoch": now, "source": source,
            "candidates": shortlist(conn, source, extra)}


def copy_syndicated(conn: sqlite3.Connection, revision: int, now: int) -> dict | None:
    original = conn.execute("""SELECT prior.id,current_report.url FROM report_revisions current
        JOIN reports current_report ON current_report.id=current.report_id
        JOIN report_revisions prior ON prior.content_hash=current.content_hash
            AND prior.evidence=current.evidence AND prior.report_id<>current.report_id
        JOIN triage_cases c ON c.revision_id=prior.id AND c.state='done'
        WHERE current.id=? AND EXISTS (SELECT 1 FROM story_evidence WHERE revision_id=prior.id)
        AND NOT EXISTS (SELECT 1 FROM story_evidence e WHERE e.revision_id=prior.id
            AND instr(current.evidence,e.quote)=0 AND instr(current.title,e.quote)=0)
        ORDER BY prior.id LIMIT 1""", (revision,)).fetchone()
    if not original:
        return None
    prior, url = original
    conn.execute("""INSERT INTO story_evidence(story_id,revision_id,evidence_version,relationship,fact,
        quote,attribution,url,recorded_at,wire_origin)
        SELECT coalesce(a.live_id,e.story_id),?,NULL,'syndicated',e.fact,e.quote,e.attribution,?,?,e.wire_origin
        FROM story_evidence e LEFT JOIN archive_comparisons a ON a.candidate_id=e.story_id AND a.outcome='same'
        WHERE e.revision_id=? ORDER BY e.story_id ON CONFLICT(story_id,revision_id) DO NOTHING""",
                 (revision, url, now, prior))
    conn.execute("""INSERT INTO triage_cases(revision_id,state,reason) VALUES(?,'done',?)
        ON CONFLICT(revision_id) DO UPDATE SET state='done',reason=excluded.reason""",
                 (revision, f"Exact text from revision {prior}"))
    stories = [row[0] for row in conn.execute(
        "SELECT story_id FROM story_evidence WHERE revision_id=? ORDER BY story_id", (revision,))]
    return {"state": "syndicated", "revision_id": revision, "original_revision": prior, "stories": stories}


def claim(conn: sqlite3.Connection, *, owner: str, lease_seconds: int = 600,
          now: int | None = None, held_revision: int | None = None,
          compare: str | None = None, held_story: str | None = None) -> dict:
    now = int(time.time()) if now is None else now
    if not owner.strip() or len(owner) > 160 or not 30 <= lease_seconds <= 1800:
        raise ValueError("provide owner and lease duration from 30 to 1800 seconds")
    with transaction(conn):
        if setting(conn, "archive_ready") != "1":
            raise ValueError("triage requires a reconciled live archive")
        conn.execute("UPDATE triage_leases SET state='expired' WHERE state='active' AND expires_at<=?", (now,))
        if held_story is not None:
            if held_revision is not None or compare is not None:
                raise ValueError("use only the held story ID to resolve insufficient evidence")
            hold = conn.execute("SELECT revision_id FROM evidence_holds WHERE story_id=?", (held_story,)).fetchone()
            if not hold:
                raise ValueError("unknown evidence hold")
            held_revision, compare = hold[0], held_story
        active = conn.execute("SELECT * FROM triage_leases WHERE state='active'").fetchone()
        if active:
            prior_packet = json.loads(active["packet"])
            if (active["owner"] != owner or active["revision_id"] != (held_revision or active["revision_id"])
                    or prior_packet.get("resolution_story") != held_story
                    or prior_packet["resolution"] != (held_revision is not None)):
                return {"state": "busy", "expires_at": active["expires_at"]}
            return prior_packet
        if held_story:
            row = (held_revision,)
        elif held_revision is not None:
            row = conn.execute("SELECT revision_id FROM triage_cases WHERE revision_id=? AND state='held'",
                               (held_revision,)).fetchone()
            if not row:
                raise ValueError("held revision required")
        else:
            row = conn.execute("""SELECT i.revision_id FROM editorial_inputs i
                LEFT JOIN triage_cases c USING(revision_id) WHERE i.eligible=1
                AND (c.state IS NULL OR c.state='open')
                ORDER BY i.observed_at,i.revision_id LIMIT 1""").fetchone()
        if not row:
            return {"state": "empty"}
        revision = row[0]
        if held_revision is None:
            copied = copy_syndicated(conn, revision, now)
            if copied:
                return copied
        token = uuid.uuid4().hex
        packet = packet_for(conn, revision, now, compare)
        packet.update(state="claimed", token=token, expires_at=now + lease_seconds,
                      resolution=held_revision is not None, resolution_story=held_story)
        conn.execute("INSERT OR IGNORE INTO triage_cases(revision_id,state) VALUES(?,'open')", (revision,))
        conn.execute("""INSERT INTO triage_leases(token,revision_id,owner,expires_at,context_version,
                     packet,state) VALUES(?,?,?,?,?,?,'active')""", (token, revision, owner, now + lease_seconds,
                     int(setting(conn, "story_context_version") or 0), json.dumps(packet)))
        return packet


def validate_timing(e: Event, source: dict) -> None:
    if e.deadline and e.expires_at and e.expires_at > e.deadline:
        raise ValueError("expiry exceeds the reader deadline")
    end = max(e.deadline or 0, e.expires_at or 0)
    start = source["freshness_epoch"]
    if end <= start + 2 * DAY:
        return
    if end > start + 90 * DAY or not e.timing_quote or e.timing_quote not in source["evidence"]:
        raise ValueError("extended timing requires a quoted service date within 90 days of the evidence")
    day = datetime.fromtimestamp(end, ZoneInfo("Europe/Berlin")).date()
    month = ("Januar Februar März April Mai Juni Juli August September Oktober November Dezember"
             .split()[day.month - 1])
    quoted = e.timing_quote.casefold()
    patterns = (re.escape(day.isoformat()), rf"0?{day.day}\.\s*0?{day.month}\.\s*{day.year}",
                rf"0?{day.day}\.\s*{month.casefold()}\s+{day.year}")
    if not any(re.search(rf"(?<!\d){pattern}(?!\d)", quoted) for pattern in patterns):
        raise ValueError("the extended deadline must match the quoted calendar date in Berlin")


def parse_decision(raw: str, packet: dict) -> Decision | Uncertain:
    if len(raw) > 64000:
        raise ValueError("decision exceeds 64000 characters")
    obj = json.loads(raw)
    if isinstance(obj, dict) and "uncertain" in obj:
        return Uncertain.model_validate(obj)
    decision = Decision.model_validate(obj)
    if packet.get("resolution_story") and (len(decision.events) != 1 or
            decision.events[0].relationship not in {"same", "correction"} or
            decision.events[0].candidate_id != packet["resolution_story"]):
        raise ValueError("evidence resolution must update the specified held story")
    ids = {s["id"] for s in packet["candidates"]}
    source = packet["source"]
    targets = set()
    titles = set()
    for e in decision.events:
        if ((e.relationship == "new" and e.candidate_id is not None) or
                (e.relationship != "new" and e.candidate_id not in ids)):
            raise ValueError("relationship requires a supplied candidate, or null for new")
        if e.relationship in {"same", "correction"}:
            if e.candidate_id in targets:
                raise ValueError("one event per existing story")
            targets.add(e.candidate_id)
        if e.title.casefold() in titles:
            raise ValueError("repeat event title in decision")
        titles.add(e.title.casefold())
        ref = e.evidence
        if ref.revision_id != source["revision_id"] or ref.url != source["url"]:
            raise ValueError("evidence must cite the supplied revision and URL")
        if ref.quote not in source["evidence"] and ref.quote not in source["title"]:
            raise ValueError("evidence quote must occur in the supplied text")
        credited = {source["publisher"], *(issuer["publisher"] for issuer in source["issuers"])}
        if ref.attribution not in credited and ref.attribution.casefold() not in (
            source["title"] + " " + source["evidence"]).casefold():
            raise ValueError("attribution must identify a supplied issuer or an explicitly named origin")
        if ref.wire_origin and ref.wire_origin not in credited and ref.wire_origin.casefold() not in (
                source["title"] + " " + source["evidence"]).casefold():
            raise ValueError("wire origin must be explicit in the source")
        if e.event_date is not None:
            if date.fromisoformat(e.event_date).isoformat() != e.event_date:
                raise ValueError("event_date must be YYYY-MM-DD")
        validate_timing(e, source)
        if not e.sufficient and not e.unresolved:
            raise ValueError("identify the missing evidence")
        if e.unresolved and e.sufficient:
            raise ValueError("unresolved factual questions require insufficient evidence")
        if e.relationship == "correction" and not e.material:
            raise ValueError("a correction requires a material changed fact")
    return decision


def record_event(conn: sqlite3.Connection, e: Event, packet: dict, now: int) -> tuple[str, int | None]:
    source = packet["source"]
    existing = e.relationship in {"same", "correction"}
    story_id = e.candidate_id if existing else "story-" + uuid.uuid4().hex
    assert story_id
    fact_time = source["freshness_epoch"]
    expiry = e.expires_at or min(fact_time + 2 * DAY, e.deadline or 253402300799)
    status = "pending"
    if not e.sufficient:
        status = "held"
    elif expiry <= now:
        status = "expired"
    elif e.score < 4:
        status = "skipped"
    version: int | None = None
    material = False
    if not existing:
        conn.execute("""INSERT INTO stories(id,title,summary,place,entities,event_date,first_seen,
            updated_at,parent_id,relationship,status,model_score,deadline,expires_at,sufficient)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (story_id, e.title, e.change, e.place,
            json.dumps(e.entities), e.event_date, source["observed_at"], now, e.candidate_id,
            e.relationship, status, e.score, e.deadline, expiry, e.sufficient))
        version = 1
    else:
        row = conn.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()
        identical = conn.execute("""SELECT 1 FROM story_evidence old
            JOIN report_revisions a ON a.id=old.revision_id
            JOIN report_revisions b ON b.id=? AND b.content_hash=a.content_hash
            WHERE old.story_id=? LIMIT 1""", (source["revision_id"], story_id)).fetchone()
        material = e.material and identical is None
        resolving = packet.get("resolution_story") == story_id and row["status"] == "held"
        if resolving or (row["status"] in MODEL_STATES and material):
            version = row["evidence_version"] + 1
            # A score override remains separate even as the model assessment changes.
            if status == "skipped" and row["editor_score"] is not None and row["editor_score"] >= 4:
                status = "pending"
            conn.execute("""UPDATE stories SET title=?,summary=?,place=?,entities=?,event_date=?,
                updated_at=?,evidence_version=?,model_score=?,deadline=?,expires_at=?,sufficient=?,
                status=?,needs_review=? WHERE id=?""", (e.title, e.change, e.place, json.dumps(e.entities),
                e.event_date, now, version, e.score, e.deadline, expiry, e.sufficient, status,
                not e.sufficient, story_id))
        elif material and (row["status"] in {"generating", "deploying"} or e.relationship == "correction"):
            conn.execute("UPDATE stories SET needs_review=1 WHERE id=?", (story_id,))
    if version is not None and not e.sufficient:
        conn.execute("""INSERT INTO evidence_holds VALUES(?,?,?) ON CONFLICT(story_id)
            DO UPDATE SET revision_id=excluded.revision_id,reason=excluded.reason""",
                     (story_id, source["revision_id"], e.unresolved))
    elif packet.get("resolution_story") == story_id:
        conn.execute("DELETE FROM evidence_holds WHERE story_id=?", (story_id,))
    elif existing and material:
        conn.execute("UPDATE evidence_holds SET revision_id=? WHERE story_id=?", (source["revision_id"], story_id))
    wire = e.evidence.wire_origin
    if not wire:
        credit = re.search(r"(?:^|\()(dpa|AFP|Reuters|AP)(?:[):/]|\s[-–])",
                           source["evidence"], re.IGNORECASE)
        wire = credit.group(1) if credit else None
    conn.execute("""INSERT INTO story_evidence(story_id,revision_id,evidence_version,relationship,fact,
                 quote,attribution,url,recorded_at,wire_origin) VALUES(?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(story_id,revision_id) DO UPDATE SET evidence_version=excluded.evidence_version,
                 relationship=excluded.relationship,fact=excluded.fact,quote=excluded.quote,
                 attribution=excluded.attribution,wire_origin=excluded.wire_origin,recorded_at=excluded.recorded_at""",
                 (story_id, source["revision_id"], version, e.relationship, e.evidence.fact, e.evidence.quote,
                  e.evidence.attribution, e.evidence.url, now, wire))
    return story_id, version


def decide(conn: sqlite3.Connection, *, token: str, raw: str, model: str, now: int | None = None) -> dict:
    now = int(time.time()) if now is None else now
    if not model.strip() or len(model) > 200:
        raise ValueError("model version or human resolver identity required")
    with transaction(conn):
        lease = conn.execute("SELECT * FROM triage_leases WHERE token=?", (token,)).fetchone()
        if not lease:
            raise ValueError("unknown lease token")
        if lease["receipt"]:
            return json.loads(lease["receipt"])
        if lease["state"] != "active" or now >= lease["expires_at"]:
            return {"state": "stale"}
        if (setting(conn, "archive_ready") != "1" or
                lease["context_version"] != int(setting(conn, "story_context_version") or 0)):
            conn.execute("UPDATE triage_leases SET state='stale' WHERE token=?", (token,))
            return {"state": "stale"}
        digest = hashlib.sha256(raw.encode()).hexdigest()
        previous = conn.execute("SELECT receipt FROM invalid_submissions WHERE token=? AND digest=?",
                                (token, digest)).fetchone()
        if previous:
            return json.loads(previous[0])
        packet = json.loads(lease["packet"])
        rev = lease["revision_id"]
        events = []
        issue = ""
        try:
            decision = parse_decision(raw, packet)
        except (ValueError, RecursionError) as exc:
            if isinstance(exc, ValidationError):
                issue = "; ".join(".".join(map(str, e["loc"])) + " " + e["msg"]
                                  for e in exc.errors(include_input=False)[:4])
            else:
                issue = str(exc)[:600]
            conn.execute("UPDATE triage_cases SET invalid_count=invalid_count+1,reason=? "
                         "WHERE revision_id=?", (issue, rev))
            failures = conn.execute("SELECT invalid_count FROM triage_cases WHERE revision_id=?", (rev,)).fetchone()[0]
            state = "held" if failures >= 2 or packet["resolution"] else "retry"
        else:
            if isinstance(decision, Uncertain):
                issue, state = decision.uncertain, "held"
            else:
                state = "done"
                for event in decision.events:
                    story_id, version = record_event(conn, event, packet, now)
                    events.append(story_id)
                    conn.execute("""INSERT INTO model_decisions(story_id,revision_id,evidence_version,
                        token,rubric,model,score,outcome,response,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                                 (story_id, rev, version, token, RUBRIC, model, event.score,
                                  event.relationship, event.model_dump_json(), now))
        if issue:
            conn.execute("""INSERT INTO model_decisions(revision_id,token,rubric,model,outcome,response,
                         recorded_at) VALUES(?,?,?,?,?,?,?)""", (rev, token, RUBRIC, model, state, issue, now))
        receipt = {"state": state, "revision_id": rev, "stories": events}
        if issue:
            receipt["reason"] = issue
        if state == "retry":
            conn.execute("INSERT INTO invalid_submissions VALUES(?,?,?)", (token, digest, json.dumps(receipt)))
        else:
            if packet["resolution"] and state == "done":
                conn.execute("""INSERT INTO editor_feedback(action_id,revision_id,story_id,actor,action,note,
                             recorded_at) VALUES(?,?,?,?,'resolve',?,?)""", (token, rev, packet.get("resolution_story"),
                                                                            lease["owner"], model, now))
            if not packet.get("resolution_story"):
                conn.execute("UPDATE triage_cases SET state=?,reason=? WHERE revision_id=?", (state, issue, rev))
            conn.execute("UPDATE triage_leases SET state='closed',receipt=? WHERE token=?",
                         (json.dumps(receipt), token))
        return receipt


def rate(conn: sqlite3.Connection, *, action_id: str, story_id: str, actor: str, rating: int,
         note: str, now: int | None = None) -> dict:
    now = int(time.time()) if now is None else now
    if (not action_id.strip() or not actor.strip() or type(rating) is not int or not 0 <= rating <= 10):
        raise ValueError("feedback requires action ID, actor and integer rating 0..10")
    with transaction(conn):
        previous = conn.execute("SELECT story_id,actor,rating,note,action FROM editor_feedback WHERE action_id=?",
                                (action_id,)).fetchone()
        if previous and tuple(previous) != (story_id, actor, rating, note, "rate"):
            raise ValueError("feedback action ID reused for another operation")
        if not previous:
            conn.execute("""INSERT INTO editor_feedback(action_id,story_id,actor,action,rating,note,recorded_at)
                         VALUES(?,?,?,'rate',?,?,?)""", (action_id, story_id, actor, rating, note, now))
            conn.execute("UPDATE stories SET editor_score=? WHERE id=?", (rating, story_id))
    return {"action_id": action_id, "story_id": story_id, "rating": rating, "action": "rate"}


def status(conn: sqlite3.Connection) -> dict:
    return {
        "archive_ready": setting(conn, "archive_ready") == "1",
        "fallback_epoch": setting(conn, "fallback_epoch"),
        "unprocessed": conn.execute("""SELECT count(*) FROM editorial_inputs i LEFT JOIN triage_cases c
            USING(revision_id) WHERE i.eligible=1 AND (c.state IS NULL OR c.state='open')""").fetchone()[0],
        "held_cases": [dict(r) for r in conn.execute("""SELECT revision_id,reason,invalid_count
            FROM triage_cases WHERE state='held' ORDER BY revision_id""")],
        "evidence_holds": [dict(r) for r in conn.execute("SELECT * FROM evidence_holds ORDER BY story_id")],
        "archive_comparisons": archive_comparisons(conn),
        "worker": [dict(r) for r in conn.execute("""SELECT revision_id,owner,expires_at
            FROM triage_leases WHERE state='active' AND expires_at>?""", (int(time.time()),))],
        "stories": dict(conn.execute("SELECT status,count(*) FROM stories GROUP BY status")),
        "needs_review": [r[0] for r in conn.execute("SELECT id FROM stories WHERE needs_review=1 ORDER BY id")],
    }

"""Revision-bound review receipts and the trusted host adapter's signed callback protocol."""

import hashlib
import hmac
import json
import os
import re
import stat
from urllib.parse import quote

from .archive import setting
from .db import transaction
from .dispatch import Policy, choose, clock, close_review, review_row

ACTIONS = {"approve", "decline", "hold", "rate", "rate-and-publish"}
DOMAIN = b"briefberlin/review-action/v1\x00"


def callback_key():
    path = os.environ.get("BRIEFBERLIN_REVIEW_KEY_FILE")
    if not path:
        raise ValueError("configure the private review adapter key file")
    with open(path, "rb") as handle:
        mode = os.fstat(handle.fileno()).st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise ValueError("review key must be a private regular file")
        key = handle.read(33)
    if len(key) != 32:
        raise ValueError("review key must contain exactly 32 random bytes")
    return key


def callback_bytes(payload):
    return DOMAIN + json.dumps(payload, ensure_ascii=True, allow_nan=False, sort_keys=True,
                               separators=(",", ":")).encode("ascii")


def signed_action(conn, envelope, *, policy=None, now=None):
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise ValueError("signed review envelope required")
    payload, signature = envelope["payload"], envelope["signature"]
    required = {"metadata", "event_id", "request_id", "story_id", "version", "verb"}
    if not isinstance(payload, dict) or not required <= set(payload) <= required | {"rating", "note"}:
        raise ValueError("invalid review payload")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise ValueError("invalid review signature")
    expected = hmac.new(callback_key(), callback_bytes(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid review signature")
    return _apply_action(conn, **payload, policy=policy, now=now)


def identity(metadata):
    fields = ("transport", "account", "conversation", "sender")
    if not isinstance(metadata, dict) or set(metadata) != set(fields):
        raise ValueError("authenticated transport envelope required")
    parts = [metadata[k] for k in fields]
    if any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 256 for v in parts):
        raise ValueError("missing transport identity")
    return "/".join(quote(v, safe="") for v in parts)


def _apply_action(conn, *, metadata, event_id, request_id, story_id, version, verb, rating=None,
                  note="", policy=None, now=None):
    p = policy or Policy.load()
    actor = identity(metadata)
    if actor not in p.editor_allowlist:
        raise ValueError("editor transport identity is not authorized")
    if (not isinstance(verb, str) or verb not in ACTIONS
            or not all(isinstance(i, str) and 1 <= len(i.strip()) <= 256 for i in (request_id, story_id))
            or not isinstance(event_id, str) or not 1 <= len(event_id.strip()) <= 512
            or type(version) is not int or not isinstance(note, str) or len(note) > 1000):
        raise ValueError("invalid editor callback")
    if verb in {"rate", "rate-and-publish"}:
        if type(rating) is not int or not 0 <= rating <= 10:
            raise ValueError("integer rating 0..10 required")
        if verb == "rate-and-publish" and rating < 4:
            raise ValueError("publish a below-threshold story through an explicit manual preview")
    elif rating is not None:
        raise ValueError("rating supplied for a decision without a rating")
    payload = json.dumps([request_id, story_id, version, verb, rating, note])
    event_key = json.dumps([metadata["transport"], metadata["account"], event_id], separators=(",", ":"))
    with transaction(conn):
        now = clock(now)
        seen = conn.execute("SELECT * FROM review_receipts WHERE event_id=?", (event_key,)).fetchone()
        if seen:
            if seen["actor"] != actor or seen["payload"] != payload:
                raise ValueError("callback identity reused with changed content")
            prior = json.loads(seen["result"])
            if prior["state"] != "retry":
                return prior
        request = conn.execute("SELECT * FROM review_requests WHERE id=?", (request_id,)).fetchone()
        if not request or (request["story_id"], request["version"]) != (story_id, version):
            raise ValueError("review request and evidence identity do not match")
        dispatch = choose(conn, now, p)
        state = conn.execute("SELECT state FROM review_requests WHERE id=?", (request_id,)).fetchone()[0]
        result = {"request_id": request_id, "story_id": story_id, "evidence_version": version, "mode": request["mode"]}
        if state != "pending" or request["mode"] != setting(conn, "dispatch_mode"):
            result.update(state="stale", request_state=state)
        elif dispatch["state"] in {"blocked", "reconcile", "requested", "preparing"}:
            result.update(state="retry", reason=dispatch["state"])
        else:
            observing = request["mode"] == "observe"
            if observing and rating is not None:
                conn.execute("""INSERT INTO observation_decisions(story_id,version,rating) VALUES(?,?,?)
                    ON CONFLICT(story_id,version) DO UPDATE SET rating=excluded.rating""", (story_id, version, rating))
            elif not observing:
                conn.execute("""INSERT INTO editor_feedback(action_id,story_id,actor,action,rating,note,recorded_at)
                    VALUES(?,?,?,?,?,?,?)""", ("review:" + event_key, story_id, actor, verb, rating, note, now))
                if rating is not None:
                    conn.execute("UPDATE stories SET editor_score=? WHERE id=?", (rating, story_id))
            if verb in {"approve", "rate-and-publish"}:
                state = "approved"
            elif verb == "decline":
                state = "declined"
                if not observing:
                    conn.execute("UPDATE stories SET status='declined' WHERE id=?", (story_id,))
            elif verb == "hold":
                state = "held"
                if observing:
                    conn.execute("""INSERT INTO observation_decisions(story_id,version,hold_until) VALUES(?,?,?)
                        ON CONFLICT(story_id,version) DO UPDATE SET hold_until=excluded.hold_until""",
                                 (story_id, version, now + p.hold_seconds))
                else:
                    conn.execute("""INSERT INTO dispatch_deferrals(story_id,hold_until) VALUES(?,?)
                        ON CONFLICT(story_id) DO UPDATE SET hold_until=excluded.hold_until""",
                                 (story_id, now + p.hold_seconds))
            else:
                state = "pending"
            close_review(conn, request_id, state)
            if state in {"approved", "held", "declined"}:
                conn.execute("UPDATE review_requests SET response_at=? WHERE id=?", (now, request_id))
            result.update(state=state, action=verb, rating=rating)
        conn.execute("""INSERT INTO review_receipts VALUES(?,?,?,?,?,?) ON CONFLICT(event_id)
                        DO UPDATE SET result=excluded.result,recorded_at=excluded.recorded_at""",
                     (event_key, request_id, actor, payload, json.dumps(result), now))
        return result


def pending(conn, *, policy=None, now=None):
    p = policy or Policy.load()
    with transaction(conn):
        mode = setting(conn, "dispatch_mode")
        result = choose(conn, clock(now), p)
        request = review_row(conn, mode)
        if result["state"] not in {"review", "awaiting-editor"} or not request:
            return {"state": result["state"], "deliver": False}
        return {"state": "pending", "deliver": mode == "live", "delivered_at": request["delivered_at"],
                "delivery_count": request["delivery_count"], "card": json.loads(request["card"])}


def delivered(conn, *, request_id, receipt, policy=None, now=None):
    if not isinstance(receipt, str) or not 1 <= len(receipt.strip()) <= 512:
        raise ValueError("delivery receipt required")
    p = policy or Policy.load()
    with transaction(conn):
        now = clock(now)
        seen = conn.execute("SELECT request_id FROM review_deliveries WHERE receipt=?", (receipt,)).fetchone()
        if seen:
            if seen[0] != request_id:
                raise ValueError("delivery receipt collision")
            return {"state": "acknowledged", "request_id": request_id}
        dispatch = choose(conn, now, p)
        r = review_row(conn, "live")
        if (dispatch["state"] not in {"awaiting-editor", "review"} or not r or r["id"] != request_id
                or setting(conn, "dispatch_mode") != "live"):
            return {"state": "stale", "request_id": request_id}
        conn.execute("INSERT INTO review_deliveries VALUES(?,?)", (receipt, request_id))
        conn.execute("""UPDATE review_requests SET delivery_count=delivery_count+1,delivered_at=?
                        WHERE id=?""", (now, request_id))
        return {"state": "acknowledged", "request_id": request_id}

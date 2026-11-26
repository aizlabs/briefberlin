"""Host-owned Telegram card outbox and authenticated callback receiver."""

import argparse
import json
import os
import re
import sys
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone

import requests

from . import publication_host as host
from . import review, review_adapter
from .db import connect, transaction
from .dispatch import Policy

PREFIX = "bb-review:"


class TelegramRateLimitError(Exception):
    """Telegram definitively rejected this attempt and supplied a cooldown."""

    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__("Telegram rate limit")


def route(policy):
    account = os.environ["BB_TELEGRAM_ACCOUNT"]
    chat = host.telegram_target().read_text().strip()
    if not re.fullmatch(r"-?[1-9][0-9]{0,18}", chat):
        raise ValueError("review delivery needs a numeric Telegram chat ID")
    prefix = review.identity(dict(transport="telegram", account=account, conversation=chat, sender="x"))[:-1]
    if not any(actor.startswith(prefix) for actor in policy.editor_allowlist):
        raise ValueError("review delivery route has no authorized editor")
    return account, chat


def date(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render(card):
    when = card["date"] or "unspecified"
    source = date(card["source_date"] or card["observed_at"])
    date_kind = "Published" if card["source_date"] else "Observed"
    text = (f'{card["mode"].upper()} · Berlin editorial review\n{card["headline"][:280]}\n'
            f'Score {card["score"]}/10 · Event date {when}\n{date_kind} {source}\n'
            f'Berlin impact: {card["berlin_impact"][:450]}\nReason: {card["rationale"][:450]}\n'
            f'{card["attribution"][:120]} · {card["source_url"]}\n'
            f'Valid until {date(card["expires_at"])}\nStory {card["story_id"]} · evidence v{card["evidence_version"]}\n'
            f'Request {card["request_id"]}\nRate records a score. Rate + publish also approves.')
    if len(text.encode("utf-16-le")) > 8192:
        raise ValueError("review text exceeds Telegram message limit")
    return text


def keyboard(conn, card_id):
    choices = [[("Approve", "approve", None), ("Decline", "decline", None), ("Hold", "hold", None)]]
    for verb, label, scores in (("rate", "Rate", range(11)), ("rate-and-publish", "Rate + publish", range(4, 11))):
        buttons = [(f"{label} {n}", verb, n) for n in scores]
        choices.extend(buttons[i:i + 3] for i in range(0, len(buttons), 3))
    rows = []
    for row in choices:
        buttons = []
        for label, verb, rating in row:
            token = uuid.uuid4().hex
            conn.execute("INSERT INTO telegram_controls VALUES(?,?,?,?)", (token, card_id, verb, rating))
            buttons.append({"text": label, "callback_data": PREFIX + token})
        rows.append(buttons)
    return {"inline_keyboard": rows}


def send_message(body):
    token = os.environ["BB_TELEGRAM_BOT_TOKEN"]
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                 json=body, timeout=(4, 20), allow_redirects=False)
        result = response.json()
        if response.status_code == 429 and result.get("ok") is False and result.get("error_code") == 429:
            delay = result.get("parameters", {}).get("retry_after")
            if type(delay) is int and 0 < delay <= 2**31 - 1:
                raise TelegramRateLimitError(delay)
        if response.status_code == 200 and result.get("ok") is True:
            message = result["result"]
            if str(message["chat"]["id"]) == body["chat_id"] and type(message["message_id"]) is int:
                return str(message["message_id"])
    except (requests.RequestException, ValueError, AttributeError, KeyError, TypeError):
        pass
    raise OSError("Telegram delivery outcome unknown; inspect the private outbox")


def outbox(conn, request_id):
    row = conn.execute("SELECT * FROM telegram_cards WHERE request_id=? ORDER BY rowid DESC LIMIT 1",
                       (request_id,)).fetchone()
    return dict(row) if row else None


def send_pending(conn, *, resend=None, observation=None, send=send_message, policy=None, now=None):
    policy = policy or Policy.load()
    pending = review.pending(conn, policy=policy, now=now)
    card = pending.get("card", {})
    request_id = card.get("request_id")
    test = observation is not None and request_id == observation and card["mode"] == "observe"
    if observation is not None and not test:
        raise ValueError("current observation request ID required")
    if not pending.get("deliver") and not test:
        return {"state": pending["state"], "sent": False}
    account, chat = route(policy)
    text = render(card)
    last = outbox(conn, request_id)
    if last and last["message_id"] and resend is None and not test:
        receipt = json.dumps([last["account"], last["chat"], last["message_id"]])
        review.delivered(conn, request_id=request_id, receipt=receipt, policy=policy, now=now)
    with transaction(conn):
        current = conn.execute("SELECT state FROM review_requests WHERE id=?", (request_id,)).fetchone()
        if not current or current[0] != "pending":
            return {"state": "stale"}
        last = outbox(conn, request_id)
        if resend is not None and (not last or last["id"] != resend):
            raise ValueError("resend requires the current attempt ID")
        current_time = int(time.time()) if now is None else now
        if last and last["retry_at"] is not None and current_time < last["retry_at"]:
            return {"state": "rate-limited", "attempt": last["id"], "retry_at": last["retry_at"]}
        if last and last["retry_at"] is None and resend is None:
            return {"state": "sent" if last["message_id"] else "ambiguous", "attempt": last["id"]}
        if not last and pending.get("delivery_count"):
            return {"state": "already-delivered"}
        attempt = uuid.uuid4().hex
        conn.execute("INSERT INTO telegram_cards(id,request_id,account,chat,created_at) VALUES(?,?,?,?,?)",
                     (attempt, request_id, account, chat, current_time))
        markup = keyboard(conn, attempt)
    try:
        message = send({"chat_id": chat, "text": text, "reply_markup": markup,
                        "link_preview_options": {"is_disabled": True}})
    except TelegramRateLimitError as exc:
        retry_at = (int(time.time()) if now is None else now) + exc.retry_after
        with transaction(conn):
            conn.execute("UPDATE telegram_cards SET retry_at=? WHERE id=?", (retry_at, attempt))
        return {"state": "rate-limited", "attempt": attempt, "retry_at": retry_at}
    with transaction(conn):
        conn.execute("UPDATE telegram_cards SET message_id=? WHERE id=?", (message, attempt))
    if not test:
        review.delivered(conn, request_id=request_id, receipt=json.dumps([account, chat, message]),
                         policy=policy, now=now)
    return {"state": "sent", "attempt": attempt, "message_id": message}


def receive(conn, update, account, *, policy=None, now=None):
    cb = update.get("callback_query") or {}
    msg = cb.get("message") or {}
    sender = cb.get("from") or {}
    chat = msg.get("chat") or {}
    data = cb.get("data")
    if (type(update.get("update_id")) is not int or not isinstance(cb.get("id"), str)
            or type(sender.get("id")) is not int or sender.get("is_bot") is not False
            or type(chat.get("id")) is not int or type(msg.get("message_id")) is not int
            or msg.get("forward_origin") or msg.get("via_bot") or msg.get("sender_chat")
            or not isinstance(data, str) or not re.fullmatch(PREFIX + r"[0-9a-f]{32}", data)):
        raise ValueError("invalid or relayed review callback")
    metadata = dict(transport="telegram", account=account, conversation=str(chat["id"]), sender=str(sender["id"]))

    def lookup(transport, bot, conversation, message, token):
        row = conn.execute("""SELECT r.id,r.story_id,r.version,c.verb,c.rating,t.id
            FROM telegram_controls c JOIN telegram_cards t ON t.id=c.card_id
            JOIN review_requests r ON r.id=t.request_id
            WHERE c.token=? AND t.account=? AND t.chat=? AND t.message_id=?""",
                           (token, bot, conversation, message)).fetchone()
        return review_adapter.Control(*row) if row else None

    envelope = review_adapter.signed_event(metadata=metadata, event_id=cb["id"], message_id=str(msg["message_id"]),
                                           control_id=data[len(PREFIX):], lookup_control=lookup)
    return review.signed_action(conn, envelope, policy=policy, now=now)


def ingress():
    """Invoked only by the authenticated ingress process; stdin is never a model capability."""
    raw = sys.stdin.buffer.read(256001)
    if len(raw) > 256000:
        raise ValueError("oversized Telegram update")
    with closing(connect()) as conn:
        try:
            result = receive(conn, json.loads(raw), os.environ["BB_TELEGRAM_ACCOUNT"])
        except (ValueError, TypeError, AttributeError):
            print("This control is unavailable for this message or editor.")
            return
        state = result["state"]
        if state == "approved":
            from .discovery_host import wake
            wake(conn)
        if state == "pending":
            message = f'Score {result["rating"]} recorded. Approval is still required.'
        elif state == "stale":
            message = f'Card is {result["request_state"]}. Request a new manual preview if needed.'
        elif state == "retry":
            message = "The dispatcher is busy. Tap again after reconciliation."
        else:
            message = f'{result["mode"].capitalize()} decision recorded: {state}.'
        print(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="inspect the last 10 attempts without sending")
    parser.add_argument("--resend-attempt")
    parser.add_argument("--observation-request")
    args = parser.parse_args()
    with closing(connect()) as conn:
        if args.status:
            rows = conn.execute("""SELECT t.id AS attempt,t.request_id,r.state AS request_state,t.message_id,
                t.created_at,t.retry_at FROM telegram_cards t JOIN review_requests r ON t.request_id=r.id
                ORDER BY t.rowid DESC LIMIT 10""")
            print(json.dumps([dict(row) for row in rows]))
        else:
            print(json.dumps(send_pending(conn, resend=args.resend_attempt, observation=args.observation_request)))

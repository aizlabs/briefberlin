"""Manual inbox, exact preview receipts and authenticated Telegram update handling."""

import hashlib
import json
import os
import re
import subprocess
import time
import uuid

from . import dispatch
from . import publication_host as host
from .db import transaction
from .publication_files import (
    POST,
    artifacts,
    changes,
    ensure_private,
    git,
    protect_text,
    source_urls,
)
from .review import identity
from .triage import shortlist

FINAL = ("discarded", "live")


def pending(conn):
    return conn.execute("SELECT * FROM publication_drafts WHERE state NOT IN ('discarded','live')").fetchone()


def source_data(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256_000:
        raise ValueError("a bounded private source file is required")
    data = path.read_bytes()
    if len(data.decode().split()) < 20:
        raise ValueError("source needs at least 20 words")
    return data


def candidates(conn, data, now):
    content = data.decode().strip()
    title = next(line.strip() for line in content.splitlines() if line.strip())[:300]
    rows = shortlist(conn, {"title": title, "evidence": content[:4000], "report_id": -1,
                            "freshness_epoch": now})
    urls = sorted(source_urls(content))
    linked = {}
    if urls:
        if len(urls) > 100:
            raise ValueError("too many URLs in manual source")
        linked = {r["id"]: dict(r) for r in conn.execute(f"""SELECT DISTINCT s.* FROM story_evidence e
            JOIN stories s ON s.id=e.story_id WHERE e.url IN ({','.join('?' for _ in urls)})
            AND s.status!='covered' ORDER BY s.id LIMIT 13""", urls)}
    choices = {**linked}
    for row in rows:
        choices.setdefault(row["id"], row)
    for row in choices.values():
        row["priority"] = (2 if row["id"] in linked else
                           int(row["title"].casefold().strip() == title.casefold()))
    return title, sorted(choices.values(), key=lambda m: -m["priority"])[:12]


def attach(conn, draft, title, story_id, version, now):
    if story_id is None:
        story_id = "story-" + uuid.uuid4().hex
        version = 1
        conn.execute("""INSERT INTO stories(id,title,first_seen,updated_at,expires_at)
            VALUES(?,?,?,?,?)""", (story_id, title, now, now, now + 2 * 86400))
    dispatch.attach_manual_tx(conn, story_id, version, draft, now)
    conn.execute("UPDATE publication_drafts SET story_id=?,version=?,state='ready' WHERE id=?",
                 (story_id, version, draft))


def stage(conn, root, path, *, importing=False):
    data = source_data(path)
    digest = hashlib.sha256(data).hexdigest()
    draft = uuid.uuid4().hex
    directory = host.area(root, "manual", draft)
    directory.mkdir(parents=True, mode=0o700)
    (directory / "evidence.source.txt").write_bytes(data)
    with transaction(conn):
        if pending(conn):
            raise ValueError("a manual draft is already waiting")
        now = int(time.time())
        title, matches = candidates(conn, data, now)
        conn.execute("""INSERT INTO publication_drafts(id,state,source_hash,created_at)
            VALUES(?,'matching',?,?)""", (draft, digest, now))
        linked = [m for m in matches if m["priority"] == 2]
        exact = [m for m in linked if m["title"].casefold().strip() == title.casefold()
                 and m["status"] in {"pending", "review"}]
        if len(linked) == len(exact) == 1:
            attach(conn, draft, title, exact[0]["id"], exact[0]["evidence_version"], now)
        elif not matches:
            attach(conn, draft, title, None, None, now)
        else:
            conn.executemany("INSERT INTO manual_match_candidates(draft_id,story_id,version,priority) VALUES(?,?,?,?)",
                             [(draft, m["id"], m["evidence_version"], m["priority"]) for m in matches])
        if importing:
            key = hashlib.sha256(str(path).encode() + b"\0" + data).hexdigest()
            conn.execute("INSERT OR REPLACE INTO settings VALUES('imported_legacy',?)", (key,))
    return pending(conn)


def match(conn, draft, selection, data):
    with transaction(conn):
        now = int(time.time())
        title, current = candidates(conn, data, now)
        fresh = {(m["id"], m["evidence_version"], m["priority"]) for m in current}
        saved = {tuple(r) for r in conn.execute("SELECT story_id,version,priority FROM manual_match_candidates WHERE draft_id=?",
                                                (draft["id"],))}
        if fresh != saved:
            conn.execute("DELETE FROM manual_match_candidates WHERE draft_id=?", (draft["id"],))
            conn.executemany("INSERT INTO manual_match_candidates(draft_id,story_id,version,priority) VALUES(?,?,?,?)",
                             [(draft["id"], *item) for item in fresh])
            return "MATCH: candidates changed; inspect bb status and decide again"
        if selection == "new":
            attach(conn, draft["id"], title, None, None, now)
        else:
            selected = next((v for s, v, _ in saved if s == selection), None)
            if selected is None:
                raise ValueError("choose a supplied story ID or new")
            attach(conn, draft["id"], title, selection, selected, now)
    return None


def status(conn):
    draft = pending(conn)
    if not draft:
        return "IDLE"
    if draft["state"] == "matching":
        rows = [dict(r) for r in conn.execute("""SELECT s.id,s.title,s.status,m.version FROM
            manual_match_candidates m JOIN stories s ON s.id=m.story_id WHERE m.draft_id=? ORDER BY m.priority DESC,s.id""", (draft["id"],))]
        return f"MATCH: choose bb match {draft['id']} STORY_ID or new. Candidates " + json.dumps(rows, ensure_ascii=False)
    work = dispatch.active(conn)
    external = work and work["manual_preview_id"] == draft["id"] and work["state"] in dispatch.EXTERNAL
    if (not external and draft["state"] in {"waiting", "approved"}
            and not dispatch.manual_story(conn, draft["id"], draft["version"], int(time.time()))):
        return f"STALE: draft {draft['id']} needs discard and fresh evidence before publication."
    return f"WAITING: {draft['state']} draft {draft['id']} for {draft['story_id']} (v{draft['version']})"


def generate(conn, root, draft):
    if draft["state"] == "matching":
        return status(conn)
    if draft["state"] not in {"ready", "generating", "failed"} or draft["tries"] >= 3:
        raise ValueError("draft already generated or its three preparation attempts are exhausted")
    directory = host.area(root, "manual", draft["id"])
    src = directory / "evidence.source.txt"
    if hashlib.sha256(source_data(src)).hexdigest() != draft["source_hash"]:
        raise ValueError("saved private source changed")
    conn.execute("UPDATE publication_drafts SET tries=tries+1,state='generating' WHERE id=?", (draft["id"],))
    tree = directory / "checkout"
    log = directory / f"generation-{draft['tries'] + 1}.log"
    try:
        if tree.exists():
            git(host.REPO, "worktree", "remove", "--force", str(tree))
        tree = host.checkout(directory)
        manifest, _ = host.generate(tree, draft["story_id"], src, log)
        ensure_private(tree, manifest, src.read_text())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        conn.execute("UPDATE publication_drafts SET state='failed' WHERE id=?", (draft["id"],))
        written = sum(bool(POST.fullmatch(p)) for p in changes(tree)) if tree.exists() else 0
        report = host.helper(tree, "bb_report.py", str(log), "1", str(written)) if log.exists() else str(exc)
        # Keep the full report on the host if provider diagnostics quote private input.
        report = report.replace(str(directory), "[private draft]")
        try:
            protect_text(report, src.read_text())
        except ValueError:
            report = "Generation failed. The detailed diagnostic contains private evidence and is retained on the host."
        buttons = [("Retry", "bb-generate"), ("Cancel", "bb-cancel")]
        host.telegram(report + "\nSource retained. Retry or cancel.", buttons)
        raise ValueError(report + f"\nFAILED: private source retained at draft {draft['id']}") from exc
    conn.execute("UPDATE publication_drafts SET state='waiting' WHERE id=?", (draft["id"],))
    scores = [line[:500] for line in log.read_text(errors="replace").splitlines()
              if line.startswith("Generated ") or "TOTAL" in line]
    return "\n".join([*scores[-6:], "READY: illustrate and preview before publishing."])


def preview(conn, root, draft):
    if draft["state"] != "waiting":
        raise ValueError("only a generated unapproved draft can be previewed")
    tree = host.area(root, "manual", draft["id"]) / "checkout"
    manifest, posts = artifacts(tree, draft["story_id"])
    ensure_private(tree, manifest, (tree.parent / "evidence.source.txt").read_text())
    token = uuid.uuid4().hex
    # A crash after delivery but before storing the receipt requires a fresh preview.
    conn.execute("UPDATE publication_drafts SET display_id=NULL,message_id=NULL,snapshot=NULL WHERE id=?", (draft["id"],))
    host.helper(tree, "bb_preview.py", *posts.values())
    sent = host.telegram("Publish these two articles to briefberlin.de? Tap a button or reply directly to this message with publish or discard.",
                         [("Publish", "bb-publish:" + token), ("Discard", "bb-discard:" + token)])
    if not sent or not re.fullmatch(r"SENT [0-9]+", sent):
        raise ValueError("preview controls need a confirmed delivery before approval")
    route = telegram_route()
    conn.execute("""UPDATE publication_drafts SET display_id=?,message_id=?,route=?,snapshot=?
        WHERE id=?""", (token, sent.split()[1], route, json.dumps(manifest, sort_keys=True), draft["id"]))
    return "PREVIEW SENT: both articles and Publish/Discard controls delivered."


def telegram_route():
    chat = host.telegram_target().read_text().strip()
    account = os.environ.get("BB_TELEGRAM_ACCOUNT")
    if not account or not chat:
        raise ValueError("configure the authenticated Telegram account and recipient")
    return json.dumps(["telegram", account, chat])


def receive_update(conn, update, account):
    """Trusted Telegram adapter ONLY, after authenticating delivery to this bot account.

    The scheduled/model-facing commands cannot create approval records. Typed messages
    must reply directly to the successfully delivered control message.
    """
    event = update.get("update_id")
    callback = update.get("callback_query")
    message = callback.get("message", {}) if callback else update.get("message", {})
    sender = (callback or message).get("from", {})
    if (type(event) is not int or type(sender.get("id")) is not int or sender.get("is_bot")
            or message.get("forward_origin") or message.get("via_bot") or message.get("sender_chat")):
        raise ValueError("invalid or relayed editor event")
    chat = str(message.get("chat", {}).get("id"))
    metadata = {"transport": "telegram", "account": account, "conversation": chat, "sender": str(sender["id"])}
    actor = identity(metadata)
    if actor not in dispatch.Policy.load().editor_allowlist:
        raise ValueError("editor not allowlisted")
    route = json.dumps(["telegram", account, chat])
    action = (callback.get("data", "") if callback else message.get("text", "").strip().lower())
    event_key = json.dumps([account, event])
    update_hash = hashlib.sha256(json.dumps(update, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with transaction(conn):
        prior = conn.execute("SELECT * FROM manual_actions WHERE event_key=?", (event_key,)).fetchone()
        if prior:
            if actor != prior["actor"] or update_hash != prior["update_hash"]:
                raise ValueError("changed editor event replay")
            return {"state": "recorded", "draft": prior["draft_id"], "verb": prior["verb"]}
        draft = pending(conn)
        if not draft or not draft["display_id"] or draft["state"] not in {"waiting", "approved"} or route != draft["route"]:
            raise ValueError("no current delivered preview for this route")
        mid = message.get("message_id")
        if type(mid) is not int:
            raise ValueError("Telegram message identity required")
        if callback:
            verb = next((v for v in ("publish", "discard") if action == f"bb-{v}:{draft['display_id']}"), None)
            if mid != int(draft["message_id"]):
                raise ValueError("stale preview control")
        else:
            verb = action
            if mid <= int(draft["message_id"]):
                raise ValueError("message predates current preview")
            reply = message.get("reply_to_message", {})
            if reply.get("message_id") != int(draft["message_id"]) or str(reply.get("chat", {}).get("id")) != chat:
                raise ValueError("reply directly to the current Publish/Discard message")
        if verb not in {"publish", "discard"}:
            raise ValueError("explicit publish or discard required")
        if verb == "publish" and not dispatch.manual_story(conn, draft["id"], draft["version"], int(time.time())):
            raise ValueError("draft evidence expired or changed; discard and prepare a fresh preview")
        if draft["state"] == "approved":
            if verb == "publish":
                conn.execute("INSERT INTO manual_actions(event_key,actor,display_id,verb,draft_id,update_hash) VALUES(?,?,?,?,?,?)",
                             (event_key, actor, draft["display_id"], verb, draft["id"], update_hash))
                return {"state": "approved", "draft": draft["id"], "verb": verb}
            active = dispatch.active(conn)
            if active and active["manual_preview_id"] == draft["id"] and active["state"] in dispatch.EXTERNAL:
                raise ValueError("reconcile outstanding publication before discarding")
            if active and active["manual_preview_id"] == draft["id"]:
                dispatch.transition(conn, active["id"], "superseded", "editor withdrew approval", int(time.time()))
            conn.execute("DELETE FROM manual_previews WHERE preview_id=?", (draft["id"],))
        conn.execute("INSERT INTO manual_actions(event_key,actor,display_id,verb,draft_id,update_hash) VALUES(?,?,?,?,?,?)",
                     (event_key, actor, draft["display_id"], verb, draft["id"], update_hash))
        state = "approved" if verb == "publish" else "withdraw"
        conn.execute("UPDATE publication_drafts SET state=?,approved_event=? WHERE id=?", (state, event_key, draft["id"]))
        return {"state": state, "draft": draft["id"], "verb": verb}

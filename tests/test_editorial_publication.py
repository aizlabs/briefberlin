"""Host-only acceptance. Real local Git objects, mocked transport, Pages and generation."""

import json
import subprocess
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.editorial import dispatch
from scripts.editorial import manual_drafts as drafts
from scripts.editorial import publication_files as files
from scripts.editorial import publication_host as host
from scripts.editorial import publication_verify as verification
from scripts.editorial import publication_worker as worker
from scripts.editorial.db import connect
from tests.test_editorial_dispatch import P, seed, story


@pytest.fixture(autouse=True)
def isolate_host_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BB_NOTIFY", "0")
    monkeypatch.setenv("BB_STATE", str(tmp_path / ".bb-pending"))
    monkeypatch.delenv("BRIEFBERLIN_EDITORIAL_POLICY", raising=False)


@pytest.fixture
def db(tmp_path):
    with closing(connect(tmp_path / "private/state.db")) as conn:
        seed(conn, now=int(time.time()))
        yield conn


@pytest.fixture
def tree(tmp_path):
    path = tmp_path / "tree"
    path.mkdir()
    for command in (["init", "-b", "main"], ["config", "user.name", "Host Test"],
                    ["config", "user.email", "host@example.invalid"], ["commit", "--allow-empty", "-m", "initial"]):
        files.git(path, *command)
    return path


def write(tree, path, text):
    dest = tree / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    return path


def edition(tree, level, *, story_id="story-one", translated=False):
    ref = "113000-change-" + level.lower()
    canon = "/articles/" + ref + "/"
    translations = f"translations:\n  de: {canon}\n  en: {canon}en/\n" if translated else ""
    common = f"date: 2026-01-01 11:30:00+01:00\nlevel: {level}\n{translations}"
    post = write(tree, "output/_posts/2026-01-01-" + ref + ".md",
                 "---\n" + common + f"title: Berlin change\nstory: {story_id}\n---\nText\n")
    if translated:
        write(tree, "output/_translations/" + ref + "/en.md", "---\n" + common + f"ref: {ref}\nlang: en\n---\nText\n")
    return post


def test_partial_wrong_and_unrelated_files_refused(tree):
    edition(tree, "A2")
    with pytest.raises(ValueError, match="one A2"):
        files.artifacts(tree, "story-one")
    path = edition(tree, "B1", story_id="story-two")
    with pytest.raises(ValueError, match="wrong story"):
        files.artifacts(tree, "story-one")
    (tree / path).unlink()
    edition(tree, "B1")
    write(tree, "output/_data/story_illustrations/other.yml", "visuals: []")
    with pytest.raises(ValueError, match="unexpected"):
        files.artifacts(tree, "story-one")


def test_midnight_restamp_preserves_urls_and_audio(tree):
    a2 = edition(tree, "A2", translated=True)
    edition(tree, "B1")
    text = (tree / a2).read_text().replace("story:", "audio: {url: https://media.briefberlin.de/old.mp3}\nstory:")
    (tree / a2).write_text(text)
    original, posts = files.artifacts(tree, "story-one")
    when = datetime(2026, 11, 26, 0, 1, tzinfo=ZoneInfo("Europe/Berlin"))
    files.restamp(tree, original, posts, when)
    manifest, new_posts = files.artifacts(tree, "story-one")
    assert manifest["editions"] == original["editions"]
    assert all(Path(path).name.startswith("2026-11-26") for path in new_posts.values())
    for path in manifest["files"]:
        assert files.front((tree / path).read_bytes())["date"] == when
    assert "https://media.briefberlin.de/old.mp3" in (tree / new_posts["A2"]).read_text()


def test_exact_match_suppresses_only_matching_automatic_story(db, tmp_path):
    now = int(time.time())
    story(db, "Housing", 10, now=now)
    story(db, "Trams", 9, now=now)
    requested = dispatch.tick(db)
    assert requested["story_id"] == "Housing"
    source = tmp_path / "input.source.txt"
    source.write_text("Housing\nhttps://example.org/Housing.\n" + "Housing detail " * 20)
    draft = drafts.stage(db, host.state_dir(db), source)
    assert (draft["story_id"], draft["version"]) == ("Housing", 1)
    assert dispatch.claim(db, work_id=requested["work_id"], owner="stale")["state"] == "unavailable"
    assert dispatch.tick(db)["story_id"] == "Trams"


def test_ambiguous_matching_requires_concrete_decision(db, tmp_path):
    story(db, "Housing", 10, now=int(time.time()))
    source = tmp_path / "input.source.txt"
    source.write_text("Housing expansion\n" + "Housing detail " * 20)
    draft = drafts.stage(db, host.state_dir(db), source)
    assert draft["state"] == "matching"
    assert dispatch.tick(db)["story_id"] == "Housing"
    with pytest.raises(ValueError, match="supplied story ID"):
        drafts.match(db, draft, "bogus", source.read_bytes())
    drafts.match(db, draft, "Housing", source.read_bytes())
    assert drafts.pending(db)["story_id"] == "Housing"


def displayed(db, monkeypatch):
    monkeypatch.setattr(dispatch.Policy, "load", classmethod(lambda cls: P))
    db.execute("INSERT INTO stories(id,title,first_seen,updated_at) VALUES('manual','Story',1,1)")
    dispatch.attach_manual_preview(db, story_id="manual", version=1, preview_id="draft")
    db.execute("""INSERT INTO publication_drafts(id,state,source_hash,created_at,story_id,version,
        display_id,route,message_id,snapshot) VALUES('draft','waiting','digest',1,'manual',1,'card',?,'10','{}')""",
               (json.dumps(["telegram", "desk", "-123"]),))


def tap(event=4, card="card", mid=10):
    return {"update_id": event, "callback_query": {"from": {"id": 456}, "data": "bb-publish:" + card,
                                                    "message": {"message_id": mid, "chat": {"id": -123}}}}


def test_duplicate_approval_and_old_typed_decisions(db, monkeypatch):
    displayed(db, monkeypatch)
    with pytest.raises(ValueError, match="predates"):
        drafts.receive_update(db, {"update_id": 3, "message": {"message_id": 8, "text": "publish",
                                    "chat": {"id": -123}, "from": {"id": 456}}}, "desk")
    with pytest.raises(ValueError):
        drafts.receive_update(db, tap(card="old"), "desk")
    with pytest.raises(ValueError):
        drafts.receive_update(db, tap(), "different")
    assert drafts.receive_update(db, tap(), "desk")["state"] == "approved"
    assert drafts.receive_update(db, tap(), "desk")["state"] == "recorded"
    assert db.execute("SELECT count(*) FROM manual_actions").fetchone()[0] == 1
    reservation = dispatch.reserve_manual(db, preview_id="draft", version=1)
    assert dispatch.reserve_manual(db, preview_id="draft", version=1) == reservation
    db.execute("UPDATE stories SET evidence_version=2 WHERE id='manual'")
    assert dispatch.reserve_manual(db, preview_id="draft", version=1)["state"] == "stale"


def test_legacy_import_keeps_original_checkout_and_source(db, tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    monkeypatch.setattr(host, "REPO", repo)
    source = repo / "private-input/20261126-091500.source.txt"
    write(repo, str(source.relative_to(repo)), "Unique\n" + "story evidence " * 20)
    dirty = write(repo, "output/_posts/unfinished.md", "still waiting")
    pointer = tmp_path / ".bb-pending"
    pointer.write_text(str(source))
    monkeypatch.setenv("BB_STATE", str(pointer))
    with pytest.raises(ValueError, match="legacy preview"):
        host.check_legacy(db)
    draft = drafts.stage(db, host.state_dir(db), host.legacy(), importing=True)
    host.check_legacy(db)
    saved = host.area(host.state_dir(db), "manual", draft["id"]) / "evidence.source.txt"
    assert saved.read_bytes() == source.read_bytes()
    assert (repo / dirty).read_text() == "still waiting"
    assert pointer.read_text() == str(source)
    pointer.write_text(str(tmp_path / "different-source.txt"))
    with pytest.raises(ValueError):
        host.legacy()


def test_lost_push_receipt_and_later_deployment(db, tree, tmp_path, monkeypatch):
    now = int(time.time())
    story(db, "story-one", 10, now=now)
    work = dispatch.tick(db)["work_id"]
    monkeypatch.setenv("BB_STATE", str(tmp_path / ".bb-pending"))
    monkeypatch.setattr(host, "REPO", tree)
    base = files.git(tree, "rev-parse", "HEAD").decode().strip()
    tip = [base]
    monkeypatch.setattr(host, "fetch", lambda: tip[0])

    def prepare(*_):
        edition(tree, "A2")
        edition(tree, "B1")
        return tree, "Evidence", []

    monkeypatch.setattr(worker, "prepare", prepare)
    pushes = []

    def lost(tree, *args, **kw):
        if args[0] == "push":
            pushes.append(args[-1])
            raise subprocess.TimeoutExpired("git push", 1)
        return files.git(tree, *args, **kw)

    monkeypatch.setattr(worker, "git", lost)
    root = host.state_dir(db)
    assert worker.send_work(db, root, work)["state"] == "external-uncertain"
    status = dispatch.status(db)
    expected = status["expected_commit"]
    assert len(pushes) == 1
    assert worker.send_work(db, root, work)["state"] == "unavailable"
    monkeypatch.setattr(verification, "public", lambda path: base)
    assert worker.recover(db, root)["state"] == "external-uncertain"
    files.git(tree, "commit", "--allow-empty", "-m", "later deploy")
    tip[0] = files.git(tree, "rev-parse", "HEAD").decode().strip()

    def page(path):
        if path.endswith(".txt"):
            return tip[0]
        level = next(k for k, p in status["manifest"]["editions"].items() if p == path)
        return (f'<link rel="canonical" href="{verification.SITE}{path}">'
                f'<article data-briefberlin-story="story-one" data-briefberlin-level="{level}">')

    monkeypatch.setattr(verification, "public", page)
    monkeypatch.setattr(verification, "api", lambda p: ([{"state": "success"}] if "statuses" in p else
                                                        [{"sha": tip[0], "id": 1, "environment": "github-pages"}]))
    assert worker.recover(db, root)["state"] == "live"
    assert worker.recover(db, root)["state"] == "idle"
    assert db.execute("SELECT count(*) FROM publication_keys WHERE publication_key=?", (expected,)).fetchone()[0] == 1
    assert len(pushes) == 1


def test_partial_generation_retains_private_source_for_bounded_retry(db, tmp_path, tree, monkeypatch):
    source = tmp_path / "retry.source.txt"
    source.write_text("Distinct\n" + "private input body " * 20)
    root = host.state_dir(db)
    draft = drafts.stage(db, root, source)
    monkeypatch.setattr(host, "checkout", lambda directory: tree)
    monkeypatch.setattr(host, "telegram", lambda *args: None)

    def partial(_tree, story_id, _source, _log, heartbeat=None):
        edition(_tree, "A2", story_id=story_id)
        return files.artifacts(_tree, story_id)

    monkeypatch.setattr(host, "generate", partial)
    for attempt in range(1, 4):
        with pytest.raises(ValueError, match="retained"):
            drafts.generate(db, root, drafts.pending(db))
        assert drafts.pending(db)["tries"] == attempt
        assert (host.area(root, "manual", draft["id"]) / "evidence.source.txt").read_bytes() == source.read_bytes()
    with pytest.raises(ValueError, match="exhausted"):
        drafts.generate(db, root, drafts.pending(db))


def test_changed_preview_bytes_never_copied(db, tree, tmp_path, monkeypatch):
    displayed(db, monkeypatch)
    root = host.state_dir(db)
    # Build a normal UUID-bound draft and its exact approved snapshot.
    db.execute("DELETE FROM manual_previews")
    db.execute("DELETE FROM publication_drafts")
    private = tmp_path / "private.source.txt"
    private.write_text("Unique\n" + "private input body " * 20)
    draft = drafts.stage(db, root, private)
    directory = host.area(root, "manual", draft["id"])
    checked = directory / "checkout"
    tree.rename(checked)
    a2 = edition(checked, "A2", story_id=draft["story_id"])
    edition(checked, "B1", story_id=draft["story_id"])
    manifest, _ = files.artifacts(checked, draft["story_id"])
    db.execute("""UPDATE publication_drafts SET state='waiting',display_id='card',message_id='10',
        route=?,snapshot=? WHERE id=?""", (json.dumps(["telegram", "desk", "-123"]), json.dumps(manifest), draft["id"]))
    drafts.receive_update(db, tap(), "desk")
    (checked / a2).write_text((checked / a2).read_text() + "altered")
    with pytest.raises(ValueError, match="changed after preview"):
        worker.copy_approved(db, root, {"preview_id": draft["id"], "story_id": draft["story_id"],
                                        "version": 1}, tmp_path / "new")


def test_story_id_generator_option_and_configured_main_routing(tmp_path, monkeypatch):
    from scripts import manual_pipeline, publish_and_push
    from scripts.editorial import publication_cli

    args = manual_pipeline.parse_args(["--story-id", "story-123", "private-input/paste.txt"])
    assert args.story_id == "story-123"
    monkeypatch.setenv("BRIEFBERLIN_EDITORIAL_DB", str(tmp_path / "state.db"))
    calls = []
    monkeypatch.setattr(publication_cli, "main", lambda args: calls.append(args) or 0)
    assert publish_and_push.main([str(tmp_path / "story.source.txt")]) == 0
    assert calls == [["manual", "stage", str(tmp_path / "story.source.txt")]]


def test_repeated_live_headline_can_choose_new(db, tmp_path):
    source = tmp_path / "regular.source.txt"
    source.write_text("Past\n" + "different current local development " * 9)
    draft = drafts.stage(db, host.state_dir(db), source)
    assert draft["state"] == "matching"
    drafts.match(db, draft, "new", source.read_bytes())
    assert drafts.pending(db)["story_id"] != "ledger"


def test_material_evidence_after_manual_start_and_discard(db, tmp_path):
    from scripts.editorial import triage
    from scripts.editorial.publication_cli import manual
    from tests.test_editorial_triage import claim, event, ingest, submit

    root = host.state_dir(db)
    source = tmp_path / "housing.source.txt"
    source.write_text("Spandau housing restart\n" + "new independent local detail " * 8)
    draft = drafts.stage(db, root, source)
    ingest(db, 1)
    packet = claim(db)
    submit(db, packet, event(packet, relationship="same", candidate_id=draft["story_id"]))
    assert dispatch.reserve_manual(db, preview_id=draft["id"], version=1)["state"] == "stale"
    manual(db, root, "cancel", [])
    row = db.execute("SELECT status,evidence_version FROM stories WHERE id=?", (draft["story_id"],)).fetchone()
    assert tuple(row) == ("pending", 2)
    ingest(db, 2)
    following = triage.claim(db, owner="next", now=packet["evaluation_epoch"] + 20)
    assert draft["story_id"] in [c["id"] for c in following["candidates"]]


def test_typed_reply_must_address_exact_delivery(db, monkeypatch):
    displayed(db, monkeypatch)
    msg = {"message_id": 30, "text": "publish", "chat": {"id": -123}, "from": {"id": 456}}
    for parent in ({}, {"message_id": 9, "chat": {"id": -123}}, {"message_id": 10, "chat": {"id": -99}}):
        with pytest.raises(ValueError, match="reply directly"):
            drafts.receive_update(db, {"update_id": 5, "message": {**msg, "reply_to_message": parent}}, "desk")
    update = {"update_id": 5, "message": {**msg, "reply_to_message": {"message_id": 10, "chat": {"id": -123}}}}
    assert drafts.receive_update(db, update, "desk")["state"] == "approved"
    update["message"]["reply_to_message"]["message_id"] = 9
    with pytest.raises(ValueError, match="changed editor event"):
        drafts.receive_update(db, update, "desk")


@pytest.mark.parametrize("column", ["expires_at", "deadline"])
def test_expiry_during_preparation_fences_manual_and_restart(db, monkeypatch, column):
    displayed(db, monkeypatch)
    now = int(time.time())
    db.execute(f"UPDATE stories SET {column}=? WHERE id='manual'", (now + 10,))
    drafts.receive_update(db, tap(), "desk")
    reservation = dispatch.reserve_manual(db, preview_id="draft", version=1, now=now)
    work = dispatch.claim(db, work_id=reservation["work_id"], owner="host", now=now)
    assert dispatch.refresh(db, token=work["token"], now=now + 10)["state"] == "superseded"
    assert dispatch.reserve_manual(db, preview_id="draft", version=1, now=now + 11)["state"] == "stale"


def test_existing_main_story_with_other_slug_refused(tree, monkeypatch):
    old = write(tree, "output/_posts/2025-12-30-old-slug.md", "---\nstory: story-one\n---\nAn earlier edition\n")
    files.git(tree, "add", "--", old)
    files.git(tree, "commit", "-m", "older story")
    tip = files.git(tree, "rev-parse", "HEAD").decode().strip()
    monkeypatch.setattr(host, "fetch", lambda: tip)
    edition(tree, "A2")
    edition(tree, "B1")
    with pytest.raises(ValueError, match="identifier already present"):
        worker.commit_story(tree, "story-one", "private")


def test_private_source_checks_before_preview_or_media(tree, monkeypatch):
    source = "Quelle (https://private.example/source).\n" + " ".join(f"Fakt{i}" for i in range(20))
    post = edition(tree, "A2")
    edition(tree, "B1")
    manifest, _ = files.artifacts(tree, "story-one")
    with pytest.raises(ValueError, match="URL"):
        files.protect_text("Read https://private.example/source", source)
    files.protect_text("Fakt1 Fakt2 Fakt3 Fakt4", source)
    (tree / post).write_text((tree / post).read_text() + source.splitlines()[1].lower())
    with pytest.raises(ValueError, match="verbatim"):
        files.ensure_private(tree, manifest, source)
    monkeypatch.setattr(host, "child", lambda *a, **k: pytest.fail("media ran with unsafe input"))
    with pytest.raises(ValueError, match="verbatim"):
        worker.optional_media(tree, "story-one", source, [], tree / "log", lambda: None, 1)


def test_configured_host_rejects_alias_and_refspec_tricks_before_generation(monkeypatch):
    from scripts import publish_and_push

    monkeypatch.setenv("BRIEFBERLIN_EDITORIAL_DB", "configured")
    monkeypatch.setattr(publish_and_push, "run_command", lambda *a, **k: pytest.fail("unexpected subprocess"))
    for switches in (["--branch", "test:refs/heads/main"], ["--branch", "HEAD"],
                     ["--remote", "mirror", "--branch", "refs/heads/main"], ["--branch", "+main"]):
        assert publish_and_push.main(["source", *switches]) == 2


def test_installed_client_uses_only_scoped_socket(tmp_path, monkeypatch):
    import os
    import socket
    import sys
    import tempfile
    from threading import Thread

    client = Path(__file__).resolve().parents[1] / "openclaw/skills/briefberlin/scripts/bb"
    monkeypatch.setenv("BRIEFBERLIN_EDITORIAL_DB", str(tmp_path / "host.db"))
    monkeypatch.setenv("BB_INBOX", str(tmp_path / "inbox"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = inbox / "article.txt"
    source.write_text("only local private words")
    with tempfile.TemporaryDirectory(dir="/tmp") as short_dir, socket.socket(socket.AF_UNIX) as server:
        sock = str(Path(short_dir) / "bb.sock")
        server.bind(sock)
        server.listen()
        server.settimeout(10)
        monkeypatch.setenv("BB_MANUAL_SOCKET", sock)

        def accept():
            for _ in range(2):
                peer, _ = server.accept()
                with peer:
                    subprocess.run([sys.executable, "-m", "scripts.editorial.publication_rpc"], stdin=peer,
                                   stdout=peer, env=os.environ.copy(), timeout=15, check=True)

        thread = Thread(target=accept, daemon=True)
        thread.start()
        assert subprocess.check_output([sys.executable, client, "received", source], text=True).strip() == "RECEIVED: 4 words"
        denied = subprocess.run([sys.executable, client, "stage", "/etc/passwd"], capture_output=True, text=True)
        assert denied.returncode and "invalid scoped" in denied.stdout
        thread.join(timeout=15)
        assert not thread.is_alive()
        source.unlink()
        source.symlink_to(tmp_path / "host.db")
        denied = subprocess.run([sys.executable, client, "received", source], capture_output=True)
        assert denied.returncode
        denied = subprocess.run([sys.executable, client, "add-image", "story", "/etc/passwd", "caption"], capture_output=True)
        assert denied.returncode and b"media inbox" in denied.stderr


def test_webhook_validates_secret_records_then_forwards_original(db, monkeypatch):
    import http.client
    from http.server import ThreadingHTTPServer
    from threading import Thread

    from scripts.editorial import telegram_ingress

    displayed(db, monkeypatch)
    db_path = db.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setenv("BRIEFBERLIN_EDITORIAL_DB", db_path)
    body = json.dumps(tap(), indent=2).encode()
    forwarded = []

    def upstream(raw, url, secret):
        with closing(connect(db_path)) as receiver:
            assert drafts.pending(receiver)["state"] == "approved"
        forwarded.append((raw, url, secret))
        return b'{}', "application/json"

    monkeypatch.setattr(telegram_ingress, "relay", upstream)
    with ThreadingHTTPServer(("127.0.0.1", 0), telegram_ingress.Handler) as server:
        server.secret, server.account = "verified-telegram-secret", "desk"
        server.upstream, server.upstream_secret = "http://127.0.0.1:9876/internal", "internal-only"
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def send(secret):
                with closing(http.client.HTTPConnection(*server.server_address, timeout=10)) as client:
                    client.request("POST", "/telegram", body, {telegram_ingress.HEADER: secret})
                    with client.getresponse() as response:
                        return response.status

            assert send("wrong") == 403
            assert not forwarded
            assert drafts.pending(db)["state"] == "waiting"
            assert send(server.secret) == send(server.secret) == 200
            assert forwarded == [(body, server.upstream, server.upstream_secret)] * 2
            assert db.execute("SELECT count(*) FROM manual_actions").fetchone()[0] == 1
        finally:
            server.shutdown()
            thread.join()


def test_real_preparation_checkout_helper_media_failure_and_local_push(db, tree, tmp_path, monkeypatch):
    import base64

    from scripts.editorial import publication_rpc

    bare = tmp_path / "remote.git"
    files.git(tree, "clone", "--bare", str(tree), str(bare))
    files.git(tree, "remote", "add", "origin", str(bare))
    monkeypatch.setattr(host, "REPO", tree)
    monkeypatch.setenv("BB_TELEGRAM_ACCOUNT", "desk")
    monkeypatch.setenv("BB_TELEGRAM_TARGET", str(tmp_path / "recipient"))
    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    monkeypatch.setenv("BB_PROVIDER", "openai")
    monkeypatch.setenv("BB_AUDIO", "1")
    monkeypatch.setattr(dispatch.Policy, "load", classmethod(lambda cls: P))
    (tmp_path / "recipient").write_text("-123")
    preview = host.helpers() / "bb_preview.py"
    preview.parent.mkdir(parents=True)
    preview.write_text("from pathlib import Path\nimport sys\nassert all(Path(p).is_file() for p in sys.argv[1:])")
    sent = []

    def notify(text, buttons=()):
        sent.append((text, buttons))
        return "SENT 10"

    def child(checkout, args, log, **kwargs):
        if "scripts.post_audio" in args:
            (checkout / args[2]).write_text("partial optional narration edit")
            raise subprocess.TimeoutExpired("audio", 1)
        story_id = args[args.index("--story-id") + 1]
        assert Path(args[-1]).read_text().startswith("Pankow")
        edition(checkout, "A2", story_id=story_id)
        edition(checkout, "B1", story_id=story_id)
        log.write_text("Generated two editions\n")
        return 0

    monkeypatch.setattr(host, "child", child)
    monkeypatch.setattr(host, "telegram", notify)
    publication_rpc.handle(db, {"action": "generate", "content": base64.b64encode(
        b"Pankow\n" + b"independent input words " * 15).decode()})
    publication_rpc.handle(db, {"action": "preview"})
    token = drafts.pending(db)["display_id"]
    assert token and sent[-1][1][0][1].endswith(token)
    drafts.receive_update(db, tap(card=token), "desk")
    reply = publication_rpc.handle(db, {"action": "publish", "args": [token]})
    result = json.loads(reply["result"])
    assert result["state"] == "external-uncertain"
    assert set(result["media_unavailable"]) == {"A2 audio", "B1 audio"}
    status = dispatch.status(db)
    assert files.git(bare, "rev-parse", "refs/heads/main").decode().strip() == status["expected_commit"]
    files.verify_commit(tree, status["expected_commit"], status["manifest"], delta=True)


def test_configured_independent_branch_push_has_explicit_destination(monkeypatch):
    from scripts import publish_and_push

    commands = []

    def run(command, **kwargs):
        commands.append(command)
        stdout = ""
        if command[1] == "symbolic-ref":
            stdout = "refs/heads/test/preview\n"
        if command[:3] == ["git", "status", "--porcelain"] and len(command) > 3:
            stdout = "?? output/_posts/new-post.md\n"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setenv("BRIEFBERLIN_EDITORIAL_DB", "configured")
    monkeypatch.setattr(publish_and_push, "run_command", run)
    assert publish_and_push.main(["--branch", "test/preview", "paste.source.txt"]) == 0
    assert commands[-1] == ["git", "push", "origin", "refs/heads/test/preview:refs/heads/test/preview"]

"""Stage 6 host acceptance. Network and service activation require separate operator opt-in."""

import json
import os
import pwd
import shutil
import subprocess
import sys
import time
from contextlib import closing
from email.utils import formatdate
from pathlib import Path

import pytest

from openclaw import install_skills
from scripts.editorial import (
    backup,
    collection,
    discovery_host,
    dispatch,
    publication_host,
    review_telegram,
)
from scripts.editorial.archive import set_setting, setting
from scripts.editorial.db import connect
from scripts.editorial.http import Client
from tests.test_editorial_collection import registry, response, rss
from tests.test_editorial_dispatch import COMMIT, NOW, P, archive, push, seed, story
from tests.test_editorial_triage import event


@pytest.fixture
def host_db(tmp_path, monkeypatch):
    path = tmp_path / "state" / "editorial.sqlite3"
    key = tmp_path / "key"
    key.write_bytes(bytes(range(32)))
    key.chmod(0o600)
    target = tmp_path / "chat"
    target.write_text("-123")
    monkeypatch.setenv("BB_TRIAGE_MODEL", "test-provider/test-model")
    monkeypatch.setenv("BB_TELEGRAM_ACCOUNT", "desk")
    monkeypatch.setenv("BB_TELEGRAM_TARGET", str(target))
    monkeypatch.setenv("BRIEFBERLIN_REVIEW_KEY_FILE", str(key))
    monkeypatch.setenv("BB_STATE", str(tmp_path / "no-legacy"))
    monkeypatch.setattr(dispatch.Policy, "load", lambda: P)
    monkeypatch.setattr(time, "time", lambda: NOW)
    with closing(connect(path)) as conn:
        seed(conn, mode="observe")
        yield conn


def test_registry_poll_claim_decide_wake_observe(host_db, tmp_path, monkeypatch):
    db = host_db
    source = registry(tmp_path / "registry.json", ("city", "feed", "/feed", "city"))
    monkeypatch.setenv("BB_SOURCE_REGISTRY", str(source))
    def fetch(self, url, headers):
        return response(url, rss(date=formatdate(time.time(), usegmt=True)))
    monkeypatch.setattr(Client, "__call__", fetch)
    collection.set_paused(db, True)
    assert discovery_host.poll(db) == {"paused": True, "endpoints": []}
    collection.set_paused(db, False)
    discovery_host.poll(db)  # first poll is historical
    registry(source, ("city", "feed", "/feed", "city"), ("office", "feed", "/other", "office"))
    monkeypatch.setattr(time, "time", lambda: NOW + 400)
    monkeypatch.setattr(Client, "__call__", lambda self, url, headers: response(url, rss(
        text="Berlin approved 300 new student homes in Spandau.", guid="new", url="https://example.org/new",
        date=formatdate(time.time(), usegmt=True))))
    discovery_host.poll(db)
    assert db.execute("SELECT count(*) FROM sources WHERE present=1").fetchone()[0] == 2
    packet = discovery_host.handle(db, {"op": "claim", "owner": "scheduled"})
    assert packet["state"] == "claimed"
    request = {"op": "decide", "token": packet["token"], "decision": {"events": [event(packet, score=9)]}}
    done = discovery_host.handle(db, request)
    assert done["state"] == "done" and discovery_host.handle(db, request) == done
    assert db.execute("SELECT model FROM model_decisions").fetchone()[0] == "requested:test-provider/test-model"
    root = publication_host.state_dir(db)
    assert (root / "dispatch.wake").exists()
    def refresh(conn, root):
        archive(conn, int(time.time()))
        return {"ready": True}
    monkeypatch.setattr(publication_host, "refresh_archive", refresh)
    assert discovery_host.dispatch_cycle(db)["state"] == "would-publish"
    assert not (root / "dispatch.wake").exists()
    assert not dispatch.active(db)
    assert discovery_host.handle(db, {"op": "claim", "owner": "scheduled"})["state"] == "empty"


@pytest.mark.parametrize("bad", [None, {}, {"op": "publish"}, {"op": "claim", "owner": []},
                                {"op": "claim", "owner": "me", "now": 1},
                                {"op": "decide", "token": "a" * 32, "decision": {}}])
def test_scoped_operations_reject_unavailable_or_malformed_capabilities(host_db, bad):
    with pytest.raises(ValueError):
        discovery_host.handle(host_db, bad)


def test_absent_model_fails_before_claim(host_db, monkeypatch):
    monkeypatch.delenv("BB_TRIAGE_MODEL")
    with pytest.raises(ValueError, match="configure"):
        discovery_host.handle(host_db, {"op": "claim", "owner": "x"})
    monkeypatch.setenv("BB_TRIAGE_MODEL", "alias")
    with pytest.raises(ValueError, match="provider/model"):
        discovery_host.handle(host_db, {"op": "claim", "owner": "x"})


def update(token, *, event="101", message=37, chat=-123, sender=456):
    return {"update_id": 1000, "callback_query": {"id": event, "from": {"id": sender, "is_bot": False},
            "data": token, "message": {"message_id": message, "chat": {"id": chat}}}}


def test_launch_fences_story_and_version_through_recovery(host_db, monkeypatch):
    db = host_db
    story(db, "target", 9)
    def refresh(conn, root):
        archive(conn, NOW)
        return {"ready": True}
    monkeypatch.setattr(publication_host, "refresh_archive", refresh)
    sent = []
    def send(conn, root, work_id):
        claim = dispatch.claim(conn, work_id=work_id, owner="host-test")
        assert push(conn, claim)["push_once"]
        sent.append(claim["story_id"])
        return {"state": "push-authorized", "work_id": work_id}
    monkeypatch.setattr(discovery_host.publication_worker, "send_work", send)
    for changed in (("other", 1), ("target", 2)):
        with pytest.raises(ValueError, match="changed"):
            discovery_host.first_story(db, *changed)
        assert setting(db, "dispatch_mode") == "observe"
    result = discovery_host.first_story(db, "target", 1)
    story(db, "competitor", 10)
    assert discovery_host.first_story(db, "target", 1)["state"] == "recover-only"
    dispatch.reconcile(db, work_id=result["work_id"], commit=COMMIT, outcome="live", evidence="fixture")
    assert discovery_host.first_story(db, "target", 1)["state"] == "recover-only"
    assert dispatch.tick(db)["state"] == "blocked" and sent == ["target"]
    dispatch.configure(db, mode="observe")
    assert setting(db, "launch_target") is None


def test_launch_review_requires_fresh_live_approval_and_blocks_replacement(host_db, monkeypatch):
    db = host_db
    story(db, "review", 6)
    def refresh(conn, root):
        archive(conn, NOW)
        return {"ready": True}
    monkeypatch.setattr(publication_host, "refresh_archive", refresh)
    monkeypatch.setattr(review_telegram, "send_pending", lambda conn: {"state": "fixture"})
    observed = dispatch.tick(db)["card"]
    decision = discovery_host.first_story(db, "review", 1)
    assert decision["card"]["request_id"] != observed["request_id"] and not dispatch.active(db)
    story(db, "urgent", 10)
    assert discovery_host.first_story(db, "review", 1)["reason"] == "launch-target-changed"
    assert not dispatch.active(db)


def test_outbox_delivery_ambiguity_signed_callback_scope_and_replay(host_db):
    db = host_db
    dispatch.configure(db, mode="live")
    archive(db, NOW)
    story(db, "review-item", 5)
    card = dispatch.tick(db)["card"]
    sent = []
    def timeout(body):
        sent.append(body)
        raise OSError("response lost")
    with pytest.raises(OSError):
        review_telegram.send_pending(db, send=timeout)
    pending = review_telegram.send_pending(db, send=timeout)
    assert pending["state"] == "ambiguous" and len(sent) == 1
    def success(body):
        sent.append(body)
        return "37"
    review_telegram.send_pending(db, resend=pending["attempt"], send=success)
    assert review_telegram.send_pending(db, send=timeout)["state"] == "sent"
    assert card["source_url"] in sent[-1]["text"] and card["berlin_impact"] in sent[-1]["text"]
    buttons = {b["text"]: b["callback_data"] for row in sent[-1]["reply_markup"]["inline_keyboard"] for b in row}
    assert len(buttons) == 21
    for params in ({"chat": 1}, {"message": 10}, {"sender": 123}):
        with pytest.raises(ValueError):
            review_telegram.receive(db, update(buttons["Approve"], **params), "desk")
    with pytest.raises(ValueError):
        review_telegram.receive(db, update(sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]), "desk")
    rating = update(buttons["Rate 9"])
    outcome = review_telegram.receive(db, rating, "desk")
    assert outcome["state"] == "pending" and review_telegram.receive(db, rating, "desk") == outcome
    approval = update(buttons["Approve"], event="102")
    assert review_telegram.receive(db, approval, "desk")["state"] == "approved"
    assert review_telegram.receive(db, approval, "desk")["state"] == "approved"
    assert db.execute("SELECT count(*) FROM review_receipts").fetchone()[0] == 2


def test_explicit_observation_delivery_and_mode_change(host_db):
    db = host_db
    story(db, "review-item", 5)
    card = dispatch.tick(db)["card"]
    assert review_telegram.send_pending(db, send=lambda body: pytest.fail())["sent"] is False
    messages = []
    def send(body):
        messages.append(body)
        return "37"
    review_telegram.send_pending(db, observation=card["request_id"], send=send)
    token = messages[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    dispatch.configure(db, mode="live")
    assert review_telegram.receive(db, update(token), "desk")["state"] == "stale"
    assert not dispatch.active(db)


def test_replacement_after_signing_cannot_apply_old_control(host_db, monkeypatch):
    db = host_db
    story(db, "review-item", 5)
    request = dispatch.tick(db)["card"]["request_id"]
    messages = []
    def send(body):
        messages.append(body)
        return str(36 + len(messages))
    first = review_telegram.send_pending(db, observation=request, send=send)
    original = review_telegram.review.signed_action
    def replace_before_transaction(conn, envelope, **kwargs):
        review_telegram.send_pending(db, observation=request, resend=first["attempt"], send=send)
        return original(conn, envelope, **kwargs)
    monkeypatch.setattr(review_telegram.review, "signed_action", replace_before_transaction)
    token = messages[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    with pytest.raises(ValueError, match="replaced"):
        review_telegram.receive(db, update(token), "desk")
    assert not db.execute("SELECT 1 FROM review_receipts").fetchone()


def test_rate_limit_persists_until_due_even_on_explicit_resend(host_db, monkeypatch):
    db = host_db
    dispatch.configure(db, mode="live")
    archive(db, NOW)
    story(db, "rate-limited", 6)
    dispatch.tick(db)
    monkeypatch.setenv("BB_TELEGRAM_BOT_TOKEN", "test")
    class Rejected:
        status_code = 429
        def json(self):
            return {"ok": False, "error_code": 429, "parameters": {"retry_after": 17}}
    monkeypatch.setattr(review_telegram.requests, "post", lambda *a, **kw: Rejected())
    result = review_telegram.send_pending(db, now=NOW)
    assert result["retry_at"] == NOW + 17
    with closing(connect(db.execute("PRAGMA database_list").fetchone()[2])) as reopened:
        assert review_telegram.send_pending(reopened, resend=result["attempt"], now=NOW + 16,
                                            send=lambda b: pytest.fail()) == result
        sent = review_telegram.send_pending(reopened, now=NOW + 17, send=lambda b: "42")
        assert sent["state"] == "sent" and sent["attempt"] != result["attempt"]


@pytest.mark.skipif(sys.platform != "linux", reason="production skill swap uses Linux renameat2")
def test_skill_install_reinstall_and_refuse_unmanaged(tmp_path, monkeypatch):
    source = tmp_path / "source"
    shutil.copytree(install_skills.SKILLS, source)
    monkeypatch.setattr(install_skills, "SKILLS", source)
    dest = tmp_path / "workspace/skills"
    assert install_skills.install(dest) == "installed"
    assert install_skills.install(dest) == "already installed"
    suite = dest / "briefberlin-suite"
    assert len(list(suite.glob("*/SKILL.md"))) == len(install_skills.CONTENTS)
    assert not (suite / "briefberlin/scripts/bb_tg.py").exists()
    (source / "briefberlin-review/SKILL.md").write_text("new")
    assert install_skills.install(dest) == "installed"
    current = suite / "briefberlin-review/SKILL.md"
    assert current.read_text() == "new"
    current.write_text("custom")
    with pytest.raises(ValueError, match="local changes"):
        install_skills.install(dest)
    assert current.read_text() == "custom"


def test_backup_linked_worktree_integrity_and_restore_fence(host_db, tmp_path, monkeypatch):
    repo = tmp_path / "clone"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-b", "main")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.org", "commit", "--allow-empty", "-m", "fixture")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.setattr(publication_host, "REPO", repo)
    root = publication_host.state_dir(host_db)
    tree = root / "manual" / ("f" * 32) / "checkout"
    tree.parent.mkdir(parents=True)
    git("worktree", "add", "--detach", str(tree), "HEAD")
    (tree.parent / "evidence.source.txt").write_text("private fixture")
    parent = tmp_path / "backups"
    parent.mkdir(mode=0o700)
    bundle = parent / "one"
    with publication_host.locked(root, "manual"), pytest.raises(BlockingIOError):
        backup.write_snapshot(host_db, bundle)
    backup.write_snapshot(host_db, bundle)
    record = backup.check(bundle)
    assert str(tree) in record["worktrees"] and setting(host_db, "restore_quarantine") is None
    with pytest.raises(ValueError):
        backup.stage_restore(bundle, root)
    stage = parent / "rehearsal"
    backup.stage_restore(bundle, stage)
    with pytest.raises(ValueError):
        backup.stage_restore(bundle, stage)
    with pytest.raises(ValueError, match="quarantined"):
        connect(stage / "editorial.sqlite3")
    with closing(connect(stage / "editorial.sqlite3", recovery=True)) as restored:
        assert setting(restored, "restore_quarantine") == "1"
        with pytest.raises(ValueError, match="original absolute paths"):
            backup.reconcile(restored, record, record["main"], "operator rehearsal in an isolated staging directory")
    assert (stage / root.name / tree.relative_to(root) / ".git").read_text() == (tree / ".git").read_text()
    (bundle / "publisher" / tree.parent.relative_to(root) / "evidence.source.txt").write_text("different")
    with pytest.raises(ValueError, match="manifest"):
        backup.check(bundle)


def test_restore_release_requires_verified_tip_and_leaves_pauses(host_db, tmp_path, monkeypatch):
    db = host_db
    repo = tmp_path / "repo"
    monkeypatch.setattr(publication_host, "REPO", repo)
    tip = "1" * 40
    monkeypatch.setattr(publication_host, "fetch", lambda: tip)
    monkeypatch.setattr(backup.publication_verify, "public", lambda path: tip)
    monkeypatch.setattr(backup, "git", lambda *args: b"")
    monkeypatch.setattr(publication_host, "refresh_archive", lambda conn, root: {"ready": True})
    path = db.execute("PRAGMA database_list").fetchone()[2]
    record = {"db": path, "repo": str(repo), "snapshot_id": "restore-id", "main": tip}
    set_setting(db, "restore_snapshot", "restore-id")
    set_setting(db, "restore_quarantine", 1)
    note = "incident fixture: compared intervening receipts with editor and main history"
    with pytest.raises(ValueError, match="deployed"):
        backup.reconcile(db, record, "2" * 40, note)
    assert setting(db, "restore_quarantine") == "1"
    result = backup.reconcile(db, record, tip, note)
    assert result["mode"] == "observe" and result["publish_paused"] and result["collection_paused"]
    assert setting(db, "restore_quarantine") is None


@pytest.mark.skipif(os.environ.get("BB_RUN_HOST_COLLECTOR_SMOKE") != "1", reason="explicit remote host smoke only")
def test_opt_in_host_collector_smoke():
    subprocess.run([sys.executable, "-B", "-m", "scripts.editorial.smoke"], check=True, timeout=1800)


def agent_templates():
    return json.loads((install_skills.SKILLS.parents[1] / "deploy/editorial/openclaw-agents.example.json").read_text())


def test_agent_workspace_templates():
    agents = agent_templates()
    assert {agent["id"] for agent in agents} == {"briefberlin-manual", "briefberlin-discovery"}
    for agent in agents:
        role = agent["id"].removeprefix("briefberlin-")
        sandbox = agent["sandbox"]
        docker = sandbox["docker"]
        assert sandbox["scope"] == "agent" and sandbox["mode"] == "all" and sandbox["workspaceAccess"] == "rw"
        assert docker["workdir"] == "/workspace" and docker["network"] == "none"
        assert docker["readOnlyRoot"] and docker["capDrop"] == ["ALL"]
        assert docker["binds"] == [agent["workspace"] + "/socket:/opt/briefberlin-socket:ro"]
        assert docker["env"]["BB_" + role.upper() + "_SOCKET"] == f"/opt/briefberlin-socket/{role}.sock"
        assert agent["tools"]["exec"]["host"] == "sandbox" and not agent["tools"]["elevated"]["enabled"]
        assert {"exec", "read", "write"} <= set(agent["tools"]["allow"])
        if role == "manual":
            assert docker["env"]["BB_INBOX"] == "/workspace/inbox"


@pytest.mark.skipif(os.environ.get("BB_TEST_INSTALLED_SOCKETS") != "1", reason="quiescent installed host only")
def test_installed_sockets_survive_restart():
    """Run as host admin on existing OpenClaw sandbox containers before turning schedules on."""
    agents = agent_templates()
    def command(*args):
        return subprocess.run(args, capture_output=True, text=True, check=True, timeout=60).stdout

    for pass_number in range(2):
        if pass_number:
            command("systemctl", "restart", "briefberlin-manual.socket", "briefberlin-discovery.socket")
        for agent in agents:
            role = agent["id"].removeprefix("briefberlin-")
            container = os.environ["BB_" + role.upper() + "_CONTAINER"]
            workspace = Path(agent["workspace"])
            socket_root = workspace / "socket"
            scratch = workspace / ("decisions" if role == "discovery" else "inbox")
            assert scratch.stat().st_mode & 0o7777 == 0o2750
            assert scratch.stat().st_gid == pwd.getpwuid(workspace.stat().st_uid).pw_gid
            assert socket_root.resolve() == socket_root and socket_root.stat().st_uid == 0
            assert socket_root.stat().st_mode & 0o022 == 0
            assert {p.name for p in socket_root.iterdir()} == {role + ".sock"}
            assert (socket_root / (role + ".sock")).is_socket()
            assert (socket_root / (role + ".sock")).stat().st_gid == socket_root.stat().st_gid
            mounts = json.loads(command("docker", "inspect", "--format", "{{json .Mounts}}", container))
            mounted = [m for m in mounts if m["Destination"] == "/opt/briefberlin-socket"]
            assert len(mounted) == 1 and not mounted[0]["RW"] and mounted[0]["Source"] == str(socket_root)
            allowed = {
                (str(workspace), "/workspace", True),
                (str(workspace / "skills"), "/workspace/skills", False),
                (str(socket_root), "/opt/briefberlin-socket", False),
            }
            if (workspace / ".agents/skills").is_dir():
                allowed.add((str(workspace / ".agents/skills"), "/workspace/.agents/skills", False))
            assert {(m["Source"], m["Destination"], m["RW"]) for m in mounts if m["Type"] != "tmpfs"} == allowed
            probe = """import json, os, socket, sys, tempfile
from pathlib import Path
role = sys.argv[1]
workspace = Path('/workspace')
scratch = workspace / ('decisions' if role == 'discovery' else 'inbox')
key = 'BB_' + role.upper() + '_SOCKET'
assert os.geteuid() == scratch.stat().st_uid
assert os.geteuid() not in (0, int(sys.argv[2]), workspace.stat().st_uid)
assert not os.access(workspace, os.W_OK)
for parent, dirs, files in os.walk(workspace):
    if Path(parent) == workspace:
        dirs.remove(scratch.name)
    for name in dirs + files:
        path = Path(parent, name)
        if path != workspace / 'socket' / (role + '.sock'):
            assert not path.is_symlink() and not os.access(path, os.W_OK), path
suite = workspace / 'skills' / 'briefberlin-suite'
for skill, files in json.loads(sys.argv[3]).items():
    for name in files:
        path = suite / skill / name
        assert path.is_file() and os.access(path, os.R_OK), path
        if name.startswith('scripts/'):
            assert os.access(path, os.X_OK), path
if role == 'manual':
    assert Path(os.environ['BB_INBOX']) == scratch
    assert os.access(scratch / 'media', os.W_OK)
with tempfile.NamedTemporaryFile(dir=scratch) as marker:
    os.fchmod(marker.fileno(), 0o640)
    assert os.fstat(marker.fileno()).st_gid == scratch.stat().st_gid
    marker.write(b'workspace fixture')
    marker.flush()
    assert Path(marker.name).read_bytes() == b'workspace fixture'
assert os.getegid() == os.stat('/opt/briefberlin-socket').st_gid
assert os.listdir('/opt/briefberlin-socket') == [role + '.sock']
assert not os.access('/opt/briefberlin-socket', os.W_OK)
with socket.socket(socket.AF_UNIX) as sock:
    sock.settimeout(30)
    sock.connect(os.environ[key])
    sock.sendall(b'{}\\n')
    sock.shutdown(socket.SHUT_WR)
    result = json.loads(sock.makefile('rb').readline())
    assert result == ({'ok': False, 'error': 'unsupported triage operation'} if role == 'discovery'
                      else {'ok': False, 'result': 'invalid scoped manual operation or arguments'})
"""
            command("docker", "exec", container, "python3", "-c", probe, role,
                    str(pwd.getpwnam("briefberlin").pw_uid), json.dumps(install_skills.CONTENTS))

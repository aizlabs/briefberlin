"""Private host workspace lifecycle and subprocess limits."""

import fcntl
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from dotenv import dotenv_values

from .db import ROOT
from .publication_files import artifacts, git

REPO = Path(os.environ.get("BB_REPO", ROOT)).resolve()
IDENTIFIER = re.compile(r"[a-f0-9]{32}")


def helpers():
    return REPO / "openclaw/skills/briefberlin/scripts"


def telegram_target():
    return Path(os.environ.get("BB_TELEGRAM_TARGET", "/opt/openclaw/work/.bb-telegram-target"))


def state_dir(conn):
    db = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    root = db.with_name(db.name + ".publisher")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.stat().st_mode & 0o077 or root.stat().st_uid != os.getuid():
        raise ValueError("publisher state needs an owner-only directory beside the private database")
    return root


@contextmanager
def locked(root, name, *, blocking=True):
    with (root / (name + ".lock")).open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield handle.fileno()


def legacy():
    pointer = Path(os.environ.get("BB_STATE", "/opt/openclaw/work/.bb-pending"))
    if not pointer.exists() and not pointer.is_symlink():
        return None
    if pointer.is_symlink() or not pointer.is_file() or pointer.stat().st_size > 4096:
        raise ValueError("inspect the invalid legacy pending pointer on the host")
    path = Path(pointer.read_text().strip())
    if (path.resolve() != path or path.parent != Path(os.environ.get("BB_LEGACY_REPO", REPO)).resolve() / "private-input"
            or not re.fullmatch(r"[0-9]{8}-[0-9]{6}\.source\.txt", path.name)
            or not path.is_file() or path.stat().st_size > 256_000):
        raise ValueError("legacy pending source needs operator inspection")
    return path


def check_legacy(conn):
    path = legacy()
    if path:
        marker = hashlib.sha256(str(path).encode() + b"\0" + path.read_bytes()).hexdigest()
        if not conn.execute("SELECT 1 FROM settings WHERE key='imported_legacy' AND value=?", (marker,)).fetchone():
            raise ValueError("legacy preview preserved; run bb legacy-import before starting the publisher")
        return marker
    return None


def area(root, kind, ident):
    if kind not in {"manual", "worker"} or not IDENTIFIER.fullmatch(ident):
        raise ValueError("invalid attempt identity")
    return root / kind / ident


def fetch():
    git(REPO, "fetch", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main")
    return git(REPO, "rev-parse", "refs/remotes/origin/main").decode().strip()


def cleanup(directory):
    tree = directory / "checkout"
    if tree.exists():
        git(REPO, "worktree", "remove", "--force", str(tree))
    if directory.exists():
        shutil.rmtree(directory)


def prune(root, kind, keep=()):
    """Caller holds the corresponding manual or sender lock."""
    parent = root / kind
    parent.mkdir(mode=0o700, exist_ok=True)
    for path in parent.iterdir():
        if IDENTIFIER.fullmatch(path.name) and path.name not in keep:
            cleanup(path)


def checkout(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    tree = directory / "checkout"
    git(REPO, "worktree", "add", "--detach", str(tree), fetch())
    return tree


def child_environment():
    # Installed service env takes precedence. Secrets never enter a worktree.
    values = {k: v for k, v in dotenv_values(REPO / ".env").items() if v is not None}
    return {**values, **os.environ, "AUDIO_ENABLED": "false", "AUDIO_UPLOAD_ENABLED": "false",
            "PYTHONDONTWRITEBYTECODE": "1"}


def child(tree, args, log, *, heartbeat=None, limit=1800):
    env = child_environment()
    env["PYTHONPATH"] = str(tree)
    with log.open("ab") as output:
        command = [sys.executable, *args]
        with subprocess.Popen(command, cwd=tree, env=env, stdout=output, stderr=subprocess.STDOUT) as proc:
            start = time.monotonic()
            try:
                while True:
                    try:
                        return proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        if time.monotonic() - start > limit or log.stat().st_size > 12_000_000:
                            raise ValueError("bounded preparation time or log size exceeded")
                        if heartbeat:
                            heartbeat()
            finally:
                if proc.poll() is None:
                    proc.kill()


def generate(tree, story, source, log, heartbeat=None):
    env = child_environment()
    provider = env.get("BB_PROVIDER", "anthropic")
    if not env.get("OPENAI_API_KEY") or (provider == "anthropic" and not env.get("ANTHROPIC_API_KEY")):
        raise ValueError("configure the generation provider credentials on the private service")
    code = child(tree, ["-m", "scripts.manual_pipeline", "--environment", "production", "--provider",
                        provider, "--story-id", story, "--level", "A2", "--level", "B1", str(source)],
                 log, heartbeat=heartbeat)
    if code:
        raise ValueError(f"generation failed (exit {code}); see private generation log")
    return artifacts(tree, story)


def helper(tree, filename, *args):
    env = child_environment()
    env["PYTHONPATH"] = str(tree)
    result = subprocess.run([sys.executable, str(helpers() / filename), *args], cwd=tree,
                            env=env, timeout=600, text=True, capture_output=True)
    if result.returncode:
        raise ValueError(result.stdout.strip() or f"{filename} failed")
    return result.stdout.strip()


def telegram(text, buttons=()):
    # Reuse the existing direct Telegram sender and return its actual receipt.
    if os.environ.get("BB_NOTIFY", "1") != "1":
        return None
    if not telegram_target().exists():
        return None
    args = [sys.executable, str(helpers() / "bb_tg.py")]
    for label, value in buttons:
        args.extend(["--button", label + "=" + value])
    result = subprocess.run([*args, text[:3800]], capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise ValueError("Telegram notification failed")
    return result.stdout.strip()


def refresh_archive(conn, root):
    from .archive import sync_archive

    # A detached fetched tree also allows recovery from a legacy dirty shared checkout.
    with locked(root, "archive"):
        directory = root / "archive"
        if directory.exists():
            cleanup(directory)
        try:
            tree = checkout(directory)
            return sync_archive(conn, output=tree / "output")
        finally:
            if directory.exists():
                cleanup(directory)

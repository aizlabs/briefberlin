#!/usr/bin/env python3
"""Install the client-only BriefBerlin skill group on a Linux OpenClaw host."""

import argparse
import ctypes
import fcntl
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

SKILLS = Path(__file__).resolve().parent / "skills"
CONTENTS = {
    "briefberlin": ("SKILL.md", "scripts/bb"),
    "briefberlin-illustrate": ("SKILL.md",),
    "briefberlin-triage": ("SKILL.md", "references/berlin-v1.md", "references/response-v1.md"),
    "briefberlin-review": ("SKILL.md",),
    "briefberlin-publisher": ("SKILL.md",),
    "briefberlin-discovery": ("SKILL.md", "scripts/bb-discovery"),
}
MANIFEST = ".briefberlin-install.json"


def inventory(root):
    files = {}
    for item in sorted(root.rglob("*")):
        mode = item.lstat().st_mode
        name = str(item.relative_to(root))
        if stat.S_ISDIR(mode):
            files[name] = ["dir", stat.S_IMODE(mode)]
        elif stat.S_ISREG(mode):
            if name != MANIFEST:
                files[name] = [hashlib.sha256(item.read_bytes()).hexdigest(), stat.S_IMODE(mode)]
        else:
            raise ValueError(f"unmanaged file type: {name}")
    return files


def install(skills):
    skills.mkdir(parents=True, exist_ok=True)
    dest = skills / "briefberlin-suite"
    with (skills.parent / ".briefberlin-install.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for name in CONTENTS:
            if os.path.lexists(skills / name):
                raise ValueError(f"preserve and move the unmanaged skill before installing: {skills / name}")
        old = None
        if os.path.lexists(dest):
            stamp = dest / MANIFEST
            if dest.is_symlink() or not stamp.is_file() or stamp.is_symlink():
                raise ValueError("existing skill group has no trusted installation manifest")
            old = inventory(dest)
            if json.loads(stamp.read_text()) != old:
                raise ValueError("installed group contains local changes; preserve them before upgrade")
        with tempfile.TemporaryDirectory(dir=skills.parent, prefix=".briefberlin-stage-") as tmp:
            stage = Path(tmp) / "group"
            stage.mkdir(mode=0o755)
            for skill, names in CONTENTS.items():
                for name in names:
                    target = stage / skill / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(SKILLS / skill / name, target)
                    target.chmod(0o755 if name.startswith("scripts/") else 0o644)
            for directory in [stage, *(p for p in stage.rglob("*") if p.is_dir())]:
                directory.chmod(0o755)
            manifest = inventory(stage)
            if manifest == old:
                return "already installed"
            (stage / MANIFEST).write_text(json.dumps(manifest, sort_keys=True))
            if old is None:
                stage.rename(dest)
            else:
                # Atomically swap two complete directories on Linux, including across process death.
                libc = ctypes.CDLL(None, use_errno=True)
                if libc.renameat2(-100, os.fsencode(stage), -100, os.fsencode(dest), 2):
                    raise OSError(ctypes.get_errno(), "cannot atomically exchange skill groups")
            return "installed"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills", type=Path, default=Path("/srv/openclaw-projects/briefberlin-manual/skills"))
    print(install(parser.parse_args().skills))

#!/bin/bash
# Copy this skill into OpenClaw's workspace, keeping the previous copy as *.prev.
set -eu
SRC=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
DEST=${BB_SKILL_DIR:-/opt/openclaw/.openclaw/workspace/skills/briefberlin}
[ "$(id -un)" = openclaw ] || { echo "Run as the openclaw user."; exit 2; }
mkdir -p "$DEST/scripts"
install_one() {
  local rel=$1 mode=$2
  [ -f "$DEST/$rel" ] && cp -p "$DEST/$rel" "$DEST/$rel.prev"
  install -m "$mode" "$SRC/$rel" "$DEST/$rel"
  echo "installed $rel"
}
install_one SKILL.md 644
for f in bb bb_setkey bb_tg.py bb_watch.sh; do install_one "scripts/$f" 700; done
for f in bb_preview.py bb_report.py; do install_one "scripts/$f" 600; done
bash -n "$DEST/scripts/bb" && echo "bb syntax ok"

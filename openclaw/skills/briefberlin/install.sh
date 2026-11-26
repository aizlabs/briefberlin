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
install_one scripts/bb 700
ILL_SRC="$SRC/../briefberlin-illustrate"
ILL_DEST="$(dirname "$DEST")/briefberlin-illustrate"
mkdir -p "$ILL_DEST"
[ -f "$ILL_DEST/SKILL.md" ] && cp -p "$ILL_DEST/SKILL.md" "$ILL_DEST/SKILL.md.prev"
install -m 644 "$ILL_SRC/SKILL.md" "$ILL_DEST/SKILL.md" && echo "installed briefberlin-illustrate/SKILL.md"
echo "Installed the scoped manual client. Configure the host socket before use."

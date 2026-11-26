#!/bin/sh
set -eu
base=$(dirname "$(realpath "$0")")
exec python3 "$base/../../install_skills.py" --skills "$(dirname "${BB_SKILL_DIR:-/srv/openclaw-projects/briefberlin-manual/skills/briefberlin}")" "$@"

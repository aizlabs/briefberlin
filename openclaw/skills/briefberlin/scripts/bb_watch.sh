#!/bin/bash
# Waits for the GitHub Pages deploy of one commit, checks the pages load, and tells the user on Telegram.
# Usage: bb_watch.sh <commit-sha> <url>...   BB_PREFIX adds a label (used for tests).
sha=$1; shift
export HOME=/opt/openclaw
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}
TARGET=/opt/openclaw/work/.bb-telegram-target
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
send() {
  python3 "$HERE/bb_tg.py" "${BB_PREFIX:-}$1" >/dev/null 2>&1
}
links=$(printf '%s\n' "$@")
api="https://api.github.com/repos/aizlabs/briefberlin/actions/runs?head_sha=$sha"
status=""; conclusion=""; run=""
end=$((SECONDS + 1200))
while [ $SECONDS -lt $end ]; do
  j=$(curl -s -m 20 -H 'User-Agent: bb-watch' -H 'Accept: application/vnd.github+json' "$api")
  status=$(echo "$j" | grep -m1 -oE '"status": *"[a-z_]+"' | sed -E 's/.*"([a-z_]+)"$/\1/')
  conclusion=$(echo "$j" | grep -m1 -oE '"conclusion": *("[a-z_]+"|null)' | sed -E 's/.*: *"?([a-z_]+)"?$/\1/')
  run=$(echo "$j" | grep -m1 -oE 'https://github.com/aizlabs/briefberlin/actions/runs/[0-9]+')
  [ "$status" = completed ] && break
  sleep 30
done

if [ "$status" != completed ]; then
  send "Deploy still not finished after 20 minutes for commit ${sha:0:7}.
${run:-https://github.com/aizlabs/briefberlin/actions}"
  exit 1
fi
if [ "$conclusion" != success ]; then
  send "Deploy FAILED for commit ${sha:0:7} (${conclusion:-unknown}). The articles are committed but not live.
Log: ${run:-https://github.com/aizlabs/briefberlin/actions}"
  exit 1
fi
for _ in 1 2 3 4 5 6; do
  bad=0
  for u in "$@"; do
    [ "$(curl -s -o /dev/null -m 20 -w '%{http_code}' -L "$u")" = 200 ] || bad=1
  done
  [ "$bad" = 0 ] && break
  sleep 30
done
if [ "$bad" = 0 ]; then
  send "Live on briefberlin.de:
$links"
else
  send "Deploy succeeded, but a page isn't loading yet. Try again in a few minutes:
$links"
fi

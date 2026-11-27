# BriefBerlin discovery operator handover

**Release status.** The starting main revision was `57c705f`. Stages 1–5 introduced the registry, collection, triage/archive, dispatcher/review and fenced publisher in commits `3a8d462`, `79f4b3e`, `3c33c3a`, `103a3c3` and `b68bf42`. Stage 6 connects those components to the installed OpenClaw host. The owner still has to merge the branch. The full merge SHA, installed OpenClaw version, host test outcomes, editor exercise, first verified deployment and activation time belong in the host's private release record. No host activation or real delivery took place during implementation.

| Shipped in this repository | Acceptance on the host |
|---|---|
| Versioned SQLite migrations and schema-v1 JSON inventory | Import 159 initial entries (151 audited and eight additions), inspect lookup resources, shared endpoints and disabled sources. |
| Feed, HTML listing, PDF index and changing-notice adapters | Check actual DNS/HTTP/proxy limits, dates, PDF tools, baselines and error coverage. |
| Versioned Berlin rubric, report matching, archive importer, ledger and editor feedback | Replay same event from different issuers, revised facts, syndicated copy, follow-up and held decisions with the installed model. Compare with held-out editorial judgments. |
| Five-minute dispatcher, 12-hour clock, scoped Telegram review | Exercise observation, empty/expired queues, competing candidates, response replay, decline, hold and rating-only versus approval. |
| Isolated manual/automatic publication, frozen manifest, push fencing and live verifier | Test the regular manual UX, provider access, media, Git, Pages, both canonical edition identities and lost push acknowledgments. |
| Six OpenClaw skills, Unix clients, units, backup and recovery tools | Verify discovery in the actual sandbox, group permissions, safe reinstall/restore, schedules and rollback. |

## What was exercised locally

The stage 2 disposable public-source collector smoke and its final-branch repeat each loaded 159 sources and sampled six endpoints across the four adapter families. Both reopened the database with 23 reports, 23 revisions and 27 sightings. The second poll added sightings to 21 prior revision ID/hash pairs and found two new reports, with no new revision on an existing report. The final-branch run finished with 25 reports, 25 revisions, 54 sightings and 33 source links, and reported `disposed=true`. Both runs observed HTTP 403 at the Council of the EU endpoint and no links at the LaGeSo document index. The final repeat includes the stage 3 observed-notice provenance change. Remaining endpoints and service integrations require host verification.

## Host layout and prerequisites

Use Linux with systemd sockets/timers/path units, local storage supporting SQLite and flock, Python 3.11+, uv, Git, gh, jq, Docker, OpenClaw and Poppler `pdftotext`. Provide disk for the private full clone, its detached worktrees, logs and a separate backup. The publisher needs DNS and HTTPS to listed public sources, provider services, Git/GitHub, Telegram and the live site. Configure SSH or a credential helper for a non-force push to origin/main, Git author name/email and `GH_TOKEN` or an authenticated gh credential for Pages deployments/statuses. The publication verifier expects aizlabs/briefberlin and briefberlin.de. Use the deployment workflow including the public commit marker.

* Trusted Unix service user/group `briefberlin` owns `/srv/briefberlin/repo`, `/var/lib/briefberlin` and its private publisher worktrees. Its DB is `/var/lib/briefberlin/editorial.sqlite3`. Root provisions `/etc/briefberlin/publisher.env` mode 0600. Use an ordinary full clone with its own local `.git` object database and only publisher-owned linked worktrees.
* Give each model a separate OpenClaw agent workspace under `/srv/openclaw-projects`. The manual and discovery socket units each listen in a root-owned `socket/` directory under their respective agent workspace. Each Docker sandbox also mounts its own socket directory read-only at `/opt/briefberlin-socket`. A directory bind follows socket replacement on systemd restart. The service clone, state, configuration, credentials, and other agent's socket are outside these mounts. The gateway is trusted and has a separate OS identity from both model shells.
* Use the per-agent settings and client environment in [openclaw-agents.example.json](../deploy/editorial/openclaw-agents.example.json). Merge the manual entry into the authorized editor's profile and bind its Telegram conversation to that agent. Put discovery in a dedicated gateway profile and keep Telegram disabled there. Supply the exact provider/model and map the container user to a non-root UID and the numeric GID of its socket group. Use Docker with agent scope and `workspaceAccess: "rw"`. This enables structured writes and mounts that agent's host workspace at `/workspace`. The trusted gateway owns the top directory and its bootstrap files. The model UID can write only its private `inbox/` (manual) or `decisions/` (discovery) in this workspace. OpenClaw mounts the existing `skills/` tree read-only. The root-owned socket directory is also protected through its workspace path. Reserve these dedicated workspaces for scoped client data. Store gateway state, credentials, repositories and backups elsewhere. Review effective inherited binds and tool policies in both profiles. The supplied settings use a non-root UID, drop all capabilities, disable networking and host execution, and keep the container root filesystem read-only. The sandbox image needs Python 3 and standard POSIX utilities. [OpenClaw sandboxing](https://docs.openclaw.ai/gateway/sandboxing)
* Configure `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` when using the default anthropic generator, and optional narration credentials `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` and AWS SDK credentials or a role for the audio bucket. See the repository's `.env.example` and publication guide for media settings. The scheduled OpenClaw model uses the gateway's own provider configuration.

### Install the owner-merged revision

Stop existing bb senders, deploy watchers, old cron jobs and legacy workflows. Preserve any pending draft, dirty working tree and outstanding push. Follow the legacy migration in [the publication guide](editorial-publication.md) before allowing a new sender. On a new host provision service identities and private directories as root. Adapt the two sandbox identities to the real host.

```sh
getent group briefberlin-client >/dev/null || sudo groupadd --system briefberlin-client
getent group briefberlin-triage >/dev/null || sudo groupadd --system briefberlin-triage
id briefberlin >/dev/null 2>&1 || sudo useradd --system --user-group --create-home --home-dir /srv/briefberlin briefberlin
sudo chmod 0700 /srv/briefberlin
sudo install -d -o briefberlin -g briefberlin -m 0700 /var/lib/briefberlin /var/backups/briefberlin
sudo install -d -m 0700 /etc/briefberlin
# GATEWAY_USER and TRIAGE_GATEWAY_USER are trusted gateway service accounts.
# Use distinct non-root model UIDs, separate from the publisher and both gateway accounts.
# Use their host-mapped IDs for ownership. Each gateway's primary group is private to that gateway.
PROJECTS=/srv/openclaw-projects
sudo install -d -o root -g root -m 0755 "$PROJECTS"
sudo install -d -o "$GATEWAY_USER" -g briefberlin-client -m 0750 "$PROJECTS/briefberlin-manual"
sudo install -d -o "$TRIAGE_GATEWAY_USER" -g briefberlin-triage -m 0750 "$PROJECTS/briefberlin-discovery"
sudo install -d -o root -g briefberlin-client -m 0750 "$PROJECTS/briefberlin-manual/socket"
sudo install -d -o root -g briefberlin-triage -m 0750 "$PROJECTS/briefberlin-discovery/socket"
sudo install -d -o root -g root -m 0755 "$PROJECTS/briefberlin-manual/skills" "$PROJECTS/briefberlin-discovery/skills"
sudo install -d -o "$TRIAGE_UID" -g "$(id -gn "$TRIAGE_GATEWAY_USER")" -m 2750 "$PROJECTS/briefberlin-discovery/decisions"
sudo install -d -o "$MANUAL_UID" -g "$(id -gn "$GATEWAY_USER")" -m 2750 "$PROJECTS/briefberlin-manual/inbox" "$PROJECTS/briefberlin-manual/inbox/media"
getent group briefberlin-client briefberlin-triage
```

The setgid scratch directories give new files the corresponding gateway's private group. The skills prepare their target files with mode 0640 so the host-side file-tool checks can read them before the sandbox writes. Keep the gateways' service umasks at 0022 or stricter so gateway-created workspace files cannot be modified by the model. For existing workspaces, move old writable content or credentials to a private backup and check existing ownership, ACLs and permissions before enabling sessions.

Use an error-stopping Bash shell (`set -euo pipefail`) for the following commands. Set `RELEASE` to the exact full SHA the owner has merged and `REMOTE` to the configured repository URL. Keep the release checkout detached. The publisher separately fetches the moving public main tip for article work. For a fresh host:

```sh
sudo -Hu briefberlin git clone "$REMOTE" /srv/briefberlin/repo
cd /srv/briefberlin/repo
sudo -Hu briefberlin git fetch origin main
sudo -Hu briefberlin git merge-base --is-ancestor "$RELEASE" origin/main
sudo -Hu briefberlin git switch --detach "$RELEASE"
sudo -Hu briefberlin git rev-parse HEAD
sudo -Hu briefberlin uv sync --frozen --extra dev
sudo install -m 0644 deploy/editorial/*.service deploy/editorial/*.socket deploy/editorial/*.timer deploy/editorial/*.path /etc/systemd/system/
sudo systemctl daemon-reload
POLICY=/var/lib/briefberlin/editorial_policy.yaml
if ! sudo test -e "$POLICY"; then
  sudo install -m 0600 -o briefberlin -g briefberlin config/editorial_policy.yaml "$POLICY"
fi
```

On upgrade preserve the existing private policy and its editor allowlist. Review new policy fields against the incoming template and merge those fields privately. Run setup in a root administration shell able to enter the private checkout. Configure the trusted environment values below. Add provider/transport credentials through the host's secret provisioning mechanism. Reuse an existing signing key on upgrade. To create one on a new host, run `sudo -Hu briefberlin sh -c 'umask 077; set -C; openssl rand 32 > /var/lib/briefberlin/review.key'`. The target file contains the numeric Telegram chat ID. Configure the private policy's `editor_allowlist` with the exact `telegram/desk/CHAT_ID/SENDER_ID` identity. Explicitly set the account/token pair belonging to that same bot.

```ini
BB_REPO=/srv/briefberlin/repo
BRIEFBERLIN_EDITORIAL_DB=/var/lib/briefberlin/editorial.sqlite3
BRIEFBERLIN_EDITORIAL_POLICY=/var/lib/briefberlin/editorial_policy.yaml
BRIEFBERLIN_REVIEW_KEY_FILE=/var/lib/briefberlin/review.key
BB_SOURCE_REGISTRY=/srv/briefberlin/repo/config/civic_sources.json
BB_TRIAGE_MODEL=provider/model-version
BB_TELEGRAM_ACCOUNT=desk
BB_TELEGRAM_TARGET=/var/lib/briefberlin/telegram-chat-id
BB_REVIEW_INGRESS=/srv/briefberlin/repo/.venv/bin/briefberlin-review-ingress
BB_OPENCLAW_WEBHOOK=http://127.0.0.1:8787/telegram-webhook
BB_INGRESS_PORT=8789
BB_STATE=/var/lib/briefberlin/legacy/.bb-pending
```

Set `BB_TELEGRAM_BOT_TOKEN` and `BB_TELEGRAM_WEBHOOK_SECRET` (at least 32 high-entropy Telegram-compatible characters) privately. Set the real loopback upstream path and port. Set `BB_OPENCLAW_WEBHOOK_SECRET` if upstream uses a separate secret. Register the bot's public HTTPS webhook through the gateway for message and callback_query updates. Reverse-proxy that single URL to 127.0.0.1:8789/telegram, preserving Telegram's secret header. Restrict the upstream gateway to trusted processes. Use one webhook consumer. Keep any old pending pointer visible at its real path using `BB_STATE` and `BB_LEGACY_REPO` during migration. If overriding DB paths, adjust `briefberlin-dispatch.path` to the matching private `.publisher/dispatch.wake` path.

Install the six skills from the selected revision in each actual workspace.

```sh
for role in manual discovery; do
  sudo python3 openclaw/install_skills.py --skills "$PROJECTS/briefberlin-$role/skills"
done
```

Set `TRIAGE_PROFILE` to the dedicated OpenClaw profile name and run its CLI as that gateway's owner with the corresponding gateway environment. With the canonical profile layout, define `oc() { sudo -Hu "$TRIAGE_GATEWAY_USER" openclaw --profile "$TRIAGE_PROFILE" "$@"; }` in the root administration shell. If the gateway uses custom configuration or state paths, supply its actual paths to this CLI as well. Use the manual gateway's CLI/profile separately to inspect its agent. Apply the Docker and tool settings above, then check the installed config using `oc config validate` and `oc sandbox explain --agent briefberlin-discovery`. For an existing sandbox, preserve pending manual inbox/session work, run `openclaw sandbox recreate --agent AGENT_ID` in the corresponding profile and start a fresh session. This applies the workspace mount and read-only skills mount to the new sandbox. The installer refuses modified or pre-existing unmanaged copies. While the sessions are stopped, move conflicting legacy directories including their customizations into a private backup **outside every indexed skill root**, review them, then rerun the installer. Reinstalling an identical release leaves it untouched. A changed managed release atomically replaces the group and drops obsolete managed files. Start fresh sessions after changing skills/groups. Confirm all six names with `oc skills list --agent briefberlin-discovery` and `oc skills info briefberlin-discovery --agent briefberlin-discovery` in the discovery gateway. Confirm grouped discovery works with the installed version before scheduling. [OpenClaw skill discovery](https://docs.openclaw.ai/tools/skills)

## Bootstrap and observe

Use this function in a trusted operator shell for commands that need the service's environment. It uses systemd to read the private env file with the same semantics as the units. Confirm the host's uv executable and any credential helpers are on the service PATH.

```sh
bbhost() {
  local tool=$1
  shift
  sudo systemd-run --quiet --wait --pipe --collect --uid=briefberlin --gid=briefberlin \
    -p UMask=0077 -p EnvironmentFile=/etc/briefberlin/publisher.env \
    -p WorkingDirectory=/srv/briefberlin/repo "/srv/briefberlin/repo/.venv/bin/$tool" "$@"
}
bbhost briefberlin-editorial init
bbhost briefberlin-editorial dispatch-mode observe
bbhost briefberlin-editorial registry-sync --registry /srv/briefberlin/repo/config/civic_sources.json
bbhost briefberlin-editorial coverage
```

Import German editions from **fetched main** against the live sitemap. Build a temporary private detached checkout in the same clone while service jobs are stopped. If a last verified story/time is independently known, use `--known-live-story ID --known-live-epoch UNIX_SECONDS` instead of the explicit initial epoch below. The initial epoch seeds only the first bootstrap. Save its rationale.

```sh
sudo -Hu briefberlin git fetch origin main
sudo -Hu briefberlin git worktree add --detach /var/lib/briefberlin/archive-bootstrap origin/main
bbhost briefberlin-editorial archive-sync --output /var/lib/briefberlin/archive-bootstrap/output --bootstrap-epoch "$(date +%s)"
sudo -Hu briefberlin git worktree remove /var/lib/briefberlin/archive-bootstrap
bbhost briefberlin-editorial dispatch-status
```

Require `ready=true`, a verified ledger entry and a nonzero fallback epoch. Shared story fields, translation paths and the versioned `archive_editions_v1.json` map historical editions. The known July collision excludes one ambiguous URL while the other unambiguous editions identify the stories. Unexpected missing identities or partial new A2/B1 editions inhibit dispatch. Inspect `triage-status` and explicitly resolve possible live duplicates via `archive-resolve`, then refresh again. [Archive operations](editorial-triage.md)

Run the regression suite using test-only paths and fixtures before starting jobs. On the remote host only, the second command opts into the disposable network check for this release. Keep private runtime env/credentials out of the test shell.

```sh
sudo -Hu briefberlin .venv/bin/python -m pytest tests/test_editorial_*.py
sudo -Hu briefberlin env BB_RUN_HOST_COLLECTOR_SMOKE=1 .venv/bin/python -m pytest -s tests/test_editorial_handover.py -k opt_in_host_collector_smoke
```

Inspect fixtures for held ambiguity, syndicated copies, material corrections, rate-only versus approval, 12-hour boundaries across Berlin clock changes, simultaneous ticks, manual versus urgent work, incomplete editions, duplicate callbacks, lost push acknowledgment and later Pages deployment. No live model or bot is needed for the fixture tests. Record the results and any skipped platform checks.

Start only the shipped schedules. The systemd poll timer reloads the registry and polls at most ten due endpoints, oldest due first, with up to three child fetches per endpoint. Pausing collection preserves its registry and cursor history. The dispatch timer recovers outstanding external work, checks fetched main and the archive, dispatches work and services the outbox. A separate path activation runs the same dispatch unit promptly after successful triage or an approved review. The OpenClaw job only claims/scores up to three revisions. The periodic dispatch timer covers lost wakes and quiet queues. Disable any old standalone publisher cycle, collector or competing OpenClaw tick.

```sh
sudo systemctl enable --now briefberlin-manual.socket briefberlin-discovery.socket briefberlin-telegram-ingress.service
oc --version
oc cron add --help
oc cron run --help
oc cron runs --help
oc cron list --all
```

Create the job disabled. Set `TRIAGE_AGENT=briefberlin-discovery` and `TRIAGE_MODEL` to the exact `BB_TRIAGE_MODEL` provider/model in the service environment. In the dedicated profile configure that same primary model with empty fallbacks both in `agents.defaults.model` and the per-agent object. Restrict `agents.defaults.models` to that identifier and remove aliases, inherited model switches and extra agents/tools that can change it. If the job already exists, disable it and inspect/edit its ID instead of adding another one. Adjust flags to the installed help. These commands use the inspected 2026.5.27 syntax. [OpenClaw cron CLI](https://docs.openclaw.ai/cli/cron)

```sh
oc cron add --name briefberlin-discovery --disabled --every 5m --session isolated --no-deliver \
  --agent "$TRIAGE_AGENT" --model "$TRIAGE_MODEL" --message 'Run the briefberlin-discovery skill once.'
oc cron list --all
# Set JOB to that job's exact ID. Pin the payload's fallback list in the gateway.
oc gateway call cron.update --params "$(jq -nc --arg id "$JOB" '{id:$id,patch:{payload:{kind:"agentTurn",fallbacks:[]}}}')"
oc config get agents --json | jq -e --arg m "$TRIAGE_MODEL" --arg a "$TRIAGE_AGENT" '
  .defaults.model == {primary:$m,fallbacks:[]} and (.defaults.models | keys) == [$m] and
  ([.list[] | select(.id==$a) | .model] == [{primary:$m,fallbacks:[]}])'
oc cron show "$JOB" --json | jq -e --arg m "$TRIAGE_MODEL" --arg a "$TRIAGE_AGENT" '
  .enabled == false and .agentId==$a and .sessionTarget=="isolated" and .delivery.mode=="none"
  and .payload.model==$m and .payload.fallbacks==[]'
RUN=$(oc cron run "$JOB" --wait --wait-timeout 20m)
RUN_ID=$(jq -er 'select(.completed==true and .status=="ok") | .runId' <<<"$RUN")
oc cron runs --id "$JOB" --run-id "$RUN_ID" | jq -e --arg m "$TRIAGE_MODEL" --arg run "$RUN_ID" '
  any(.entries[]; .runId==$run and .action=="finished" and .status=="ok" and (.provider+"/"+.model)==$m)'
```

On another CLI version use the job identifier form printed by `cron runs --help`. If `--wait` is unavailable, capture the run ID and poll its history until this exact run finishes. Record the UTC time, run ID, reported provider/model, summary, claimed revisions and rubric. An enqueued, skipped or errored run does not pass. Keep observation active until a completed run with a real decision confirms model and rubric. The SQLite model field records the host's **requested** identifier with a `requested:` prefix. The separate gateway run record supplies the actual provider/model. Recheck both after any model/profile/job change.

Start a manual sandbox session and the discovery sandbox above. Use each profile's `sandbox list --json` to find the two existing Docker container names, set `MANUAL_CONTAINER` and `DISCOVERY_CONTAINER`, and confirm their resolved mounts and GIDs. From each agent session, use the structured write tool to create a unique harmless marker under its relative `inbox/` or `decisions/` path. Follow that skill's file preparation step. Read it back through the tool, confirm the same bytes with sandbox exec and remove the marker. Also confirm a structured write of a new marker at workspace root and under `skills/` is denied. Use fresh filenames for these checks. While there are no in-flight RPCs, run the installed-host acceptance test below. It sends side-effect-free invalid requests, checks scratch creation, protected workspace paths, client executables and mount isolation, restarts both systemd sockets, then repeats the probes in the same containers. The test opt-in is separate from the collector smoke. After it passes, start the three systemd triggers and the observed cron schedule.

```sh
sudo env BB_TEST_INSTALLED_SOCKETS=1 BB_MANUAL_CONTAINER="$MANUAL_CONTAINER" \
  BB_DISCOVERY_CONTAINER="$DISCOVERY_CONTAINER" .venv/bin/python -B -m pytest -p no:cacheprovider -q \
  tests/test_editorial_handover.py -k installed_sockets_survive_restart
sudo systemctl enable --now briefberlin-poll.timer briefberlin-dispatch.timer briefberlin-dispatch.path
oc cron enable "$JOB"
```

Observe the actual skill packet and decision through the group-restricted client. A first poll baselines historical items. Wait for new dated material or explicitly baseline selected new sources with the bounded `collect --lookback-hours` described in [collection operations](editorial-collection.md). Compare the requested identifier and rubric in SQLite with the completed run in gateway history. Replay the editor-confirmed Spandau student housing case (8) and separately calibrate proposed anchors for official Berlin election results (10), a single school's climbing area (5) and a Brandenburg-only ruling (2). Measure elapsed time, duplicate rate, source errors, model cost and disagreements before releasing a new prompt version.

## Editor exercise and controlled publication

Scoring applies to the concrete event across issuers. 9–10 is immediate Tier 0, 7–8 is Tier 1 after 12 elapsed hours, 4–6 is Tier 2 subject to an affirmative editor decision in that open slot, 0–3 skips. The global clock advances once per verified live story across editions, translations, manual and automatic paths. Default Tier 2 re-prompt interval and hold are 12 hours. Unscheduled candidate freshness is 48 hours, shortened by a known deadline. A more distant service end requires evidence. [Dispatcher contract](editorial-dispatch.md)

1. Inspect `bbhost briefberlin-editorial dispatch-status`, `triage-status`, `coverage` and `bbhost briefberlin-review-send --status`. During observation automatic candidates return `would-publish` or a private card. There is no automatic Telegram card. In an agreed test conversation, with the editor present, explicitly send that single observation card using `bbhost briefberlin-review-send --observation-request "$REQUEST"`. Verify the exact source, Berlin consequence and reason, an independent score change, approval and stale/rejected controls. Exercise decline and hold on fresh observation cards or fixtures. Observed decisions stay in observation. Switching mode invalidates outstanding test approvals.
2. The bridge records opaque fixed controls before sending. Each delivered control requires the configured bot, chat, exact message, authorized sender, request, story and evidence version. The authenticated webhook signs the stored action and replies to Telegram with a callback acknowledgment. A Telegram message ID acknowledges delivery only. A retry of the same accepted callback returns the recorded outcome. A rate-only action still requires approval; explicit rate + publish accepts 4–10. For a score below 4 use the manual preview. A Telegram 429 with a definitive rejection and positive retry_after records the earliest retry time. A later tick retries only after that persisted cooldown. A timeout after send can leave an actual card with no known message ID. Automatic ticks leave it ambiguous. Check the configured conversation and `briefberlin-review-send --status`. To replace **that attempt**, use `bbhost briefberlin-review-send --resend-attempt "$ATTEMPT"`; for an observation card also pass its `--observation-request "$REQUEST"`. The replacement gets new bindings, and older controls cannot grant a new decision. Silence or delivery never releases the publisher.
3. Confirm the normal manual paste, Generate, exact A2/B1 preview and Discard. With the owner's explicit choice of a real publishable story, repeat and approve the exact preview. Manual approval can publish even during observation or automatic pause. Verify the persisted manifest/commit, Pages success, marker, both public canonical identities and the single ledger entry. Check a waiting unrelated draft survives automatic processing in the acceptance fixtures.
4. For the first real automatic story, stop all three systemd triggers and disable the OpenClaw job as below. Wait for active writers, recover outstanding receipts and defer new manual decisions. In observation run `bbhost briefberlin-discovery dispatch`. Record the returned story ID and evidence version from the would-publish decision or review card. Obtain the owner's approval for **that pair** and set `STORY` and `VERSION` accordingly.
5. Run `bbhost briefberlin-discovery first-story "$STORY" "$VERSION"`. The host rechecks the observed selection under a write lock, pins that pair durably, changes to live and refreshes the archive. A changed selection blocks the launch. A Tier 2 story gets a fresh live card and needs a fresh editor approval. Only for that card, after approval, invoke the same exact-ID command again. If the send is rate-limited, retry that card after its cooldown. For an unavailable or superseded target, return to observation and obtain a new owner decision. During this controlled launch manual reservations are held as well.
6. From the first push authorization onward, use only `bbhost briefberlin-publisher recover` and `bbhost briefberlin-editorial dispatch-status`. Repeat recovery until the saved commit and both live editions verify. Confirm the target story advanced the ledger exactly once. Record activation UTC, story/version, score, work ID, commit, deployment, both edition identities and any media failures. The launch stays fenced after verification. For accepted regular operation deliberately clear the pin with `bbhost briefberlin-editorial dispatch-mode observe`, then run `bbhost briefberlin-editorial dispatch-mode live` and restart the three triggers and cron. If stopping after the trial, return to observation and leave schedules stopped.

## Status, pause and stop

```sh
bbhost briefberlin-editorial coverage
bbhost briefberlin-editorial triage-status
bbhost briefberlin-editorial dispatch-status
bbhost briefberlin-review-send --status
sudo systemctl list-timers 'briefberlin-*'
sudo systemctl status briefberlin-dispatch.path briefberlin-telegram-ingress
sudo journalctl -u briefberlin-poll -u briefberlin-dispatch -u briefberlin-telegram-ingress --since today
bbhost briefberlin-editorial collection-pause
bbhost briefberlin-editorial publish-pause
```

Keep verification running during an automatic pause. `publish-resume` requires a fresh archive before automatic authorization. Resume with `bbhost briefberlin-editorial collection-resume`, `bbhost briefberlin-editorial publish-resume` and `bbhost briefberlin-discovery dispatch` after reviewing the queue. Inspect source-specific `last_failure` and collection gaps independently of successful polls. External uncertainty occupies the single publication reservation. `briefberlin-publisher recover` verifies its immutable commit/manifest. Only an operator with definitive remote evidence and a fenced, terminated sender may use `confirmed-absent`. [Publisher recovery](editorial-publication.md)

To suspend scheduling without interrupting an in-flight push:

```sh
oc cron disable "$JOB"
sudo systemctl stop briefberlin-poll.timer briefberlin-dispatch.timer briefberlin-dispatch.path
sudo systemctl list-units 'briefberlin-*'
```

For maintenance also stop the ingress and both listening sockets, finish/stop all active RPC instances and polling/dispatch services, and verify no existing process or other host can still send. Inspect any interrupted push through its saved receipt. For a persistent shutdown use `systemctl disable --now` on the installed timers/path/sockets/ingress. To resume, start the units listed in bootstrap, then `oc cron enable "$JOB"`.

## Private backup, restore rehearsal and release rollback

Create snapshots outside both state and clone, under a service-owned 0700 backup root with encrypted storage and restricted retention. `create` uses SQLite's online backup API, checks integrity and foreign keys, takes the sender/manual/archive locks, and includes private worktrees, evidence, manifests, logs and the clone's common Git directory/objects. It refuses a busy publisher; retry after the active job finishes. Avoid concurrent administrator Git maintenance, upgrades or edits to the private clone during backup. The clone's venv is rebuilt on restore. A pending external receipt can be backed up and remains fenced. A snapshot database itself is quarantined. Keep original host credentials, policy, service configs, gateway state, inbox, pending legacy data and audited release record in a separate protected host backup.

```sh
BUNDLE=/var/backups/briefberlin/release-$(date -u +%Y%m%dT%H%M%SZ)
bbhost briefberlin-editorial-backup create "$BUNDLE"
bbhost briefberlin-editorial-backup check "$BUNDLE"
bbhost briefberlin-editorial-backup stage "$BUNDLE" "$BUNDLE-rehearsal"
```

The rehearsal destination must be new. Repeating the stage command at the same destination must fail. Verify both the recorded absolute paths and the included linked worktree `.git` files/private evidence. Opening the staged DB with `bbhost briefberlin-editorial --db "$BUNDLE-rehearsal/editorial.sqlite3" init` must fail with the quarantine message. Never run Git or services in a staged worktree on a live machine: the Git admin links retain the original host paths. For a full rehearsal use an isolated host with the same absolute paths, separate test accounts and no production push capability. Preserve the production backup and retire the rehearsal copy privately.

For an actual restore, disable every sender/schedule and save the current private state, clone, database sidecars (WAL, SHM and journal), worktrees, bot receipts and any newer evidence **as a set**. Compare this set with the snapshot. Never overwrite a live database or copy snapshots over old sidecars. Use a fresh stage destination and a fresh protected incident directory. Example on the canonical host, as root, with `STAGE` the checked staged directory, `INCIDENT` a new incident directory and all services confirmed quiescent:

```sh
install -d -o briefberlin -g briefberlin -m 0700 "$INCIDENT"
test ! -e "$INCIDENT/state" && test ! -e "$INCIDENT/repo"
mv -T /var/lib/briefberlin "$INCIDENT/state"
mv -T /srv/briefberlin/repo "$INCIDENT/repo"
install -d -o briefberlin -g briefberlin -m 0700 /var/lib/briefberlin
mv -T "$STAGE/repo" /srv/briefberlin/repo
mv -T "$STAGE/editorial.sqlite3" /var/lib/briefberlin/editorial.sqlite3
mv -T "$STAGE/editorial.sqlite3.publisher" /var/lib/briefberlin/editorial.sqlite3.publisher
cd /srv/briefberlin/repo
sudo -Hu briefberlin uv sync --frozen --extra dev
```

Use an error-stopping shell and preserve ownership. Restore the reviewed non-database policy, Telegram target, review key and legacy pointer from the protected host configuration at their configured paths. Leave schedules and sockets stopped. The restored repository and publisher state must occupy the original absolute paths. Inspect `git worktree list --porcelain` and each draft's inverse `.git/worktrees/*/gitdir` link. Compare post-snapshot main commits, Pages deployments, latest editor decisions, outstanding work IDs, staged manifests, commit SHAs and both live article identities against the saved current state. Account for any missing approvals, withdrawals or pushes after the backup, including sender processes on other hosts. Reconcile facts with the editor; never replay an old approval. If discrepancies remain, retain quarantine and preserve the newer ledger for investigation.

Fetch main read-only and record the exact reviewed, deployed tip as `VERIFIED_MAIN`. Run the following with an incident reference and a concrete account of the operator's reconciliation:

```sh
bbhost briefberlin-editorial dispatch-status
bbhost briefberlin-editorial-backup reconcile "$BUNDLE" --verified-main "$VERIFIED_MAIN" --audit "$AUDIT_NOTE"
```

Reconciliation requires matching snapshot identity, original paths, ancestor history, current Pages marker, successful recovery of active external outcomes and a ready archive from fetched main. For blocked archive comparisons use `triage-status` and `archive-resolve` then rerun reconciliation. For a definitively absent commit use the documented `briefberlin-publisher confirmed-absent WORK_ID SHA --evidence "$PROOF"` only after establishing absence and fencing the old sender. A timeout or unknown remote remains quarantined. The restored DB reopens in observation with automatic publishing and collection paused, prior cards superseded and unfinished manual approvals withdrawn. Re-preview manual drafts, verify observations against production and make a separate decision about resuming.

For a normal upgrade, pause, back up, quiesce, select the new owner-merged SHA, repeat the pinned install/migrations and atomic skills install, rerun the host suite and return to observation. For rollback prefer disabling schedules and selecting a compatible previously tested release while preserving the latest ledger. Older code rejects newer schemas. For an incompatible rollback preserve both generations and deploy a forward compatibility fix or use the guarded incident restore above with full post-snapshot reconciliation. Do not point the old publisher at a pre-upgrade snapshot. Retain UTC times, SHAs, operator and verification results in the host release record.

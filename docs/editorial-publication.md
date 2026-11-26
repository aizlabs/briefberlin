# Host publication and recovery

The manual Telegram workflow and scheduled publisher use one private SQLite database. Use the merged installation and its pinned virtual environment. Run the host acceptance suite before enabling automatic mode. Schedule `briefberlin-publisher cycle` every five minutes even during observation or automatic publication pause. It verifies unresolved work first, refreshes the archive from a detached copy of fetched main, then calls the dispatcher. A separately running collection/triage job feeds the queue. The review service handles returned Tier 2 cards according to the [dispatch contract](editorial-dispatch.md).

## Installation and trust boundary

Set `BRIEFBERLIN_EDITORIAL_DB` to the same absolute database path for every host service, `BB_REPO` to the installed Git clone, `BRIEFBERLIN_EDITORIAL_POLICY` to the private policy, and `BB_TELEGRAM_ACCOUNT` to the trusted bot account name used in its allowlist. Use an owner-only state directory on a local POSIX filesystem with working SQLite and flock semantics. The publisher places a 0700 directory named after the database with suffix `.publisher` beside it. Reserve disk space for three detached worktrees (draft, publication and archive) and their logs. Keep Git and GitHub credentials in the service environment or credential helper, with fetch access to the full history and non-force push rights to origin/main. Configure Git's sender identity. Configure `gh` to read Pages deployment and status records for aizlabs/briefberlin. Production deployment must serve the workflow's commit marker and the updated article layout on briefberlin.de.

Set generation, translation, image, audio and object-storage credentials in the host service environment or its private checkout .env. The generator reads secrets into the child environment. The worktrees receive private source inputs by absolute path. `BB_PROVIDER` defaults to anthropic. Set `BB_AUDIO=0` to disable narration and `BB_ILLUSTRATE=0` to skip the optional automatic illustration. Both defaults preserve the enabled media workflow. Failed optional narration is reported and leaves the post publishable. Generation and quality failure stop the attempt. Missing publication or verification credentials leave a private error or pending receipt, never a successful live status.

### Install the scoped manual socket and webhook

The supplied Linux/systemd units use a separate service identity named `briefberlin`, an isolated clone at `/srv/briefberlin/repo`, and a local client group named `briefberlin-client`. Install the pinned project in the clone's virtual environment with `uv sync --frozen`. Keep the clone, DB, logs, Git credentials, provider keys, review key and gateway config inaccessible to the model's shell. The publisher must own its clone for Git worktrees. Keep the upstream OpenClaw gateway (including its bot token and webhook secret) outside that shell's OS user or container. Give the model's sandbox only the skill, its own writable paste/media inbox and access to the manual socket. On a container host, mount the socket and map its group ID. The socket grants manual workflow access. It exposes no shell, event-ingestion, operator staging or Git endpoint.

Example operator setup on a systemd host (adjust the sandbox username if different):

```sh
sudo groupadd --system briefberlin-client
sudo useradd --system --create-home --home-dir /srv/briefberlin briefberlin
sudo chmod 0700 /srv/briefberlin
sudo usermod -aG briefberlin-client openclaw
sudo install -d -m 0700 /etc/briefberlin
sudo install -d -o briefberlin -g briefberlin -m 0700 /var/lib/briefberlin
sudo install -m 0644 deploy/editorial/*.service deploy/editorial/*.socket /etc/systemd/system/
```

Use the merged clone for the installation. From a separate skill checkout run `openclaw/skills/briefberlin/install.sh` as the skill user, or install its `SKILL.md`, its executable Python `scripts/bb` and the illustration skill into the sandbox workspace. The client uses Python's standard library. The publisher loads its subprocess helpers from `BB_REPO/openclaw/skills/briefberlin/scripts`, including for wheel installations. Restart the sandbox session to apply the new group. Its optional environment variables are `BB_MANUAL_SOCKET`, `BB_INBOX` and `BB_MEDIA_INBOX`. The defaults are `/run/briefberlin-manual.sock`, `/opt/openclaw/work/inbox` and the `media` directory inside that inbox. The source must be the regular file `article.txt`; an attached image must be a regular file directly in the media inbox. The client reads bounded bytes, rejects symlinks and sends the bytes. The service creates its own private copy, with no model-supplied host path.

Create a root-owned mode-0600 `/etc/briefberlin/publisher.env` with the generation and Git settings above and these host-specific values. Use real paths and credentials from the host secret store.

```ini
BB_REPO=/srv/briefberlin/repo
BRIEFBERLIN_EDITORIAL_DB=/var/lib/briefberlin/editorial.sqlite3
BRIEFBERLIN_EDITORIAL_POLICY=/var/lib/briefberlin/editorial_policy.yaml
BB_TELEGRAM_ACCOUNT=desk
BB_TELEGRAM_TARGET=/var/lib/briefberlin/telegram-chat-id
BB_TELEGRAM_BOT_TOKEN=<gateway bot token>
BB_TELEGRAM_WEBHOOK_SECRET=<random Telegram-compatible secret of at least 32 characters>
BB_OPENCLAW_WEBHOOK=http://127.0.0.1:8787/telegram-webhook
BB_STATE=/var/lib/briefberlin/legacy/.bb-pending
```

The target file contains only the Telegram chat ID. Install a private copy of the repository policy with the exact `telegram/ACCOUNT/CHAT/SENDER` editor identity. Set `BB_LEGACY_REPO` to the old clone when it differs from `BB_REPO` and grant the service read-only access to its preserved private input. Select the actual legacy pointer during migration; an empty replacement would hide a pending draft. Use the same environment for the cycle and operator commands. Configure OpenClaw's Telegram channel in webhook mode with its real loopback port/path as the upstream, the public webhook URL pointing to this ingress, and the same high-entropy `webhookSecret` as the ingress. Configure your public HTTPS reverse proxy to forward only that URL's POSTs to `http://127.0.0.1:8789/telegram` and pass the Telegram secret header. Register this public URL via the gateway's webhook configuration with `message` and `callback_query` updates enabled. No second polling consumer runs. A distinct upstream header can be set with `BB_OPENCLAW_WEBHOOK_SECRET` if the operator controls registration separately. Restrict direct access to the gateway's loopback port from the model's container. Start with observation enabled.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now briefberlin-manual.socket briefberlin-telegram-ingress.service
sudo -u openclaw /opt/openclaw/.openclaw/workspace/skills/briefberlin/scripts/bb status
```

### Upgrade with a legacy pending draft

Upgrading a pre-ingress ledger invalidates unsubmitted approvals and requires a new preview. Authorized external receipts still require reconciliation. Stop the old bb sender, deploy watcher and any previous automatic publication jobs. Check the existing `/opt/openclaw/work/.bb-pending` (or configured `BB_STATE`) and the legacy clone's Git status under the operator account. Take a private backup of its pending source and changed files. If it indicates an unresolved push, determine the remote and deployment outcome before bootstrap. A pending file suppresses publication until inspected and imported. `briefberlin-publisher manual legacy-import` checks that the pointer identifies a bounded regular timestamped source beneath the installed clone's private-input directory. It copies those bytes into a fresh draft, runs matching and regeneration and records a fingerprint of the legacy source. It preserves the old pending file, source and dirty checkout; old buttons have no matching receipt. This produces a new preview and requires fresh approval. If the legacy draft was already published, reconcile its live archive identity and explicitly retire the old pointer in the backed-up private host folder. For an invalid pointer inspect and preserve the affected files before retiring it. Never run the old bb cleanup in the shared clone.

### Authenticated Telegram decisions

The ingress compares Telegram's secret in constant time before reading an update, binds the account to host configuration and forwards the original body to the upstream gateway after processing any manual decision. A transport failure requests Telegram redelivery. The durable event hash makes identical retries idempotent. The account, chat, sender, control delivery message and preview token must agree. To type a decision, use Telegram's Reply on the delivered controls message and send just `publish` or `discard`. Old replies and unthreaded words grant no approval. The model can then call the scoped `bb publish` or `bb discard`. For a separate Tier 2 receiver, set `BB_REVIEW_INGRESS` to the absolute path of a private fixed executable. For a `bb-review:` callback it receives authenticated Update JSON on stdin and reads its account from service configuration. It must check its immutable review outbox, sender and delivery, return zero on handled retries/stale controls and nonzero on retryable delivery errors. Reserve Tier 2 card delivery for the review service.

## Entry points

- `bb received INBOX/article.txt` counts a split paste and offers Generate/Cancel. Append subsequent parts to the same file until generation starts. `bb generate INBOX/article.txt` privately stages the complete source and suppresses matching automatic work in the same database transaction. An exact headline plus a unique matching source URL can attach to an active event. A headline alone always offers a choice, including new. Exact-title and source-link candidates receive a five-minute matching hold; broad lexical matches remain eligible for dispatch. An ambiguous MATCH response lists candidate IDs and their states. After reviewing them, use `bb match DRAFT_ID STORY_ID` or `bb match DRAFT_ID new`. A changed shortlist requires a renewed choice. A failed preparation keeps the source and accepts up to three generation attempts. `bb cancel` clears an incomplete draft. A pending draft holds no publication worker.
- `bb stories`, `bb illustrate STORY PROMPT ALT`, `bb add-image STORY FILE ALT [CAPTION]` and `bb preview` use only that draft's isolated artifacts. Previews send both German editions and the image, then deliver the approval controls. Repreviewing or editing invalidates older controls. `bb status` reports the private draft and its state. After the authenticated editor event, `bb publish [token]` reserves that exact snapshot or reports busy, deferred, stale or blocked. An approved busy draft is retried by the cycle. `bb discard [token]` retires the draft and deletes its private worktree. Before every reservation, preparation refresh and push authorization the ledger checks the evidence version, reader deadline and actual expiry. Fresh untriaged manual events expire after two days. To renew a stale event, discard via its controls, let triage apply current material with a new evidence version and revised dates, then stage and approve a fresh preview. Discarding releases the candidate for normal triage.
- `briefberlin-publisher work WORK_ID` handles a dispatch reservation, including recovery of a requested manual reservation. Automated work receives only attributed evidence attached through its reserved version. It generates one quality-approved A2/B1 pair with the stable story ID, optionally illustrates the public text, and uses the existing post-audio uploader. A manual reservation starts from the digests of the actual delivered preview.
- `briefberlin-publisher cycle` recovers, refreshes archive evidence and services eligible work. `briefberlin-publisher recover` only inspects remote/public state, reconciles the saved receipt and delivers pending manual notifications. `briefberlin-editorial dispatch-status` reports expected commit, manifest, clock and active work without exposing a lease token. Bootstrap first as described in [editorial triage](editorial-triage.md).
- `briefberlin-manual --story-id ID --level A2 --level B1 PRIVATE_SOURCE` is the generator used inside detached worktrees; standalone callers can omit the ID. The generation-only tools still write drafts. On an editorial host configured with `BRIEFBERLIN_EDITORIAL_DB`, `briefberlin-publish-and-push SOURCE` for main enters the approved manual path and retains the caller's source. The host path accepts one source, origin/main and the live publication clock. Standalone unconfigured installations and explicit test branches retain the previous command behavior. The agent and production credentials must use the scoped ledger services.

## Commit, deployment and ambiguity

Before sending public text to the media providers, exposing a preview or making a publication commit, the publisher checks for private evidence URLs, paths and passages of sixteen consecutive words shared with the private source. Short factual quotations remain possible. The publisher scopes each attempt to a private worktree, rechecks both editions and every reciprocal translation or illustration link, and accepts only new public files belonging to that story. The visible post and translation dates use the current Berlin wall clock. The date prefix of a German post can change across midnight while its URL slug, translation links, illustration and audio associations stay stable. After refreshing origin/main it checks for the shared story ID even in older posts with unrelated slugs and verifies the actual added-file delta, regular Git blob modes and SHA-256 digests. Final authorization records the full commit and manifest before a single non-force push of that SHA. A newer remote head forces a new exact local commit before authorization or a pending remote outcome after authorization.

The sender lock remains held across the external call. A timeout, reboot or lost Git response leaves the durable receipt in push-authorized/external-uncertain. The verifier checks the expected commit in fetched main's history, the SHA marker currently served by Pages, a successful github-pages deployment for that SHA, manifest blobs in that deployment and the two canonical HTML pages with their exact story and level. A later deploy containing the original commit qualifies. Successful reconciliation records the live story and advances the fallback clock once. The next cycle can retry a lost notification; delivery receipts never authorize publication.

If verification remains pending, inspect `dispatch-status`, fetch main and inspect GitHub's deployment history and canonical pages without retrying the push. Temporary 404s, missing credentials, stale deployment markers, failed builds and force-rewritten history require investigation. Leave an ambiguous outcome pending. For a **definitive negative** only, stop every process or job with the push credentials and establish with remote-side evidence that no in-flight update can complete and the expected SHA was never accepted. After documenting the evidence, an operator can run `briefberlin-publisher confirmed-absent WORK_ID FULL_SHA --evidence 'remote rejection and sender-fencing details'`. It takes the sender lock, requires a fetched main history excluding that SHA and checks the ledger receipt. This is a privileged decision. The dispatcher defers a fresh preparation. A SHA reachable on main must continue through deployment repair and normal verification.

## Host acceptance

Run these offline tests on the merged, installed host before connecting credentials or enabling the schedule.

```sh
uv run pytest tests/test_editorial_publication.py tests/test_editorial_dispatch.py tests/test_story_id.py tests/test_publish_and_push.py
uv run pytest
```

Use a disposable host deployment fixture for verification exercises. Inject a lost push reply, serve a different or later deployment, present an old preview button, and confirm that an unrelated queued Tier 0 proceeds while a manual draft waits. Exercise both day rollover and Telegram typed/button paths. Record results and any remaining deployment or transport restrictions in the host handover. After a first real publication, check both canonical identities, News sitemap dates and the B1 podcast entry when that edition has audio.

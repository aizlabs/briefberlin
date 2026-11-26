# BriefBerlin OpenClaw skill

The Telegram workflow the OpenClaw bot runs: paste an article → **Generate** → preview →
**Publish** or **Discard**. Nothing reaches GitHub until Publish.

| File | Role |
|---|---|
| `SKILL.md` | Instructions the OpenClaw agent follows |
| `scripts/bb` | `generate`, `preview`, `publish`, `discard`, `status` |
| `scripts/bb_tg.py` | Sends messages and buttons straight to the Telegram chat |
| `scripts/bb_preview.py` | Sends the A2/B1 article text for review |
| `scripts/bb_report.py` | Turns a failed run's log into a short report |
| `briefberlin-publisher recover` | Verifies both edition identities and the deployed manifest before the live notification |

## Behaviour

- **Generate** runs `briefberlin-manual --environment production --provider anthropic`
  (Opus writes, adapts and grades; Terra translates). `BB_PROVIDER=openai` uses Terra only.
- **Publish** narrates both approved posts with ElevenLabs, uploads the MP3s to
  `briefberlin-audio-prod/articles/`, then commits and pushes. If audio fails, the posts
  still go live and the Telegram message says so. `BB_AUDIO=0` turns audio off.

## Host credentials

The publisher service owns the generation, Telegram, audio, object storage and Git credentials. On the model side, the `bb` executable reads only the private article/media inbox and uses a group-protected Unix socket. Typed Publish and Discard decisions must be Telegram replies to the delivered controls message. For host installation, permissions and the authenticated webhook, follow [editorial publication](../../../docs/editorial-publication.md).

## Install or update on the bot

The running copy lives in OpenClaw's workspace. After changing files here and pushing:

```bash
openclaw/skills/briefberlin/install.sh
```

Run it as the `openclaw` user from the bot's clone (`/opt/openclaw/work/briefberlin`).
It copies these files into `/opt/openclaw/.openclaw/workspace/skills/briefberlin/` and
keeps the previous copy as `*.prev`.

The installed workflow also requires the private ledger, authenticated Telegram input adapter and verifier described in [editorial publication](../../../docs/editorial-publication.md). Run the upgrade preflight there before replacing the legacy helper.

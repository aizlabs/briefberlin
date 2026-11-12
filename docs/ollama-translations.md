# Local reader-language translation with Ollama

Reader-language translations can run entirely on a local [Ollama](https://ollama.com) server
instead of the cloud provider. Everything else in the pipeline — synthesis, adaptation, quality
checks, glossary generation, audio — keeps using the cloud provider unchanged. There is no
implicit cloud fallback for translation: if the local backend fails a language, that language is
dropped and the German article still publishes.

## Selection and precedence

`translations.provider` selects the backend:

- `null` (default) — inherit the cloud provider. Model precedence stays
  `translations.model` → `llm.models.translation` → `llm.models.adaptation` → `llm.models.generation`.
- `ollama` — route translations to the local server configured under `translations.ollama`.

The global `llm.provider` and `llm.base_url` are never mutated by this switch. An active local
backend (`provider: ollama` with `translations.enabled: true`) requires an explicit non-blank
`translations.model`; a cloud model name is never inherited for local translation, because cloud
model tags generally do not exist on a local Ollama server. Disabled translations need no local
model, and disabled/empty-language runs initialize no client and make no network requests.
Configuration validation itself is offline.

Layering, last wins: `config/base.yaml` → environment YAML (e.g. `config/local.yaml`) →
environment variables → explicit backfill `--model`:

- `TRANSLATIONS_PROVIDER` — `ollama` to go local, `inherit` to reset to null.
- `TRANSLATIONS_ENABLED`, `TRANSLATIONS_MODEL`, `TRANSLATIONS_LANGUAGES` (filters the YAML
  language list; it never adds new languages or headings).
- `TRANSLATIONS_OLLAMA_BASE_URL`, `TRANSLATIONS_OLLAMA_TIMEOUT_SECONDS`,
  `TRANSLATIONS_MAX_WORKERS` (1–8), `TRANSLATIONS_MAX_ATTEMPTS` (1–5).

## Model setup

Pick and pull an explicit translation model tag; a good default is TranslateGemma
(see https://ollama.com/library/translategemma):

```bash
ollama pull translategemma
# verify the exact tag the server will use:
ollama list
```

Then enable the backend (example `config/local.yaml`):

```yaml
translations:
  provider: ollama
  model: translategemma   # explicit local tag, never a cloud model name
  max_workers: 1          # recommended starting point for local hardware
```

## Native endpoint, not /v1

The adapter calls the native `POST {base_url}/api/chat` endpoint with `stream=false`, the selected
model, `options.temperature`, and exactly one user message, reading `message.content`
(https://docs.ollama.com/api/chat). Do **not** point `translations.ollama.base_url` at an
OpenAI-compatible `/v1` route (validation rejects it) and do not route Ollama through the cloud
structured-output chain. Ollama is not assumed to support JSON/tool calling or every model.

`base_url` defaults to `http://localhost:11434`; a path prefix such as
`http://host.example/prefix` is preserved (`.../prefix/api/chat` is called).

**Docker note:** inside a container, `localhost` is the container itself. On macOS/Windows hosts
use `http://host.docker.internal:11434`; on Linux either `--network host` or the host IP.

## Timeouts, concurrency, retries

- `timeout_seconds` (default 120) is the read timeout for one unit request; the connect timeout is
  capped at 10 s. It is not an article-wide deadline.
- `max_workers` bounds concurrent language workers. Within a language all units run sequentially.
  `max_workers: 1` is the recommended local override.
- `max_attempts` (default 2) bounds each translated unit (title, nonempty summary, each body
  paragraph, visible glossary field). There are no whole-language retries multiplying it and no
  implicit HTTP retries in the transport. Transient failures (connection errors, timeouts,
  HTTP 408/429/5xx) retry with exponential backoff capped at 4.0 seconds per wait; permanent
  configuration/model errors (404 model not found, other 4xx, malformed, empty, incomplete
  `done`, token-limit termination) fail promptly. There is never a sleep after the final attempt.

## Assembly and glossary tradeoffs

The title, nonempty summary, each body paragraph and the visible glossary fields are translated as
separate units and reassembled in Python, so paragraph boundaries, row order and German headwords
survive byte-for-byte. Unit translation preserves structure but limits the model's context to one
unit — a deliberate tradeoff. For glossary labels, an existing English gloss is reused for English
and otherwise translated explicitly from English (a sense-preserving pivot); without a gloss the
German headword itself is translated from German, and German explanations are always translated
from German. This pivoting trades full-article context and all-direct-German translation for
stability; hidden click-only hints never become published rows.

## Failure policy and dry runs

- `translate_article` (used by both pipelines and backfill) is fail-open: failed languages are
  recorded in `last_run_stats`, successful languages are retained, and the German article
  publishes even after a total translation failure.
- `translate_to_language` raises on failure.
- Errors and logs never contain raw API payloads, source bodies or credentials; diagnostics carry
  backend, model, language, level, request count, retries, elapsed time and safe failed-unit
  kind/index/category.
- Backfill `--dry-run` skips inference entirely and writes nothing. Manual pipeline `--dry-run`
  may generate and translate but suppresses publication (pass `--no-translate` to skip
  translations). Backfill can run keyless with `provider: ollama` because only the translation
  backend is validated; cloud backfill still requires its cloud credentials.
- Local token/timing metadata is recorded under provider `ollama` when the server returns it.
  Missing metadata never fails a translation. Local compute is unpriced compute: it shows as
  `N/A` and is excluded from the known subtotal — never priced as zero, and never priced with a
  same-named cloud model's rates.

## Hermetic smoke check (no live inference)

The behavior contract is verified by the mocked test suite; this procedure exercises the real
wiring without a server or cloud credentials:

```bash
uv sync
uv run pytest tests/test_ollama_translation.py -q
uv run ruff check scripts tests
uv run mypy scripts/ --config-file mypy.ini
```

To smoke-check publication shape on synthetic data with isolated output paths (still no network —
the transport is mocked by the suite), the publisher-compatibility cases in the same file write
only to pytest temporary directories. A live linguistic smoke check against a real server is a
deployment decision, not part of this repository's gates: latency, quality and hardware
suitability are unverified non-goals.

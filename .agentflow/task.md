# Configurable local reader-language translation with Ollama

## Corrective campaign af2
This branch is seeded from prior-art checkpoint 96306a4e2406b6878e9a4490bee3536c29c3bbb2. No feature implementation exists yet. Retain the complete product contract below and exactly the two criterion IDs below; do not expand scope or weaken existing tests. Strengthen existing authored tests before implementing.

The final oracle identified these exact defects:
1. oracle-diagnostic-attribution: diagnostic_records carries parent scalar context into descendant records, and test_local_diagnostics_safe_and_useful concatenates records selected by any language-code occurrence. An ancestor languages='en ar' can make unlabelled/swapped child measurements pass for both languages. Associate each observation with an explicit target-language field or an enclosing language key, and assert each language's request count, retries, elapsed time and failure details together. Swapped and unlabelled observations must not satisfy the assertion. Allow reasonable diagnostic representations without imposing an unnecessary production schema.
2. oracle-cloud-prompt-coverage: canned cloud TranslationResponse results and model fallback assertions do not prove submitted prompt/schema compatibility. Through both public translation methods, inspect the cloud factory schema and submitted prompt. Assert source title, summary, body, visible glossary inclusion, hidden-hint exclusion and existing cloud translation instructions, retaining paragraph-mismatch and all model-fallback regression tests.

Keep the earlier corrections: independent sensitive-fragment exclusion, same-name cloud/local price isolation, configured language success ordering, native transport retry bounds, and isolated backfill main tests.
The ignored logging configuration in backfill is a pre-existing out-of-scope product bug; do not fix it here. Isolate tests instead.
Operational correction: the previous operator ran independent pytest during read-only oracle review, changing ignored .pytest_cache files and triggering the integrity guard. The operator will now run authoring, independent checks, and oracle sequentially. This is not a production-code requirement. No AgentFlow changes are authorized.
Static-analysis is an always-passing check criterion. Do not manufacture a type error or require intended-red behavior for it. Its authoritative gate is in ../ollama-translation-evidence/agentflow-execution.json; mypy.ini is available in this worktree. The oracle must complete its source review.
Operational evidence for this new campaign belongs in ../ollama-translation-af2-evidence; retain the same external af.sh, configuration, execution document, private environment and state home from the original campaign. Never modify old approved PLAN.md or CRITERIA.json.

Implement an optional Ollama backend for finished German A2/B1 reader-language translations, independently of synthesis, adaptation, quality checks and audio. Existing configs retain cloud behavior. Finish clean under every gate in the execution document.

## Fixed acceptance criterion IDs
CRITERIA.json must contain exactly these two nonempty executable criteria, matching the execution bindings:
- ollama-translation (kind test, gate tests): the complete behavioral contract below, covered by hermetic pytest cases.
- static-analysis (kind check, gate types): scripts pass the repository mypy configuration.
Do not introduce other criterion IDs. Include the detailed behavioral requirements in the plan and test coverage attached to ollama-translation. Lint and format are mandatory preflight gates.
The controller operator will read PLAN.md and CRITERIA.json before approval. Never approve an empty criteria document. Do not change an approved plan or criteria; escalate.

## Product decisions for this implementation
Ollama is opt-in. Global cloud settings and config/local.yaml defaults stay unchanged. No implicit cloud fallback. Preserve translate_article fail-open behavior: failed languages are recorded, successful languages retained, German publication continues even on total translation failure. Preserve translate_to_language raising on failure. Preserve backfill's current return-code policy while clearly reporting failures. Do not add a new failure-policy framework.
Exact local model and hardware are deployment choices, not hard-coded defaults. No live inference, model downloads, paid generation, archive backfill, publishing or deployment in this task.

## Configuration contract
Add translations.provider: null (inherit global provider) or ollama. Add a nested Ollama configuration with base_url default http://localhost:11434 and positive timeout_seconds default 120. Preserve translations defaults enabled=false in minimal model fixtures, model=null, temperature=0.2, max_workers=4 (1..8), max_attempts=2 (1..5), languages and level filtering.
Inherited cloud model fallback remains translations.model -> llm.models.translation -> adaptation -> generation. Enabled Ollama requires an explicit nonblank translation model; never send the inherited cloud model name. Inactive translation performs no client initialization/network calls. Validate configuration without contacting the server; disabled translations must not need an Ollama model.
Environment variables: TRANSLATIONS_PROVIDER (inherit resets to null), existing TRANSLATIONS_MODEL, TRANSLATIONS_OLLAMA_BASE_URL, TRANSLATIONS_OLLAMA_TIMEOUT_SECONDS, TRANSLATIONS_MAX_WORKERS, TRANSLATIONS_MAX_ATTEMPTS. Preserve TRANSLATIONS_ENABLED and TRANSLATIONS_LANGUAGES (filter YAML languages, not a source of new entries). Preserve duplicate-code and level validation. Precedence: base YAML -> environment YAML -> env vars -> explicit backfill --model. Apply effective CLI model before validating its requirement.
Never mutate llm.provider or llm.base_url to enable Ollama.
Narrowly scope credential validation so Ollama-only backfill can load valid config without unrelated cloud keys. Full generation keeps its existing credential requirements and provider fallback behavior. Cloud-only backfill validates its effective cloud credentials. Never use fake keys, model_construct, or disable all configuration validation.

## Architecture and protocol
Keep ArticleTranslator as the shared API and preserve existing cloud structured prompt chain and regression behavior. Add a small requests-based adapter in scripts/ollama_translation.py (requests is already a dependency); do not introduce a generic provider framework or route Ollama through cloud structured output.
Native POST /api/chat with stream=false, configured model, options.temperature, and a single user message. Read translation text from message.content. Use a documented finite connect/read timeout, explaining that this is not an entire-article deadline.
TranslateGemma template (source/target names and codes must match actual input):
You are a professional {SOURCE_LANG} ({SOURCE_CODE}) to {TARGET_LANG} ({TARGET_CODE}) translator. Your goal is to accurately convey the meaning and nuances of the original {SOURCE_LANG} text while adhering to {TARGET_LANG} grammar, vocabulary, and cultural sensitivities.
Produce only the {TARGET_LANG} translation, without any additional explanations or commentary. Please translate the following {SOURCE_LANG} text into {TARGET_LANG}:
[exactly two empty lines]
{TEXT}
The separator after the colon is three newline characters, producing two empty lines before text. Test exact bytes. Official reference: https://ollama.com/library/translategemma and https://docs.ollama.com/api/chat . Do not assume JSON/tool calling support or support for every Ollama model.

## Deterministic assembly
Translate title, nonempty summary, each body paragraph and visible glossary fields. Assemble ArticleTranslation in Python in original source order. Preserve source paragraph boundaries; normalize internal newlines of one returned paragraph, then join with the existing separator. Reject empty required results instead of dropping them.
Keep German glossary headwords byte-identical and preserve row order/identity programmatically. Hidden glossary hints must not become published rows.
For glossary labels: reuse a nonempty existing English gloss for English; for other targets translate that gloss explicitly from English. If absent, translate the German headword explicitly from German. Translate each nonempty German explanation explicitly from German. Preserve absent optional source fields as empty. This sense-preserving use of existing glosses must be documented as a quality tradeoff, not represented as all-direct German translation.
Copy German reading_time and store actual selected model metadata.
Preserve output schema, filenames, front matter, localized headings, links, RTL and audio references. Never translate private base drafts.

## Failure, retries, concurrency
Only language workers run concurrently; fields within a language are sequential. Existing max_workers bounds requests; document max_workers: 1 as the recommended starting local override.
For Ollama, max_attempts bounds each text unit, without outer whole-language retries multiplying it or implicit HTTP retries. Keep successful units in memory while retrying a failed unit. Retry transient network/timeouts/server failures with bounded backoff; fail promptly for permanent model/configuration errors.
Distinguish connection/unreachable, missing model, timeout, HTTP/API errors, malformed response, empty response, incomplete done status and explicit token-limit termination. Never log raw API payloads. Do not claim semantic omissions can all be detected by string checks.
If any required unit fails, omit the incomplete language and report it while retaining other successful languages. Preserve the current cloud path's paragraph mismatch handling.
Both public translation methods must use the same backend and specified raising/fail-open distinction.

## Integration and accounting
manual_pipeline translates only finalized German articles after quality and glossary enrichment. Backfill uses the same backend, preserves incremental missing-language selection and existing sibling maps, and carries German audio metadata.
Backfill --dry-run skips inference. Manual --dry-run may perform generation/translation while suppressing publication; do not silently change this unrelated behavior.
Record backend, model, language, level, request count, retries and elapsed time, with failed unit type/index and safe error category. Avoid source bodies, private URLs, credentials and raw responses.
Preserve contextvars propagation and cloud token/cost accounting. Record Ollama token/timing metadata when present under provider ollama using a narrowly extended direct usage source if needed. Never price it as the global cloud provider. Missing local pricing is unpriced compute, not zero total cost. Missing token metadata is not a translation failure.

## Files in scope
scripts/translator.py, new scripts/ollama_translation.py, scripts/models.py, scripts/config.py, scripts/backfill_translations.py, scripts/usage_report.py; minimal necessary integration adjustments in scripts/manual_pipeline.py and scripts/main.py. Existing cloud factory/prompt behavior must remain compatible.
config/base.yaml (backward-compatible defaults and comments), .env.example, README.md and an appropriate existing/new docs page explaining the feature.
New behavioral tests in tests/test_ollama_translation.py; focused additions to existing translator/config/model/manual/backfill/publisher/usage tests only where useful. Do not modify unrelated tests.
Operational notes, plans, logs and other campaign documents remain in the external evidence directory. .agentflow/task.md is the explicit committed input exception; requested product documentation belongs in the repository.

## Out of scope
Generated output/, public articles, private inputs, source feed changes, website layout, audio generation, language list/site-fork configuration, production defaults/deployment, AgentFlow code, global Codex config, unrelated refactors, dependency upgrades, cloud comparison calls and git push/PR/merge by child agents. The outer operator handles pushing and PR after verified completion.

## Test requirements
All new tests are hermetic and mocked: no live Ollama/cloud calls, no real credentials, no downloads. Isolate dotenv/environment behavior, use temporary filesystem locations and stub retry sleeps. Use startup-tolerant subprocess timeouts if subprocess tests are necessary (at least 30 seconds, not subsecond deadlines).
Cover defaults, validation, precedence, CLI override, keyless local backfill versus full-run credentials; disabled/no-language short circuits; exact prompt/source language, endpoint/model/options/timeouts; Unicode including Arabic/Cyrillic, multiline input; all error categories, bounded retries/concurrency, no cloud fallback; A2/B1 title/summary/paragraph/glossary alignment, headwords, reading_time/model; partial/total failure and direct raising; incremental backfill and output/audio compatibility; correctly attributed local usage and preserved cloud context.
Tests must assert behavior through stable public/config/adapter boundaries rather than mirror private implementation. Avoid top-level imports of an absent new module causing collection errors: feature assertions should fail for intended missing behavior while existing tests remain collectable. Use existing fixtures.
Test author must lint and format new tests and keep them type-compatible before handoff. The outer operator independently runs lint, types and tests after 00b-tests before oracle review (AgentFlow issue #44).

## Verification and docs
Execution document in ../ollama-translation-evidence/agentflow-execution.json is authoritative. Lint scripts/tests with ruff --no-cache; format new scripts/ollama_translation.py and tests/test_ollama_translation.py only (56 legacy files already fail whole-repository format); mypy scripts/ --config-file mypy.ini; scoped pytest gates and full pytest measurement. Private Python 3.12 environment combines locked BriefBerlin dev dependencies with AgentFlow for python -m agentflow.pytest_report.
Documentation must explain model tag/setup (commands only), cloud vs local selection, env precedence, native endpoint vs /v1, localhost vs Docker host connectivity, retries/concurrency/timeout tuning, glossary/context tradeoffs, failure and dry-run behavior, and a reproducible public/synthetic isolated-output smoke check. No live smoke test is authorized.
The final change must be clean under every gate in the execution document and the repository full lint/type/test checks. Report structural/mock verification separately from unverified live language quality, latency and hardware suitability.

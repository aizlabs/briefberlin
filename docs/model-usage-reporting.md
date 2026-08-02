# Model usage reporting

The manual generation, publish-source, post-audio, and glossary-eval commands report model usage at
the end of each run. One ASCII table combines:

- text-model usage collected by LangChain's `get_usage_metadata_callback()`; and
- direct OpenAI speech usage collected from `speech.audio.done` SSE events for
  `gpt-4o-mini-tts` and its dated snapshots.

The report is emitted from a `finally` block, so completed calls remain visible when a later pipeline
step fails. Rows are grouped by provider, exact returned model name, and modality. Cached input is a
subset of input tokens and is charged at its configured cached-input rate.

## Pricing

Rates live under `llm.usage_reporting.prices` in `config/base.yaml`. They are decimal USD prices per
one million tokens. A canonical model may declare `aliases` using shell-style patterns so dated model
identifiers returned by providers use the intended price without being relabeled in the report.

Update both the rates and `pricing_as_of` after checking the provider's official pricing page. Avoid
broad aliases that could match models with different prices. If a returned model has no matching rate,
or a request did not return complete usage, the row displays `N/A` and is excluded from the known
subtotal. Provider invoices remain authoritative.

Set `llm.usage_reporting.enabled: false` in an environment config, or set
`USAGE_REPORTING_ENABLED=false`, to suppress collection and output.

## Audio fallback

The dedicated OpenAI SSE path writes base64 audio deltas to a temporary file, validates the final
usage event, and atomically replaces the destination. Other speech models retain the normal OpenAI
binary-response path, but their usage is reported as incomplete because that response does not expose
the exact billable speech token counts used by this reporter.

With `briefberlin-eval-glossary --json`, the JSON document remains alone on stdout and the ASCII usage
table is written to stderr.

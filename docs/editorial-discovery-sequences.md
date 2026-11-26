# Editorial discovery implementation sequences

The owner merges this branch. Local runtime verification is limited to the disposable collection/SQLite smoke in sequence 2. Write the remaining tests for the installed OpenClaw host. Each sequence has an isolated implementation, independent static adversarial review, and a separate remediation pass for findings.

## 1. Registry and database

1. Preserve every ID and URL in `config/civic_sources.json`. Classify each endpoint explicitly for polling (feed, HTML listing, document index, changing notice) or lookup (including contact and subscription). Provide an editable cadence, active flag and geographic scope, retaining uncertainty where a source covers multiple jurisdictions. One network endpoint can have several issuers; changing a single issuer's address must not lose another's cursor.
2. Add a small package at `scripts/editorial/`. Implement a SQLite connection factory with configurable database path outside public output, UTC epoch times, foreign keys, explicit short transactions, busy timeout and versioned migrations. Supply durable settings, source/endpoint relationships, cursor, failure and baseline state. Provide stable endpoint identity independent of the URL; a changed address must be rebaselined safely. Later migrations must work on an existing host DB.
3. Build registry validation and transactional reload. A malformed reload rolls back. A paused or removed source stops polling while preserving history. Reject duplicate IDs, unusable URLs and incompatible settings for shared active endpoints. Expose a command to sync, inspect adapter coverage and initialise state. Use `pyproject.toml` for the console entry point, and `python -m scripts.editorial` for development. Check how `config/sources.yaml` supports the existing manual workflow before touching it.
4. Provide host tests under `tests/` for all 159 inventory entries, stable reload, shared endpoints, pausing, editing and migrations. Document operational defaults in code/config as needed. No ingestion, LLM, review or publishing logic in this increment.

Acceptance: the source inventory reconciles to 151 original entries and eight additions; lookup-only rows remain identifiable; reloads preserve identities and historical state. The next sequence can obtain due endpoint records and update cursors transactionally.

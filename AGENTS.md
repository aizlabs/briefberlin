# Repository Guidelines

## Project Structure & Modules
- `scripts/`: core pipeline modules (`topic_discovery.py`, `content_fetcher.py`, `content_generator.py`, `quality_gate.py`, `publisher.py`) plus CLI entrypoints used by `uv run spai-*`.
- `config/`: YAML configs; `base.yaml` is defaults, `local.yaml` is the local override, `sources.yaml` lists RSS/news feeds.
- `tests/`: unit and integration tests (`test_integration_two_step.py`) covering discovery → generation flow; add new cases here.
- `output/` & `logs/`: generated posts, metrics, and run logs; safe to delete via `make clean`.
- `docs/`, `CLAUDE.md`, `DESING.md`: architecture and operational notes; mirror their terms when adding new components or pipeline steps.

## Build, Test, and Development Commands
- Install: `uv sync` (pulls deps + SpaCy model). Configure secrets via `.env` (copy from `.env.example`).
- Run modules: `uv run spai-discover`, `uv run spai-fetch`, `uv run spai-generate`, or full `uv run spai-pipeline`.
- Docker: `make build` builds the image; `docker compose run generator ...` runs commands inside the container.
- Tests: `uv run pytest` (or `docker compose run generator python -m pytest`).
- Lint: `uv run ruff check` before pushing.
- Type check: `uv sync --extra dev` then `uv run mypy scripts/ --config-file mypy.ini`.
- Diagnostics: `python scripts/diagnose_sources.py` to validate feeds; `tail -f logs/local.log` while developing.
- Clean: `make clean` removes generated posts/logs.

## Coding Style & Naming
- Python 3.11; prefer type hints (package ships `py.typed`).
- Ruff enforces lint rules (`line-length = 100`, ignores `E501`); keep imports sorted (`I` rules enabled).
- Functions, modules, and files use descriptive snake_case; keep pipeline steps mirrored between code and `config/*.yaml`.
- Keep logging consistent with `scripts/logger.py`; include key identifiers (topic, level, source count).

## Testing Guidelines
- Framework: `pytest` with tests under `tests/`; name files `test_*.py`.
- Add focused unit tests for new helpers and integration coverage when adding pipeline stages; follow the pattern in `test_integration_two_step.py`.
- Prefer fast tests; network calls should be stubbed or cached. Use fixtures in `tests/conftest.py`.

## Commit & Pull Request Guidelines
- Commit style is short, imperative; maintenance fixes often use `fix: ...`. Automated content commits follow `Generate articles - YYYY-MM-DD HH:MM UTC`.
- One logical change per commit; include configs/migrations alongside code.
- PRs: describe intent and risk, link issues, note config/env changes, and include before/after samples for generated content when relevant. Request reviewers when touching pipeline ordering or output format.

## Security & Configuration
- Secrets live in `.env`; never commit keys. Use `.env.example` to document new variables.
- Config layering: `config/base.yaml` → `config/local.yaml` → environment variables. Local defaults: `quality_gate.min_score: 7.5`, `quality_gate.max_attempts: 3`, `generation.articles_per_run: 2` (prod uses 4), target words `A2: 200`, `B1: 300`. Alert config (`alerts.enabled`, `alerts.email`, `alerts.email_config.smtp`) can be overridden by `ALERTS_ENABLED`, `ALERT_EMAIL`, `ALERT_SMTP_*`, and `EMAIL_USERNAME`/`EMAIL_PASSWORD` when set.
- Validate `config/sources.yaml` entries before running; a bad feed URL will halt discovery.
- Lower thresholds locally (e.g., `min_score: 6.0`) to iterate faster; revert before committing.
- Generated content can include URLs—strip or normalize domains before publishing changes to formatting.

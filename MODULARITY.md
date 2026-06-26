# BriefBerlin Modularity - Quick Reference

Core components remain independently testable. The active workflow is manual private-source generation, with legacy discovery/fetching modules kept for component tests and future reference.

## Component Testing Commands

### Manual Pipeline

```bash
uv run briefberlin-manual private-input/source-1.source.txt
uv run briefberlin-manual --dry-run private-input/source-1.source.txt
```

**What it does:** Accepts ignored private source text, runs generation and quality checks, and writes reviewed public markdown.
**Output:** Markdown files in `output/_posts/`.
**Config:** `config/base.yaml` -> `generation`, `quality_gate`, `output`.

### Content Generator

```bash
uv run pytest tests/test_content_generator.py tests/test_integration_two_step.py
```

**What it does:** Runs two-step generation:

- `ArticleSynthesizer` creates a source synthesis.
- `LevelAdapter` adapts that article to A2 or B1 German.

**Output:** Adapted article with vocabulary, summary, metadata, and retained base article for regeneration.
**Config:** `config/base.yaml` -> `generation`, `llm`.

### Quality Gate

```bash
uv run pytest tests/test_quality_gate.py
```

**What it does:** Scores generated articles and triggers regeneration if needed.
**Output:** Approved article or rejection after max attempts.
**Config:** `config/base.yaml` -> `quality_gate`.

### Publisher

```bash
uv run pytest tests/test_publisher_sources.py
```

**What it does:** Saves approved articles as Jekyll posts. Manual private-source output should use empty public source attribution.
**Output:** Markdown files in `output/_posts/`.
**Config:** `config/base.yaml` -> `output`.

### Site Build

```bash
cd output
bundle exec jekyll build
```

**What it does:** Builds the public Jekyll site that GitHub Pages deploys.

## Iteration Workflow

### Improve Manual Generation

```bash
vim scripts/manual_pipeline.py
vim scripts/content_generator.py
vim config/base.yaml
uv run briefberlin-manual --dry-run private-input/source-1.source.txt
tail -20 logs/local.log
```

### Improve Publishing

```bash
vim scripts/publisher.py
uv run pytest tests/test_publisher_sources.py
cd output
bundle exec jekyll build
```

## Key Files

| Component | Implementation | Test | Config Section |
|-----------|----------------|------|----------------|
| Manual Pipeline | `scripts/manual_pipeline.py` | `tests/test_manual_pipeline.py` | `generation`, `quality_gate`, `output` |
| Synthesizer | `scripts/article_synthesizer.py` | `tests/test_article_synthesizer.py` | `generation`, `llm` |
| Level Adapter | `scripts/level_adapter.py` | `tests/test_level_adapter.py` | `generation`, `llm` |
| Generator | `scripts/content_generator.py` | `tests/test_content_generator.py` | `generation`, `llm` |
| Quality Gate | `scripts/quality_gate.py` | `tests/test_quality_gate.py` | `quality_gate` |
| Publisher | `scripts/publisher.py` | `tests/test_publisher_sources.py` | `output` |
| Telegram Publish | `scripts/publish_telegram_channel.py` | `tests/test_telegram_channel_publisher.py` | site config + deploy workflow |
| Config | `scripts/config.py` | `tests/test_config.py` | `config/base.yaml`, `config/local.yaml` |

## Quick Diagnostics

```bash
uv run python -c "import spacy; nlp = spacy.load('de_core_news_sm'); print('Model loaded')"
uv run ruff check scripts tests
uv run pytest
```

## Development Tips

1. Test early with focused pytest commands.
2. Tune via config before changing code when possible.
3. Watch logs during manual generation with `tail -f logs/local.log`.
4. Keep private inputs local and ignored.
5. Commit only reviewed public posts.

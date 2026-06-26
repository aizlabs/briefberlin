# Component Modularity - Quick Reference

**Modularity Score: 9/10** ⭐

Core components remain independently testable, but the system now includes the full production pipeline rather than discovery/fetching only.

---

## Component Testing Commands

### Topic Discovery
```bash
# Test topic discovery alone
uv run spai-discover

# View detailed logs
tail -f logs/local.log
```

**What it does:** Fetches from 22 RSS sources, extracts entities with SpaCy, ranks topics
**Output:** List of 10 ranked topics
**Config:** `config/base.yaml` → `discovery` and `ranking` sections

### Content Fetcher
```bash
# Test content fetcher alone
uv run spai-fetch

# View logs
tail -f logs/local.log
```

**What it does:** Fetches articles from URLs, extracts clean text with Trafilatura
**Output:** 5 sources per topic (300 words each)
**Config:** `config/base.yaml` → `sources` section

### Content Generator
```bash
# Test generation pipeline
uv run spai-generate
```

**What it does:** Runs two-step generation:
- `ArticleSynthesizer` creates a native-level source synthesis
- `LevelAdapter` adapts that article to A2 or B1

**Output:** Adapted article with vocabulary, summary, metadata, and retained base article for regeneration
**Config:** `config/base.yaml` → `generation`, `llm`

### Quality Gate

**What it does:** Scores generated articles and triggers regeneration if needed
**Output:** Approved article or rejection after max attempts
**Config:** `config/base.yaml` → `quality_gate`

### Publisher

**What it does:** Saves approved articles as Jekyll posts with structured source metadata
**Output:** Markdown files in `output/_posts/`
**Config:** `config/base.yaml` → `output`

---

## Iteration Workflow

### Improve Topic Discovery
```bash
# 1. Edit discovery code
vim scripts/topic_discovery.py

# 2. Or tune ranking algorithm
vim config/base.yaml
# Change: ranking.cultural_bonus, ranking.source_weight, etc.

# 3. Test immediately
uv run spai-discover

# 4. Check results in logs
tail -20 logs/local.log
```

### Improve Content Fetching
```bash
# 1. Edit fetcher code
vim scripts/content_fetcher.py

# 2. Or tune fetch parameters
vim config/base.yaml
# Change: sources.max_words_per_source, sources.fetch_timeout, etc.

# 3. Test immediately
uv run spai-fetch

# 4. Check results
tail -20 logs/local.log
```

---

## Component Architecture

### Zero Coupling Design
```python
# Topic Discovery (scripts/topic_discovery.py)
discoverer = TopicDiscoverer(config, logger)
topics = discoverer.discover(limit=10)  # Returns List[Dict]

# Content Fetcher (scripts/content_fetcher.py)
fetcher = ContentFetcher(config, logger)
sources = fetcher.fetch_topic_sources(topic)  # Returns List[Dict]

# No shared state, pure data passing
```

### Configuration Independence
```yaml
# base.yaml - Each component has its own section
discovery:
  min_sources: 3
  max_topics: 15

sources:
  max_words_per_source: 300
  fetch_timeout: 10

ranking:
  source_weight: 3
  cultural_bonus: 5
```

---

## Key Files

| Component | Implementation | Test Script | Config Section |
|-----------|---------------|-------------|----------------|
| Discovery | `scripts/topic_discovery.py` | `scripts/test_discovery.py` | `discovery`, `ranking` |
| Fetcher | `scripts/content_fetcher.py` | `scripts/test_fetcher.py` | `sources` |
| Synthesizer | `scripts/article_synthesizer.py` | `tests/test_article_synthesizer.py` | `generation`, `llm` |
| Level Adapter | `scripts/level_adapter.py` | `tests/test_level_adapter.py` | `generation`, `llm` |
| Generator | `scripts/content_generator.py` | `scripts/test_generator.py` | `generation`, `llm` |
| Quality Gate | `scripts/quality_gate.py` | `tests/test_quality_gate.py` | `quality_gate` |
| Publisher | `scripts/publisher.py` | `tests/test_publisher_sources.py` | `output` |
| Telegram Publish | `scripts/publish_telegram_channel.py` | `tests/test_telegram_channel_publisher.py` | site config + deploy workflow |
| Config | `scripts/config.py` | `tests/test_config.py` | `config/base.yaml`, `config/local.yaml` |

---

## Quick Diagnostics

```bash
# Check RSS sources
python scripts/diagnose_sources.py

# List configured sources
python -c "
from scripts.config import load_config
config = load_config('local')
for i, s in enumerate(config['sources_list'], 1):
    print(f'{i:2}. {s[\"name\"]:25} ({s[\"type\"]})')
"

# Verify SpaCy model
uv run python -c "import spacy; nlp = spacy.load('es_core_news_sm'); print('✓ Model loaded')"
```

---

## Development Tips

1. **Test early and often** - Use component commands after every change
2. **Tune via config first** - Avoid code changes when config changes work
3. **Watch logs in real-time** - `tail -f logs/local.log` during development
4. **Local config for fast iteration** - `config/local.yaml` has faster settings
5. **Components never import each other** - Pure data passing only

---

## Status

✅ **Implemented & Modular:**
- Topic Discovery Engine
- Content Fetcher
- Two-step Content Generation
- Quality Gate
- Publisher
- Main Pipeline Orchestrator (`scripts/main.py`)
- Telegram Channel Publisher
- Configuration System
- Logger Infrastructure

**Result:** You can iterate on most pipeline stages independently, then verify orchestration with the integration tests in `tests/`.

See also: [docs/monetization-roadmap.md](docs/monetization-roadmap.md)

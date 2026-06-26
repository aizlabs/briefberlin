# BriefBerlin - System Design

This document describes the current BriefBerlin operating model.

## Purpose

BriefBerlin publishes simplified German articles for A2 and B1 learners. The system is optimized for a private manual-source workflow: source material is supplied locally, transformed into learner-friendly German, reviewed, and then committed as public Jekyll output.

## Non-Negotiable Privacy Rule

Manual source articles are private inputs. They must not be committed, logged, uploaded as artifacts, exposed in generated markdown, or used as public attribution.

Accepted private input locations:

- `private-input/`
- `input/private/`
- files ending in `.source.txt`

## Pipeline

```text
private source text
  -> manual_pipeline.py
  -> content generation
  -> quality gate
  -> glossary/audio preparation when enabled
  -> publisher.py
  -> output/_posts/*.md
  -> reviewed commit
  -> GitHub Pages deploy
```

## Active CLI

```bash
uv run briefberlin-manual private-input/source-1.source.txt
```

Options:

- `--level A2`
- `--level B1`
- `--dry-run`

The old public-source console entrypoints are intentionally not registered. `scripts/main.py` remains available for tests and future reference, but production deployment should rely on committed public output only.

## Content Model

Public posts are Markdown files under `output/_posts/` with front matter for:

- `title`
- `date`
- `level`
- `topics`
- `sources: []`
- `audio`
- `reading_time`

Generated posts should contain German learner text, optional `Vokabeln`, and no private source attribution.

## CEFR Targets

### A2

- About 200 words.
- Short sentences.
- Common vocabulary.
- Clear structure and direct explanations.

### B1

- About 300 words.
- More context than A2.
- Moderate sentence variety.
- Still suitable for intermediate learners.

## Configuration

Configuration layers:

```text
config/base.yaml -> config/local.yaml -> environment variables
```

Important settings:

- `generation.levels`
- `generation.target_word_count`
- `quality_gate.min_score`
- `quality_gate.max_attempts`
- `audio.*`
- `alerts.*`

## Website

The public site is a Jekyll project in `output/`.

Before deployment, verify:

- `output/_config.yml` has production `url`, `baseurl`, and `repository`.
- Public pages use German/BriefBerlin copy.
- Privacy policy reflects active analytics, ads, contact forms, and cookies.
- `output/_posts/` contains only approved public articles.

## Tests and Quality Gates

Run before committing:

```bash
uv run ruff check scripts tests
uv run pytest
bundle exec jekyll build
```

Run mypy when touching shared models or pipeline contracts:

```bash
uv run mypy scripts/ --config-file mypy.ini
```

## Deployment Model

GitHub Actions builds and deploys committed Jekyll output from `output/`. The deploy workflow must not fetch private source material or generate new articles.

Optional Telegram article publishing runs after Pages deployment when the publish secrets are configured.

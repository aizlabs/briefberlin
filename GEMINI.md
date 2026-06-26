# Project Overview

BriefBerlin is a private-input pipeline for publishing simplified German learner articles. It turns manually provided source material into reviewed A2/B1 German posts for a Jekyll site.

Private source material is local-only. It must not be committed, logged, uploaded as workflow artifacts, or published as attribution.

## Main Technologies

- Python 3.11
- uv
- SpaCy German model
- OpenAI/Anthropic-compatible LLM adapters
- Jekyll and GitHub Pages
- Docker for optional local container runs

## Architecture

The active public workflow is:

1. Place source text in an ignored private file such as `private-input/source-1.source.txt`.
2. Run `uv run briefberlin-manual private-input/source-1.source.txt`.
3. Review generated markdown under `output/_posts/`.
4. Commit only approved public output and code/config changes.
5. GitHub Pages builds and deploys the committed Jekyll site.

The legacy public-source discovery pipeline still exists for component coverage, but it is not exposed as a project CLI.

## Building and Running

```bash
uv sync
cp .env.example .env
uv run briefberlin-manual private-input/source-1.source.txt
uv run pytest
uv run ruff check scripts tests
```

For the site:

```bash
cd output
bundle install
bundle exec jekyll build
```

## Development Conventions

- Keep Python modules and functions in descriptive snake_case.
- Prefer type hints for new code.
- Add focused pytest coverage for new helpers or behavior.
- Keep generated public posts free of original source URLs and private source text.
- Keep configuration in `config/base.yaml`, `config/local.yaml`, and environment variables.

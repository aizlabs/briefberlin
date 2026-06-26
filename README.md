# BriefBerlin

Private German learner-article simplification pipeline.

This repository prepares public German A2/B1 learner articles from manually provided source material. Manual source articles are private inputs and must not be committed, logged, uploaded as artifacts, or published as source attribution.

## Privacy Rules

- Keep manual source articles in ignored local paths such as `private-input/`.
- Do not commit original source text, base article JSON, logs, metrics, or audio working files.
- Public posts in `output/_posts/` must contain only generated German learner content.
- GitHub Actions must deploy already-committed public output only; it must not run private/manual generation.

## Development

- Install dependencies: `uv sync`
- Run tests: `uv run pytest`
- Lint: `uv run ruff check`

## Output

The Jekyll site lives under `output/`. Generated posts use CEFR levels `A2` and `B1`, German article text, a `Vokabeln` section when vocabulary exists, and no source attribution.

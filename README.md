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

## Manual Generation

Put private source articles in ignored local files, then run:

```bash
uv run briefberlin-manual private-input/source-1.source.txt private-input/source-2.source.txt
```

Use `--level B1` or repeat `--level A2 --level B1` to override configured levels. Use `--dry-run` to validate without writing a post.

To generate A2 and B1 posts with uploaded website audio in one step:

```bash
uv run briefberlin-publish-source private-input/source-1.source.txt
```

To generate both A2 and B1 posts with local audio artifacts in the same run, enable audio for the
manual pipeline:

```bash
AUDIO_ENABLED=true uv run briefberlin-manual --level A2 --level B1 private-input/source-1.source.txt
```

This requires `OPENAI_API_KEY`. Local audio files are written under `output/audio/` and must remain
uncommitted. To publish playable website audio in post front matter, also enable upload and configure
the audio delivery variables documented in `docs/website-audio-checklist.md`.

## Output

The Jekyll site lives under `output/`. Generated posts use CEFR levels `A2` and `B1`, German article text, a `Vokabeln` section when vocabulary exists, and no source attribution.

Deployment runs through GitHub Pages. See `.github/GITHUB_PAGES_SETUP.md` for `gh run` commands to
check recent and ongoing deployment status.

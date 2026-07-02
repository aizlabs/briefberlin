# Language-Profile Fork Guide

This repository now has a small language profile boundary for runtime settings that are safe to configure without changing behavior:

- `config/base.yaml` → `language.*`
- `scripts.models.LanguageConfig`
- `scripts/language_profiles/` built-in defaults
- glossary heading and locale in publisher, audio, Telegram, and browser glossary metadata
- SpaCy model selection in glossary validation and dormant topic discovery

The built-in profile remains German and preserves current BriefBerlin output.

## Italian Fork Checklist

Set the new profile values first:

```yaml
language:
  target_language: Italian
  target_language_code: it
  locale: it-IT
  learner_native_language: English
  spacy_model: it_core_news_sm
  glossary_heading: Vocabolario
  legacy_glossary_headings:
    - Vokabeln
  prompt_pack: italian
  glossary_rules: italian
  site_name: BriefItalia
```

Then do the fork-specific work that config alone cannot make correct:

- Add and test an Italian prompt pack for synthesis, A2/B1 adaptation, quality judging, and glossary generation.
- Replace German-specific glossary rules: stopwords, named-entity filters, cognate/loanword filters, compound handling, and explanation style.
- Install and verify the Italian SpaCy model (`it_core_news_sm`) in local, CI, and Docker environments.
- Create Italian source fixtures and generated article fixtures.
- Add Italian unit tests for prompts, glossary validation, publishing, audio parsing, and Telegram formatting.
- Add Italian evals with expected A2/B1 outputs and quality thresholds.
- Review public UI strings that are still product-copy decisions, such as glossary popup buttons.
- Re-run full verification: `uv run pytest`, `uv run ruff check`, and `uv run mypy scripts/ --config-file mypy.ini`.

## Compatibility Notes

Generated posts will use `language.glossary_heading` for new output. Parsers can still read legacy headings through `language.legacy_glossary_headings`, so existing German posts remain compatible after a fork changes the heading.

Topic metadata remains language-agnostic: manual source text is summarized by the LLM into a public title and keyword list before generation.

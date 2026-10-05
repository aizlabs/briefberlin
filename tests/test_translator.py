"""Unit tests for ArticleTranslator.

The defining behaviour under test is FAIL-OPEN: one language blowing up must
never cost the other languages, and must never stop the German article from
publishing.
"""

import contextvars
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from scripts.models import AdaptedArticle, VocabularyItem
from scripts.translator import (
    ArticleTranslator,
    TranslationResponse,
    TranslationVocabularyResponse,
)


@pytest.fixture
def article() -> AdaptedArticle:
    return AdaptedArticle(
        title="Linke gewinnt in Berlin",
        content="Erster Absatz über die Wahl in Berlin.\n\nZweiter Absatz über die Folgen.",
        summary="Die Linke wird stärkste Kraft.",
        reading_time=3,
        level="B1",
        vocabulary=[
            VocabularyItem(term="Landtagswahlen", english="state elections",
                           explanation="Wahlen für ein Landesparlament.", default_glossary=True),
            VocabularyItem(term="Bundesregierung", english="federal government",
                           explanation="Die Regierung des ganzen Staates.", default_glossary=True),
        ],
        translation_hints=[
            VocabularyItem(term="Landtagswahlen", english="state elections",
                           explanation="Wahlen für ein Landesparlament.", default_glossary=True),
            VocabularyItem(term="deutlich", english="clearly",
                           explanation="Gut erkennbar.", default_glossary=False),
            VocabularyItem(term="Bundesregierung", english="federal government",
                           explanation="Die Regierung des ganzen Staates.", default_glossary=True),
        ],
    )


def _response(lang: str = "en") -> TranslationResponse:
    return TranslationResponse(
        title=f"The Left wins in Berlin [{lang}]",
        summary="The Left becomes the strongest force.",
        content="First paragraph about the Berlin election.\n\nSecond paragraph about the consequences.",
        vocabulary=[
            TranslationVocabularyResponse(
                term="Landtagswahlen", translation="state elections",
                explanation="Elections for a state parliament."),
            TranslationVocabularyResponse(
                term="Bundesregierung", translation="federal government",
                explanation="The government of the whole country."),
        ],
    )


@pytest.mark.parametrize("level", ["A2", "B1"])
@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize(
    "explicit,translation,adaptation,expected",
    [
        ("reader-model", "translation-model", "adaptation-model", "reader-model"),
        (None, "translation-model", "adaptation-model", "translation-model"),
        (None, None, "adaptation-model", "adaptation-model"),
        (None, None, None, "generation-model"),
    ],
)
@patch("scripts.translator.build_structured_prompt_chain")
def test_cloud_model_fallback_precedence(
    mock_chain, base_config, mock_logger, article,
    explicit, translation, adaptation, expected, direct, level,
):
    article.level = level
    base_config.translations.temperature = 0.37
    base_config.translations.model = explicit
    base_config.llm.models = type(base_config.llm.models)(
        generation="generation-model",
        translation=translation,
        adaptation=adaptation or "",
        quality_check="quality-model",
    )
    mock_chain.return_value.invoke.return_value = _response()
    translator = ArticleTranslator(base_config, mock_logger)
    mock_chain.assert_not_called()

    if direct:
        result = translator.translate_to_language(article, base_config.translations.languages[0])
        assert result.model == expected
    else:
        translated = translator.translate_article(article)
        assert translated.translations
        assert all(item.model == expected for item in translated.translations)
    mock_chain.assert_called_once()
    assert mock_chain.call_args.args[1] == expected
    config, model, temperature, schema = mock_chain.call_args.args
    assert config == base_config.llm.model_dump()
    assert model == expected
    assert temperature == 0.37
    assert schema is TranslationResponse
    response_schema = schema.model_json_schema()
    fields = response_schema["properties"]
    for field in ("title", "summary", "content"):
        assert fields[field]["type"] == "string"
        assert field in response_schema["required"]
    assert fields["vocabulary"]["type"] == "array"
    row_ref = fields["vocabulary"]["items"]["$ref"].split("/")[-1]
    row_schema = response_schema["$defs"][row_ref]
    for field in ("term", "translation", "explanation"):
        assert row_schema["properties"][field]["type"] == "string"
        assert field in row_schema["required"]

    languages = (
        [base_config.translations.languages[0]]
        if direct else base_config.translations.for_level(level)
    )
    submitted = mock_chain.return_value.invoke.call_args_list
    assert len(submitted) == len(languages)
    prompts = [call.args[0]["prompt"] for call in submitted]
    for language in languages:
        matching = [p for p in prompts if f"TARGET LANGUAGE: {language.name}" in p]
        assert len(matching) == 1
        prompt = matching[0]
        for source in (article.title, article.summary, article.content):
            assert source in prompt
        for hint in article.translation_hints:
            for value in (hint.term, hint.english, hint.explanation):
                if hint.default_glossary:
                    assert value in prompt
                else:
                    assert value not in prompt
        # Independent clauses, never an expected prompt from the production helper.
        text = " ".join(prompt.split())
        for clause in (
            "exactly the same number of paragraphs",
            "in the same order",
            "separated by one blank line",
            "one-to-one correspondence",
            "Never merge, split, reorder, summarize, expand",
            "No markdown",
            "no HTML",
            "no buttons, no footnotes",
            "Keep in German form: organisation and institution names",
            "party names and abbreviations",
            "personal names",
            "street/park names",
            "Everything else is ordinary vocabulary and MUST be translated",
            "long German compound",
            "Numbers, percentages, dates, election results and quantities must match the German exactly",
            "echo every `term` back BYTE-IDENTICAL IN GERMAN",
            f"Put the {language.name} rendering in `translation`",
            "rewrite the explanation",
            "one row per input row, in the same order",
            "this does NOT apply to the body",
            "Cyrillic or Arabic script",
            "native-script form",
            "Do NOT leave a Latin-script word sitting inside Cyrillic or Arabic text",
            "Do not insert directional control characters",
            "not mirror punctuation by hand",
        ):
            assert clause in text
        if level == "A2":
            for clause in (
                "CEFR A2", "short sentences, common words",
                "no academic or bureaucratic register",
                "one target sentence per German sentence",
            ):
                assert clause in text
        else:
            for clause in (
                "CEFR B1", "clear, plain news prose", "natural sentence variety",
                "ordinary journalistic vocabulary", "no academic or legalistic register",
            ):
                assert clause in text


@patch("scripts.translator.build_structured_prompt_chain")
def test_translates_every_configured_language_for_the_level(mock_chain, base_config, mock_logger, article):
    chain = MagicMock()
    chain.invoke.return_value = _response()
    mock_chain.return_value = chain

    result = ArticleTranslator(base_config, mock_logger).translate_article(article)

    # 'ru' is restricted to A2, so a B1 article gets only en + ar.
    assert sorted(t.lang for t in result.translations) == ["ar", "en"]
    assert chain.invoke.call_count == 2


@patch("scripts.translator.build_structured_prompt_chain")
def test_level_restricted_language_included_for_its_level(mock_chain, base_config, mock_logger, article):
    chain = MagicMock()
    chain.invoke.return_value = _response()
    mock_chain.return_value = chain

    a2 = article.model_copy(update={"level": "A2"})
    result = ArticleTranslator(base_config, mock_logger).translate_article(a2)

    assert sorted(t.lang for t in result.translations) == ["ar", "en", "ru"]


@patch("scripts.translator.build_structured_prompt_chain")
def test_one_failing_language_does_not_lose_the_others(mock_chain, base_config, mock_logger, article):
    chain = MagicMock()

    def invoke(payload):
        # Key on the TARGET LANGUAGE header, not a bare substring: the prompt body
        # mentions "Arabic script" for every language, so "Arabic" in prompt would
        # match all of them.
        if "TARGET LANGUAGE: Arabic" in payload["prompt"]:
            raise RuntimeError("upstream 500")
        return _response()

    chain.invoke.side_effect = invoke
    mock_chain.return_value = chain

    translator = ArticleTranslator(base_config, mock_logger)
    result = translator.translate_article(article)

    assert [t.lang for t in result.translations] == ["en"]
    assert translator.last_run_stats["failed_languages"] == ["ar"]


@patch("scripts.translator.build_structured_prompt_chain")
def test_total_failure_still_returns_a_publishable_article(mock_chain, base_config, mock_logger, article):
    chain = MagicMock()
    chain.invoke.side_effect = RuntimeError("everything is down")
    mock_chain.return_value = chain

    result = ArticleTranslator(base_config, mock_logger).translate_article(article)

    assert result.translations == []
    assert result.title == article.title
    assert result.content == article.content


@patch("scripts.translator.build_structured_prompt_chain")
def test_disabled_short_circuits_without_calling_the_model(mock_chain, base_config, mock_logger, article):
    base_config.translations.enabled = False

    result = ArticleTranslator(base_config, mock_logger).translate_article(article)

    assert result.translations == []
    mock_chain.assert_not_called()


@patch("scripts.translator.build_structured_prompt_chain")
def test_only_visible_glossary_rows_are_translated(mock_chain, base_config, mock_logger, article):
    chain = MagicMock()
    chain.invoke.return_value = _response()
    mock_chain.return_value = chain

    result = ArticleTranslator(base_config, mock_logger).translate_article(article)
    english = next(t for t in result.translations if t.lang == "en")

    # 'deutlich' is a click-only hint: it has no German word to attach to in a
    # translated body, so it must not be translated.
    assert [item.term for item in english.vocabulary] == ["Landtagswahlen", "Bundesregierung"]


@patch("scripts.translator.build_structured_prompt_chain")
def test_german_headwords_survive_byte_for_byte(mock_chain, base_config, mock_logger, article):
    chain = MagicMock()
    # A model that "helpfully" translates the headword must not be trusted.
    chain.invoke.return_value = TranslationResponse(
        title="T", summary="S",
        content="First paragraph of the translation.\n\nSecond paragraph of the translation.",
        vocabulary=[
            TranslationVocabularyResponse(term="Landtagswahlen", translation="state elections",
                                          explanation="Elections."),
            TranslationVocabularyResponse(term="federal government", translation="federal government",
                                          explanation="Gov."),
        ],
    )
    mock_chain.return_value = chain

    result = ArticleTranslator(base_config, mock_logger).translate_article(article)
    english = next(t for t in result.translations if t.lang == "en")

    assert [item.term for item in english.vocabulary] == ["Landtagswahlen", "Bundesregierung"]
    # The row the model failed to echo is kept, with an empty translation, so the
    # parallel glossary never loses a row.
    assert english.vocabulary[1].translation == ""


@patch("scripts.translator.build_structured_prompt_chain")
def test_reading_time_is_copied_not_re_estimated(mock_chain, base_config, mock_logger, article):
    chain = MagicMock()
    chain.invoke.return_value = _response()
    mock_chain.return_value = chain

    result = ArticleTranslator(base_config, mock_logger).translate_article(article)

    assert all(t.reading_time == article.reading_time for t in result.translations)


@patch("scripts.translator.build_structured_prompt_chain")
def test_markup_is_stripped_from_the_translated_body(mock_chain, base_config, mock_logger, article):
    chain = MagicMock()
    chain.invoke.return_value = TranslationResponse(
        title="**Bold title**", summary="S",
        content="<p>First paragraph of the translation.</p>\n\n**Second paragraph here.**",
        vocabulary=[],
    )
    mock_chain.return_value = chain

    result = ArticleTranslator(base_config, mock_logger).translate_article(article)
    english = next(t for t in result.translations if t.lang == "en")

    assert "**" not in english.content and "<" not in english.content
    assert english.title == "Bold title"


@patch("scripts.translator.build_structured_prompt_chain")
def test_paragraph_mismatch_is_recorded_but_accepted(mock_chain, base_config, mock_logger, article):
    chain = MagicMock()
    chain.invoke.return_value = TranslationResponse(
        title="T", summary="S",
        content="Only one paragraph, where the German source had two.",
        vocabulary=[],
    )
    mock_chain.return_value = chain

    translator = ArticleTranslator(base_config, mock_logger)
    result = translator.translate_article(article)

    # A dropped language is worse for the reader than an imperfect split.
    assert len(result.translations) == 2
    assert set(translator.last_run_stats["paragraph_mismatches"]) == {"en", "ar"}


@patch("scripts.translator.build_structured_prompt_chain")
def test_retries_before_giving_up_on_a_language(mock_chain, base_config, mock_logger, article):
    base_config.translations.languages = [
        lang for lang in base_config.translations.languages if lang.code == "en"
    ]
    chain = MagicMock()
    chain.invoke.side_effect = [RuntimeError("transient"), _response()]
    mock_chain.return_value = chain

    result = ArticleTranslator(base_config, mock_logger).translate_article(article)

    assert [t.lang for t in result.translations] == ["en"]
    assert chain.invoke.call_count == 2


# Regression guard for the usage-accounting context bug: copy_context() must be
# evaluated in the SUBMITTING thread. Evaluated inside the worker it snapshots
# the worker's own empty context, and every translation call silently vanishes
# from the run cost report.
_usage_probe = contextvars.ContextVar("usage_probe", default="MISSING")


@patch("scripts.translator.build_structured_prompt_chain")
def test_usage_context_reaches_worker_threads(mock_chain, base_config, mock_logger, article):
    seen = []
    chain = MagicMock()

    def invoke(_payload):
        seen.append(_usage_probe.get())
        return _response()

    chain.invoke.side_effect = invoke
    mock_chain.return_value = chain

    token = _usage_probe.set("ACTIVE")
    try:
        ArticleTranslator(base_config, mock_logger).translate_article(article)
    finally:
        _usage_probe.reset(token)

    assert seen and all(value == "ACTIVE" for value in seen), (
        "translation calls ran without the caller's context; token usage would be "
        "dropped from the cost report"
    )


@patch("scripts.translator.build_structured_prompt_chain")
def test_usage_context_reaches_workers_when_caller_is_itself_a_worker(
    mock_chain, base_config, mock_logger, article
):
    """The pipeline can invoke this from inside another pool worker."""
    seen = []
    chain = MagicMock()

    def invoke(_payload):
        seen.append(_usage_probe.get())
        return _response()

    chain.invoke.side_effect = invoke
    mock_chain.return_value = chain

    translator = ArticleTranslator(base_config, mock_logger)

    token = _usage_probe.set("ACTIVE")
    try:
        ctx = contextvars.copy_context()
        with ThreadPoolExecutor(1) as pool:
            pool.submit(ctx.run, translator.translate_article, article).result()
    finally:
        _usage_probe.reset(token)

    assert seen and all(value == "ACTIVE" for value in seen)

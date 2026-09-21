"""Unit tests for ArticleTranslator.

The defining behaviour under test is FAIL-OPEN: one language blowing up must
never cost the other languages, and must never stop the German article from
publishing.
"""

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
        if "Arabic" in payload["prompt"]:
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

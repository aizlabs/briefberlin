"""Publisher behaviour for reader-language translations."""

from datetime import datetime

import pytest

from scripts.models import (
    AdaptedArticle,
    ArticleTranslation,
    TranslatedVocabularyItem,
    VocabularyItem,
)
from scripts.publisher import Publisher

TIMESTAMP = datetime(2026, 9, 21, 5, 24, 10)


def _translation(lang: str, heading: str, title: str) -> ArticleTranslation:
    return ArticleTranslation(
        lang=lang,
        glossary_heading=heading,
        title=title,
        summary="A translated summary of the article.",
        content="First translated paragraph.\n\nSecond translated paragraph.",
        vocabulary=[
            TranslatedVocabularyItem(
                term="Landtagswahlen", translation="state elections",
                explanation="Elections for a state parliament."),
        ],
        reading_time=3,
    )


@pytest.fixture
def article() -> AdaptedArticle:
    return AdaptedArticle(
        title="Linke gewinnt in Berlin und setzt Regierung unter Druck",
        content="Erster Absatz über die Landtagswahlen.\n\nZweiter Absatz über die Folgen.",
        summary="Die Linke wird stärkste Kraft in Berlin.",
        reading_time=3,
        level="B1",
        category="Politik",
        author="clara-becker",
        vocabulary=[
            VocabularyItem(term="Landtagswahlen", english="state elections",
                           explanation="Wahlen für ein Landesparlament.", default_glossary=True),
        ],
        translations=[
            _translation("en", "Vocabulary", "The Left wins in Berlin"),
            _translation("ar", "المفردات", "اليسار يفوز في برلين"),
        ],
    )


@pytest.fixture
def publisher(base_config, mock_logger, tmp_path) -> Publisher:
    base_config.output = {"path": str(tmp_path / "_posts"), "default_author": "clara-becker"}
    base_config.translations.output_path = str(tmp_path / "_translations")
    return Publisher(base_config, mock_logger)


def test_ref_matches_jekylls_slugified_title(publisher, article):
    """Jekyll collapses runs of non-alphanumerics, so `unter--b1` publishes as
    `unter-b1`. Deriving the ref any other way 404s every translation link."""
    ref = publisher._post_ref(article, TIMESTAMP)

    assert ref == "052410-linke-gewinnt-in-berlin-und-setzt-regierung-unter-b1"
    assert "--" not in ref
    # ...while the post filename keeps its historical double dash.
    assert publisher._generate_filename(article, TIMESTAMP).startswith("2026-09-21-052410-")


def test_writes_one_file_per_language_under_the_ref_directory(publisher, article, tmp_path):
    publisher.save_article(article, timestamp=TIMESTAMP)

    ref = publisher._post_ref(article, TIMESTAMP)
    base = tmp_path / "_translations" / ref
    assert sorted(p.name for p in base.glob("*.md")) == ["ar.md", "en.md"]


def test_arabic_title_still_yields_an_ascii_path(publisher, article, tmp_path):
    """slugify_text is ASCII-only, so a slugified Arabic title would be ""."""
    publisher.save_article(article, timestamp=TIMESTAMP)

    ref = publisher._post_ref(article, TIMESTAMP)
    assert (tmp_path / "_translations" / ref / "ar.md").exists()


def test_translations_map_is_identical_everywhere_and_includes_de_and_self(publisher, article, tmp_path):
    publisher.save_article(article, timestamp=TIMESTAMP)
    ref = publisher._post_ref(article, TIMESTAMP)

    expected = [
        f"  de: /articles/{ref}/",
        f"  en: /articles/{ref}/en/",
        f"  ar: /articles/{ref}/ar/",
    ]
    german = (tmp_path / "_posts" / publisher._generate_filename(article, TIMESTAMP)).read_text("utf-8")
    for line in expected:
        assert line in german

    for lang in ("en", "ar"):
        text = (tmp_path / "_translations" / ref / f"{lang}.md").read_text("utf-8")
        for line in expected:
            assert line in text, f"{lang} is missing {line}"


def test_translated_page_frontmatter(publisher, article, tmp_path):
    publisher.save_article(article, timestamp=TIMESTAMP)
    ref = publisher._post_ref(article, TIMESTAMP)
    text = (tmp_path / "_translations" / ref / "ar.md").read_text("utf-8")

    assert "lang: ar" in text
    assert f"ref: {ref}" in text
    assert 'source_title: "Linke gewinnt in Berlin und setzt Regierung unter Druck"' in text
    assert 'glossary_heading: "المفردات"' in text
    assert 'category: "Politik"' in text
    assert "reading_time: 3" in text
    # The URL comes from the file's location; a permalink key would be a second
    # source of truth. A canonical_url would de-index every translation.
    assert "permalink:" not in text
    assert "canonical_url:" not in text


def test_translated_body_has_no_german_hint_markup(publisher, article, tmp_path):
    publisher.save_article(article, timestamp=TIMESTAMP)
    ref = publisher._post_ref(article, TIMESTAMP)
    text = (tmp_path / "_translations" / ref / "en.md").read_text("utf-8")

    assert "<button" not in text
    assert "article-glossary-data" not in text
    assert "data-term-id" not in text


def test_translated_glossary_keeps_german_headword_marked_ltr(publisher, article, tmp_path):
    publisher.save_article(article, timestamp=TIMESTAMP)
    ref = publisher._post_ref(article, TIMESTAMP)
    text = (tmp_path / "_translations" / ref / "ar.md").read_text("utf-8")

    assert "## المفردات" in text
    assert '<strong lang="de" dir="ltr">Landtagswahlen</strong>' in text
    assert "## Vokabeln" not in text


def test_resaving_overwrites_instead_of_duplicating(publisher, article, tmp_path):
    publisher.save_article(article, timestamp=TIMESTAMP)
    publisher.save_article(article, timestamp=TIMESTAMP)

    ref = publisher._post_ref(article, TIMESTAMP)
    assert len(list((tmp_path / "_translations" / ref).glob("*.md"))) == 2


def test_article_without_translations_emits_no_translations_key(publisher, article, tmp_path):
    """Regression guard for every existing frontmatter assertion."""
    bare = article.model_copy(update={"translations": []})

    publisher.save_article(bare, timestamp=TIMESTAMP)

    text = (tmp_path / "_posts" / publisher._generate_filename(bare, TIMESTAMP)).read_text("utf-8")
    assert "translations:" not in text
    assert not (tmp_path / "_translations").joinpath(publisher._post_ref(bare, TIMESTAMP)).exists()


def test_translation_write_failure_does_not_fail_the_german_post(publisher, article, monkeypatch):
    """A False return triggers a 'Publishing failed' alert upstream."""
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(publisher, "save_translations", boom)

    assert publisher.save_article(article, timestamp=TIMESTAMP) is True

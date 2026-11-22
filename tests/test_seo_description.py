"""Search-snippet descriptions: always name Berlin, always fit the snippet."""

import pytest

from scripts.seo_description import (
    MAX_DESCRIPTION_CHARS,
    finalize_seo_description,
    mentions_city,
)


@pytest.mark.parametrize(
    "text",
    [
        "Streik bei der BVG in Berlin.",
        "Berliner Linke will Emde nicht mehr im Parlament.",
        "Protest in Berlins Mitte.",
        "Strajk w Berlinie.",
        "Berlin'de grev var.",
        "Забастовка в Берлине.",
        "Страйк у Берліні.",
        "إضراب في برلين.",
        "Huelga en Berlín.",
        "Sciopero a Berlino.",
    ],
)
def test_detects_inflected_city_names(text):
    assert mentions_city(text)


def test_adds_localized_city_when_missing():
    assert finalize_seo_description("Café Kranzler öffnet neu.", "de") == (
        "Berlin aktuell: Café Kranzler öffnet neu."
    )
    assert finalize_seo_description("Кафе Kranzler открывается.", "ru").startswith(
        "Новости Берлина: "
    )
    assert finalize_seo_description("Kranzler riapre.", "it").startswith("Notizie da Berlino: ")
    assert finalize_seo_description("Kranzler rouvre.", "fr").startswith(
        "Actualités de Berlin : "
    )


def test_unknown_language_falls_back_to_berlin():
    assert finalize_seo_description("Kranzler.", "nl") == "Berlin news: Kranzler."


def test_strips_markdown_emphasis():
    assert finalize_seo_description("Die **Mieten** in Berlin steigen.", "de") == (
        "Die Mieten in Berlin steigen."
    )


def test_keeps_existing_mention_unchanged():
    text = "Streik bei der BVG in Berlin am Donnerstag."
    assert finalize_seo_description(text, "de") == text


def test_empty_stays_empty():
    assert finalize_seo_description("  ", "de") == ""


def test_collapses_whitespace():
    assert finalize_seo_description("In Berlin\n  gibt es  Streit.", "de") == (
        "In Berlin gibt es Streit."
    )


def test_truncates_at_word_boundary_with_ellipsis():
    text = "In Berlin " + "sehr lange Beschreibung " * 20
    result = finalize_seo_description(text, "de")

    assert len(result) <= MAX_DESCRIPTION_CHARS
    assert result.endswith("…")
    assert text.startswith(result[:-1])
    assert not result[:-1].endswith(" ")


def test_truncates_at_sentence_end_when_late_enough():
    first = "In Berlin streiken heute die Beschäftigten der BVG, und viele Busse und Bahnen fahren nicht bis zum späten Abend."
    text = first + " Ein zweiter Satz mit vielen weiteren Details folgt hier."
    assert finalize_seo_description(text, "de") == first


def test_is_deterministic_for_level_pairing():
    text = "Kranzler " * 40
    assert finalize_seo_description(text, "de") == finalize_seo_description(text, "de")


# -- backfill ---------------------------------------------------------------

from scripts.backfill_seo_descriptions import drop_truncated_tail, rewrite_description  # noqa: E402

POST = """---
title: "Estrel Tower"
level: A2
topics: &id001 [Estrel]
description: Der Estrel Tower steht an der Sonnenallee. Das Hochhaus
  ist 176 Meter hoch und hat 45 Etagen. Es soll das höchste Gebäude...
keywords: *id001
---

Body stays **untouched**.
"""


def test_drop_truncated_tail_falls_back_to_last_full_sentence():
    assert drop_truncated_tail("Erster Satz. Zweiter Satz ist abgebroch...") == "Erster Satz."
    assert drop_truncated_tail("Nur ein Satz ohne Ende...") == "Nur ein Satz ohne Ende..."
    assert drop_truncated_tail("Fertig.") == "Fertig."


def test_rewrite_replaces_only_the_folded_description_entry():
    new_content, _, new = rewrite_description(POST, "de")

    assert new == (
        "Berlin aktuell: Der Estrel Tower steht an der Sonnenallee. "
        "Das Hochhaus ist 176 Meter hoch und hat 45 Etagen."
    )
    assert f'description: "{new}"\nkeywords: *id001\n' in new_content
    assert new_content.endswith("---\n\nBody stays **untouched**.\n")
    assert "  ist 176" not in new_content


def test_rewrite_skips_posts_without_level_and_already_good_ones():
    assert rewrite_description(POST.replace("level: A2\n", ""), "de") is None
    good = 'description: "Streik bei der BVG in Berlin."'
    assert rewrite_description(f"---\nlevel: A2\n{good}\n---\nx\n", "de") is None


def test_backfill_is_idempotent_after_word_boundary_cut():
    # A short first sentence, so a second run could wrongly fall back to it.
    long_sentence = "Streit in Berlin. Es gibt " + "eine sehr lange Debatte " * 8 + "."
    post = f'---\nlevel: B1\ndescription: "{long_sentence}"\n---\nx\n'
    once, _, _ = rewrite_description(post, "de")
    assert rewrite_description(once, "de") is None

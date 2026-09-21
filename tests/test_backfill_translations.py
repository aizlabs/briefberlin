"""Tests for the translation backfill script.

The script is shipped but not run: the existing archive stays German-only until
someone asks for it. These tests keep it honest in the meantime.
"""

from pathlib import Path

from scripts.backfill_translations import (
    append_translations_block,
    load_post,
    missing_languages,
    post_ref,
    recover_article,
    recover_vocabulary,
    rewrite_sibling_maps,
    sibling_map,
)

HEADINGS = ["Vokabeln"]

POST = """---
title: "Linke gewinnt in Berlin"
date: 2026-09-21 05:24:10
author: "clara-becker"
level: B1
category: "Politik"
summary: "Die Linke wird stärkste Kraft."
audio:
  url: "https://media.example/a.mp3"
  mime_type: "audio/mpeg"
reading_time: 3
---

Bei den <button type="button" class="article-term article-term--default" \
data-term-id="term-1">Landtagswahlen</button> hat sich viel verändert.

Die <button type="button" class="article-term" data-term-id="term-2">Lage</button> bleibt offen.

<script type="application/json" class="article-glossary-data" \
data-glossary-heading="Vokabeln" data-glossary-locale="de-DE">\
[{"id":"term-1","term":"Landtagswahlen","english":"state elections",\
"explanation":"Wahlen für ein Landesparlament.","defaultGlossary":true},\
{"id":"term-2","term":"Lage","english":"situation",\
"explanation":"Die aktuelle Situation.","defaultGlossary":false}]</script>

## Vokabeln

- **Landtagswahlen** - state elections - Wahlen für ein Landesparlament.

---
*Vereinfachter Artikel zu Lernzwecken.*
"""


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "2026-09-21-052410-linke-gewinnt-in-berlin-unter--b1.md"
    path.write_text(POST, encoding="utf-8")
    return path


def test_post_ref_matches_jekylls_slugified_title(tmp_path):
    assert post_ref(_write(tmp_path)) == "052410-linke-gewinnt-in-berlin-unter-b1"


def test_body_recovery_strips_all_generated_markup(tmp_path):
    _, data, body = load_post(_write(tmp_path))
    article = recover_article(data, body, HEADINGS)

    assert "<button" not in article.content
    assert "article-glossary-data" not in article.content
    assert "Landtagswahlen" in article.content
    assert "## Vokabeln" not in article.content
    assert article.level == "B1"
    assert article.reading_time == 3


def test_glossary_is_recovered_from_the_json_payload(tmp_path):
    _, _, body = load_post(_write(tmp_path))
    items = recover_vocabulary(body, HEADINGS)

    # The payload is authoritative because it carries defaultGlossary.
    assert [i.term for i in items] == ["Landtagswahlen", "Lage"]
    assert [i.default_glossary for i in items] == [True, False]


def test_glossary_falls_back_to_the_rendered_list_for_older_posts(tmp_path):
    path = tmp_path / "2026-01-01-000000-old-post-b1.md"
    path.write_text(
        POST.split('<script type="application/json"')[0]
        + "\n## Vokabeln\n\n- **Landtagswahlen** - state elections - Wahlen für ein Parlament.\n",
        encoding="utf-8",
    )
    _, _, body = load_post(path)
    items = recover_vocabulary(body, HEADINGS)

    assert [i.term for i in items] == ["Landtagswahlen"]
    assert items[0].english == "state elections"
    assert items[0].default_glossary is True


def test_missing_languages_detection(tmp_path):
    ref = "052410-x-b1"
    (tmp_path / ref).mkdir(parents=True)
    (tmp_path / ref / "en.md").write_text("x", encoding="utf-8")

    assert missing_languages(tmp_path, ref, ["en", "ar"], overwrite=False) == ["ar"]
    assert missing_languages(tmp_path, ref, ["en", "ar"], overwrite=True) == ["en", "ar"]


def test_append_translations_block_preserves_all_other_bytes(tmp_path):
    frontmatter, _, _ = load_post(_write(tmp_path))

    updated = append_translations_block(
        frontmatter, {"de": "/articles/x/", "en": "/articles/x/en/"}
    )

    # Every original line survives verbatim: re-dumping the YAML would reflow the
    # quoting and the nested audio mapping across the whole archive.
    for line in frontmatter.splitlines():
        assert line in updated
    assert "translations:\n  de: /articles/x/\n  en: /articles/x/en/" in updated


def test_append_translations_block_replaces_an_existing_map(tmp_path):
    frontmatter, _, _ = load_post(_write(tmp_path))
    once = append_translations_block(frontmatter, {"de": "/a/", "en": "/a/en/"})
    twice = append_translations_block(once, {"de": "/a/", "en": "/a/en/", "ar": "/a/ar/"})

    assert twice.count("translations:") == 1
    assert "  ar: /a/ar/" in twice


def test_sibling_map_is_built_from_disk_not_from_this_runs_subset(tmp_path):
    """An incremental run must not drop previously generated languages.

    Regression guard: building the map from article.translations (only the
    languages just generated) silently removed every earlier language from the
    German post's selector and broke hreflang reciprocity.
    """
    ref = "052410-x-b1"
    (tmp_path / ref).mkdir(parents=True)
    for code in ("en", "ru"):
        (tmp_path / ref / f"{code}.md").write_text("---\nlang: x\n---\nbody\n", encoding="utf-8")

    urls = sibling_map(tmp_path, ref, ["en", "tr", "ru", "ar"])

    assert list(urls) == ["de", "en", "ru"]
    assert urls["de"] == f"/articles/{ref}/"
    assert urls["ru"] == f"/articles/{ref}/ru/"


def test_sibling_map_keeps_languages_no_longer_configured(tmp_path):
    """A page that exists must stay reachable even if dropped from config."""
    ref = "052410-x-b1"
    (tmp_path / ref).mkdir(parents=True)
    (tmp_path / ref / "vi.md").write_text("---\nlang: vi\n---\nbody\n", encoding="utf-8")

    urls = sibling_map(tmp_path, ref, ["en"])

    assert "vi" in urls


def test_rewrite_sibling_maps_makes_every_sibling_agree(tmp_path):
    """All siblings must advertise an identical set or hreflang stops being
    reciprocal and Google discards the cluster."""
    ref = "052410-x-b1"
    (tmp_path / ref).mkdir(parents=True)
    # en.md carries a stale, smaller map from an earlier run
    (tmp_path / ref / "en.md").write_text(
        "---\nlang: en\ntranslations:\n  de: /articles/x/\n  en: /articles/x/en/\n---\nbody\n",
        encoding="utf-8",
    )
    (tmp_path / ref / "ar.md").write_text("---\nlang: ar\n---\nbody\n", encoding="utf-8")

    urls = sibling_map(tmp_path, ref, ["en", "ar"])
    count = rewrite_sibling_maps(tmp_path, ref, urls)

    assert count == 2
    for code in ("en", "ar"):
        text = (tmp_path / ref / f"{code}.md").read_text(encoding="utf-8")
        assert text.count("translations:") == 1
        for sibling in ("de", "en", "ar"):
            assert f"  {sibling}: /articles/{ref}/{sibling}/".replace("/de/", "/") in text
        assert "lang: " + code in text


def test_recover_article_carries_the_german_audio(tmp_path):
    """Translated pages deliberately keep the German track so the reader can
    listen in German while reading their own language. Dropping audio here
    silently removed the player from every backfilled translation."""
    path = _write(tmp_path)
    _, data, body = load_post(path)

    article = recover_article(data, body, HEADINGS)

    assert article.audio is not None
    assert article.audio.url == "https://media.example/a.mp3"
    assert article.audio.mime_type == "audio/mpeg"

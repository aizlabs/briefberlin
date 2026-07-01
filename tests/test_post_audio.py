from pathlib import Path

import pytest

from scripts.models import AudioAsset
from scripts.post_audio import build_article_from_post, update_post_audio


def _write_public_post(repo_root: Path, filename: str = "2026-06-27-test-a2.md") -> Path:
    post_path = repo_root / "output" / "_posts" / filename
    post_path.parent.mkdir(parents=True, exist_ok=True)
    post_path.write_text(
        """---
title: Test Artikel
date: 2026-06-27 01:35:05
level: A2
topics:
- deutsch
sources: []
audio: null
reading_time: 2
---

In Berlin gibt es eine neue Meinung. Eine Umfrage zeigt neue Pläne.

Der zweite Absatz bleibt Teil des Artikels.
## Vokabeln

- **Umfrage** - survey - Eine Befragung von Menschen.

---
*Vereinfachter Artikel zu Lernzwecken.*
""",
        encoding="utf-8",
    )
    return post_path


def test_build_article_from_post_uses_public_article_body_and_vocabulary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    post_path = _write_public_post(tmp_path)

    article, timestamp, frontmatter, body = build_article_from_post(post_path)

    assert article.title == "Test Artikel"
    assert article.level == "A2"
    assert article.summary == "In Berlin gibt es eine neue Meinung."
    assert "## Vokabeln" not in article.content
    assert "*Vereinfachter Artikel" not in article.content
    assert article.vocabulary[0].term == "Umfrage"
    assert article.vocabulary[0].english == "survey"
    assert timestamp.strftime("%Y-%m-%d %H:%M:%S") == "2026-06-27 01:35:05"
    assert frontmatter["audio"] is None
    assert "## Vokabeln" in body


def test_build_article_from_post_strips_interactive_glossary_markup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    post_path = _write_public_post(tmp_path, filename="2026-06-27-glossary-a2.md")
    post_path.write_text(
        """---
title: Test Artikel
date: 2026-06-27 01:35:05
level: A2
topics:
- deutsch
sources: []
audio: null
reading_time: 2
---

In Berlin gibt es eine <button type="button" class="article-term" data-term-id="term-1">Umfrage</button>. Viele Menschen lesen die Ergebnisse.

<script type="application/json" class="article-glossary-data">[{"id":"term-1","term":"Umfrage"}]</script>

## Vokabeln

- **Umfrage** - survey - Eine Befragung von Menschen.

---
*Vereinfachter Artikel zu Lernzwecken.*
""",
        encoding="utf-8",
    )

    article, _timestamp, _frontmatter, _body = build_article_from_post(post_path)

    assert article.content == "In Berlin gibt es eine Umfrage. Viele Menschen lesen die Ergebnisse."
    assert article.summary == "In Berlin gibt es eine Umfrage."
    assert "article-glossary-data" not in article.content
    assert "<button" not in article.content


def test_build_article_from_post_rejects_paths_outside_public_posts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    private_path = tmp_path / "private-input" / "article.source.txt"
    private_path.parent.mkdir(parents=True)
    private_path.write_text("not a public post", encoding="utf-8")

    with pytest.raises(ValueError, match="output/_posts"):
        build_article_from_post(private_path)


def test_update_post_audio_writes_audio_frontmatter_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    post_path = _write_public_post(tmp_path)
    _article, _timestamp, frontmatter, body = build_article_from_post(post_path)

    update_post_audio(
        post_path,
        AudioAsset(
            url="https://media.briefberlin.de/articles/test/article.mp3",
            format="mp3",
            mime_type="audio/mpeg",
            provider="openai",
            voice="alloy",
        ),
        frontmatter,
        body,
    )

    updated = post_path.read_text(encoding="utf-8")
    assert "audio:\n  url: https://media.briefberlin.de/articles/test/article.mp3" in updated
    assert "mime_type: audio/mpeg" in updated
    assert "In Berlin gibt es eine neue Meinung. Eine Umfrage zeigt neue Pläne." in updated

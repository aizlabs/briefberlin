from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from urllib import error

from scripts.publish_telegram_channel import (
    TelegramPost,
    build_article_url,
    format_telegram_message,
    parse_jekyll_post,
    publish_posts,
    send_telegram_audio,
    send_telegram_message,
)

POST_TEMPLATE = """---
title: "Deutschland baut mehr Windenergie aus"
date: 2026-03-17 04:09:15
level: A2
topics: ["windenergie"]
sources:
- name: "tagesschau.de"
  url: "https://tagesschau.de"
reading_time: 2
---

Deutschland baut mehr **Windenergie** aus. Das hilft bei der Energiewende.

Neue **Windräder** produzieren sauberen Strom für viele Haushalte.

## Vokabeln

- **Windenergie** - wind energy - Strom aus der Kraft des Windes
- **Windräder** - wind turbines - große Anlagen, die mit Wind Strom machen

---
*Vereinfachter Artikel zu Lernzwecken.*
"""

POST_WITH_AUDIO_TEMPLATE = """---
title: "Deutschland baut mehr Windenergie aus"
date: 2026-03-17 04:09:15
level: A2
topics: ["windenergie"]
sources:
- name: "tagesschau.de"
  url: "https://tagesschau.de"
audio:
  url: "https://media.briefberlin.de/articles/2026/03/windenergie-a2/article.mp3"
  format: "mp3"
  mime_type: "audio/mpeg"
  provider: "openai"
  voice: "alloy"
  duration_seconds: 105
reading_time: 2
---

Deutschland baut mehr **Windenergie** aus. Das hilft bei der Energiewende.

---
*Vereinfachter Artikel zu Lernzwecken.*
"""


class DummyResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self) -> bytes:
        return self.payload


def write_post(tmp_path: Path, name: str, content: str = POST_TEMPLATE) -> Path:
    post_path = tmp_path / name
    post_path.write_text(content, encoding="utf-8")
    return post_path


def write_site_config(tmp_path: Path, *, url: str = "https://briefberlin.de", baseurl: str = "") -> Path:
    config_path = tmp_path / "_config.yml"
    config_path.write_text(
        f'title: "BriefBerlin"\nurl: "{url}"\nbaseurl: "{baseurl}"\n',
        encoding="utf-8",
    )
    return config_path


def test_parse_jekyll_post_extracts_frontmatter_body_and_vocabulary(tmp_path):
    post_path = write_post(tmp_path, "2026-03-17-040915-windenergie-a2.md")

    post = parse_jekyll_post(post_path)

    assert post.title == "Deutschland baut mehr Windenergie aus"
    assert post.level == "A2"
    assert post.reading_time == 2
    assert post.paragraphs == [
        "Deutschland baut mehr **Windenergie** aus. Das hilft bei der Energiewende.",
        "Neue **Windräder** produzieren sauberen Strom für viele Haushalte.",
    ]
    assert post.vocabulary_lines == [
        "- **Windenergie** - wind energy - Strom aus der Kraft des Windes",
        "- **Windräder** - wind turbines - große Anlagen, die mit Wind Strom machen",
    ]
    assert post.audio_url is None


def test_parse_jekyll_post_strips_interactive_glossary_markup(tmp_path):
    post_path = write_post(
        tmp_path,
        "2026-03-17-040915-windenergie-a2.md",
        content="""---
title: "Deutschland baut mehr Windenergie aus"
date: 2026-03-17 04:09:15
level: A2
topics: ["windenergie"]
reading_time: 2
---

Deutschland baut mehr <button type="button" class="article-term" data-term-id="term-1">Windenergie</button> aus.

<script type="application/json" class="article-glossary-data">[{"id":"term-1","term":"Windenergie"}]</script>

## Vokabeln

- **Windenergie** - wind energy - Strom aus der Kraft des Windes

---
*Vereinfachter Artikel zu Lernzwecken.*
""",
    )

    post = parse_jekyll_post(post_path)

    assert post.paragraphs == ["Deutschland baut mehr Windenergie aus."]
    assert "article-glossary-data" not in "\n".join(post.paragraphs)
    assert "<button" not in "\n".join(post.paragraphs)


def test_parse_jekyll_post_extracts_audio_frontmatter(tmp_path):
    post_path = write_post(
        tmp_path,
        "2026-03-17-040915-windenergie-a2.md",
        content=POST_WITH_AUDIO_TEMPLATE,
    )

    post = parse_jekyll_post(post_path)

    assert post.audio_url == "https://media.briefberlin.de/articles/2026/03/windenergie-a2/article.mp3"
    assert post.audio_mime_type == "audio/mpeg"
    assert post.audio_duration_seconds == 105


def test_build_article_url_uses_timestamped_slug_and_site_config(tmp_path):
    config_path = write_site_config(tmp_path, url="https://example.com", baseurl="/briefberlin")
    post_path = tmp_path / "2026-03-17-040915-windenergie-a2.md"

    article_url = build_article_url(post_path, config_path)

    assert article_url == "https://example.com/briefberlin/articles/040915-windenergie-a2/"


def test_format_telegram_message_converts_markdown_and_omits_source_footer():
    post = TelegramPost(
        path=Path("output/_posts/2026-03-17-040915-windenergie-a2.md"),
        title="Deutschland baut mehr Windenergie aus",
        level="A2",
        reading_time=2,
        paragraphs=[
            "Deutschland baut mehr **Windenergie** aus.",
            "Neue **Windräder** produzieren Strom.",
        ],
        vocabulary_lines=["- **Windenergie** - wind energy - Strom aus der Kraft des Windes"],
    )

    message = format_telegram_message(post, "https://example.com/articles/040915-windenergie-a2/")

    assert "<b>Deutschland baut mehr Windenergie aus</b>" in message
    assert "<i>A2 • 2 min</i>" in message
    assert "<b>Windenergie</b>" in message
    assert "<b>Windräder</b>" in message
    assert "<b>Vokabeln</b>" in message
    assert "• <b>Windenergie</b> - wind energy - Strom aus der Kraft des Windes" in message
    assert "**Windenergie**" not in message
    assert "Fuentes" not in message
    assert 'href="https://example.com/articles/040915-windenergie-a2/"' in message


def test_format_telegram_message_trims_at_boundaries_and_preserves_link():
    repeated_paragraph = " ".join(["Wort"] * 25)
    post = TelegramPost(
        path=Path("output/_posts/2026-03-17-040915-windenergie-a2.md"),
        title="Langer Titel",
        level="B1",
        reading_time=3,
        paragraphs=[
            f"Erster Absatz {repeated_paragraph}",
            f"Zweiter Absatz {repeated_paragraph}",
            f"Dritter Absatz {repeated_paragraph}",
        ],
        vocabulary_lines=[
            "- **Begriff eins** - first definition",
            "- **Begriff zwei** - second definition",
        ],
    )

    message = format_telegram_message(
        post,
        "https://example.com/articles/040915-windenergie-a2/",
        limit=360,
    )

    assert len(message) <= 360
    assert "Erster Absatz" in message
    assert "Dritter Absatz" not in message
    assert "..." in message
    assert 'href="https://example.com/articles/040915-windenergie-a2/"' in message


def test_publish_posts_sends_messages_in_filename_order(tmp_path):
    config_path = write_site_config(tmp_path)
    later_post = write_post(tmp_path, "2026-03-17-184500-segundo-b1.md")
    earlier_post = write_post(tmp_path, "2026-03-17-040915-primero-a2.md")
    sent_messages: list[str] = []

    def fake_send(bot_token: str, chat_id: str, message: str) -> None:
        assert bot_token == "bot-token"
        assert chat_id == "channel-id"
        sent_messages.append(message)

    publish_posts(
        [later_post, earlier_post],
        config_path=config_path,
        bot_token="bot-token",
        chat_id="channel-id",
        send_func=fake_send,
    )

    assert len(sent_messages) == 2
    assert sent_messages[0].startswith("<b>Deutschland baut mehr Windenergie aus</b>")
    assert 'href="https://briefberlin.de/articles/040915-primero-a2/"' in sent_messages[0]
    assert 'href="https://briefberlin.de/articles/184500-segundo-b1/"' in sent_messages[1]


def test_publish_posts_sends_audio_when_post_has_audio_url(tmp_path):
    config_path = write_site_config(tmp_path)
    post_path = write_post(
        tmp_path,
        "2026-03-17-040915-windenergie-a2.md",
        content=POST_WITH_AUDIO_TEMPLATE,
    )
    sent_messages: list[str] = []
    sent_audio: list[tuple[TelegramPost, str]] = []

    def fake_send(bot_token: str, chat_id: str, message: str) -> None:
        sent_messages.append(message)

    def fake_send_audio(
        bot_token: str,
        chat_id: str,
        post: TelegramPost,
        article_url: str,
    ) -> None:
        assert bot_token == "bot-token"
        assert chat_id == "channel-id"
        sent_audio.append((post, article_url))

    publish_posts(
        [post_path],
        config_path=config_path,
        bot_token="bot-token",
        chat_id="channel-id",
        send_func=fake_send,
        audio_send_func=fake_send_audio,
    )

    assert sent_messages == []
    assert len(sent_audio) == 1
    post, article_url = sent_audio[0]
    assert post.title == "Deutschland baut mehr Windenergie aus"
    assert post.audio_url == "https://media.briefberlin.de/articles/2026/03/windenergie-a2/article.mp3"
    assert article_url == "https://briefberlin.de/articles/040915-windenergie-a2/"


def test_send_telegram_audio_uses_audio_metadata_and_web_button():
    captured_payloads: list[dict] = []

    post = TelegramPost(
        path=Path("output/_posts/2026-03-17-040915-windenergie-a2.md"),
        title="Deutschland baut mehr Windenergie aus",
        level="A2",
        reading_time=2,
        paragraphs=[],
        vocabulary_lines=[],
        audio_url="https://media.briefberlin.de/articles/2026/03/windenergie-a2/article.mp3",
        audio_mime_type="audio/mpeg",
        audio_duration_seconds=105,
    )

    def fake_opener(req, timeout):  # noqa: ANN001, ANN002
        assert req.full_url == "https://api.telegram.org/botbot-token/sendAudio"
        captured_payloads.append(json.loads(req.data.decode("utf-8")))
        return DummyResponse(b'{"ok": true, "result": {"message_id": 1}}')

    send_telegram_audio(
        "bot-token",
        "channel-id",
        post,
        "https://example.com/articles/040915-windenergie-a2/",
        opener=fake_opener,
    )

    assert captured_payloads == [
        {
            "chat_id": "channel-id",
            "audio": "https://media.briefberlin.de/articles/2026/03/windenergie-a2/article.mp3",
            "title": "Deutschland baut mehr Windenergie aus",
            "performer": "BriefBerlin • A2",
            "caption": "<b>Deutschland baut mehr Windenergie aus</b>\n<i>A2 • 2 min</i>",
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "Im Web lesen",
                            "url": "https://example.com/articles/040915-windenergie-a2/",
                        }
                    ]
                ]
            },
            "duration": 105,
        }
    ]


def test_send_telegram_message_retries_on_429_with_retry_after():
    attempts = {"count": 0}
    sleep_calls: list[float] = []

    def fake_opener(req, timeout):  # noqa: ANN001, ANN002
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise error.HTTPError(
                req.full_url,
                429,
                "Too Many Requests",
                hdrs=None,
                fp=BytesIO(b'{"ok": false, "parameters": {"retry_after": 7}}'),
            )
        return DummyResponse(b'{"ok": true, "result": {"message_id": 1}}')

    send_telegram_message(
        "bot-token",
        "channel-id",
        "hola",
        opener=fake_opener,
        sleep=sleep_calls.append,
    )

    assert attempts["count"] == 2
    assert sleep_calls == [7]


def test_send_telegram_message_retries_on_500():
    attempts = {"count": 0}
    sleep_calls: list[float] = []

    def fake_opener(req, timeout):  # noqa: ANN001, ANN002
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise error.HTTPError(
                req.full_url,
                500,
                "Internal Server Error",
                hdrs=None,
                fp=BytesIO(b'{"ok": false, "description": "server error"}'),
            )
        return DummyResponse(b'{"ok": true, "result": {"message_id": 1}}')

    send_telegram_message(
        "bot-token",
        "channel-id",
        "hola",
        opener=fake_opener,
        sleep=sleep_calls.append,
    )

    assert attempts["count"] == 2
    assert sleep_calls == [1]

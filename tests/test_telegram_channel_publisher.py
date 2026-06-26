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
title: "España tiene menos contaminación"
date: 2026-03-17 04:09:15
level: A2
topics: ["espana"]
sources:
- name: "elpais.com"
  url: "https://elpais.com"
reading_time: 2
---

España reduce sus emisiones de CO2. Esto ayuda al **medio ambiente**.

El país usa más **energías renovables** para producir electricidad.

## Vokabeln

- **medio ambiente** - environment - la naturaleza que nos rodea
- **energías renovables** - renewable energy - energía del sol y del viento

---
*Vereinfachter Artikel zu Lernzwecken.*
"""

POST_WITH_AUDIO_TEMPLATE = """---
title: "España tiene menos contaminación"
date: 2026-03-17 04:09:15
level: A2
topics: ["espana"]
sources:
- name: "elpais.com"
  url: "https://elpais.com"
audio:
  url: "https://media.briefberlin.com/articles/2026/03/espana-a2/article.mp3"
  format: "mp3"
  mime_type: "audio/mpeg"
  provider: "openai"
  voice: "alloy"
  duration_seconds: 105
reading_time: 2
---

España reduce sus emisiones de CO2. Esto ayuda al **medio ambiente**.

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


def write_site_config(tmp_path: Path, *, url: str = "https://briefberlin.com", baseurl: str = "") -> Path:
    config_path = tmp_path / "_config.yml"
    config_path.write_text(
        f'title: "BriefBerlin"\nurl: "{url}"\nbaseurl: "{baseurl}"\n',
        encoding="utf-8",
    )
    return config_path


def test_parse_jekyll_post_extracts_frontmatter_body_and_vocabulary(tmp_path):
    post_path = write_post(tmp_path, "2026-03-17-040915-espana-a2.md")

    post = parse_jekyll_post(post_path)

    assert post.title == "España tiene menos contaminación"
    assert post.level == "A2"
    assert post.reading_time == 2
    assert post.paragraphs == [
        "España reduce sus emisiones de CO2. Esto ayuda al **medio ambiente**.",
        "El país usa más **energías renovables** para producir electricidad.",
    ]
    assert post.vocabulary_lines == [
        "- **medio ambiente** - environment - la naturaleza que nos rodea",
        "- **energías renovables** - renewable energy - energía del sol y del viento",
    ]
    assert post.audio_url is None


def test_parse_jekyll_post_extracts_audio_frontmatter(tmp_path):
    post_path = write_post(
        tmp_path,
        "2026-03-17-040915-espana-a2.md",
        content=POST_WITH_AUDIO_TEMPLATE,
    )

    post = parse_jekyll_post(post_path)

    assert post.audio_url == "https://media.briefberlin.com/articles/2026/03/espana-a2/article.mp3"
    assert post.audio_mime_type == "audio/mpeg"
    assert post.audio_duration_seconds == 105


def test_build_article_url_uses_timestamped_slug_and_site_config(tmp_path):
    config_path = write_site_config(tmp_path, url="https://example.com", baseurl="/briefberlin")
    post_path = tmp_path / "2026-03-17-040915-espana-a2.md"

    article_url = build_article_url(post_path, config_path)

    assert article_url == "https://example.com/briefberlin/articles/040915-espana-a2/"


def test_format_telegram_message_converts_markdown_and_omits_source_footer():
    post = TelegramPost(
        path=Path("output/_posts/2026-03-17-040915-espana-a2.md"),
        title="España tiene menos contaminación",
        level="A2",
        reading_time=2,
        paragraphs=[
            "España reduce sus emisiones. Esto ayuda al **medio ambiente**.",
            "El país usa más **energías renovables**.",
        ],
        vocabulary_lines=["- **medio ambiente** - environment - la naturaleza que nos rodea"],
    )

    message = format_telegram_message(post, "https://example.com/articles/040915-espana-a2/")

    assert "<b>España tiene menos contaminación</b>" in message
    assert "<i>A2 • 2 min</i>" in message
    assert "<b>medio ambiente</b>" in message
    assert "<b>energías renovables</b>" in message
    assert "<b>Vokabeln</b>" in message
    assert "• <b>medio ambiente</b> - environment - la naturaleza que nos rodea" in message
    assert "**medio ambiente**" not in message
    assert "Fuentes" not in message
    assert 'href="https://example.com/articles/040915-espana-a2/"' in message


def test_format_telegram_message_trims_at_boundaries_and_preserves_link():
    repeated_paragraph = " ".join(["palabra"] * 25)
    post = TelegramPost(
        path=Path("output/_posts/2026-03-17-040915-espana-a2.md"),
        title="Título largo",
        level="B1",
        reading_time=3,
        paragraphs=[
            f"Primer párrafo {repeated_paragraph}",
            f"Segundo párrafo {repeated_paragraph}",
            f"Tercer párrafo {repeated_paragraph}",
        ],
        vocabulary_lines=[
            "- **término uno** - primera definición",
            "- **término dos** - segunda definición",
        ],
    )

    message = format_telegram_message(
        post,
        "https://example.com/articles/040915-espana-a2/",
        limit=360,
    )

    assert len(message) <= 360
    assert "Primer párrafo" in message
    assert "Tercer párrafo" not in message
    assert "..." in message
    assert 'href="https://example.com/articles/040915-espana-a2/"' in message


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
    assert sent_messages[0].startswith("<b>España tiene menos contaminación</b>")
    assert 'href="https://briefberlin.com/articles/040915-primero-a2/"' in sent_messages[0]
    assert 'href="https://briefberlin.com/articles/184500-segundo-b1/"' in sent_messages[1]


def test_publish_posts_sends_audio_when_post_has_audio_url(tmp_path):
    config_path = write_site_config(tmp_path)
    post_path = write_post(
        tmp_path,
        "2026-03-17-040915-espana-a2.md",
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
    assert post.title == "España tiene menos contaminación"
    assert post.audio_url == "https://media.briefberlin.com/articles/2026/03/espana-a2/article.mp3"
    assert article_url == "https://briefberlin.com/articles/040915-espana-a2/"


def test_send_telegram_audio_uses_audio_metadata_and_web_button():
    captured_payloads: list[dict] = []

    post = TelegramPost(
        path=Path("output/_posts/2026-03-17-040915-espana-a2.md"),
        title="España tiene menos contaminación",
        level="A2",
        reading_time=2,
        paragraphs=[],
        vocabulary_lines=[],
        audio_url="https://media.briefberlin.com/articles/2026/03/espana-a2/article.mp3",
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
        "https://example.com/articles/040915-espana-a2/",
        opener=fake_opener,
    )

    assert captured_payloads == [
        {
            "chat_id": "channel-id",
            "audio": "https://media.briefberlin.com/articles/2026/03/espana-a2/article.mp3",
            "title": "España tiene menos contaminación",
            "performer": "BriefBerlin • A2",
            "caption": "<b>España tiene menos contaminación</b>\n<i>A2 • 2 min</i>",
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "Im Web lesen",
                            "url": "https://example.com/articles/040915-espana-a2/",
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

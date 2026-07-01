#!/usr/bin/env python3
"""Publish generated Jekyll posts to a Telegram channel."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, Iterable, List, Sequence
from urllib import error, request

import yaml

from scripts.text_utils import strip_article_ui_markup

TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_AUDIO_CAPTION_LIMIT = 1024
TELEGRAM_AUDIO_TITLE_LIMIT = 128
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_RETRIES = 3


@dataclass(frozen=True)
class TelegramPost:
    """Structured data extracted from a Jekyll post."""

    path: Path
    title: str
    level: str
    reading_time: int
    paragraphs: List[str]
    vocabulary_lines: List[str]
    audio_url: str | None = None
    audio_mime_type: str | None = None
    audio_duration_seconds: int | None = None


def _strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _extract_frontmatter_value(frontmatter: str, key: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}:\s*(.+)$", re.MULTILINE)
    match = pattern.search(frontmatter)
    if not match:
        raise ValueError(f"Missing frontmatter value: {key}")
    return _strip_wrapping_quotes(match.group(1))


def _parse_frontmatter(frontmatter: str) -> dict[str, Any]:
    parsed = yaml.safe_load(frontmatter) or {}
    if not isinstance(parsed, dict):
        raise ValueError("Post frontmatter must be a YAML mapping")
    return parsed


def _required_frontmatter_string(frontmatter: dict[str, Any], key: str) -> str:
    value = frontmatter.get(key)
    if value is None:
        raise ValueError(f"Missing frontmatter value: {key}")
    return str(value)


def _required_frontmatter_int(frontmatter: dict[str, Any], key: str) -> int:
    value = frontmatter.get(key)
    if value is None:
        raise ValueError(f"Missing frontmatter value: {key}")
    return int(value)


def _optional_frontmatter_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_frontmatter_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _extract_audio_metadata(frontmatter: dict[str, Any]) -> tuple[str | None, str | None, int | None]:
    audio = frontmatter.get("audio")
    if not isinstance(audio, dict):
        return None, None, None

    return (
        _optional_frontmatter_string(audio.get("url")),
        _optional_frontmatter_string(audio.get("mime_type")),
        _optional_frontmatter_int(audio.get("duration_seconds")),
    )


def _split_frontmatter(content: str) -> tuple[str, str]:
    if not content.startswith("---\n"):
        raise ValueError("Post is missing YAML frontmatter")

    end_index = content.find("\n---\n", 4)
    if end_index == -1:
        raise ValueError("Post frontmatter is not terminated")

    frontmatter = content[4:end_index]
    body = content[end_index + len("\n---\n") :]
    return frontmatter, body.lstrip()


def _strip_attribution_footer(body: str) -> str:
    if "\n\n---\n" in body:
        return body.split("\n\n---\n", 1)[0].rstrip()
    return body.rstrip()


def parse_jekyll_post(path: Path) -> TelegramPost:
    """Extract the Telegram-relevant content from a generated Jekyll post."""

    raw_content = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw_content)
    frontmatter_values = _parse_frontmatter(frontmatter)
    audio_url, audio_mime_type, audio_duration_seconds = _extract_audio_metadata(frontmatter_values)
    article_body = _strip_attribution_footer(body)

    vocabulary_lines: List[str] = []
    if "\n## Vokabeln\n\n" in article_body:
        main_text, vocabulary_block = article_body.split("\n## Vokabeln\n\n", 1)
        vocabulary_lines = [line.strip() for line in vocabulary_block.splitlines() if line.strip()]
    else:
        main_text = article_body

    clean_main_text = strip_article_ui_markup(main_text)
    paragraphs = [
        paragraph.strip()
        for paragraph in clean_main_text.split("\n\n")
        if paragraph.strip()
    ]

    return TelegramPost(
        path=path,
        title=_required_frontmatter_string(frontmatter_values, "title"),
        level=_required_frontmatter_string(frontmatter_values, "level"),
        reading_time=_required_frontmatter_int(frontmatter_values, "reading_time"),
        paragraphs=paragraphs,
        vocabulary_lines=vocabulary_lines,
        audio_url=audio_url,
        audio_mime_type=audio_mime_type,
        audio_duration_seconds=audio_duration_seconds,
    )


def load_site_config(config_path: Path) -> tuple[str, str]:
    """Read the minimal site URL configuration needed for Telegram links."""

    raw_config = config_path.read_text(encoding="utf-8")
    url = _extract_frontmatter_value(raw_config, "url")
    baseurl = ""

    baseurl_match = re.search(r"^baseurl:\s*(.+)$", raw_config, re.MULTILINE)
    if baseurl_match:
        baseurl = _strip_wrapping_quotes(baseurl_match.group(1))

    return url.rstrip("/"), baseurl.strip()


def build_article_url(post_path: Path, config_path: Path) -> str:
    """Build the canonical article URL from the current Jekyll slug convention."""

    site_url, baseurl = load_site_config(config_path)
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", post_path.stem)

    normalized_baseurl = baseurl.strip("/")
    base = site_url
    if normalized_baseurl:
        base = f"{base}/{normalized_baseurl}"

    return f"{base}/articles/{slug}/"


def markdown_to_telegram_html(text: str) -> str:
    """Convert the limited markdown produced by the pipeline into Telegram HTML."""

    bold_pattern = re.compile(r"\*\*(.+?)\*\*")
    parts: List[str] = []
    last_index = 0

    for match in bold_pattern.finditer(text):
        parts.append(escape(text[last_index : match.start()]))
        parts.append(f"<b>{escape(match.group(1))}</b>")
        last_index = match.end()

    parts.append(escape(text[last_index:]))
    return "".join(parts)


def _format_vocabulary_line(line: str) -> str:
    line_match = re.match(r"^- \*\*(.+?)\*\* - (.+)$", line)
    if line_match:
        term, definition = line_match.groups()
        return f"• <b>{escape(term)}</b> - {markdown_to_telegram_html(definition)}"

    cleaned_line = line[2:] if line.startswith("- ") else line
    return f"• {markdown_to_telegram_html(cleaned_line)}"


def _render_message(
    post: TelegramPost,
    article_url: str,
    body_blocks: List[str],
    vocabulary_blocks: List[str],
    trimmed: bool,
) -> str:
    header = "\n".join(
        [
            f"<b>{escape(post.title)}</b>",
            f"<i>{escape(post.level)} • {post.reading_time} min</i>",
        ]
    )

    sections = [header]

    if body_blocks:
        sections.append("\n\n".join(body_blocks))

    if vocabulary_blocks:
        glossary = "<b>Vokabeln</b>\n" + "\n".join(vocabulary_blocks)
        sections.append(glossary)

    if trimmed:
        sections.append("...")

    sections.append(f'<a href="{escape(article_url, quote=True)}">Leer en la web</a>')

    return "\n\n".join(sections)


def format_telegram_message(post: TelegramPost, article_url: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> str:
    """Render a Telegram-safe HTML message, trimming at paragraph/list boundaries when needed."""

    body_blocks = [markdown_to_telegram_html(paragraph) for paragraph in post.paragraphs]
    vocabulary_blocks = [_format_vocabulary_line(line) for line in post.vocabulary_lines]

    full_message = _render_message(post, article_url, body_blocks, vocabulary_blocks, trimmed=False)
    if len(full_message) <= limit:
        return full_message

    blocks = [("body", block) for block in body_blocks] + [("vocab", block) for block in vocabulary_blocks]
    selected: List[tuple[str, str]] = []

    for index, block in enumerate(blocks):
        tentative = selected + [block]
        remaining_blocks = index < len(blocks) - 1
        candidate_message = _render_message(
            post,
            article_url,
            [text for kind, text in tentative if kind == "body"],
            [text for kind, text in tentative if kind == "vocab"],
            trimmed=remaining_blocks,
        )
        if len(candidate_message) <= limit:
            selected = tentative
            continue
        break

    trimmed_message = _render_message(
        post,
        article_url,
        [text for kind, text in selected if kind == "body"],
        [text for kind, text in selected if kind == "vocab"],
        trimmed=True,
    )

    if len(trimmed_message) <= limit:
        return trimmed_message

    minimal_message = _render_message(post, article_url, [], [], trimmed=True)
    if len(minimal_message) <= limit:
        return minimal_message

    raise ValueError(f"Unable to fit Telegram message within {limit} characters for {post.path}")


def _extract_retry_after(payload: str) -> int | None:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None

    parameters = parsed.get("parameters", {})
    retry_after = parameters.get("retry_after")
    if isinstance(retry_after, int) and retry_after >= 0:
        return retry_after
    return None


def _should_retry_status_code(status_code: int | None) -> bool:
    if not isinstance(status_code, int):
        return False
    return status_code == 429 or 500 <= status_code < 600


def _build_telegram_request(bot_token: str, chat_id: str, message: str) -> request.Request:
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    body = json.dumps(payload).encode("utf-8")
    return request.Request(
        url=f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _trim_telegram_field(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def format_telegram_audio_caption(post: TelegramPost) -> str:
    """Render the compact caption used under Telegram audio cards."""

    title = _trim_telegram_field(post.title, TELEGRAM_AUDIO_TITLE_LIMIT)
    metadata = f"{post.level} • {post.reading_time} min"

    while True:
        caption = "\n".join(
            [
                f"<b>{escape(title)}</b>",
                f"<i>{escape(metadata)}</i>",
            ]
        )
        if len(caption) <= TELEGRAM_AUDIO_CAPTION_LIMIT or len(title) <= 1:
            return caption
        title = _trim_telegram_field(title, len(title) - 1)


def _build_telegram_audio_request(
    bot_token: str,
    chat_id: str,
    post: TelegramPost,
    article_url: str,
) -> request.Request:
    if not post.audio_url:
        raise ValueError(f"Post does not have an audio URL: {post.path}")

    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "audio": post.audio_url,
        "title": _trim_telegram_field(post.title, TELEGRAM_AUDIO_TITLE_LIMIT),
        "performer": f"BriefBerlin • {post.level}",
        "caption": format_telegram_audio_caption(post),
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "Im Web lesen",
                        "url": article_url,
                    }
                ]
            ]
        },
    }
    if post.audio_duration_seconds is not None:
        payload["duration"] = post.audio_duration_seconds

    body = json.dumps(payload).encode("utf-8")
    return request.Request(
        url=f"https://api.telegram.org/bot{bot_token}/sendAudio",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _send_telegram_request(
    request_obj: request.Request,
    *,
    timeout: int,
    retries: int,
    opener: Callable[..., object],
    sleep: Callable[[float], None],
) -> None:
    """Send a prepared Telegram API request with retry handling."""

    for attempt in range(retries + 1):
        try:
            response = opener(request_obj, timeout=timeout)
            with response:
                payload = response.read().decode("utf-8")
        except error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            retry_after = _extract_retry_after(payload)
            should_retry = _should_retry_status_code(exc.code)
            if should_retry and attempt < retries:
                sleep(retry_after if retry_after is not None else 2 ** attempt)
                continue
            raise RuntimeError(f"Telegram API request failed with HTTP {exc.code}: {payload}") from exc
        except error.URLError as exc:
            if attempt < retries:
                sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Telegram API request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Telegram API returned invalid JSON: {payload}") from exc

        if parsed.get("ok") is True:
            return

        retry_after = _extract_retry_after(payload)
        status_code = parsed.get("error_code")
        should_retry = _should_retry_status_code(status_code)
        if should_retry and attempt < retries:
            sleep(retry_after if retry_after is not None else 2 ** attempt)
            continue

        raise RuntimeError(f"Telegram API returned an error response: {payload}")


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    message: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    opener: Callable[..., object] = request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Send a Telegram message with retry handling for throttling and transient failures."""

    request_obj = _build_telegram_request(bot_token, chat_id, message)
    _send_telegram_request(
        request_obj,
        timeout=timeout,
        retries=retries,
        opener=opener,
        sleep=sleep,
    )


def send_telegram_audio(
    bot_token: str,
    chat_id: str,
    post: TelegramPost,
    article_url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRIES,
    opener: Callable[..., object] = request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Send an article audio card to Telegram with identifying metadata."""

    request_obj = _build_telegram_audio_request(bot_token, chat_id, post, article_url)
    _send_telegram_request(
        request_obj,
        timeout=timeout,
        retries=retries,
        opener=opener,
        sleep=sleep,
    )


def publish_posts(
    post_paths: Iterable[Path],
    *,
    config_path: Path,
    bot_token: str,
    chat_id: str,
    send_func: Callable[[str, str, str], None] = send_telegram_message,
    audio_send_func: Callable[[str, str, TelegramPost, str], None] = send_telegram_audio,
) -> int:
    """Publish a sequence of posts to Telegram in deterministic filename order."""

    published_count = 0

    for post_path in sorted(Path(path) for path in post_paths):
        post = parse_jekyll_post(post_path)
        article_url = build_article_url(post_path, config_path)
        if post.audio_url:
            audio_send_func(bot_token, chat_id, post, article_url)
        else:
            message = format_telegram_message(post, article_url)
            send_func(bot_token, chat_id, message)
        published_count += 1

    return published_count


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        print("Usage: publish_telegram_channel.py <post1> [<post2> ...]", file=sys.stderr)
        return 1

    bot_token = os.getenv("TELEGRAM_PUBLISH_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_PUBLISH_CHAT_ID")
    if not bot_token or not chat_id:
        print(
            "TELEGRAM_PUBLISH_BOT_TOKEN and TELEGRAM_PUBLISH_CHAT_ID must both be set",
            file=sys.stderr,
        )
        return 1

    try:
        published_count = publish_posts(
            [Path(arg) for arg in argv],
            config_path=Path("output/_config.yml"),
            bot_token=bot_token,
            chat_id=chat_id,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Telegram channel publish failed: {exc}", file=sys.stderr)
        return 1

    print(f"Published {published_count} article(s) to Telegram")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

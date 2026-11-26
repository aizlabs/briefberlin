#!/usr/bin/env python3
"""Sends one message to the BriefBerlin Telegram chat straight through the Telegram Bot API.

Why not `openclaw message send`:
- it also writes to the agent's chat session, which collides with the gateway
  (ReplySessionInitConflictError) and loses the agent's "command finished" results;
- it wraps button values as plugin-only callbacks ("tgcb1:..."), so taps end in
  "This action is no longer available." and never reach the agent.
Plain callback_data sent from here arrives at the agent as `callback_data: <value>`.

Usage: bb_tg.py [--markdown] [--button LABEL=VALUE ...] TEXT
The bot token is read from OpenClaw's config and is never printed.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid

CONFIG = "/opt/openclaw/.openclaw/openclaw.json"
TARGET = os.environ.get("BB_TELEGRAM_TARGET", "/opt/openclaw/work/.bb-telegram-target")


def _token() -> str:
    token = os.environ.get("BB_TELEGRAM_BOT_TOKEN")
    if token:
        return token
    with open(CONFIG, encoding="utf-8") as f:
        token = json.load(f).get("channels", {}).get("telegram", {}).get("botToken")
    if not isinstance(token, str) or ":" not in token:
        raise RuntimeError("no usable Telegram bot token in the OpenClaw config")
    return token


def markdown_to_html(text: str) -> str:
    """Supports the two markers the previews use: **bold** and _italic_."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out, flags=re.S)
    return re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", out)


def send(text: str, buttons: list[tuple[str, str]] | None = None, markdown: bool = False) -> int:
    """Sends a message, optionally with one row of buttons; returns the Telegram message id."""
    with open(TARGET, encoding="utf-8") as f:
        chat = f.read().strip()
    body: dict = {"chat_id": chat, "text": text, "link_preview_options": {"is_disabled": True}}
    if markdown:
        body["text"] = markdown_to_html(text)
        body["parse_mode"] = "HTML"
    if buttons:
        for _, value in buttons:
            if not value or len(value.encode()) > 64:
                raise RuntimeError(f"button value must be 1-64 bytes: {value!r}")
        body["reply_markup"] = {
            "inline_keyboard": [[{"text": label, "callback_data": value} for label, value in buttons]]
        }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{_token()}/sendMessage",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as err:
        try:
            description = json.load(err).get("description", "")
        except ValueError:
            description = ""
        raise RuntimeError(f"Telegram API HTTP {err.code}: {description}") from None
    except urllib.error.URLError as err:
        raise RuntimeError(f"Telegram API unreachable: {err.reason}") from None
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result.get('description')}")
    return int(result["result"]["message_id"])


def _call(method: str, data: bytes, content_type: str) -> dict:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{_token()}/{method}",
        data=data,
        headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as err:
        try:
            description = json.load(err).get("description", "")
        except ValueError:
            description = ""
        raise RuntimeError(f"Telegram API HTTP {err.code}: {description}") from None
    except urllib.error.URLError as err:
        raise RuntimeError(f"Telegram API unreachable: {err.reason}") from None
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result.get('description')}")
    return result


def send_photo(path: str, caption: str = "") -> int:
    """Sends an image file (WebP/PNG/JPEG) as a photo; returns the Telegram message id."""
    with open(TARGET, encoding="utf-8") as f:
        chat = f.read().strip()
    with open(path, "rb") as f:
        image = f.read()
    boundary = uuid.uuid4().hex
    fields = {"chat_id": chat}
    if caption:
        fields["caption"] = caption[:1000]
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    filename = path.rsplit("/", 1)[-1]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    body = b"".join(parts) + image + f"\r\n--{boundary}--\r\n".encode()
    result = _call("sendPhoto", body, f"multipart/form-data; boundary={boundary}")
    return int(result["result"]["message_id"])


def main(argv: list[str]) -> int:
    markdown, buttons, rest = False, [], []
    args = iter(argv)
    for arg in args:
        if arg == "--markdown":
            markdown = True
        elif arg == "--button":
            label, _, value = next(args, "").partition("=")
            buttons.append((label, value))
        else:
            rest.append(arg)
    if len(rest) != 1:
        print("usage: bb_tg.py [--markdown] [--button LABEL=VALUE ...] TEXT", file=sys.stderr)
        return 2
    try:
        message_id = send(rest[0], buttons, markdown)
    except (OSError, RuntimeError) as err:
        print(f"Telegram send failed: {err}", file=sys.stderr)
        return 1
    print(f"SENT {message_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

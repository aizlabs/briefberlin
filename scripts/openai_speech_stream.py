"""Exact OpenAI speech usage capture through the speech SSE stream."""

from __future__ import annotations

import base64
import binascii
import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SpeechTokenUsage:
    """Billable text-input and audio-output token usage for one speech request."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


def supports_speech_usage_stream(model: str) -> bool:
    """Return whether the configured OpenAI speech model supports SSE usage events."""
    return model == "gpt-4o-mini-tts" or model.startswith("gpt-4o-mini-tts-")


def synthesize_speech_sse(
    client: Any,
    *,
    input_text: str,
    model: str,
    voice: str,
    response_format: str,
    destination: Path,
) -> SpeechTokenUsage | None:
    """Stream speech audio atomically and return exact usage from the done event."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    done_seen = False
    usage: SpeechTokenUsage | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temp_path = Path(output.name)
            response = client.audio.speech.with_streaming_response.create(
                input=input_text,
                model=model,
                voice=voice,
                response_format=response_format,
                stream_format="sse",
            )
            with response as stream:
                for event in iter_sse_json_events(stream.iter_lines()):
                    event_type = str(event.get("type") or "")
                    if event_type == "speech.audio.delta":
                        if done_seen:
                            raise ValueError("OpenAI speech stream emitted audio after completion")
                        output.write(_decode_audio_delta(event))
                    elif event_type == "speech.audio.done":
                        if done_seen:
                            raise ValueError("OpenAI speech stream emitted duplicate completion")
                        done_seen = True
                        usage = _parse_usage(event.get("usage"))
                    elif event_type == "error":
                        raise RuntimeError(_format_error_event(event))

            if not done_seen:
                raise ValueError("OpenAI speech stream ended without speech.audio.done")
            output.flush()
            os.fsync(output.fileno())

        os.replace(temp_path, destination)
        temp_path = None
        return usage
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def iter_sse_json_events(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Parse JSON data objects from a stream of Server-Sent Event lines."""
    data_lines: list[str] = []
    event_name: str | None = None

    def build_event() -> dict[str, Any] | None:
        nonlocal data_lines, event_name
        if not data_lines:
            event_name = None
            return None
        payload = "\n".join(data_lines)
        data_lines = []
        current_name = event_name
        event_name = None
        if payload == "[DONE]":
            return None
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in OpenAI speech SSE event: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI speech SSE data must be a JSON object")
        if current_name and not parsed.get("type"):
            parsed["type"] = current_name
        return parsed

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            event = build_event()
            if event is not None:
                yield event
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            continue
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event_name = value
        elif field == "data":
            data_lines.append(value)

    event = build_event()
    if event is not None:
        yield event


def _decode_audio_delta(event: Mapping[str, Any]) -> bytes:
    encoded = event.get("audio")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("OpenAI speech audio delta is missing base64 audio data")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("OpenAI speech audio delta contains invalid base64") from exc


def _parse_usage(raw_usage: Any) -> SpeechTokenUsage | None:
    if raw_usage is None:
        return None
    if not isinstance(raw_usage, Mapping):
        raise ValueError("OpenAI speech completion usage must be an object")
    try:
        input_tokens = int(raw_usage["input_tokens"])
        output_tokens = int(raw_usage["output_tokens"])
        total_tokens = int(raw_usage["total_tokens"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("OpenAI speech completion usage is incomplete") from exc
    if min(input_tokens, output_tokens, total_tokens) < 0:
        raise ValueError("OpenAI speech completion usage cannot contain negative tokens")
    if total_tokens != input_tokens + output_tokens:
        raise ValueError("OpenAI speech completion total tokens do not match input plus output")
    return SpeechTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _format_error_event(event: Mapping[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        if message:
            return f"OpenAI speech stream failed: {message}"
    return "OpenAI speech stream failed"

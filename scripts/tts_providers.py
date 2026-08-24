"""Provider-neutral text-to-speech adapters."""

from __future__ import annotations

import base64
import binascii
import logging
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests
from openai import OpenAI

from scripts.config import AppConfig
from scripts.models import AudioWordCue
from scripts.openai_speech_stream import supports_speech_usage_stream, synthesize_speech_sse


@dataclass(frozen=True)
class TTSUsage:
    """Provider-neutral billable usage returned by a speech request."""

    input_tokens: int = 0
    output_tokens: int = 0
    input_characters: int = 0


@dataclass(frozen=True)
class TTSResult:
    """Speech output plus optional word timing and usage metadata."""

    cues: list[AudioWordCue] | None = None
    usage: TTSUsage | None = None
    usage_note: str | None = None
    timing_note: str | None = None


class TTSProvider(Protocol):
    """Uniform interface implemented by each speech provider."""

    name: str
    model: str
    voice: str

    def synthesize(
        self, text: str, destination: Path, audio_format: str, *, level: str | None = None
    ) -> TTSResult:
        """Write speech to destination and return optional provider metadata."""


class OpenAITTSProvider:
    """OpenAI speech adapter. OpenAI currently does not return word timings."""

    name = "openai"

    def __init__(self, config: AppConfig, client: Any | None = None):
        self.model = config.audio.resolved_model()
        self.voice = config.audio.resolved_voice()
        self._model_configs = config.llm.usage_reporting.prices.get("openai", {})
        if client is not None:
            self.client = client
        else:
            api_key = config.llm.openai_api_key
            if not api_key:
                raise ValueError("OpenAI TTS requires OPENAI_API_KEY to be configured")
            self.client = OpenAI(api_key=api_key)

    def synthesize(
        self, text: str, destination: Path, audio_format: str, *, level: str | None = None
    ) -> TTSResult:
        response_format = _openai_response_format(audio_format)
        if supports_speech_usage_stream(self.model, self._model_configs):
            result = synthesize_speech_sse(
                self.client,
                input_text=text,
                model=self.model,
                voice=self.voice,
                response_format=response_format,
                destination=destination,
            )
            usage = None
            if result.usage is not None:
                usage = TTSUsage(
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                )
            return TTSResult(usage=usage, usage_note=result.usage_note)

        response = self.client.audio.speech.create(
            input=text,
            model=self.model,
            voice=self.voice,
            response_format=response_format,
        )
        response.write_to_file(destination)
        return TTSResult(
            usage_note="the configured speech model does not expose exact usage through SSE.",
            timing_note="OpenAI speech generation did not return word timings.",
        )


class ElevenLabsTTSProvider:
    """ElevenLabs adapter using the native speech-with-timestamps endpoint."""

    name = "elevenlabs"
    api_base_url = "https://api.elevenlabs.io/v1"

    def __init__(self, config: AppConfig, client: Any | None = None):
        provider_config = config.audio.providers.elevenlabs
        self.model = config.audio.resolved_model()
        self.voice = config.audio.resolved_voice()
        self.output_format = provider_config.output_format
        self.speed_by_level = {
            level.strip().lower(): speed
            for level, speed in provider_config.speed_by_level.items()
        }
        self.api_key = provider_config.api_key
        if not self.api_key:
            raise ValueError("ElevenLabs TTS requires ELEVENLABS_API_KEY to be configured")
        self.client = client or requests.Session()

    def synthesize(
        self, text: str, destination: Path, audio_format: str, *, level: str | None = None
    ) -> TTSResult:
        if audio_format != "mp3" or not self.output_format.startswith("mp3_"):
            raise ValueError(
                "ElevenLabs currently requires audio.format=mp3 and an mp3 output format"
            )

        response = self.client.post(
            f"{self.api_base_url}/text-to-speech/{self.voice}/with-timestamps",
            params={"output_format": self.output_format},
            headers={
                "xi-api-key": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": self.model,
                **self._voice_settings(level),
            },
            timeout=120,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ValueError(
                "ElevenLabs TTS request failed with "
                f"HTTP {response.status_code}: {_elevenlabs_error_detail(response)}"
            ) from exc
        payload = response.json()
        encoded_audio = payload.get("audio_base64") if isinstance(payload, dict) else None
        if not isinstance(encoded_audio, str) or not encoded_audio:
            raise ValueError("ElevenLabs response did not contain audio_base64")
        try:
            audio_bytes = base64.b64decode(encoded_audio, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("ElevenLabs returned invalid base64 audio") from exc
        _write_bytes_atomically(destination, audio_bytes)

        cues: list[AudioWordCue] | None = None
        timing_note: str | None = None
        try:
            cues = _word_cues_from_alignment(text, payload.get("alignment"))
        except (TypeError, ValueError) as exc:
            timing_note = f"ElevenLabs timing alignment was ignored: {exc}"

        return TTSResult(
            cues=cues,
            usage=TTSUsage(input_characters=len(text)),
            usage_note="ElevenLabs usage is measured in input characters.",
            timing_note=timing_note,
        )

    def _voice_settings(self, level: str | None) -> dict[str, dict[str, float]]:
        if level is None:
            return {}
        speed = self.speed_by_level.get(level.strip().lower())
        return {"voice_settings": {"speed": speed}} if speed is not None else {}


def build_tts_provider(
    config: AppConfig,
    *,
    client: Any | None = None,
    logger: logging.Logger | None = None,
) -> TTSProvider:
    """Build the configured provider without leaking provider details to callers."""
    provider = config.audio.provider.strip().lower()
    if provider == "openai":
        return OpenAITTSProvider(config, client=client)
    if provider == "elevenlabs":
        return ElevenLabsTTSProvider(config, client=client)
    if logger:
        logger.error("Unsupported audio provider '%s'", config.audio.provider)
    raise ValueError(f"Unsupported audio provider: {config.audio.provider}")


def _word_cues_from_alignment(text: str, alignment: Any) -> list[AudioWordCue]:
    if not isinstance(alignment, dict):
        raise ValueError("alignment is missing")
    characters = alignment.get("characters")
    starts = alignment.get("character_start_times_seconds")
    ends = alignment.get("character_end_times_seconds")
    if not isinstance(characters, list) or not isinstance(starts, list) or not isinstance(ends, list):
        raise ValueError("alignment arrays are missing")
    if not characters or len(characters) != len(starts) or len(starts) != len(ends):
        raise ValueError("alignment arrays have inconsistent lengths")
    if not all(isinstance(character, str) for character in characters):
        raise ValueError("alignment contains a non-string character")
    if "".join(characters) != text:
        raise ValueError("alignment text does not match the narration")

    numeric_starts = [_timestamp(value) for value in starts]
    numeric_ends = [_timestamp(value) for value in ends]
    previous_start = 0.0
    previous_end = 0.0
    for start, end in zip(numeric_starts, numeric_ends, strict=True):
        if start < previous_start or end < previous_end or end < start:
            raise ValueError("alignment timestamps are not monotonic")
        previous_start = start
        previous_end = end

    return [
        AudioWordCue(
            text=match.group(0),
            text_start=match.start(),
            text_end=match.end(),
            start_seconds=numeric_starts[match.start()],
            end_seconds=numeric_ends[match.end() - 1],
        )
        for match in re.finditer(r"\S+", text)
    ]


def _timestamp(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("alignment contains an invalid timestamp")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("alignment contains an invalid timestamp") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("alignment contains an invalid timestamp")
    return number


def _elevenlabs_error_detail(response: Any) -> str:
    """Extract a concise provider error without exposing request credentials or narration."""
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None

    detail: Any = None
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error") or payload.get("message")
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("detail") or detail.get("status")

    if not detail:
        detail = getattr(response, "text", "")

    normalized = " ".join(str(detail).split())
    return normalized[:1000] or "ElevenLabs did not return an error detail"


def _write_bytes_atomically(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temp_path = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _openai_response_format(format_name: str) -> str:
    response_formats = {"mp3": "mp3", "m4a": "aac", "wav": "wav"}
    try:
        return response_formats[format_name]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported audio format for OpenAI TTS response mapping: {format_name}"
        ) from exc

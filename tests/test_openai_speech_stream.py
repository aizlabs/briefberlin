import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.openai_speech_stream import (
    SpeechTokenUsage,
    iter_sse_json_events,
    supports_speech_usage_stream,
    synthesize_speech_sse,
)


class FakeStream:
    def __init__(self, lines: list[str]):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def iter_lines(self):
        return iter(self.lines)


class FakeCreate:
    def __init__(self, lines: list[str]):
        self.lines = lines
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self.lines)


def _client(lines: list[str]) -> tuple[SimpleNamespace, FakeCreate]:
    create = FakeCreate(lines)
    client = SimpleNamespace(
        audio=SimpleNamespace(
            speech=SimpleNamespace(
                with_streaming_response=create,
            )
        )
    )
    return client, create


def _event(payload: str) -> list[str]:
    return [f"data: {payload}", ""]


def test_speech_sse_writes_audio_and_returns_exact_usage(tmp_path: Path):
    encoded_audio = base64.b64encode(b"audio-bytes").decode("ascii")
    lines = [
        *_event(f'{{"type":"speech.audio.delta","audio":"{encoded_audio}"}}'),
        *_event(
            '{"type":"speech.audio.done","usage":'
            '{"input_tokens":12,"output_tokens":34,"total_tokens":46}}'
        ),
    ]
    client, create = _client(lines)
    destination = tmp_path / "article.mp3"

    usage = synthesize_speech_sse(
        client,
        input_text="Hallo Berlin",
        model="gpt-4o-mini-tts",
        voice="alloy",
        response_format="mp3",
        destination=destination,
    )

    assert destination.read_bytes() == b"audio-bytes"
    assert usage == SpeechTokenUsage(input_tokens=12, output_tokens=34, total_tokens=46)
    assert create.kwargs == {
        "input": "Hallo Berlin",
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",
        "response_format": "mp3",
        "stream_format": "sse",
    }


def test_speech_sse_does_not_replace_existing_file_when_stream_is_incomplete(tmp_path: Path):
    client, _create = _client(_event('{"type":"speech.audio.delta","audio":"bmV3LWF1ZGlv"}'))
    destination = tmp_path / "article.mp3"
    destination.write_bytes(b"existing-audio")

    with pytest.raises(ValueError, match="without speech.audio.done"):
        synthesize_speech_sse(
            client,
            input_text="Hallo",
            model="gpt-4o-mini-tts",
            voice="alloy",
            response_format="mp3",
            destination=destination,
        )

    assert destination.read_bytes() == b"existing-audio"
    assert list(tmp_path.glob("*.tmp")) == []


def test_speech_sse_rejects_inconsistent_usage(tmp_path: Path):
    client, _create = _client(
        _event(
            '{"type":"speech.audio.done","usage":'
            '{"input_tokens":1,"output_tokens":2,"total_tokens":4}}'
        )
    )

    with pytest.raises(ValueError, match="do not match"):
        synthesize_speech_sse(
            client,
            input_text="Hallo",
            model="gpt-4o-mini-tts",
            voice="alloy",
            response_format="mp3",
            destination=tmp_path / "article.mp3",
        )


def test_sse_parser_uses_event_field_and_supports_final_unterminated_frame():
    events = list(
        iter_sse_json_events(
            [
                ": heartbeat",
                "event: speech.audio.done",
                'data: {"usage":{"input_tokens":0,',
                'data: "output_tokens":0,"total_tokens":0}}',
            ]
        )
    )

    assert events == [
        {
            "type": "speech.audio.done",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }
    ]


def test_supports_speech_usage_stream_only_for_compatible_model_family():
    assert supports_speech_usage_stream("gpt-4o-mini-tts")
    assert supports_speech_usage_stream("gpt-4o-mini-tts-2025-12-15")
    assert not supports_speech_usage_stream("tts-1")

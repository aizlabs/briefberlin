import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from scripts.tts_providers import ElevenLabsTTSProvider


def _response(text: str, *, include_alignment: bool = True) -> MagicMock:
    response = MagicMock()
    payload = {"audio_base64": base64.b64encode(b"eleven-audio").decode("ascii")}
    if include_alignment:
        payload["alignment"] = {
            "characters": list(text),
            "character_start_times_seconds": [index * 0.05 for index in range(len(text))],
            "character_end_times_seconds": [(index + 1) * 0.05 for index in range(len(text))],
        }
    response.json.return_value = payload
    return response


def test_elevenlabs_writes_audio_and_returns_word_cues(base_config, tmp_path: Path):
    text = "Hallo Welt."
    base_config.audio.provider = "elevenlabs"
    base_config.audio.providers.elevenlabs.api_key = "eleven-test-key"
    client = MagicMock()
    client.post.return_value = _response(text)
    destination = tmp_path / "article.mp3"

    result = ElevenLabsTTSProvider(base_config, client=client).synthesize(
        text,
        destination,
        "mp3",
    )

    assert destination.read_bytes() == b"eleven-audio"
    assert [cue.text for cue in result.cues or []] == ["Hallo", "Welt."]
    assert result.cues is not None
    assert result.cues[1].text_start == 6
    assert result.cues[1].text_end == 11
    assert result.usage is not None
    assert result.usage.input_characters == len(text)
    request = client.post.call_args
    assert request.args[0].endswith(
        "/text-to-speech/OYTbf65OHHFELVut7v2H/with-timestamps"
    )
    assert request.kwargs["json"] == {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "language_code": "de",
    }
    assert request.kwargs["params"] == {"output_format": "mp3_44100_128"}


def test_elevenlabs_uses_target_language_code_from_language_config(
    base_config,
    tmp_path: Path,
):
    base_config.audio.provider = "elevenlabs"
    base_config.audio.providers.elevenlabs.api_key = "eleven-test-key"
    base_config.language.target_language_code = "fr"
    client = MagicMock()
    client.post.return_value = _response("Bonjour Berlin.")

    ElevenLabsTTSProvider(base_config, client=client).synthesize(
        "Bonjour Berlin.",
        tmp_path / "article.mp3",
        "mp3",
    )

    assert client.post.call_args.kwargs["json"]["language_code"] == "fr"


def test_elevenlabs_uses_configured_speed_for_article_level(base_config, tmp_path: Path):
    base_config.audio.provider = "elevenlabs"
    base_config.audio.providers.elevenlabs.api_key = "eleven-test-key"
    base_config.audio.providers.elevenlabs.speed_by_level = {
        "A2": 0.7,
        "B1": 0.8,
    }
    client = MagicMock()
    client.post.return_value = _response("Hallo Welt.")

    ElevenLabsTTSProvider(base_config, client=client).synthesize(
        "Hallo Welt.",
        tmp_path / "article.mp3",
        "mp3",
        level="A2",
    )

    assert client.post.call_args.kwargs["json"]["voice_settings"] == {"speed": 0.7}


def test_elevenlabs_keeps_audio_when_alignment_is_missing(base_config, tmp_path: Path):
    text = "Hallo Welt."
    base_config.audio.provider = "elevenlabs"
    base_config.audio.providers.elevenlabs.api_key = "eleven-test-key"
    client = MagicMock()
    client.post.return_value = _response(text, include_alignment=False)
    destination = tmp_path / "article.mp3"

    result = ElevenLabsTTSProvider(base_config, client=client).synthesize(
        text,
        destination,
        "mp3",
    )

    assert destination.read_bytes() == b"eleven-audio"
    assert result.cues is None
    assert result.timing_note is not None
    assert "alignment is missing" in result.timing_note


def test_elevenlabs_ignores_alignment_for_different_text(base_config, tmp_path: Path):
    base_config.audio.provider = "elevenlabs"
    base_config.audio.providers.elevenlabs.api_key = "eleven-test-key"
    client = MagicMock()
    client.post.return_value = _response("Anderer Text")
    destination = tmp_path / "article.mp3"

    result = ElevenLabsTTSProvider(base_config, client=client).synthesize(
        "Erwarteter Text",
        destination,
        "mp3",
    )

    assert destination.read_bytes() == b"eleven-audio"
    assert result.cues is None
    assert result.timing_note is not None
    assert "does not match" in result.timing_note


def test_elevenlabs_includes_provider_error_detail(base_config, tmp_path: Path):
    base_config.audio.provider = "elevenlabs"
    base_config.audio.providers.elevenlabs.api_key = "eleven-test-key"
    client = MagicMock()
    response = MagicMock()
    response.status_code = 400
    response.json.return_value = {
        "detail": {"message": "The selected voice is not available to this account."}
    }
    response.raise_for_status.side_effect = requests.HTTPError("400 Client Error")
    client.post.return_value = response

    with pytest.raises(ValueError, match="selected voice is not available"):
        ElevenLabsTTSProvider(base_config, client=client).synthesize(
            "Hallo Berlin.",
            tmp_path / "article.mp3",
            "mp3",
        )

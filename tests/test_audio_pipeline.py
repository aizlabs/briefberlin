from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.audio_pipeline import AudioPipeline
from scripts.audio_script_builder import build_speech_script
from scripts.models import AudioWordCue, ModelPricingConfig
from scripts.openai_speech_stream import SpeechSynthesisResult, SpeechTokenUsage
from scripts.tts_providers import TTSResult
from scripts.usage_report import collect_run_usage


class DummySpeechResponse:
    def __init__(self, payload: bytes = b"audio-bytes"):
        self.payload = payload

    def write_to_file(self, path: str | Path) -> None:
        Path(path).write_bytes(self.payload)


def _enable_sse_usage_for_default_tts(base_config) -> None:
    base_config.llm.usage_reporting.prices = {
        "openai": {
            "gpt-4o-mini-tts": ModelPricingConfig(
                aliases=["gpt-4o-mini-tts-*"],
                modality="audio",
                supports_sse_usage=True,
                input_per_million="0.60",
                output_per_million="12.00",
            )
        }
    }


@patch("scripts.tts_providers.synthesize_speech_sse")
def test_audio_pipeline_registers_exact_sse_usage_in_active_run(
    mock_synthesize_speech_sse,
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    base_config.audio.enabled = True
    base_config.audio.output_path = str(tmp_path / "audio")
    base_config.audio.provider = "openai"
    base_config.audio.model = "gpt-4o-mini-tts-2025-12-15"
    base_config.audio.voice = "alloy"
    _enable_sse_usage_for_default_tts(base_config)
    mock_synthesize_speech_sse.return_value = SpeechSynthesisResult(
        usage=SpeechTokenUsage(
            input_tokens=12,
            output_tokens=34,
            total_tokens=46,
        )
    )

    pipeline = AudioPipeline(base_config, mock_logger, tts_client=MagicMock())
    with collect_run_usage(base_config.llm.usage_reporting, "openai") as report:
        pipeline.prepare_for_publish(
            sample_a2_article,
            timestamp=datetime(2024, 1, 2, 12, 0, 0),
        )

    [usage] = report.as_dict()["models"]
    assert usage["model"] == "gpt-4o-mini-tts-2025-12-15"
    assert usage["modality"] == "audio"
    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] == 34


@patch("scripts.tts_providers.synthesize_speech_sse")
def test_audio_pipeline_keeps_audio_when_sse_usage_is_incomplete(
    mock_synthesize_speech_sse,
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    base_config.audio.enabled = True
    base_config.audio.output_path = str(tmp_path / "audio")
    base_config.audio.provider = "openai"
    base_config.audio.model = "gpt-4o-mini-tts-2025-12-15"
    _enable_sse_usage_for_default_tts(base_config)

    def synthesize_with_incomplete_usage(*_args, destination, **_kwargs):
        destination.write_bytes(b"complete-audio")
        return SpeechSynthesisResult(
            usage=None,
            usage_note="exact speech token usage could not be parsed: changed payload",
        )

    mock_synthesize_speech_sse.side_effect = synthesize_with_incomplete_usage

    pipeline = AudioPipeline(base_config, mock_logger, tts_client=MagicMock())
    with collect_run_usage(base_config.llm.usage_reporting, "openai") as report:
        prepared = pipeline.prepare_for_publish(
            sample_a2_article,
            timestamp=datetime(2024, 1, 2, 12, 0, 0),
        )

    assert prepared.audio is not None
    assert Path(prepared.audio.local_audio_path or "").read_bytes() == b"complete-audio"
    [usage] = report.as_dict()["models"]
    assert usage["usage_complete"] is False
    assert usage["total_cost"] is None
    assert any("could not be parsed" in note for note in report.as_dict()["notes"])


def test_audio_pipeline_writes_manifest_and_script_when_enabled(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    base_config.audio.enabled = True
    base_config.audio.output_path = str(tmp_path / "audio")
    base_config.audio.provider = "openai"
    base_config.audio.model = "custom-tts-model"

    mock_tts_client = MagicMock()
    mock_tts_client.audio.speech.create.return_value = DummySpeechResponse()

    pipeline = AudioPipeline(base_config, mock_logger, tts_client=mock_tts_client)

    prepared_article = pipeline.prepare_for_publish(
        sample_a2_article,
        timestamp=datetime(2024, 1, 2, 12, 0, 0),
    )

    assert prepared_article.audio is not None
    assert prepared_article.audio.storage_key == (
        "articles/2024/01/20240102-120000-deutschland-baut-mehr-windenergie-aus-a2/article.mp3"
    )
    assert prepared_article.audio.url is None
    assert prepared_article.audio.local_audio_path is not None

    script_path = (
        tmp_path
        / "audio"
        / "scripts"
        / "2024"
        / "01"
        / "20240102-120000-deutschland-baut-mehr-windenergie-aus-a2.txt"
    )
    manifest_path = (
        tmp_path
        / "audio"
        / "manifests"
        / "2024"
        / "01"
        / "20240102-120000-deutschland-baut-mehr-windenergie-aus-a2.json"
    )
    audio_path = (
        tmp_path
        / "audio"
        / "generated"
        / "2024"
        / "01"
        / "20240102-120000-deutschland-baut-mehr-windenergie-aus-a2"
        / "article.mp3"
    )
    assert script_path.exists()
    assert manifest_path.exists()
    assert audio_path.exists()
    assert "Ende des Artikels." in script_path.read_text(encoding="utf-8")
    mock_tts_client.audio.speech.create.assert_called_once()
    assert mock_tts_client.audio.speech.create.call_args.kwargs["model"] == "custom-tts-model"
    assert mock_tts_client.audio.speech.create.call_args.kwargs["voice"] == "marin"
    info_messages = [call.args[0] for call in mock_logger.info.call_args_list]
    assert (
        "Skipping audio upload for '%s' because audio.upload_enabled=false; audio remains local at %s"
        in info_messages
    )


def test_audio_pipeline_uploads_and_sets_public_url_when_upload_enabled(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    base_config.audio.enabled = True
    base_config.audio.provider = "openai"
    base_config.audio.model = "custom-tts-model"
    base_config.audio.voice = "alloy"
    base_config.audio.upload_enabled = True
    base_config.audio.output_path = str(tmp_path / "audio")
    base_config.audio.public_base_url = "https://media.briefberlin.de"
    base_config.audio.s3.bucket = "briefberlin-audio-prod"

    mock_tts_client = MagicMock()
    mock_tts_client.audio.speech.create.return_value = DummySpeechResponse()
    mock_s3_client = MagicMock()

    pipeline = AudioPipeline(
        base_config,
        mock_logger,
        tts_client=mock_tts_client,
        s3_client=mock_s3_client,
    )

    prepared_article = pipeline.prepare_for_publish(
        sample_a2_article,
        timestamp=datetime(2024, 1, 2, 12, 0, 0),
    )

    assert prepared_article.audio is not None
    assert (
        prepared_article.audio.url
        == "https://media.briefberlin.de/articles/2024/01/20240102-120000-deutschland-baut-mehr-windenergie-aus-a2/article.mp3"
    )
    assert prepared_article.audio.storage_key == (
        "articles/2024/01/20240102-120000-deutschland-baut-mehr-windenergie-aus-a2/article.mp3"
    )
    mock_s3_client.upload_file.assert_called_once()
    info_messages = [call.args[0] for call in mock_logger.info.call_args_list]
    assert "Synthesizing audio for '%s' with provider=%s voice=%s format=%s" in info_messages
    assert "Synthesized audio for '%s' at %s" in info_messages
    assert "Uploading audio for '%s' to s3://%s/%s" in info_messages
    assert "Uploaded audio for '%s' to %s" in info_messages


def test_audio_pipeline_maps_m4a_to_openai_aac_response_format(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    base_config.audio.enabled = True
    base_config.audio.provider = "openai"
    base_config.audio.model = "custom-tts-model"
    base_config.audio.voice = "alloy"
    base_config.audio.format = "m4a"
    base_config.audio.output_path = str(tmp_path / "audio")

    mock_tts_client = MagicMock()
    mock_tts_client.audio.speech.create.return_value = DummySpeechResponse()

    pipeline = AudioPipeline(base_config, mock_logger, tts_client=mock_tts_client)

    prepared_article = pipeline.prepare_for_publish(
        sample_a2_article,
        timestamp=datetime(2024, 1, 2, 12, 0, 0),
    )

    assert prepared_article.audio is not None
    assert prepared_article.audio.format == "m4a"
    assert prepared_article.audio.local_audio_path is not None
    assert prepared_article.audio.local_audio_path.endswith("article.m4a")
    mock_tts_client.audio.speech.create.assert_called_once()
    assert mock_tts_client.audio.speech.create.call_args.kwargs["response_format"] == "aac"


def test_audio_pipeline_raises_when_upload_enabled_without_bucket(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    base_config.audio.enabled = True
    base_config.audio.provider = "openai"
    base_config.audio.model = "custom-tts-model"
    base_config.audio.voice = "alloy"
    base_config.audio.upload_enabled = True
    base_config.audio.output_path = str(tmp_path / "audio")
    base_config.audio.public_base_url = "https://media.briefberlin.de"

    mock_tts_client = MagicMock()
    mock_tts_client.audio.speech.create.return_value = DummySpeechResponse()

    pipeline = AudioPipeline(base_config, mock_logger, tts_client=mock_tts_client)

    try:
        pipeline.prepare_for_publish(
            sample_a2_article,
            timestamp=datetime(2024, 1, 2, 12, 0, 0),
        )
    except ValueError as exc:
        assert "audio.s3.bucket" in str(exc)
        error_calls = mock_logger.error.call_args_list
        assert error_calls
        assert error_calls[-1].args == (
            "Audio upload cannot start for '%s': audio.s3.bucket is not configured",
            sample_a2_article.title,
        )
    else:
        raise AssertionError("Expected ValueError when bucket is missing")


def test_audio_pipeline_logs_when_audio_disabled(base_config, mock_logger, sample_a2_article):
    base_config.audio.enabled = False

    pipeline = AudioPipeline(base_config, mock_logger)

    prepared_article = pipeline.prepare_for_publish(sample_a2_article)

    assert prepared_article.audio is None
    mock_logger.info.assert_called_with(
        "Skipping audio preparation for '%s' because audio.enabled=false",
        sample_a2_article.title,
    )


def test_audio_pipeline_publishes_word_timing_sidecar(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    base_config.audio.enabled = True
    base_config.audio.provider = "elevenlabs"
    base_config.audio.providers.elevenlabs.api_key = "eleven-test-key"
    base_config.audio.output_path = str(tmp_path / "audio")
    base_config.audio.upload_enabled = True
    base_config.audio.public_base_url = "https://media.briefberlin.de"
    base_config.audio.s3.bucket = "briefberlin-audio-prod"
    mock_s3_client = MagicMock()
    provider = MagicMock()

    def synthesize(narration, destination, _audio_format):
        Path(destination).write_bytes(b"audio")
        title_end = len(sample_a2_article.title)
        return TTSResult(
            cues=[
                AudioWordCue(
                    text=sample_a2_article.title,
                    text_start=0,
                    text_end=title_end,
                    start_seconds=0,
                    end_seconds=1.2,
                )
            ]
        )

    provider.synthesize.side_effect = synthesize
    pipeline = AudioPipeline(base_config, mock_logger, s3_client=mock_s3_client)
    pipeline.tts_provider = provider

    prepared = pipeline.prepare_for_publish(
        sample_a2_article,
        timestamp=datetime(2024, 1, 2, 12, 0, 0),
    )

    assert prepared.audio is not None
    assert prepared.audio.timings_url is not None
    assert prepared.audio.timings_url.endswith("/article.timings.json")
    assert prepared.audio.timing_granularity == "word"
    assert prepared.audio.highlight_context == "sentence"
    timing_path = Path(prepared.audio.local_timings_path or "")
    timing_payload = timing_path.read_text(encoding="utf-8")
    assert '"block_kind": "title"' in timing_payload
    assert '"granularity": "word"' in timing_payload
    assert mock_s3_client.upload_file.call_count == 2


def test_build_speech_script_marks_vocabulary_false_when_article_has_no_glossary(sample_a2_article):
    article_without_vocabulary = sample_a2_article.model_copy(update={"vocabulary": []})

    script = build_speech_script(article_without_vocabulary, include_vocabulary=True)

    assert script.includes_vocabulary is False
    assert "Vokabeln." not in script.narration


def test_build_speech_script_skips_summary_when_body_starts_with_same_sentence(sample_a2_article):
    article = sample_a2_article.model_copy(
        update={
            "summary": "In Berlin gibt es eine neue Meinung über das Tempelhofer Feld.",
            "content": (
                "In Berlin gibt es eine neue Meinung über das Tempelhofer Feld. "
                "Eine Umfrage zeigt neue Pläne.\n\n"
                "Die Mitte des Feldes bleibt grün."
            ),
        }
    )

    script = build_speech_script(article)

    repeated_sentence = "In Berlin gibt es eine neue Meinung über das Tempelhofer Feld."
    assert script.sections[0] == article.title
    assert script.narration.count(repeated_sentence) == 1


def test_build_speech_script_includes_english_only_glossary_items(sample_a2_article):
    article_with_english_only_glossary = sample_a2_article.model_copy(
        update={
            "vocabulary": [
                {
                    "term": "Sturmschäden",
                    "english": "storm damage",
                    "explanation": "",
                }
            ]
        }
    )

    script = build_speech_script(article_with_english_only_glossary, include_vocabulary=True)

    assert script.includes_vocabulary is True
    assert "Vokabeln. Sturmschäden heißt auf Englisch storm damage." in script.narration


def test_build_speech_script_uses_configured_glossary_heading(sample_a2_article):
    article_with_glossary = sample_a2_article.model_copy(
        update={
            "vocabulary": [
                {
                    "term": "Sturmschäden",
                    "english": "storm damage",
                    "explanation": "",
                }
            ]
        }
    )

    script = build_speech_script(
        article_with_glossary,
        include_vocabulary=True,
        glossary_heading="Vocabolario",
    )

    assert "Vocabolario. Sturmschäden heißt auf Englisch storm damage." in script.narration
    assert "Vokabeln." not in script.narration

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from scripts.audio_pipeline import AudioPipeline
from scripts.audio_script_builder import build_speech_script


class DummySpeechResponse:
    def __init__(self, payload: bytes = b"audio-bytes"):
        self.payload = payload

    def write_to_file(self, path: str | Path) -> None:
        Path(path).write_bytes(self.payload)


def test_audio_pipeline_writes_manifest_and_script_when_enabled(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    base_config.audio.enabled = True
    base_config.audio.output_path = str(tmp_path / "audio")
    base_config.audio.provider = "openai"
    base_config.audio.voice = "alloy"

    mock_tts_client = MagicMock()
    mock_tts_client.audio.speech.create.return_value = DummySpeechResponse()

    pipeline = AudioPipeline(base_config, mock_logger, tts_client=mock_tts_client)

    prepared_article = pipeline.prepare_for_publish(
        sample_a2_article,
        timestamp=datetime(2024, 1, 2, 12, 0, 0),
    )

    assert prepared_article.audio is not None
    assert prepared_article.audio.storage_key == (
        "articles/2024/01/20240102-120000-espana-tiene-menos-contaminacion-a2/article.mp3"
    )
    assert prepared_article.audio.url is None
    assert prepared_article.audio.local_audio_path is not None

    script_path = (
        tmp_path
        / "audio"
        / "scripts"
        / "2024"
        / "01"
        / "20240102-120000-espana-tiene-menos-contaminacion-a2.txt"
    )
    manifest_path = (
        tmp_path
        / "audio"
        / "manifests"
        / "2024"
        / "01"
        / "20240102-120000-espana-tiene-menos-contaminacion-a2.json"
    )
    audio_path = (
        tmp_path
        / "audio"
        / "generated"
        / "2024"
        / "01"
        / "20240102-120000-espana-tiene-menos-contaminacion-a2"
        / "article.mp3"
    )
    assert script_path.exists()
    assert manifest_path.exists()
    assert audio_path.exists()
    assert "Ende des Artikels." in script_path.read_text(encoding="utf-8")
    mock_tts_client.audio.speech.create.assert_called_once()
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
    base_config.audio.voice = "alloy"
    base_config.audio.upload_enabled = True
    base_config.audio.output_path = str(tmp_path / "audio")
    base_config.audio.public_base_url = "https://media.briefberlin.com"
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
        == "https://media.briefberlin.com/articles/2024/01/20240102-120000-espana-tiene-menos-contaminacion-a2/article.mp3"
    )
    assert prepared_article.audio.storage_key == (
        "articles/2024/01/20240102-120000-espana-tiene-menos-contaminacion-a2/article.mp3"
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
    base_config.audio.voice = "alloy"
    base_config.audio.upload_enabled = True
    base_config.audio.output_path = str(tmp_path / "audio")
    base_config.audio.public_base_url = "https://media.briefberlin.com"

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


def test_build_speech_script_marks_vocabulary_false_when_article_has_no_glossary(sample_a2_article):
    article_without_vocabulary = sample_a2_article.model_copy(update={"vocabulary": []})

    script = build_speech_script(article_without_vocabulary, include_vocabulary=True)

    assert script.includes_vocabulary is False
    assert "Vokabeln." not in script.narration


def test_build_speech_script_includes_english_only_glossary_items(sample_a2_article):
    article_with_english_only_glossary = sample_a2_article.model_copy(
        update={
            "vocabulary": [
                {
                    "term": "bombardeos",
                    "english": "bombings",
                    "explanation": "",
                }
            ]
        }
    )

    script = build_speech_script(article_with_english_only_glossary, include_vocabulary=True)

    assert script.includes_vocabulary is True
    assert "Vokabeln. bombardeos heißt auf Englisch bombings." in script.narration

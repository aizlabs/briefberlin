import os
from argparse import Namespace
from unittest.mock import patch

import pytest

from scripts.publish_source import apply_audio_defaults, main


def test_apply_audio_defaults_forces_audio_upload(monkeypatch):
    monkeypatch.setenv("AUDIO_ENABLED", "false")
    monkeypatch.setenv("AUDIO_UPLOAD_ENABLED", "false")
    monkeypatch.setenv("AUDIO_VOICE", "custom")

    apply_audio_defaults()

    assert os.environ["AUDIO_ENABLED"] == "true"
    assert os.environ["AUDIO_UPLOAD_ENABLED"] == "true"
    assert os.environ["AUDIO_PROVIDER"] == "openai"
    assert os.environ["AUDIO_VOICE"] == "custom"
    assert os.environ["AUDIO_PUBLIC_BASE_URL"] == "https://media.briefberlin.de"
    assert os.environ["AUDIO_S3_BUCKET"] == "briefberlin-audio-prod"


@patch("scripts.publish_source.run_manual_pipeline")
def test_main_delegates_to_manual_pipeline_with_audio_levels(mock_run_manual_pipeline, monkeypatch):
    for key in (
        "AUDIO_ENABLED",
        "AUDIO_UPLOAD_ENABLED",
        "AUDIO_PROVIDER",
        "AUDIO_VOICE",
        "AUDIO_FORMAT",
        "AUDIO_PUBLIC_BASE_URL",
        "AUDIO_S3_BUCKET",
        "AUDIO_S3_REGION",
        "AUDIO_S3_PREFIX",
    ):
        monkeypatch.delenv(key, raising=False)
    mock_run_manual_pipeline.return_value = 0

    result = main(["private-input/source-5.source.txt"])

    assert result == 0
    mock_run_manual_pipeline.assert_called_once()
    args = mock_run_manual_pipeline.call_args.args[0]
    assert isinstance(args, Namespace)
    assert args.sources == ["private-input/source-5.source.txt"]
    assert args.level == ["A2", "B1"]
    assert args.dry_run is False
    assert args.publish_timestamp is None
    assert args.author is None
    assert not hasattr(args, "topic")


@patch("scripts.publish_source.run_manual_pipeline")
def test_main_forwards_publish_timestamp(mock_run_manual_pipeline, monkeypatch):
    monkeypatch.delenv("AUDIO_ENABLED", raising=False)
    mock_run_manual_pipeline.return_value = 0

    result = main([
        "--publish-timestamp",
        "2026-07-03T09:00:00",
        "private-input/source-5.source.txt",
    ])

    assert result == 0
    args = mock_run_manual_pipeline.call_args.args[0]
    assert args.publish_timestamp == "2026-07-03T09:00:00"


@patch("scripts.publish_source.run_manual_pipeline")
def test_main_forwards_author(mock_run_manual_pipeline, monkeypatch):
    monkeypatch.delenv("AUDIO_ENABLED", raising=False)
    mock_run_manual_pipeline.return_value = 0

    result = main([
        "--author",
        "future-author",
        "private-input/source-5.source.txt",
    ])

    assert result == 0
    args = mock_run_manual_pipeline.call_args.args[0]
    assert args.author == "future-author"


def test_main_rejects_removed_topic_option():
    with pytest.raises(SystemExit):
        main(["--topic", "Alter Titel", "private-input/source-5.source.txt"])

from argparse import Namespace
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.manual_pipeline import load_private_sources, run_manual_pipeline
from scripts.models import QualityResult
from scripts.topic_metadata_extractor import TopicMetadataResponse


def _write_source(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Dies ist ein privater Quelltext mit genug Wörtern für den lokalen "
        "Pipeline-Test. Er beschreibt ein Ereignis, liefert Kontext und enthält "
        "mehrere einfache Sätze für die Verarbeitung.",
        encoding="utf-8",
    )
    return path


def test_load_private_sources_uses_generic_labels(tmp_path):
    source_path = _write_source(tmp_path / "private-input" / "article.source.txt")

    sources = load_private_sources([source_path])

    assert len(sources) == 1
    assert sources[0].source == "Private source 1"
    assert sources[0].url is None
    assert "privater Quelltext" in sources[0].text


def test_load_private_sources_rejects_non_private_path(tmp_path):
    source_path = _write_source(tmp_path / "public.txt")

    try:
        load_private_sources([source_path])
    except ValueError as exc:
        assert "Refusing input" in str(exc)
    else:
        raise AssertionError("Expected non-private input path to be rejected")


@patch("scripts.manual_pipeline.datetime")
@patch("scripts.manual_pipeline.Publisher")
@patch("scripts.manual_pipeline.AudioPipeline")
@patch("scripts.manual_pipeline.GlossaryGenerator")
@patch("scripts.manual_pipeline.QualityGate")
@patch("scripts.manual_pipeline.ContentGenerator")
@patch("scripts.manual_pipeline.TopicMetadataExtractor")
@patch("scripts.manual_pipeline.setup_logger")
@patch("scripts.manual_pipeline.load_config")
def test_run_manual_pipeline_generates_and_publishes(
    mock_load_config,
    mock_setup_logger,
    mock_topic_metadata_extractor_class,
    mock_generator_class,
    mock_quality_gate_class,
    mock_glossary_class,
    mock_audio_class,
    mock_publisher_class,
    mock_datetime,
    base_config,
    mock_logger,
    sample_a2_text_article,
    tmp_path,
):
    source_path = _write_source(tmp_path / "private-input" / "article.source.txt")
    base_config.generation.levels = ["A2"]
    base_config.audio.enabled = False
    publish_timestamp = datetime(2026, 6, 27, 12, 34, 56)
    mock_datetime.utcnow.return_value = datetime(2026, 6, 27, 10, 34, 50)
    mock_datetime.now.return_value = publish_timestamp
    mock_load_config.return_value = base_config
    mock_setup_logger.return_value = mock_logger

    mock_topic_metadata_extractor = MagicMock()
    mock_topic_metadata_extractor.extract.return_value = TopicMetadataResponse(
        title="Milder Frühling in Deutschland",
        keywords=["frühling", "wetter", "stadtfeste"],
    )
    mock_topic_metadata_extractor_class.return_value = mock_topic_metadata_extractor

    mock_generator = MagicMock()
    mock_generator.generate_article.return_value = sample_a2_text_article
    mock_generator_class.return_value = mock_generator

    mock_quality_gate = MagicMock()
    mock_quality_gate.check_and_improve.return_value = (
        sample_a2_text_article,
        QualityResult(
            passed=True,
            score=8.3,
            issues=[],
            strengths=["klar"],
            attempts=1,
            grammar_score=3.0,
            educational_score=2.5,
            content_score=1.8,
            level_score=1.0,
        ),
    )
    mock_quality_gate_class.return_value = mock_quality_gate

    mock_glossary = MagicMock()
    mock_glossary.enrich_article.return_value = sample_a2_text_article
    mock_glossary_class.return_value = mock_glossary

    mock_publisher = MagicMock()
    mock_publisher.save_article.return_value = True
    mock_publisher_class.return_value = mock_publisher

    args = Namespace(
        sources=[str(source_path)],
        level=["A2"],
        environment="local",
        dry_run=False,
    )

    result = run_manual_pipeline(args)

    assert result == 0
    generated_topic, generated_sources, generated_level = mock_generator.generate_article.call_args.args
    assert generated_topic.title == "Milder Frühling in Deutschland"
    assert generated_topic.keywords == ["frühling", "wetter", "stadtfeste"]
    assert generated_level == "A2"
    assert [source.source for source in generated_sources] == ["Private source 1"]
    mock_topic_metadata_extractor.extract.assert_called_once_with(generated_sources)
    mock_publisher_class.assert_called_once_with(base_config, mock_logger, dry_run=False)
    mock_publisher.save_article.assert_called_once_with(
        sample_a2_text_article,
        timestamp=publish_timestamp,
    )
    mock_audio_class.assert_called_once()


@patch("scripts.manual_pipeline.datetime")
@patch("scripts.manual_pipeline.Publisher")
@patch("scripts.manual_pipeline.AudioPipeline")
@patch("scripts.manual_pipeline.GlossaryGenerator")
@patch("scripts.manual_pipeline.QualityGate")
@patch("scripts.manual_pipeline.ContentGenerator")
@patch("scripts.manual_pipeline.TopicMetadataExtractor")
@patch("scripts.manual_pipeline.setup_logger")
@patch("scripts.manual_pipeline.load_config")
def test_run_manual_pipeline_reuses_publish_timestamp_for_audio(
    mock_load_config,
    mock_setup_logger,
    mock_topic_metadata_extractor_class,
    mock_generator_class,
    mock_quality_gate_class,
    mock_glossary_class,
    mock_audio_class,
    mock_publisher_class,
    mock_datetime,
    base_config,
    mock_logger,
    sample_a2_text_article,
    tmp_path,
):
    source_path = _write_source(tmp_path / "private-input" / "article.source.txt")
    publish_timestamp = datetime(2026, 6, 27, 12, 34, 56)
    base_config.generation.levels = ["A2"]
    base_config.audio.enabled = True
    mock_datetime.utcnow.return_value = datetime(2026, 6, 27, 10, 34, 50)
    mock_datetime.now.return_value = publish_timestamp
    mock_load_config.return_value = base_config
    mock_setup_logger.return_value = mock_logger

    mock_topic_metadata_extractor = MagicMock()
    mock_topic_metadata_extractor.extract.return_value = TopicMetadataResponse(
        title="Milder Frühling in Deutschland",
        keywords=["frühling"],
    )
    mock_topic_metadata_extractor_class.return_value = mock_topic_metadata_extractor

    mock_generator = MagicMock()
    mock_generator.generate_article.return_value = sample_a2_text_article
    mock_generator_class.return_value = mock_generator

    mock_quality_gate = MagicMock()
    mock_quality_gate.check_and_improve.return_value = (
        sample_a2_text_article,
        QualityResult(
            passed=True,
            score=8.3,
            issues=[],
            strengths=["klar"],
            attempts=1,
            grammar_score=3.0,
            educational_score=2.5,
            content_score=1.8,
            level_score=1.0,
        ),
    )
    mock_quality_gate_class.return_value = mock_quality_gate

    mock_glossary = MagicMock()
    mock_glossary.enrich_article.return_value = sample_a2_text_article
    mock_glossary_class.return_value = mock_glossary

    mock_audio = MagicMock()
    mock_audio.prepare_for_publish.return_value = sample_a2_text_article
    mock_audio_class.return_value = mock_audio

    mock_publisher = MagicMock()
    mock_publisher.save_article.return_value = True
    mock_publisher_class.return_value = mock_publisher

    args = Namespace(
        sources=[str(source_path)],
        level=["A2"],
        environment="local",
        dry_run=False,
    )

    result = run_manual_pipeline(args)

    assert result == 0
    mock_audio.prepare_for_publish.assert_called_once_with(
        sample_a2_text_article,
        timestamp=publish_timestamp,
    )
    mock_publisher.save_article.assert_called_once_with(
        sample_a2_text_article,
        timestamp=publish_timestamp,
    )


@patch("scripts.manual_pipeline.Publisher")
@patch("scripts.manual_pipeline.AudioPipeline")
@patch("scripts.manual_pipeline.GlossaryGenerator")
@patch("scripts.manual_pipeline.QualityGate")
@patch("scripts.manual_pipeline.ContentGenerator")
@patch("scripts.manual_pipeline.TopicMetadataExtractor")
@patch("scripts.manual_pipeline.setup_logger")
@patch("scripts.manual_pipeline.load_config")
def test_run_manual_pipeline_dry_run_skips_audio_preparation(
    mock_load_config,
    mock_setup_logger,
    mock_topic_metadata_extractor_class,
    mock_generator_class,
    mock_quality_gate_class,
    mock_glossary_class,
    mock_audio_class,
    mock_publisher_class,
    base_config,
    mock_logger,
    sample_a2_text_article,
    tmp_path,
):
    source_path = _write_source(tmp_path / "private-input" / "article.source.txt")
    base_config.generation.levels = ["A2"]
    base_config.audio.enabled = True
    mock_load_config.return_value = base_config
    mock_setup_logger.return_value = mock_logger

    mock_topic_metadata_extractor = MagicMock()
    mock_topic_metadata_extractor.extract.return_value = TopicMetadataResponse(
        title="Manual source article",
        keywords=[],
    )
    mock_topic_metadata_extractor_class.return_value = mock_topic_metadata_extractor

    mock_generator = MagicMock()
    mock_generator.generate_article.return_value = sample_a2_text_article
    mock_generator_class.return_value = mock_generator

    mock_quality_gate = MagicMock()
    mock_quality_gate.check_and_improve.return_value = (
        sample_a2_text_article,
        QualityResult(
            passed=True,
            score=8.3,
            issues=[],
            strengths=["klar"],
            attempts=1,
            grammar_score=3.0,
            educational_score=2.5,
            content_score=1.8,
            level_score=1.0,
        ),
    )
    mock_quality_gate_class.return_value = mock_quality_gate

    mock_glossary = MagicMock()
    mock_glossary.enrich_article.return_value = sample_a2_text_article
    mock_glossary_class.return_value = mock_glossary

    mock_audio = MagicMock()
    mock_audio_class.return_value = mock_audio

    mock_publisher = MagicMock()
    mock_publisher.save_article.return_value = True
    mock_publisher_class.return_value = mock_publisher

    args = Namespace(
        sources=[str(source_path)],
        level=["A2"],
        environment="local",
        dry_run=True,
    )

    result = run_manual_pipeline(args)

    assert result == 0
    mock_audio_class.assert_called_once_with(base_config, mock_logger)
    mock_audio.prepare_for_publish.assert_not_called()
    mock_publisher_class.assert_called_once_with(base_config, mock_logger, dry_run=True)
    mock_publisher.save_article.assert_called_once()
    saved_article = mock_publisher.save_article.call_args.args[0]
    assert saved_article == sample_a2_text_article

from unittest.mock import MagicMock, patch

from scripts import main as main_module
from scripts.models import QualityResult


@patch("scripts.main.Publisher")
@patch("scripts.main.AudioPipeline")
@patch("scripts.main.GlossaryGenerator")
@patch("scripts.main.QualityGate")
@patch("scripts.main.ContentGenerator")
@patch("scripts.main.ContentFetcher")
@patch("scripts.main.TopicDiscoverer")
@patch("scripts.main.AlertManager")
@patch("scripts.main.setup_logger")
@patch("scripts.main.load_config")
def test_main_logs_glossary_retry_counts_when_glossary_stays_empty(
    mock_load_config,
    mock_setup_logger,
    mock_alert_manager_class,
    mock_discoverer_class,
    mock_fetcher_class,
    mock_generator_class,
    mock_quality_gate_class,
    mock_glossary_generator_class,
    mock_audio_pipeline_class,
    mock_publisher_class,
    base_config,
    mock_logger,
    sample_topic,
    sample_sources,
    sample_a2_text_article,
):
    base_config.generation.articles_per_run = 1
    base_config.generation.levels = ["A2"]
    base_config.audio.enabled = False

    mock_load_config.return_value = base_config
    mock_setup_logger.return_value = mock_logger

    mock_alert_manager = MagicMock()
    mock_alert_manager_class.return_value = mock_alert_manager

    mock_discoverer = MagicMock()
    mock_discoverer.discover.return_value = [sample_topic]
    mock_discoverer_class.return_value = mock_discoverer

    mock_fetcher = MagicMock()
    mock_fetcher.fetch_topic_sources.return_value = sample_sources
    mock_fetcher_class.return_value = mock_fetcher

    mock_generator = MagicMock()
    mock_generator.generate_article.return_value = sample_a2_text_article
    mock_generator_class.return_value = mock_generator

    mock_quality_gate = MagicMock()
    mock_quality_gate.check_and_improve.return_value = (
        sample_a2_text_article,
        QualityResult(
            passed=True,
            score=8.5,
            issues=[],
            strengths=["clear structure"],
            attempts=1,
            grammar_score=3.0,
            educational_score=2.5,
            content_score=2.0,
            level_score=1.0,
        ),
    )
    mock_quality_gate_class.return_value = mock_quality_gate

    mock_glossary_generator = MagicMock()
    mock_glossary_generator.enrich_article.return_value = sample_a2_text_article.model_copy(
        update={"vocabulary": []}
    )
    mock_glossary_generator.last_run_stats = {
        "glossary_candidates_initial": 5,
        "glossary_candidates_retry": 3,
        "glossary_accepted": 0,
        "glossary_empty_after_retry": True,
        "retry_used": True,
    }
    mock_glossary_generator_class.return_value = mock_glossary_generator

    mock_audio_pipeline_class.return_value = MagicMock()

    mock_publisher = MagicMock()
    mock_publisher.save_article.return_value = True
    mock_publisher_class.return_value = mock_publisher

    result = main_module.main()

    assert result == 0
    assert any(
        "glossary_candidates_initial=5" in str(call.args[0])
        for call in mock_logger.info.call_args_list
    )
    assert any(
        "glossary_candidates_retry=3" in str(call.args[0])
        for call in mock_logger.info.call_args_list
    )
    assert any(
        "glossary_accepted=0" in str(call.args[0])
        for call in mock_logger.info.call_args_list
    )
    assert any(
        "Glossary still empty after retry" in str(call.args[0])
        and "glossary_candidates_initial=5" in str(call.args[0])
        and "glossary_candidates_retry=3" in str(call.args[0])
        for call in mock_logger.warning.call_args_list
    )


@patch("scripts.main.Publisher")
@patch("scripts.main.AudioPipeline")
@patch("scripts.main.GlossaryGenerator")
@patch("scripts.main.QualityGate")
@patch("scripts.main.ContentGenerator")
@patch("scripts.main.ContentFetcher")
@patch("scripts.main.TopicDiscoverer")
@patch("scripts.main.AlertManager")
@patch("scripts.main.setup_logger")
@patch("scripts.main.load_config")
def test_main_does_not_log_after_retry_warning_when_no_retry_was_used(
    mock_load_config,
    mock_setup_logger,
    mock_alert_manager_class,
    mock_discoverer_class,
    mock_fetcher_class,
    mock_generator_class,
    mock_quality_gate_class,
    mock_glossary_generator_class,
    mock_audio_pipeline_class,
    mock_publisher_class,
    base_config,
    mock_logger,
    sample_topic,
    sample_sources,
    sample_a2_text_article,
):
    base_config.generation.articles_per_run = 1
    base_config.generation.levels = ["A2"]
    base_config.audio.enabled = False

    mock_load_config.return_value = base_config
    mock_setup_logger.return_value = mock_logger

    mock_alert_manager = MagicMock()
    mock_alert_manager_class.return_value = mock_alert_manager

    mock_discoverer = MagicMock()
    mock_discoverer.discover.return_value = [sample_topic]
    mock_discoverer_class.return_value = mock_discoverer

    mock_fetcher = MagicMock()
    mock_fetcher.fetch_topic_sources.return_value = sample_sources
    mock_fetcher_class.return_value = mock_fetcher

    mock_generator = MagicMock()
    mock_generator.generate_article.return_value = sample_a2_text_article
    mock_generator_class.return_value = mock_generator

    mock_quality_gate = MagicMock()
    mock_quality_gate.check_and_improve.return_value = (
        sample_a2_text_article,
        QualityResult(
            passed=True,
            score=8.5,
            issues=[],
            strengths=["clear structure"],
            attempts=1,
            grammar_score=3.0,
            educational_score=2.5,
            content_score=2.0,
            level_score=1.0,
        ),
    )
    mock_quality_gate_class.return_value = mock_quality_gate

    mock_glossary_generator = MagicMock()
    mock_glossary_generator.enrich_article.return_value = sample_a2_text_article.model_copy(
        update={"vocabulary": []}
    )
    mock_glossary_generator.last_run_stats = {
        "glossary_candidates_initial": 5,
        "glossary_candidates_retry": 0,
        "glossary_accepted": 0,
        "glossary_empty_after_retry": False,
        "retry_used": False,
    }
    mock_glossary_generator_class.return_value = mock_glossary_generator

    mock_audio_pipeline_class.return_value = MagicMock()

    mock_publisher = MagicMock()
    mock_publisher.save_article.return_value = True
    mock_publisher_class.return_value = mock_publisher

    result = main_module.main()

    assert result == 0
    assert not any(
        "Glossary still empty after retry" in str(call.args[0])
        for call in mock_logger.warning.call_args_list
    )

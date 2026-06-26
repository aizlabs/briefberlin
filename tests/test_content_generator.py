"""
Unit tests for ContentGenerator component (orchestrator)
"""

from unittest.mock import MagicMock, patch

import pytest

from scripts.content_generator import ContentGenerator
from scripts.models import AdaptedArticle


class TestContentGeneratorInit:
    """Test ContentGenerator initialization"""

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_init_default_settings(self, mock_adapter_class, mock_synth_class,
                                    base_config, mock_logger):
        """Test initialization with default settings"""
        generator = ContentGenerator(base_config, mock_logger)

        assert generator.save_base_articles is False
        assert generator.regeneration_strategy == 'adaptation_only'
        assert generator.base_article_path == './output/base_articles/'

        # Verify sub-components initialized
        mock_synth_class.assert_called_once_with(base_config, mock_logger)
        mock_adapter_class.assert_called_once_with(base_config, mock_logger)

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_init_save_base_articles_enabled(self, mock_adapter_class, mock_synth_class,
                                              base_config, mock_logger):
        """Configured base article saving is ignored for private-source safety."""
        base_config.generation.two_step_synthesis.save_base_article = True

        generator = ContentGenerator(base_config, mock_logger)

        assert generator.save_base_articles is False
        mock_logger.getChild.return_value.warning.assert_called_once()


class TestContentGeneratorGenerateArticle:
    """Test article generation (two-step process)"""

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_generate_article_a2(self, mock_adapter_class, mock_synth_class,
                                  base_config, mock_logger, sample_topic, sample_sources,
                                  sample_base_article, sample_a2_article):
        """Test generating A2 article through two-step process"""
        # Setup mocks
        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        mock_adapter.adapt_to_level.return_value = sample_a2_article
        mock_adapter_class.return_value = mock_adapter

        # Generate
        generator = ContentGenerator(base_config, mock_logger)
        result = generator.generate_article(sample_topic, sample_sources, 'A2')

        # Verify two-step process
        mock_synthesizer.synthesize.assert_called_once_with(sample_topic, sample_sources)
        mock_adapter.adapt_to_level.assert_called_once_with(sample_base_article, 'A2')

        # Verify result
        assert result == sample_a2_article

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_generate_article_b1(self, mock_adapter_class, mock_synth_class,
                                  base_config, mock_logger, sample_topic, sample_sources,
                                  sample_base_article, sample_b1_article):
        """Test generating B1 article through two-step process"""
        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        mock_adapter.adapt_to_level.return_value = sample_b1_article
        mock_adapter_class.return_value = mock_adapter

        generator = ContentGenerator(base_config, mock_logger)
        result = generator.generate_article(sample_topic, sample_sources, 'B1')

        mock_adapter.adapt_to_level.assert_called_once_with(sample_base_article, 'B1')
        assert result == sample_b1_article


class TestContentGeneratorSaveBaseArticle:
    """Test base article persistence is disabled."""

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    @patch('builtins.open', new_callable=MagicMock)
    @patch('pathlib.Path.mkdir')
    def test_save_base_article_enabled(self, mock_mkdir, mock_open,
                                        mock_adapter_class, mock_synth_class,
                                        base_config, mock_logger, sample_topic,
                                        sample_sources, sample_base_article, sample_a2_article):
        """Base article is not saved even when config enables the old debug path."""
        base_config.generation.two_step_synthesis.save_base_article = True

        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        mock_adapter.adapt_to_level.return_value = sample_a2_article
        mock_adapter_class.return_value = mock_adapter

        generator = ContentGenerator(base_config, mock_logger)
        generator.generate_article(sample_topic, sample_sources, 'A2')

        mock_mkdir.assert_not_called()
        mock_open.assert_not_called()

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    @patch('builtins.open', new_callable=MagicMock)
    def test_save_base_article_disabled(self, mock_open, mock_adapter_class, mock_synth_class,
                                         base_config, mock_logger, sample_topic,
                                         sample_sources, sample_base_article, sample_a2_article):
        """Test base article not saved when disabled"""
        base_config.generation.two_step_synthesis.save_base_article = False

        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        mock_adapter.adapt_to_level.return_value = sample_a2_article
        mock_adapter_class.return_value = mock_adapter

        generator = ContentGenerator(base_config, mock_logger)
        generator.generate_article(sample_topic, sample_sources, 'A2')

        # Verify no file operations
        mock_open.assert_not_called()


class TestContentGeneratorRegenerateWithFeedback:
    """Test regeneration with quality feedback"""

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_regenerate_adaptation_only_strategy(self, mock_adapter_class, mock_synth_class,
                                                   base_config, mock_logger, sample_topic,
                                                   sample_sources, sample_a2_article):
        """Test regeneration with adaptation_only strategy"""
        base_config.generation.two_step_synthesis.regeneration_strategy = 'adaptation_only'

        mock_synthesizer = MagicMock()
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        improved_article = sample_a2_article.model_copy() # Use model_copy for Pydantic objects
        improved_article.title = 'Improved Title'
        mock_adapter.adapt_to_level.return_value = improved_article
        mock_adapter_class.return_value = mock_adapter

        generator = ContentGenerator(base_config, mock_logger)
        issues = ["Sentences too complex", "Missing vocabulary"]

        result = generator.regenerate_with_feedback(
            sample_topic,
            sample_sources,
            'A2',
            sample_a2_article,  # Previous attempt with base_article stored
            issues
        )

        # Should NOT call synthesizer (reuses base article)
        mock_synthesizer.synthesize.assert_not_called()

        # Should call adapter with feedback
        mock_adapter.adapt_to_level.assert_called_once()
        call_args = mock_adapter.adapt_to_level.call_args
        assert call_args[1]['feedback'] == issues

        assert result.title == 'Improved Title'

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_regenerate_full_pipeline_strategy(self, mock_adapter_class, mock_synth_class,
                                                 base_config, mock_logger, sample_topic,
                                                 sample_sources, sample_base_article,
                                                 sample_a2_article):
        """Test regeneration with full_pipeline strategy"""
        base_config.generation.two_step_synthesis.regeneration_strategy = 'full_pipeline'

        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        improved_article = sample_a2_article.model_copy()
        improved_article.title = 'Improved Title'
        mock_adapter.adapt_to_level.return_value = improved_article
        mock_adapter_class.return_value = mock_adapter

        generator = ContentGenerator(base_config, mock_logger)
        issues = ["Factual error"]

        result = generator.regenerate_with_feedback(
            sample_topic,
            sample_sources,
            'A2',
            sample_a2_article,
            issues
        )

        # Should call BOTH synthesizer and adapter
        mock_synthesizer.synthesize.assert_called_once_with(sample_topic, sample_sources)
        mock_adapter.adapt_to_level.assert_called_once()

        assert result.title == 'Improved Title'

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_regenerate_missing_base_article_fallback(self, mock_adapter_class, mock_synth_class,
                                                        base_config, mock_logger, sample_topic,
                                                        sample_sources, sample_base_article,
                                                        sample_a2_article):
        """Test regeneration falls back to full pipeline if base_article missing"""
        base_config.generation.two_step_synthesis.regeneration_strategy = 'adaptation_only'

        # Previous attempt WITHOUT base_article
        previous_attempt = AdaptedArticle(
            title='Old Title',
            content='Content' * 10, # Make sure content is long enough for validation
            summary='Summary' * 2, # Make sure summary is long enough for validation
            reading_time=2,
            level='A2'
            # Missing 'base_article' key
        )

        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        mock_adapter.adapt_to_level.return_value = sample_a2_article
        mock_adapter_class.return_value = mock_adapter

        generator = ContentGenerator(base_config, mock_logger)
        issues = ["Issue"]

        generator.regenerate_with_feedback(
            sample_topic,
            sample_sources,
            'A2',
            previous_attempt,
            issues
        )

        # Should fall back to synthesizing new base article
        mock_synthesizer.synthesize.assert_called_once()
        mock_adapter.adapt_to_level.assert_called_once()


class TestContentGeneratorErrorHandling:
    """Test error handling"""

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_synthesis_error_propagates(self, mock_adapter_class, mock_synth_class,
                                         base_config, mock_logger, sample_topic, sample_sources):
        """Test synthesis errors propagate correctly"""
        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.side_effect = Exception("Synthesis failed")
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter_class.return_value = MagicMock()

        generator = ContentGenerator(base_config, mock_logger)

        with pytest.raises(Exception, match="Synthesis failed"):
            generator.generate_article(sample_topic, sample_sources, 'A2')

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_adaptation_error_propagates(self, mock_adapter_class, mock_synth_class,
                                          base_config, mock_logger, sample_topic, sample_sources,
                                          sample_base_article):
        """Test adaptation errors propagate correctly"""
        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        mock_adapter.adapt_to_level.side_effect = Exception("Adaptation failed")
        mock_adapter_class.return_value = mock_adapter

        generator = ContentGenerator(base_config, mock_logger)

        with pytest.raises(Exception, match="Adaptation failed"):
            generator.generate_article(sample_topic, sample_sources, 'A2')

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    @patch('builtins.open', side_effect=IOError("Disk full"))
    @patch('pathlib.Path.mkdir')
    def test_save_base_article_path_is_not_used(self, mock_mkdir, mock_open,
                                                 mock_adapter_class, mock_synth_class,
                                                 base_config, mock_logger, sample_topic,
                                                 sample_sources, sample_base_article,
                                                 sample_a2_article):
        """The old debug save path is not touched, so disk errors cannot leak source-derived text."""
        base_config.generation.two_step_synthesis.save_base_article = True

        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        mock_adapter.adapt_to_level.return_value = sample_a2_article
        mock_adapter_class.return_value = mock_adapter

        generator = ContentGenerator(base_config, mock_logger)

        # Should not raise exception despite save error
        result = generator.generate_article(sample_topic, sample_sources, 'A2')

        assert result == sample_a2_article
        mock_mkdir.assert_not_called()
        mock_open.assert_not_called()

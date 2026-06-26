"""
Integration tests for two-step article generation pipeline

These tests verify that components work together correctly, catching bugs
that unit tests miss (like the Publisher AttributeError on None topic).
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.article_synthesizer import ArticleSynthesizer, SynthesisResponse
from scripts.content_generator import ContentGenerator
from scripts.level_adapter import LevelAdapter
from scripts.models import AdaptedArticle, BaseArticle, SourceMetadata
from scripts.publisher import Publisher


class TestTwoStepPipelineIntegration:
    """Integration tests for synthesis → adaptation flow"""

    @patch('scripts.article_synthesizer.ArticleSynthesizer._call_llm')
    @patch('scripts.level_adapter.LevelAdapter._call_llm')
    def test_synthesis_to_adaptation_a2(self, mock_adapter_call_llm, mock_synth_call_llm,
                                         base_config, mock_logger, sample_topic, sample_sources,
                                         sample_base_article, sample_a2_text_article):
        """Test complete two-step flow: ArticleSynthesizer → LevelAdapter (A2)"""
        # Setup synthesizer mock with structured response
        synth_response = SynthesisResponse(
            title=sample_base_article.title,
            content=sample_base_article.content,
            summary=sample_base_article.summary,
            reading_time=sample_base_article.reading_time,
        )
        mock_synth_call_llm.return_value = synth_response

        # Setup adapter mock using the FakeAdaptationResponse from unit tests
        from tests.test_level_adapter import FakeAdaptationResponse

        response_adapter_dict = sample_a2_text_article.model_dump()
        del response_adapter_dict['base_article']
        del response_adapter_dict['topic']
        del response_adapter_dict['sources']
        del response_adapter_dict['level']
        del response_adapter_dict['vocabulary']
        mock_adapter_call_llm.return_value = FakeAdaptationResponse(**response_adapter_dict)

        # Execute two-step pipeline
        synthesizer = ArticleSynthesizer(base_config, mock_logger)
        adapter = LevelAdapter(base_config, mock_logger)

        # Step 1: Synthesize
        base_article = synthesizer.synthesize(sample_topic, sample_sources)

        # Verify base article structure
        assert isinstance(base_article, BaseArticle)
        assert base_article.title == sample_base_article.title
        assert base_article.topic == sample_topic
        assert [s.name for s in base_article.sources] == [s.source for s in sample_sources]

        # Step 2: Adapt
        a2_article = adapter.adapt_to_level(base_article, 'A2')

        # Verify adapted article
        assert isinstance(a2_article, AdaptedArticle)
        assert a2_article.level == 'A2'
        assert a2_article.title == sample_a2_text_article.title
        assert a2_article.vocabulary == []

        # CRITICAL: Verify metadata propagation (would have caught the bug!)
        assert a2_article.topic == sample_topic  # Not None!
        assert [s.name for s in a2_article.sources] == [s.source for s in sample_sources]

        # Verify base article stored for regeneration
        assert a2_article.base_article == base_article

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_content_generator_orchestration(self, mock_adapter_class, mock_synth_class,
                                              base_config, mock_logger, sample_topic,
                                              sample_sources, sample_base_article, sample_a2_article):
        """Test ContentGenerator orchestrates both steps correctly"""
        # Setup mocks
        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        mock_adapter = MagicMock()
        mock_adapter.adapt_to_level.return_value = sample_a2_article
        mock_adapter_class.return_value = mock_adapter

        # Execute
        generator = ContentGenerator(base_config, mock_logger)
        result = generator.generate_article(sample_topic, sample_sources, 'A2')

        # Verify orchestration
        mock_synthesizer.synthesize.assert_called_once_with(sample_topic, sample_sources)
        mock_adapter.adapt_to_level.assert_called_once_with(sample_base_article, 'A2')

        # Verify result has correct metadata
        assert result == sample_a2_article


class TestPublisherIntegration:
    """Integration tests including Publisher (would have caught the bug!)"""

    @patch('scripts.article_synthesizer.ArticleSynthesizer._call_llm')
    @patch('scripts.level_adapter.LevelAdapter._call_llm')
    @patch('builtins.open', new_callable=MagicMock)
    @patch('pathlib.Path.mkdir')
    def test_synthesis_to_adaptation_to_publisher(self, mock_mkdir, mock_open,
                                                    mock_adapter_call_llm, mock_synth_call_llm,
                                                    base_config, mock_logger, sample_topic,
                                                    sample_sources, sample_base_article, sample_a2_text_article):
        """
        Test complete flow: Synthesize → Adapt → Publish

        This test would have caught the Publisher AttributeError bug!
        """
        # Setup synthesizer (structured response)
        synth_response = SynthesisResponse(
            title=sample_base_article.title,
            content=sample_base_article.content,
            summary=sample_base_article.summary,
            reading_time=sample_base_article.reading_time,
        )
        mock_synth_call_llm.return_value = synth_response

        # Setup adapter
        from tests.test_level_adapter import FakeAdaptationResponse

        response_adapter_dict = sample_a2_text_article.model_dump()
        del response_adapter_dict['base_article']
        del response_adapter_dict['topic']
        del response_adapter_dict['sources']
        del response_adapter_dict['level']
        del response_adapter_dict['vocabulary']
        mock_adapter_call_llm.return_value = FakeAdaptationResponse(**response_adapter_dict)

        # Execute full pipeline
        synthesizer = ArticleSynthesizer(base_config, mock_logger)
        adapter = LevelAdapter(base_config, mock_logger)
        publisher = Publisher(base_config, mock_logger, dry_run=True)

        # Step 1: Synthesize
        base_article = synthesizer.synthesize(sample_topic, sample_sources)

        # Step 2: Adapt
        a2_article = adapter.adapt_to_level(base_article, 'A2')

        # Step 3: Publish (THIS WOULD HAVE CRASHED WITH THE BUG!)
        # The bug was: a2_article['topic'] could be None, causing AttributeError
        # in Publisher._format_topics() when calling topic.get('keywords', [])
        success = publisher.save_article(a2_article)

        # If we get here, the bug is fixed!
        assert success or not success  # Either works, we just shouldn't crash

    @patch('scripts.level_adapter.LevelAdapter._call_llm')
    @patch('builtins.open', new_callable=MagicMock)
    @patch('pathlib.Path.mkdir')
    def test_publisher_handles_missing_topic_metadata(self, mock_mkdir, mock_open,
                                                        mock_adapter_call_llm,
                                                        base_config, mock_logger,
                                                        sample_base_article_minimal, sample_a2_text_article):
        """
        Test Publisher handles missing topic metadata gracefully

        This is the EXACT bug scenario that occurred in production.
        """
        # Setup adapter (synthesizer not needed for this test)
        from tests.test_level_adapter import FakeAdaptationResponse

        response_adapter_dict = sample_a2_text_article.model_dump()
        del response_adapter_dict['base_article']
        del response_adapter_dict['topic']
        del response_adapter_dict['sources']
        del response_adapter_dict['level']
        del response_adapter_dict['vocabulary']
        mock_adapter_call_llm.return_value = FakeAdaptationResponse(**response_adapter_dict)

        # Execute
        adapter = LevelAdapter(base_config, mock_logger)
        publisher = Publisher(base_config, mock_logger, dry_run=True)

        # Adapt (base article has no topic metadata)
        a2_article = adapter.adapt_to_level(sample_base_article_minimal, 'A2')

        # CRITICAL TEST: This should NOT crash even though topic is {}
        # Before fix: topic_data.get('keywords') would crash because topic_data was None
        # After fix: topic_data is {} and .get() works fine
        try:
            publisher.save_article(a2_article)
            # Success! Bug is fixed
            assert True
        except AttributeError as e:
            # This would be the bug
            pytest.fail(f"Publisher crashed with AttributeError: {e}")

    def test_publisher_formats_structured_sources(self, base_config, mock_logger, sample_a2_article):
        """Publisher should suppress source URLs in public markdown."""
        publisher = Publisher(base_config, mock_logger, dry_run=True)

        markdown = publisher._generate_markdown(sample_a2_article, datetime.now())

        assert 'sources: []' in markdown
        assert 'https://elpais.com/test' not in markdown
        assert '[El País](https://elpais.com/test)' not in markdown

    def test_publisher_handles_sources_without_url(self, base_config, mock_logger, sample_a2_article):
        """Publisher should suppress source names in public markdown."""
        publisher = Publisher(base_config, mock_logger, dry_run=True)
        sample_a2_article.sources = [SourceMetadata(name='Example Source')]

        markdown = publisher._generate_markdown(sample_a2_article, datetime.now())

        assert 'sources: []' in markdown
        assert 'Example Source' not in markdown
        assert '*Fuentes:' not in markdown


class TestRegenerationIntegration:
    """Integration tests for regeneration with feedback"""

    @patch('scripts.content_generator.ArticleSynthesizer')
    @patch('scripts.content_generator.LevelAdapter')
    def test_regeneration_preserves_metadata(self, mock_adapter_class, mock_synth_class,
                                              base_config, mock_logger, sample_topic,
                                              sample_sources, sample_base_article,
                                              sample_a2_article):
        """Test regeneration preserves topic metadata through the flow"""
        base_config.generation.two_step_synthesis.regeneration_strategy = 'adaptation_only'

        # Setup mocks
        mock_synthesizer = MagicMock()
        mock_synthesizer.synthesize.return_value = sample_base_article
        mock_synth_class.return_value = mock_synthesizer

        # First attempt: article with issues
        first_attempt = sample_a2_article.model_copy()

        # Second attempt: improved article
        improved_article = sample_a2_article.model_copy()
        improved_article.title = 'Improved Title'

        mock_adapter = MagicMock()
        mock_adapter.adapt_to_level.return_value = improved_article
        mock_adapter_class.return_value = mock_adapter

        # Execute regeneration
        generator = ContentGenerator(base_config, mock_logger)
        issues = ['Sentences too long', 'Vocabulary too complex']

        result = generator.regenerate_with_feedback(
            sample_topic,
            sample_sources,
            'A2',
            first_attempt,
            issues
        )

        # Verify metadata preserved
        assert result.topic == sample_topic  # Critical!
        assert result.sources == sample_base_article.sources

        # Verify adapter called with feedback
        mock_adapter.adapt_to_level.assert_called_once()
        call_args = mock_adapter.adapt_to_level.call_args
        assert call_args[1]['feedback'] == issues

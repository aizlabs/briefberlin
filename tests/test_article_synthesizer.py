"""
Unit tests for ArticleSynthesizer component
"""

from unittest.mock import patch

import pytest

from scripts.article_synthesizer import ArticleSynthesizer, SynthesisResponse
from scripts.models import BaseArticle


class TestArticleSynthesizerInit:
    """Test ArticleSynthesizer initialization with shared LLM config."""

    def test_init_uses_llm_config(self, base_config, mock_logger):
        synthesizer = ArticleSynthesizer(base_config, mock_logger)

        assert synthesizer.config is base_config
        assert synthesizer.llm_config == base_config.llm.model_dump()
        mock_logger.getChild.assert_called_with('ArticleSynthesizer')


class TestArticleSynthesizerSynthesize:
    """Test synthesis functionality with structured outputs."""

    @patch('scripts.article_synthesizer.ArticleSynthesizer._call_llm')
    def test_synthesize_success(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_topic,
        sample_sources,
        sample_base_article,
    ):
        """Test successful article synthesis from structured response."""
        # Map BaseArticle sample into SynthesisResponse
        resp = SynthesisResponse(
            title=sample_base_article.title,
            content=sample_base_article.content,
            summary=sample_base_article.summary,
            reading_time=sample_base_article.reading_time,
        )
        mock_call_llm.return_value = resp

        synthesizer = ArticleSynthesizer(base_config, mock_logger)
        result = synthesizer.synthesize(sample_topic, sample_sources)

        assert isinstance(result, BaseArticle)
        assert result.title == sample_base_article.title
        assert result.content == sample_base_article.content
        assert result.summary == sample_base_article.summary
        assert result.reading_time == sample_base_article.reading_time
        assert result.topic == sample_topic
        assert [s.name for s in result.sources] == [s.source for s in sample_sources]
        assert [s.url for s in result.sources] == [s.url for s in sample_sources]

        mock_call_llm.assert_called_once()
        assert synthesizer.config.llm.models.generation == base_config.llm.models.generation

    @patch('scripts.article_synthesizer.ArticleSynthesizer._call_llm')
    @patch('scripts.article_synthesizer.ArticleSynthesizer._build_base_article')
    def test_synthesize_invalid_base_article_structure(
        self,
        mock_build_base_article,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_topic,
        sample_sources,
    ):
        """Test synthesis surfaces errors when BaseArticle construction fails."""
        resp = SynthesisResponse(
            title="Test",
            content="a" * 200,
            summary="summary text",
            reading_time=3,
        )
        mock_call_llm.return_value = resp
        mock_build_base_article.side_effect = Exception("Validation failed")

        synthesizer = ArticleSynthesizer(base_config, mock_logger)

        with pytest.raises(Exception, match="Validation failed"):
            synthesizer.synthesize(sample_topic, sample_sources)

    @patch('scripts.article_synthesizer.ArticleSynthesizer._call_llm')
    def test_synthesize_llm_api_error(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_topic,
        sample_sources,
    ):
        """Test synthesis handles LLM API errors from the chain."""
        mock_call_llm.side_effect = Exception("API Error")

        synthesizer = ArticleSynthesizer(base_config, mock_logger)

        with pytest.raises(Exception, match="API Error"):
            synthesizer.synthesize(sample_topic, sample_sources)

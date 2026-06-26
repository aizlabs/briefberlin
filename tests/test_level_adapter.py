"""
Unit tests for LevelAdapter.
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from scripts.level_adapter import LevelAdapter
from scripts.models import AdaptedArticle


class FakeAdaptationResponse(BaseModel):
    """Simple stand-in for the internal AdaptationResponse used in LevelAdapter."""

    title: str
    content: str
    summary: str
    reading_time: int


def _response_payload(article: AdaptedArticle) -> dict:
    payload = article.model_dump()
    for field in ("base_article", "topic", "sources", "level", "vocabulary", "audio"):
        payload.pop(field, None)
    return payload


class TestLevelAdapterInit:
    @patch("scripts.level_adapter.create_chat_model")
    def test_init_uses_llm_and_generation_config(
        self,
        mock_create_chat_model,
        base_config,
        mock_logger,
    ):
        mock_create_chat_model.return_value = MagicMock()

        adapter = LevelAdapter(base_config, mock_logger)

        assert adapter.config is base_config
        assert adapter.llm_config == base_config.llm.model_dump()
        assert adapter.generation_config == base_config.generation.model_dump()
        mock_logger.getChild.assert_called_with("LevelAdapter")


class TestLevelAdapterA2:
    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_adapt_to_a2_success(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
        sample_a2_text_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_a2_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        result = adapter.adapt_to_a2(sample_base_article)

        assert isinstance(result, AdaptedArticle)
        assert result.level == "A2"
        assert result.title == sample_a2_text_article.title
        assert result.vocabulary == []
        assert result.base_article == sample_base_article
        assert result.topic == sample_base_article.topic
        assert result.sources == sample_base_article.sources
        mock_call_llm.assert_called_once()

    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_adapt_to_a2_with_feedback(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
        sample_a2_text_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_a2_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        result = adapter.adapt_to_a2(sample_base_article, feedback=["Sentences too long"])

        prompt = mock_call_llm.call_args.args[0]
        assert "PREVIOUS ATTEMPT HAD ISSUES" in prompt
        assert "Sentences too long" in prompt
        assert result.vocabulary == []

    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_adapt_to_a2_strips_markdown_emphasis(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(
            title="Test",
            content=("La **tasa** sube en el país. " * 8).strip(),
            summary="Resumen simple suficiente",
            reading_time=2,
        )

        adapter = LevelAdapter(base_config, mock_logger)
        result = adapter.adapt_to_a2(sample_base_article)

        assert "**" not in result.content
        assert result.vocabulary == []


class TestLevelAdapterB1:
    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_adapt_to_b1_success(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
        sample_b1_text_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_b1_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        result = adapter.adapt_to_b1(sample_base_article)

        assert isinstance(result, AdaptedArticle)
        assert result.level == "B1"
        assert result.title == sample_b1_text_article.title
        assert result.vocabulary == []
        assert result.base_article == sample_base_article

    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_adapt_to_b1_with_feedback(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
        sample_b1_text_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_b1_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        result = adapter.adapt_to_b1(sample_base_article, feedback=["Tenses too simple"])

        prompt = mock_call_llm.call_args.args[0]
        assert "PREVIOUS ATTEMPT HAD ISSUES" in prompt
        assert "Tenses too simple" in prompt
        assert result.vocabulary == []


class TestLevelAdapterGeneric:
    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_adapt_to_level_a2(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
        sample_a2_text_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_a2_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        result = adapter.adapt_to_level(sample_base_article, "A2")

        assert result.level == "A2"

    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_adapt_to_level_b1(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
        sample_b1_text_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_b1_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        result = adapter.adapt_to_level(sample_base_article, "B1")

        assert result.level == "B1"

    @patch("scripts.level_adapter.create_chat_model")
    def test_adapt_to_level_unsupported(
        self,
        mock_create_chat_model,
        base_config,
        mock_logger,
        sample_base_article,
    ):
        mock_create_chat_model.return_value = MagicMock()
        adapter = LevelAdapter(base_config, mock_logger)

        with pytest.raises(ValueError, match="Unsupported level"):
            adapter.adapt_to_level(sample_base_article, "C1")


class TestLevelAdapterParsing:
    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    @patch("scripts.level_adapter.LevelAdapter._build_adapted_article")
    def test_build_adapted_article_error_is_propagated(
        self,
        mock_build_adapted,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(
            title="Test",
            content="a" * 100,
            summary="Summary text",
            reading_time=2,
        )
        mock_build_adapted.side_effect = ValueError(
            "Invalid adapted article structure or Pydantic validation error"
        )

        adapter = LevelAdapter(base_config, mock_logger)

        with pytest.raises(
            ValueError, match="Invalid adapted article structure or Pydantic validation error"
        ):
            adapter.adapt_to_a2(sample_base_article)


class TestLevelAdapterModelSelection:
    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_uses_adaptation_model(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
        sample_a2_text_article,
    ):
        base_config.llm.models.adaptation = "gpt-4o-mini"
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_a2_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        adapter.adapt_to_a2(sample_base_article)

        assert adapter.llm_config["models"]["adaptation"] == "gpt-4o-mini"

    @patch("scripts.level_adapter.create_chat_model")
    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_fallback_to_generation_model(
        self,
        mock_call_llm,
        mock_create_chat_model,
        base_config,
        mock_logger,
        sample_base_article,
        sample_a2_text_article,
    ):
        base_config.llm.models.adaptation = None
        mock_create_chat_model.return_value = MagicMock()
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_a2_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        adapter.adapt_to_a2(sample_base_article)

        assert adapter.llm_config["models"]["generation"] == base_config.llm.models.generation


class TestLevelAdapterMetadata:
    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_adapt_with_missing_topic_metadata(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article_minimal,
        sample_a2_text_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_a2_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        result = adapter.adapt_to_a2(sample_base_article_minimal)

        assert result.topic is None
        assert result.sources == []

    @patch("scripts.level_adapter.LevelAdapter._call_llm")
    def test_base_article_preserved_in_result(
        self,
        mock_call_llm,
        base_config,
        mock_logger,
        sample_base_article,
        sample_a2_text_article,
    ):
        mock_call_llm.return_value = FakeAdaptationResponse(**_response_payload(sample_a2_text_article))

        adapter = LevelAdapter(base_config, mock_logger)
        result = adapter.adapt_to_a2(sample_base_article)

        assert result.base_article == sample_base_article

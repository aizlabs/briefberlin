from unittest.mock import MagicMock

from scripts.topic_metadata_extractor import TopicMetadataExtractor, TopicMetadataResponse


def _extractor(base_config, mock_logger, monkeypatch):
    monkeypatch.setattr(TopicMetadataExtractor, "_init_chain", lambda self: None)
    return TopicMetadataExtractor(base_config, mock_logger)


def test_build_prompt_includes_source_labels_and_text(base_config, mock_logger, sample_sources, monkeypatch):
    extractor = _extractor(base_config, mock_logger, monkeypatch)

    prompt = extractor._build_prompt(sample_sources[:2])

    assert "Private or fetched source material" in prompt
    assert "<source_1 (Tagesschau)>" in prompt
    assert sample_sources[0].text in prompt
    assert "<source_2 (RBB24)>" in prompt
    assert sample_sources[1].text in prompt
    assert '"title"' in prompt
    assert '"keywords"' in prompt


def test_build_prompt_truncates_source_text_for_metadata_extraction(
    base_config,
    mock_logger,
    sample_sources,
    monkeypatch,
):
    base_config.sources.max_words_per_source = 5
    extractor = _extractor(base_config, mock_logger, monkeypatch)

    prompt = extractor._build_prompt(sample_sources[:1])

    assert "Deutschland hat im ersten Halbjahr" in prompt
    assert "mehr Strom aus Windenergie" not in prompt


def test_build_prompt_warns_against_private_keywords(
    base_config,
    mock_logger,
    sample_sources,
    monkeypatch,
):
    extractor = _extractor(base_config, mock_logger, monkeypatch)

    prompt = extractor._build_prompt(sample_sources[:1])

    assert "Never use private proper nouns" in prompt
    assert "confidential codenames" in prompt
    assert "return an empty keyword list" in prompt


def test_extract_parses_structured_output_and_filters_keywords(
    base_config,
    mock_logger,
    sample_sources,
    monkeypatch,
):
    extractor = _extractor(base_config, mock_logger, monkeypatch)
    extractor._call_llm = MagicMock(
        return_value=TopicMetadataResponse(
            title="  Windenergie in Deutschland  ",
            keywords=[" Energie ", "energie", "", "Klimapolitik", "Klimapolitik"],
        )
    )

    metadata = extractor.extract(sample_sources)

    assert metadata.title == "Windenergie in Deutschland"
    assert metadata.keywords == ["Energie", "Klimapolitik"]
    extractor._call_llm.assert_called_once()


def test_extract_returns_fallback_on_llm_failure(
    base_config,
    mock_logger,
    sample_sources,
    monkeypatch,
):
    extractor = _extractor(base_config, mock_logger, monkeypatch)
    extractor._call_llm = MagicMock(side_effect=RuntimeError("API error"))

    metadata = extractor.extract(sample_sources)

    assert metadata.title == "Manual source article"
    assert metadata.keywords == []
    mock_logger.warning.assert_called()


def test_extract_returns_fallback_for_empty_title(
    base_config,
    mock_logger,
    sample_sources,
    monkeypatch,
):
    extractor = _extractor(base_config, mock_logger, monkeypatch)
    extractor._call_llm = MagicMock(
        return_value=TopicMetadataResponse(title="  ", keywords=["energie"])
    )

    metadata = extractor.extract(sample_sources)

    assert metadata.title == "Manual source article"
    assert metadata.keywords == []

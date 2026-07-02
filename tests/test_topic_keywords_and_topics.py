from datetime import datetime
from unittest.mock import patch

import spacy

from scripts.models import Topic
from scripts.publisher import Publisher
from scripts.topic_discovery import TopicDiscoverer
from scripts.topic_utils import is_noisy_topic_keyword, sanitize_topic_keywords


def test_extract_keywords_ignores_html_href(base_config, mock_logger):
    """_extract_keywords should ignore HTML href fragments from summaries."""
    with patch("scripts.topic_discovery.spacy.load", return_value=spacy.blank("de")):
        discoverer = TopicDiscoverer(base_config, mock_logger)

    headlines = [
        {
            "text": "Madrid vive un día importante",
            "summary": '&nbsp;<a href="https://www.elmundo.es/madrid/2026/03/17/69b93e48.html">Leer</a>',
            "url": "https://www.example.com",
            "source": "Example",
            "id": "1",
        }
    ]

    keywords = discoverer._extract_keywords(headlines)

    joined = " ".join(k.lower() for k in keywords)
    assert "href" not in joined
    assert "elmundo.es" not in joined


def test_publisher_filters_href_from_topics(base_config, mock_logger, sample_a2_article):
    """_format_topics should drop href/URL-like keywords before YAML serialization."""
    # Construct a Topic with a bad keyword plus a good one
    topic = Topic(
        title="Madrid",
        sources=["El Mundo"],
        mentions=3,
        score=10.0,
        keywords=['madrid', 'href="https://www.elmundo.es'],
        urls=["https://www.elmundo.es/madrid/2026/03/17/69b93e48.html"],
    )

    article_with_topic = sample_a2_article.model_copy(update={"topic": topic})

    publisher = Publisher(base_config, mock_logger, dry_run=True)
    markdown = publisher._generate_markdown(article_with_topic, datetime(2026, 3, 17, 12, 0, 0))

    # Topics line should not contain href/URL fragments
    assert 'href="https://www.elmundo.es' not in markdown
    # But should still include the valid topic keyword
    assert 'topics: ["madrid"]' in markdown


def test_publisher_renders_empty_topics_when_keywords_missing(
    base_config,
    mock_logger,
    sample_a2_article,
):
    topic = Topic(
        title="Manual source article",
        sources=["Private source 1"],
        mentions=1,
        score=10.0,
        keywords=[],
        urls=[],
    )
    article_with_topic = sample_a2_article.model_copy(update={"topic": topic})

    publisher = Publisher(base_config, mock_logger, dry_run=True)
    markdown = publisher._generate_markdown(article_with_topic, datetime(2026, 3, 17, 12, 0, 0))

    assert "topics: []" in markdown
    assert 'topics: ["general"]' not in markdown


def test_publisher_renders_extracted_topic_keywords(
    base_config,
    mock_logger,
    sample_a2_article,
):
    topic = Topic(
        title="Windenergie in Deutschland",
        sources=["Private source 1"],
        mentions=1,
        score=10.0,
        keywords=["energie", "klimapolitik"],
        urls=[],
    )
    article_with_topic = sample_a2_article.model_copy(update={"topic": topic})

    publisher = Publisher(base_config, mock_logger, dry_run=True)
    markdown = publisher._generate_markdown(article_with_topic, datetime(2026, 3, 17, 12, 0, 0))

    assert 'topics: ["energie", "klimapolitik"]' in markdown


def test_shared_noise_filter_flags_href_and_urls():
    """Shared helper should consistently classify HTML/URL artefacts as noisy."""
    noisy_candidates = [
        'href="https://www.elmundo.es',
        "https://example.com",
        "www.example.com",
        "<a href='https://example.com'>",
    ]
    for kw in noisy_candidates:
        assert is_noisy_topic_keyword(kw)


def test_sanitize_topic_keywords_filters_dedupes_and_caps():
    keywords = [
        " Energie ",
        "energie",
        'href="https://example.com',
        "Klimapolitik",
        "Wind",
    ]

    assert sanitize_topic_keywords(keywords, max_keywords=2, lowercase=True) == [
        "energie",
        "klimapolitik",
    ]

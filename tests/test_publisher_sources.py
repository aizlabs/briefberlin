from datetime import datetime

from scripts.models import AudioAsset, SourceMetadata
from scripts.publisher import Publisher


def test_publisher_formats_sources_with_links(base_config, mock_logger, sample_a2_article, tmp_path):
    """Sources with URLs must not be exposed in public markdown."""
    base_config.output['path'] = str(tmp_path)
    sources = [
        SourceMetadata(name='elpais.com', url='https://elpais.com'),
        SourceMetadata(name='elpais.com', url='https://elpais.com'),  # Duplicate - should be deduplicated
    ]
    article = sample_a2_article.model_copy(update={'sources': sources})

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert 'sources: []' in markdown
    assert 'elpais.com' not in markdown
    assert 'https://elpais.com' not in markdown
    assert "*Fuentes:" not in markdown
    assert "*Vereinfachter Artikel zu Lernzwecken.*" in markdown


def test_publisher_falls_back_to_plain_text_when_url_missing(base_config, mock_logger, sample_a2_article, tmp_path):
    """Sources without URLs must not be exposed in public markdown."""
    base_config.output['path'] = str(tmp_path)
    sources = [
        SourceMetadata(name='Unknown Source'),
        SourceMetadata(name='Unknown Source'),  # Duplicate - should be deduplicated
    ]
    article = sample_a2_article.model_copy(update={'sources': sources})

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert 'sources: []' in markdown
    assert 'Unknown Source' not in markdown
    assert '*Fuentes:' not in markdown


def test_publisher_handles_mixed_sources_with_and_without_urls(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    """Mixed sources must not be exposed in public markdown."""
    base_config.output['path'] = str(tmp_path)
    sources = [
        SourceMetadata(name='El País', url='https://elpais.com'),
        SourceMetadata(name='Unknown Source'),  # No URL
    ]
    article = sample_a2_article.model_copy(update={'sources': sources})

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert 'sources: []' in markdown
    assert 'El País' not in markdown
    assert 'https://elpais.com' not in markdown
    assert 'Unknown Source' not in markdown


def test_publisher_handles_empty_sources_gracefully(base_config, mock_logger, sample_a2_article, tmp_path):
    """Test that empty source lists are handled gracefully"""
    base_config.output['path'] = str(tmp_path)
    article = sample_a2_article.model_copy(update={'sources': []})

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert 'sources: []' in markdown
    assert '*Fuentes:' not in markdown
    assert '*Vereinfachter Artikel zu Lernzwecken.*' in markdown


def test_publisher_handles_legacy_string_sources(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    """Legacy string sources must not be exposed in public markdown."""
    base_config.output['path'] = str(tmp_path)
    # Pass strings - should be converted via coerce_sources validator
    article = sample_a2_article.model_copy(update={'sources': ['El País', 'BBC Mundo']})

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert 'sources: []' in markdown
    assert 'El País' not in markdown
    assert 'BBC Mundo' not in markdown
    assert '*Fuentes:' not in markdown


def test_publisher_escapes_markdown_in_source_labels(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    """Special characters in source names are irrelevant because sources are suppressed."""
    base_config.output['path'] = str(tmp_path)
    sources = [
        SourceMetadata(name='Example [Site]', url='https://example.com'),
    ]
    article = sample_a2_article.model_copy(update={'sources': sources})

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert 'sources: []' in markdown
    assert 'Example [Site]' not in markdown
    assert 'https://example.com' not in markdown


def test_publisher_escapes_special_chars_in_structured_sources(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    """Source names and URLs are not included in attribution."""
    base_config.output['path'] = str(tmp_path)
    # Test all special markdown characters: [, ], (, )
    sources_with_special_chars = [
        SourceMetadata(name='News [Site]', url='https://example.com'),
        SourceMetadata(name='Article (2024)', url='https://example.org'),
        SourceMetadata(name='Source [with] (parens)', url='https://example.net'),
    ]
    article = sample_a2_article.model_copy(update={'sources': sources_with_special_chars})

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))
    assert 'sources: []' in markdown
    assert 'News [Site]' not in markdown
    assert 'Article (2024)' not in markdown
    assert 'Source [with] (parens)' not in markdown
    assert "https://example.com" not in markdown
    assert "https://example.org" not in markdown
    assert "https://example.net" not in markdown


def test_publisher_normalizes_malformed_vocabulary_terms(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    """Test that malformed stored glossary terms render as clean markdown."""
    base_config.output['path'] = str(tmp_path)
    article = sample_a2_article.model_copy(
        update={
            'vocabulary': {
                '****medio ambiente****': 'environment - la naturaleza que nos rodea',
            }
        }
    )

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert "- **medio ambiente** - environment - la naturaleza que nos rodea" in markdown
    assert "****medio ambiente****" not in markdown


def test_publisher_skips_vocabulary_items_without_any_definition(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    base_config.output['path'] = str(tmp_path)
    article = sample_a2_article.model_copy(
        update={
            'vocabulary': [
                {
                    'term': 'bombardeos',
                    'english': '',
                    'explanation': '',
                }
            ]
        }
    )

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert "- **bombardeos** -" not in markdown
    assert "## Vokabeln" not in markdown


def test_publisher_includes_audio_frontmatter_when_public_url_exists(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    """Website audio metadata should be serialized into frontmatter when available."""
    base_config.output['path'] = str(tmp_path)
    article = sample_a2_article.model_copy(
        update={
            'audio': AudioAsset(
                url='https://media.spaili.com/articles/2024/01/test/article.mp3',
                provider='elevenlabs',
                voice='newsreader',
                format='mp3',
                mime_type='audio/mpeg',
            )
        }
    )

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert 'audio:' in markdown
    assert 'url: "https://media.spaili.com/articles/2024/01/test/article.mp3"' in markdown
    assert 'provider: "elevenlabs"' in markdown
    assert 'voice: "newsreader"' in markdown


def test_publisher_omits_audio_frontmatter_when_website_audio_disabled(
    base_config,
    mock_logger,
    sample_a2_article,
    tmp_path,
):
    """Website feature flag should suppress audio metadata in published posts."""
    base_config.output['path'] = str(tmp_path)
    base_config.audio.website.enabled = False
    article = sample_a2_article.model_copy(
        update={
            'audio': AudioAsset(
                url='https://media.spaili.com/articles/2024/01/test/article.mp3',
                provider='elevenlabs',
                voice='newsreader',
                format='mp3',
                mime_type='audio/mpeg',
            )
        }
    )

    publisher = Publisher(base_config, mock_logger, dry_run=True)

    markdown = publisher._generate_markdown(article, datetime(2024, 1, 1, 12, 0, 0))

    assert 'audio: null' in markdown
    assert 'https://media.spaili.com/articles/2024/01/test/article.mp3' not in markdown

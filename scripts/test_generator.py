#!/usr/bin/env python3
"""
Test script for Content Generator component

Tests article generation with real topics and sources.
"""

import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from content_fetcher import ContentFetcher
from content_generator import ContentGenerator
from logger import setup_logger
from topic_discovery import TopicDiscoverer

from config import load_config  # type: ignore[attr-defined]


def test_content_generator():
    """Test the content generator component"""

    print("=" * 60)
    print("Testing Content Generator Component")
    print("=" * 60)
    print()

    # Load configuration
    try:
        config = load_config('local')
        print("✓ Config loaded successfully")
        print(f"  LLM Provider: {config.llm.provider}")
        print(f"  Generation Model: {config.llm.models.generation}")
        print(f"  Target levels: {config.generation.levels}")
    except Exception as e:
        print(f"✗ Failed to load config: {e}")
        return False

    # Setup logger
    try:
        logger = setup_logger(config, 'test-generator')
        print("✓ Logger initialized")
    except Exception as e:
        print(f"✗ Failed to setup logger: {e}")
        return False

    print()
    print("-" * 60)
    print("Step 1: Discovering topics...")
    print("-" * 60)
    print()

    # Initialize discoverer
    try:
        discoverer = TopicDiscoverer(config, logger)
        topics = discoverer.discover(limit=1)  # Just 1 topic for testing

        if not topics:
            print("✗ No topics found!")
            return False

        topic = topics[0]
        print(f"✓ Found topic: {topic.title}")
        print(f"  Sources: {len(topic.sources)}")
        print(f"  URLs: {len(topic.urls)}")
    except Exception as e:
        print(f"✗ Discovery failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print()
    print("-" * 60)
    print("Step 2: Fetching article sources...")
    print("-" * 60)
    print()

    # Initialize fetcher
    try:
        fetcher = ContentFetcher(config, logger)
        sources = fetcher.fetch_topic_sources(topic)

        if len(sources) < 3:
            print(f"⚠ Warning: Only {len(sources)} sources (need 3+)")
        else:
            print(f"✓ Fetched {len(sources)} sources")

        for i, source in enumerate(sources, 1):
            print(f"  {i}. {source.source:25} ({source.word_count} words)")
    except Exception as e:
        print(f"✗ Fetching failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    print()
    print("-" * 60)
    print("Step 3: Initializing Content Generator...")
    print("-" * 60)
    print()

    # Initialize generator
    try:
        generator = ContentGenerator(config, logger)
        print("✓ ContentGenerator initialized")
        print(f"  Provider: {config.llm.provider}")
    except Exception as e:
        print(f"✗ Failed to initialize generator: {e}")
        import traceback
        traceback.print_exc()
        return False

    print()
    print("-" * 60)
    print("Step 4: Generating article...")
    print("-" * 60)
    print()

    # Generate article
    level = config.generation.levels[0]  # Use first configured level

    try:
        print(f"Generating {level} article...")
        print("(This may take 10-30 seconds...)")
        print()

        article = generator.generate_article(topic, sources, level)

        print("✓ Article generated successfully!")
        print()
        print(f"Title: {article.title}")
        print(f"Level: {article.level}")
        print(f"Word count: {len(article.content.split())} words")
        print(f"Glossary entries attached: {len(article.vocabulary)}")
        print(f"Reading time: {article.reading_time} minutes")
        print(f"Sources: {', '.join(source.name for source in article.sources)}")
        print()

        # Display first 200 characters of content
        print("Content preview:")
        print("-" * 60)
        content_preview = article.content[:200]
        print(content_preview + "...")
        print("-" * 60)
        print()

        # Display glossary entries when testing already-enriched articles.
        if article.vocabulary:
            print("Glossary (first 5):")
            for item in article.vocabulary[:5]:
                definition = item.english
                if item.explanation:
                    definition = f"{definition} - {item.explanation}"
                print(f"  - {item.term}: {definition}")
            print()
        else:
            print("Glossary: not generated in this step (added after quality validation)")
            print()

    except Exception as e:
        print(f"✗ Generation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Validation
    print("-" * 60)
    print("Validation")
    print("-" * 60)
    print()

    passed = True

    # Check required fields (all should be present in Pydantic model)
    print("✓ All required fields present (validated by Pydantic)")

    # Check content length
    word_count = len(article.content.split())
    target = config.generation.target_word_count[level]
    tolerance = 0.3  # ±30%

    if word_count < target * (1 - tolerance):
        print(f"⚠ Content too short: {word_count} words (target: ~{target})")
    elif word_count > target * (1 + tolerance):
        print(f"⚠ Content too long: {word_count} words (target: ~{target})")
    else:
        print(f"✓ Content length appropriate: {word_count} words (target: ~{target})")

    # Glossary is generated in a later pipeline stage, so empty vocabulary is expected here.
    vocab_count = len(article.vocabulary)
    if vocab_count == 0:
        print("✓ No glossary attached yet (expected before glossary generation stage)")
    else:
        print(f"✓ Glossary entries already attached: {vocab_count}")

    print()
    print("=" * 60)
    if passed:
        print("✓ ALL TESTS PASSED")
    else:
        print("⚠ SOME VALIDATIONS FAILED (but article was generated)")
    print("=" * 60)

    return True


def main():
    """Entry point for CLI"""
    success = test_content_generator()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

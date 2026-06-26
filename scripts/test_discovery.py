#!/usr/bin/env python3
"""
Test script for Topic Discovery component

Tests the topic discovery system in isolation.
"""

import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from logger import setup_logger
from topic_discovery import TopicDiscoverer

from config import load_config  # type: ignore[attr-defined]


def test_topic_discovery():
    """Test the topic discovery component"""

    print("=" * 60)
    print("Testing Topic Discovery Component")
    print("=" * 60)
    print()

    # Load configuration
    try:
        config = load_config('local')
        print("✓ Config loaded successfully")
        print(f"  Sources configured: {len(config.sources_list)}")
    except Exception as e:
        print(f"✗ Failed to load config: {e}")
        return False

    # Setup logger
    try:
        logger = setup_logger(config, 'test-discovery')
        print("✓ Logger initialized")
    except Exception as e:
        print(f"✗ Failed to setup logger: {e}")
        return False

    print()
    print("-" * 60)
    print("Starting topic discovery...")
    print("-" * 60)
    print()

    # Initialize discoverer
    try:
        discoverer = TopicDiscoverer(config, logger)
        print("✓ TopicDiscoverer initialized")
        print("  SpaCy model loaded: de_core_news_sm")
    except Exception as e:
        print(f"✗ Failed to initialize discoverer: {e}")
        return False

    # Run discovery
    try:
        topics = discoverer.discover(limit=10)
        print()
        print("✓ Discovery completed")
        print(f"  Topics found: {len(topics)}")
    except Exception as e:
        print(f"✗ Discovery failed: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Validate results
    print()
    print("-" * 60)
    print("Validation")
    print("-" * 60)

    passed = True

    # Check: At least 1 topic found
    if len(topics) == 0:
        print("✗ No topics found")
        passed = False
    else:
        print(f"✓ Found {len(topics)} topics")

    # Check: Respect limit
    if len(topics) > 10:
        print(f"✗ Too many topics: {len(topics)} (limit was 10)")
        passed = False
    else:
        print(f"✓ Respects limit: {len(topics)} ≤ 10")

    # Validate each topic
    for i, topic in enumerate(topics, 1):
        print()
        print(f"Topic {i}: {topic.get('title', 'MISSING TITLE')}")

        # Check structure
        required_fields = ['title', 'mentions', 'sources', 'score', 'keywords', 'headlines']
        for field in required_fields:
            if field not in topic:
                print(f"  ✗ Missing field: {field}")
                passed = False

        # Check source count
        source_count = len(topic.get('sources', []))
        if source_count < 3:
            print(f"  ✗ Too few sources: {source_count} (need ≥3)")
            passed = False
        else:
            print(f"  ✓ Sources: {source_count}")

        # Check score
        score = topic.get('score', 0)
        if score <= 0:
            print(f"  ✗ Invalid score: {score}")
            passed = False
        else:
            print(f"  ✓ Score: {score}")

        # Check keywords
        keywords = topic.get('keywords', [])
        if len(keywords) == 0:
            print("  ✗ No keywords")
            passed = False
        else:
            print(f"  ✓ Keywords: {len(keywords)} ({', '.join(keywords[:3])}...)")

        # Check headlines
        headlines = topic.get('headlines', [])
        if len(headlines) == 0:
            print("  ✗ No headlines")
            passed = False
        else:
            print(f"  ✓ Headlines: {len(headlines)}")
            # Validate first headline
            if headlines:
                h = headlines[0]
                if 'url' not in h or 'text' not in h or 'source' not in h:
                    print("  ✗ Invalid headline structure")
                    passed = False

    # Display top topics
    print()
    print("-" * 60)
    print("Top 5 Topics")
    print("-" * 60)

    for i, topic in enumerate(topics[:5], 1):
        sources_str = ', '.join(topic['sources'][:3])
        if len(topic['sources']) > 3:
            sources_str += f" (+{len(topic['sources']) - 3} more)"

        print(f"{i}. {topic['title']}")
        print(f"   Score: {topic['score']} | Mentions: {topic['mentions']}")
        print(f"   Sources: {sources_str}")
        print()

    # Final result
    print("=" * 60)
    if passed:
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        return True
    else:
        print("✗ SOME TESTS FAILED")
        print("=" * 60)
        return False


def main():
    """Entry point for CLI"""
    success = test_topic_discovery()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

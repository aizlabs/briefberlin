#!/usr/bin/env python3
"""
BriefBerlin - Main Pipeline Entry Point

This script orchestrates the entire content generation pipeline:
1. Topic Discovery
2. Content Fetching
3. Article Generation
4. Quality Gate
5. Publishing

Usage:
    uv run spai-pipeline              # Run full pipeline
    ENVIRONMENT=local uv run spai-pipeline
    DRY_RUN=true uv run spai-pipeline  # Generate but don't publish
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from alerts import AlertManager
from audio_pipeline import AudioPipeline
from content_fetcher import ContentFetcher
from content_generator import ContentGenerator
from glossary_generator import GlossaryGenerator
from logger import setup_logger
from models import AdaptedArticle, QualityResult
from publisher import Publisher
from quality_gate import QualityGate
from topic_discovery import TopicDiscoverer

from config import load_config  # type: ignore[attr-defined]


def detect_environment() -> str:
    """Detect execution environment"""
    if os.getenv('GITHUB_ACTIONS') == 'true':
        return 'production'
    return os.getenv('ENVIRONMENT', 'local')


def create_run_id() -> str:
    """Generate unique run identifier"""
    env = detect_environment()
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    return f"{env}-{timestamp}"


def main():
    """Main pipeline execution"""

    # Setup
    run_id = create_run_id()
    environment = detect_environment()
    dry_run = os.getenv('DRY_RUN', 'false').lower() == 'true'
    start_time = time.time()

    # Load configuration
    config = load_config(environment)

    # Initialize logging
    logger = setup_logger(config, run_id)

    # Initialize alerting
    alert_manager = AlertManager(config, logger)

    logger.info("=" * 60)
    logger.info("BriefBerlin - Content Generation Pipeline")
    logger.info("=" * 60)
    logger.info(f"Run ID: {run_id}")
    logger.info(f"Environment: {environment}")
    logger.info(f"Dry Run: {dry_run}")
    logger.info(f"Provider: {config.llm.provider}")
    logger.info(f"Articles per run: {config.generation.articles_per_run}")
    logger.info(f"Levels: {config.generation.levels}")
    logger.info("=" * 60)
    logger.info("")
    logger.info(f"Pipeline started - {run_id}")

    # Statistics
    stats = {
        'attempted': 0,
        'published': 0,
        'rejected': 0,
        'regenerations': 0,
        'total_quality_score': 0.0
    }
    published_articles: List[Tuple[str, str]] = []  # (title, level) for each published article

    current_stage = "startup"

    try:
        # Initialize pipeline components
        current_stage = "initialization"
        logger.info("Initializing components...")
        discoverer = TopicDiscoverer(config, logger)
        fetcher = ContentFetcher(config, logger)
        generator = ContentGenerator(config, logger)
        quality_gate = QualityGate(config, logger)
        glossary_generator = GlossaryGenerator(config, logger)
        audio_pipeline = AudioPipeline(config, logger)
        publisher = Publisher(config, logger, dry_run=dry_run)

        logger.info("✓ All components initialized")
        logger.info("")

        # Phase 1: Topic Discovery
        current_stage = "topic_discovery"
        logger.info("-" * 60)
        logger.info("Phase 1: Topic Discovery")
        logger.info("-" * 60)

        topics = discoverer.discover(limit=10)
        logger.info(f"✓ Discovered {len(topics)} topics")
        logger.info("")

        if not topics:
            alert_manager.send_error(
                "No topics discovered",
                {"run_id": run_id, "environment": environment, "component": "discovery"},
            )
            raise Exception("No topics discovered")

        # Phase 2-5: Process each topic
        target_articles = config.generation.articles_per_run
        levels = config.generation.levels
        target_reached = False

        for topic in topics:
            if stats['published'] >= target_articles:
                logger.info(f"✓ Target reached: {target_articles} articles published")
                break

            logger.info("=" * 60)
            logger.info(f"Topic: {topic.title}")
            logger.info(f"Sources: {len(topic.sources)} | Mentions: {topic.mentions}")
            logger.info("=" * 60)
            logger.info("")

            # Phase 2: Fetch Sources
            current_stage = "fetch_sources"
            logger.info("Phase 2: Fetching article sources...")
            source_articles = fetcher.fetch_topic_sources(topic)  # Returns SourceArticle objects

            if len(source_articles) < 3:
                logger.warning(f"⚠ Insufficient sources ({len(source_articles)}/3), skipping topic")
                logger.info("")
                continue

            logger.info(f"✓ Fetched {len(source_articles)} sources")
            for i, s in enumerate(source_articles, 1):
                logger.info(f"  {i}. {s.source:25} ({s.word_count} words)")
            logger.info("")

            # Generate articles for each level
            for level in levels:
                if target_reached:
                    break

                stats['attempted'] += 1

                current_stage = f"generate_and_quality:{level}"
                logger.info("-" * 60)
                logger.info(f"Generating {level} article...")
                logger.info("-" * 60)

                # Phase 3: Generate Article
                article = generator.generate_article(topic, source_articles, level)
                word_count = len(article.content.split())

                logger.info(f"✓ Generated: {article.title}")
                logger.info(f"  Word count: {word_count}")
                logger.info("  Glossary: pending Phase 5 generation")
                logger.info("")

                # Phase 4: Quality Gate (with regeneration)
                logger.info("Phase 4: Quality check...")
                final_article: Optional[AdaptedArticle]
                quality_result: QualityResult
                final_article, quality_result = quality_gate.check_and_improve(
                    article,
                    generator,
                    topic,
                    source_articles
                )

                if final_article:
                    # Quality passed
                    stats['total_quality_score'] += quality_result.score
                    stats['regenerations'] += (quality_result.attempts - 1)

                    logger.info("✅ Quality check passed!")
                    logger.info(f"  Score: {quality_result.score:.1f}/10")
                    logger.info(f"  Attempts: {quality_result.attempts}")
                    if quality_result.strengths:
                        logger.info(f"  Strengths: {', '.join(quality_result.strengths[:2])}")
                    logger.info("")

                    logger.info("Phase 5: Generating glossary...")
                    final_article = glossary_generator.enrich_article(final_article)
                    glossary_stats = glossary_generator.last_run_stats
                    logger.info(
                        "  glossary_candidates_initial="
                        f"{glossary_stats['glossary_candidates_initial']}"
                    )
                    logger.info(
                        "  glossary_candidates_retry="
                        f"{glossary_stats['glossary_candidates_retry']}"
                    )
                    logger.info(
                        "  glossary_accepted="
                        f"{glossary_stats['glossary_accepted']}"
                    )
                    logger.info(
                        "  glossary_empty_after_retry="
                        f"{glossary_stats['glossary_empty_after_retry']}"
                    )
                    if glossary_stats["retry_used"] and glossary_stats["glossary_empty_after_retry"]:
                        logger.warning(
                            "Glossary still empty after retry for "
                            f"'{final_article.title}' "
                            f"(glossary_candidates_initial={glossary_stats['glossary_candidates_initial']}, "
                            f"glossary_candidates_retry={glossary_stats['glossary_candidates_retry']}, "
                            f"glossary_accepted={glossary_stats['glossary_accepted']})"
                        )
                    logger.info("")

                    # Optional website audio preparation
                    if config.audio.enabled:
                        logger.info("Phase 6: Preparing website audio metadata...")
                        final_article = audio_pipeline.prepare_for_publish(final_article)
                        logger.info("")
                    else:
                        logger.info(
                            "Phase 6: Skipping website audio preparation because "
                            "audio.enabled=false"
                        )
                        logger.info("")

                    # Phase 7: Publish
                    current_stage = f"publishing:{level}"
                    logger.info("Phase 7: Publishing...")
                    is_published = publisher.save_article(final_article)

                    if is_published:
                        stats['published'] += 1
                        published_articles.append((final_article.title, level))
                        logger.info("✅ Published successfully!")

                        # Check if target reached after each publication
                        if stats['published'] >= target_articles:
                            logger.info(f"✓ Target reached: {target_articles} articles published")
                            target_reached = True
                            break
                    else:
                        alert_manager.send_error(
                            "Publishing failed",
                            {
                                "run_id": run_id,
                                "environment": environment,
                                "topic": topic.title,
                                "level": level,
                            },
                        )

                else:
                    # Quality failed
                    stats['rejected'] += 1
                    logger.warning("❌ Quality check failed")
                    logger.warning(f"  Score: {quality_result.score:.1f}/10 (min: {config.quality_gate.min_score})")
                    logger.warning(f"  Attempts: {quality_result.attempts}")
                    if quality_result.issues:
                        logger.warning("  Issues:")
                        for issue in quality_result.issues[:3]:
                            logger.warning(f"    - {issue}")

                logger.info("")

            # Break out of topic loop if target reached
            if target_reached:
                break

        # Pipeline completed successfully
        duration = time.time() - start_time
        avg_quality = stats['total_quality_score'] / stats['published'] if stats['published'] > 0 else 0

        logger.info("=" * 60)
        logger.info("Pipeline Completed Successfully")
        logger.info("=" * 60)
        logger.info("")
        logger.info("✨ Summary:")
        logger.info(f"   Articles attempted:  {stats['attempted']}")
        logger.info(f"   Articles published:  {stats['published']}")
        logger.info(f"   Articles rejected:   {stats['rejected']}")
        if stats['attempted'] > 0:
            logger.info(f"   Success rate:        {stats['published']/stats['attempted']*100:.0f}%")
        else:
            logger.info("   Success rate:        N/A")
        logger.info(f"   Regenerations:       {stats['regenerations']}")
        if stats['published'] > 0:
            logger.info(f"   Avg quality score:   {avg_quality:.1f}/10")
        else:
            logger.info("   Avg quality score:   N/A")
        logger.info(f"   Duration:            {duration:.1f}s")
        logger.info("=" * 60)

        logger.info(f"Pipeline completed - Published: {stats['published']}/{stats['attempted']}")

        if stats['published'] > 0 and not dry_run:
            alert_manager.send_success_summary(
                run_id=run_id,
                duration_seconds=duration,
                attempted=stats['attempted'],
                published=stats['published'],
                rejected=stats['rejected'],
                regenerations=stats['regenerations'],
                published_articles=published_articles,
            )

        return 0

    except Exception as e:
        duration = time.time() - start_time

        logger.error("")
        logger.error("=" * 60)
        logger.error("Pipeline Failed")
        logger.error("=" * 60)
        logger.error(f"Error: {str(e)}")
        logger.error(f"Duration: {duration:.1f}s")
        logger.error("=" * 60)

        logger.error(f"Pipeline failed: {str(e)}", exc_info=True)
        alert_manager.send_failure_alert(
            run_id=run_id,
            environment=environment,
            stage=current_stage,
            exception=e,
        )

        alert_manager.send_critical(
            "Pipeline failure",
            {
                "run_id": run_id,
                "environment": environment,
                "duration_seconds": f"{duration:.1f}",
                "error": str(e),
            },
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())

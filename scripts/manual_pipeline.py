"""Manual private-input article generation pipeline."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from scripts.audio_pipeline import AudioPipeline
from scripts.config import load_config
from scripts.content_generator import ContentGenerator
from scripts.glossary_generator import GlossaryGenerator
from scripts.logger import setup_logger
from scripts.models import AdaptedArticle, QualityResult, SourceArticle, Topic
from scripts.publisher import Publisher
from scripts.quality_gate import QualityGate

MIN_SOURCE_WORDS = 20


def create_run_id(environment: str) -> str:
    """Generate a non-sensitive run identifier."""
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"{environment}-manual-{timestamp}"


def is_allowed_private_input_path(path: Path) -> bool:
    """Return whether a path follows the repo's private-input conventions."""
    parts = path.parts
    if path.name.endswith(".source.txt"):
        return True
    if "private-input" in parts:
        return True
    return any(left == "input" and right == "private" for left, right in zip(parts, parts[1:]))


def load_private_sources(paths: Sequence[Path]) -> list[SourceArticle]:
    """Read private source files into memory with generic source labels."""
    if not paths:
        raise ValueError("At least one private source file is required")

    sources: list[SourceArticle] = []
    for index, path in enumerate(paths, 1):
        if not is_allowed_private_input_path(path):
            raise ValueError(
                "Refusing input that is not under private-input/, input/private/, "
                "or named *.source.txt"
            )
        if not path.exists() or not path.is_file():
            raise ValueError(f"Private input {index} does not exist or is not a file")

        text = path.read_text(encoding="utf-8").strip()
        word_count = len(text.split())
        if word_count < MIN_SOURCE_WORDS:
            raise ValueError(
                f"Private input {index} is too short "
                f"({word_count} words, minimum {MIN_SOURCE_WORDS})"
            )

        sources.append(
            SourceArticle(
                source=f"Private source {index}",
                text=text,
                word_count=word_count,
                url=None,
            )
        )

    return sources


def build_manual_topic(title: str, sources: Sequence[SourceArticle]) -> Topic:
    """Create the in-memory topic used by the generation components."""
    return Topic(
        title=title,
        sources=[source.source for source in sources],
        mentions=len(sources),
        score=10.0,
        keywords=["deutsch"],
        urls=[],
    )


def run_manual_pipeline(args: argparse.Namespace) -> int:
    """Run generation from private source files through publish."""
    environment = args.environment or os.getenv("ENVIRONMENT", "local")
    dry_run = bool(args.dry_run)
    run_id = create_run_id(environment)

    config = load_config(environment)
    logger = setup_logger(config, run_id)

    levels = args.level or config.generation.levels
    source_paths = [Path(path).expanduser() for path in args.sources]
    sources = load_private_sources(source_paths)
    topic = build_manual_topic(args.topic, sources)

    logger.info("=" * 60)
    logger.info("BriefBerlin - Manual Private Input Pipeline")
    logger.info("=" * 60)
    logger.info("Run ID: %s", run_id)
    logger.info("Environment: %s", environment)
    logger.info("Dry Run: %s", dry_run)
    logger.info("Provider: %s", config.llm.provider)
    logger.info("Levels: %s", levels)
    logger.info("Private source count: %s", len(sources))
    logger.info("=" * 60)

    generator = ContentGenerator(config, logger)
    quality_gate = QualityGate(config, logger)
    glossary_generator = GlossaryGenerator(config, logger)
    audio_pipeline = AudioPipeline(config, logger)
    publisher = Publisher(config, logger, dry_run=dry_run)

    published: list[tuple[str, str, float]] = []
    failed = 0

    for level in levels:
        logger.info("-" * 60)
        logger.info("Generating %s article from private inputs", level)
        logger.info("-" * 60)

        article = generator.generate_article(topic, sources, level)
        final_article: AdaptedArticle | None
        quality_result: QualityResult
        final_article, quality_result = quality_gate.check_and_improve(
            article,
            generator,
            topic,
            sources,
        )

        if not final_article:
            failed += 1
            logger.warning(
                "Quality gate failed for %s article: score=%.1f issues=%s",
                level,
                quality_result.score,
                len(quality_result.issues),
            )
            continue

        logger.info("Quality gate passed for %s article: score=%.1f", level, quality_result.score)
        final_article = glossary_generator.enrich_article(final_article)

        if config.audio.enabled and not dry_run:
            final_article = audio_pipeline.prepare_for_publish(final_article)

        if publisher.save_article(final_article):
            published.append((final_article.title, level, quality_result.score))
            logger.info("Published %s article: %s", level, final_article.title)
        else:
            failed += 1
            logger.error("Publishing failed for %s article", level)

    logger.info("=" * 60)
    logger.info("Manual pipeline complete: published=%s failed=%s", len(published), failed)
    logger.info("=" * 60)

    for title, level, score in published:
        print(f"Generated {level} article: {title} (quality {score:.1f}/10)")
    if dry_run:
        print("Dry run enabled; no post was written.")

    return 0 if published and failed == 0 else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate German learner articles from private local source files.",
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="Private input files under private-input/, input/private/, or named *.source.txt",
    )
    parser.add_argument(
        "--topic",
        default="Manuell bereitgestellter Artikel",
        help="Non-private topic title used for generation context",
    )
    parser.add_argument(
        "--level",
        action="append",
        choices=["A2", "B1"],
        help="CEFR level to generate. Repeat for multiple levels. Defaults to config levels.",
    )
    parser.add_argument(
        "--environment",
        default=None,
        help="Configuration environment to load. Defaults to ENVIRONMENT or local.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run generation and validation without writing a post.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run_manual_pipeline(parse_args(argv))
    except Exception as exc:
        print(f"Manual pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

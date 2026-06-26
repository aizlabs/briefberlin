"""
Content Generator - Orchestrates Two-Step Generation

Coordinates ArticleSynthesizer (Step 1) and LevelAdapter (Step 2)
to produce level-appropriate German articles.

Architecture:
  Step 1: ArticleSynthesizer.synthesize() → Native-level article
  Step 2: LevelAdapter.adapt_to_level() → CEFR-adapted article
"""

import logging
from typing import List

from scripts.article_synthesizer import ArticleSynthesizer
from scripts.config import AppConfig
from scripts.level_adapter import LevelAdapter
from scripts.models import AdaptedArticle, SourceArticle, Topic


class ContentGenerator:
    """Orchestrates two-step article generation (synthesis + adaptation)"""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('ContentGenerator')
        self.generation_config = config.generation

        # Initialize sub-components
        self.synthesizer = ArticleSynthesizer(config, logger)
        self.adapter = LevelAdapter(config, logger)

        # Two-step settings
        two_step_config = self.generation_config.two_step_synthesis
        configured_save_base_articles = two_step_config.save_base_article
        self.save_base_articles = False
        self.base_article_path = two_step_config.base_article_path
        self.regeneration_strategy = two_step_config.regeneration_strategy

        self.logger.info("ContentGenerator initialized (two-step synthesis enabled)")
        if configured_save_base_articles:
            self.logger.warning(
                "Ignoring generation.two_step_synthesis.save_base_article=true because "
                "base article persistence is disabled for private source inputs"
            )

    def generate_article(
        self,
        topic: Topic,
        sources: List[SourceArticle],
        level: str
    ) -> AdaptedArticle:
        """
        Generate article using two-step process

        Args:
            topic: Topic dict from discovery with 'title' key
            sources: List of source content dicts
            level: 'A2' or 'B1'

        Returns:
            Complete article ready for quality gate with:
            - title, content, vocabulary, summary, reading_time
            - level, topic, sources (metadata)
            - base_article (stored for regeneration)
        """
        # Step 1: Synthesize native-level base article
        self.logger.info(f"Starting two-step generation for {level}: {topic.title}")
        base_article = self.synthesizer.synthesize(topic, sources)

        # Step 2: Adapt to target CEFR level
        article = self.adapter.adapt_to_level(base_article, level)

        self.logger.info(f"Two-step generation complete: {article.title}")

        return article

    def regenerate_with_feedback(
        self,
        topic: Topic,
        sources: List[SourceArticle],
        level: str,
        previous_attempt: AdaptedArticle,
        issues: List[str]
    ) -> AdaptedArticle:
        """
        Regenerate article with quality feedback

        Strategy is configurable via regeneration_strategy:
        - 'adaptation_only': Re-adapt same base article with feedback (default, faster)
        - 'full_pipeline': Re-synthesize + re-adapt (more thorough)

        Args:
            topic: Topic dict
            sources: Source content
            level: CEFR level ('A2' or 'B1')
            previous_attempt: Previous article that failed quality check
            issues: List of specific issues from quality gate

        Returns:
            Improved article
        """
        self.logger.info(
            f"Regenerating {level} article with {len(issues)} issues "
            f"(strategy: {self.regeneration_strategy})"
        )

        if self.regeneration_strategy == 'adaptation_only':
            # Extract base article from previous attempt
            base_article = previous_attempt.base_article

            if not base_article:
                # Fallback: Re-synthesize if base article not available
                self.logger.warning(
                    "Base article not found in previous attempt, "
                    "falling back to full pipeline regeneration"
                )
                base_article = self.synthesizer.synthesize(topic, sources)
            else:
                self.logger.debug("Reusing base article from previous attempt")

            # Re-adapt with feedback
            return self.adapter.adapt_to_level(base_article, level, feedback=issues)

        else:  # 'full_pipeline'
            # Re-synthesize + re-adapt
            self.logger.info("Regenerating full pipeline (synthesis + adaptation)")
            base_article = self.synthesizer.synthesize(topic, sources)

            return self.adapter.adapt_to_level(base_article, level, feedback=issues)

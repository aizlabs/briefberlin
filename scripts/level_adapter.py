"""
Level Adapter - Step 2 of Two-Step Generation

Adapts base (native-level) articles to specific CEFR levels.
Uses different strategies per level:
- A2: Strict simplification
- B1: Light adaptation with vocabulary simplification
"""

import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from scripts.config import AppConfig
from scripts.llm_factory import build_structured_prompt_chain
from scripts.models import AdaptedArticle, BaseArticle


class LevelAdapter:
    """Adapts articles to specific CEFR levels"""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('LevelAdapter')
        self.llm_config = config.llm.model_dump()
        self.generation_config = config.generation.model_dump()

        self.temperature = self.llm_config.get('temperature', 0.3)
        self._init_chains()

    def adapt_to_level(
        self,
        base_article: BaseArticle,
        level: str,
        feedback: Optional[List[str]] = None
    ) -> AdaptedArticle:
        """
        Adapt base article to target CEFR level

        Args:
            base_article: Article from ArticleSynthesizer with native-level German
            level: 'A2' or 'B1'
            feedback: Optional list of issues from quality gate (for regeneration)

        Returns:
            Adapted article dict with:
            - title (level-appropriate)
            - content (adapted to level)
            - summary (level-appropriate)
            - reading_time (int)
            - level (metadata)
            - topic (metadata)
            - sources (metadata)
            - base_article (stored for regeneration)
        """
        if level == 'A2':
            return self.adapt_to_a2(base_article, feedback)
        elif level == 'B1':
            return self.adapt_to_b1(base_article, feedback)
        else:
            raise ValueError(f"Unsupported level: {level}. Supported: A2, B1")

    def adapt_to_a2(
        self,
        base_article: BaseArticle,
        feedback: Optional[List[str]] = None
    ) -> AdaptedArticle:
        """
        Adapt to A2 with text-only simplification.
        """
        from scripts import prompts

        prompt = prompts.get_a2_adaptation_prompt(base_article, feedback)

        self.logger.info(f"Adapting to A2: {base_article.title}")
        if feedback:
            self.logger.debug(f"A2 adaptation with feedback: {len(feedback)} issues")

        response = self._call_llm(prompt, level='A2')
        article = self._build_adapted_article(response, base_article, 'A2')

        word_count = len(article.content.split())
        vocab_count = len(article.vocabulary)
        self.logger.info(f"A2 article adapted: {word_count} words, {vocab_count} vocabulary items")

        return article

    def adapt_to_b1(
        self,
        base_article: BaseArticle,
        feedback: Optional[List[str]] = None
    ) -> AdaptedArticle:
        """
        Adapt to B1 with light text-only modifications.
        """
        from scripts import prompts

        prompt = prompts.get_b1_adaptation_prompt(base_article, feedback)

        self.logger.info(f"Adapting to B1: {base_article.title}")
        if feedback:
            self.logger.debug(f"B1 adaptation with feedback: {len(feedback)} issues")

        response = self._call_llm(prompt, level='B1')
        article = self._build_adapted_article(response, base_article, 'B1')

        word_count = len(article.content.split())
        vocab_count = len(article.vocabulary)
        self.logger.info(f"B1 article adapted: {word_count} words, {vocab_count} vocabulary items")

        return article

    def _init_chains(self) -> None:
        """Initialize LangChain structured-output chains for A2 and B1 adaptation."""
        # Use adaptation model (can be cheaper than generation model)
        model_name = self.llm_config['models'].get(
            'adaptation',
            self.llm_config['models']['generation'],
        ) or self.llm_config['models']['generation']

        class AdaptationResponse(BaseModel):
            title: str = Field(..., description="Level-appropriate title")
            content: str = Field(..., description="Level-adapted content")
            summary: str = Field(..., description="Level-appropriate summary")
            reading_time: int = Field(..., description="Estimated reading time in minutes")

        self._adaptation_model = AdaptationResponse
        self.chain = build_structured_prompt_chain(
            self.llm_config,
            model_name,
            self.temperature,
            AdaptationResponse,
        )

    def _call_llm(self, prompt: str, level: str) -> BaseModel:
        """Call LLM for level adaptation and return structured response."""
        try:
            return self.chain.invoke({"prompt": prompt})
        except Exception as e:
            self.logger.error(f"LLM API call failed during {level} adaptation: {e}")
            raise

    def _build_adapted_article(
        self,
        response: BaseModel,
        base_article: BaseArticle,
        level: str
    ) -> AdaptedArticle:
        """Convert structured adaptation response into AdaptedArticle with metadata."""
        try:
            parsed = response.model_dump()
            parsed["content"] = parsed.get("content", "").replace("**", "")
            parsed["vocabulary"] = []

            parsed['level'] = level
            parsed['topic'] = base_article.topic.model_dump() if base_article.topic else None
            parsed['sources'] = [s.model_dump() for s in base_article.sources]
            parsed['base_article'] = base_article.model_dump()

            return AdaptedArticle(**parsed)
        except Exception as e:
            self.logger.error(f"Invalid adapted article structure or Pydantic validation error: {e}")
            raise ValueError(f"Invalid adapted article structure or Pydantic validation error: {e}")

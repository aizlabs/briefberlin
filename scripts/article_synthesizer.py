"""
Article Synthesizer - Step 1 of Two-Step Generation

Synthesizes multiple source articles into one coherent native-level
German article. No level adjustment - focuses on factual accuracy
and natural German expression.
"""

import logging
from typing import List

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from scripts.config import AppConfig
from scripts.llm_factory import create_chat_model, with_structured_output
from scripts.models import BaseArticle, SourceArticle, Topic


class SynthesisResponse(BaseModel):
    """Raw synthesis response structure from the LLM."""

    title: str = Field(..., description="Engaging headline in German")
    content: str = Field(..., description="Full article in natural German")
    summary: str = Field(..., description="One sentence summary in German")
    reading_time: int = Field(..., description="Estimated reading time in minutes")


class ArticleSynthesizer:
    """Synthesizes native-level German articles from multiple sources"""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('ArticleSynthesizer')

        # Cache LLM config as dict for the factory
        self.llm_config = config.llm.model_dump()
        self.temperature = self.llm_config.get('temperature', 0.3)
        self._init_chain()

    def synthesize(self, topic: Topic, sources: List[SourceArticle]) -> BaseArticle:
        """
        Synthesize native-level article from multiple sources

        Args:
            topic: Topic dict from discovery with 'title' key
            sources: List of source content dicts with 'source' and 'text' keys

        Returns:
            Base article dict with:
            - title (German)
            - content (native-level German, 300-400 words)
            - summary (German, one sentence)
            - reading_time (int, estimated minutes)
            - topic (metadata)
            - sources (metadata, list of source names)
        """
        from scripts import prompts

        prompt = prompts.get_synthesis_prompt(topic, sources)

        self.logger.info(f"Synthesizing base article for topic: {topic.title}")

        response = self._call_llm(prompt)
        article = self._build_base_article(response, topic, sources)

        self.logger.info(f"Synthesized base article: {article.title}")
        self.logger.debug(f"Base article word count: {len(article.content.split())}")

        return article

    def _init_chain(self) -> None:
        """Initialize LangChain structured-output chain for synthesis."""
        model_name = self.llm_config['models']['generation']
        chat_model = create_chat_model(self.llm_config, model_name, self.temperature)
        structured_llm = with_structured_output(chat_model, SynthesisResponse)

        # Simple wrapper prompt: we already build the full prompt string in prompts.py
        self.prompt_template = ChatPromptTemplate.from_messages(
            [("user", "{prompt}")]
        )
        self.chain = self.prompt_template | structured_llm

    def _call_llm(self, prompt: str) -> SynthesisResponse:
        """Call LLM with prompt for synthesis and return structured response."""
        try:
            return self.chain.invoke({"prompt": prompt})
        except Exception as e:
            self.logger.error(f"LLM API call failed during synthesis: {e}")
            raise

    def _build_base_article(
        self,
        response: SynthesisResponse,
        topic: Topic,
        sources: List[SourceArticle]
    ) -> BaseArticle:
        """Convert structured synthesis response into BaseArticle with metadata."""
        try:
            data = response.model_dump()
            data['topic'] = topic.model_dump()
            data['sources'] = [
                {'name': s.source, 'url': s.url} if s.url else {'name': s.source}
                for s in sources
            ]
            return BaseArticle(**data)
        except Exception as e:
            self.logger.error(f"Failed to build BaseArticle from synthesis response: {e}")
            raise

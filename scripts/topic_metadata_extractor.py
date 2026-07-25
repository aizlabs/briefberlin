"""Extract public-safe topic metadata from article sources."""

from __future__ import annotations

import logging
import re
from typing import List, cast

from pydantic import BaseModel, Field

from scripts.config import AppConfig
from scripts.llm_factory import build_structured_prompt_chain
from scripts.models import SourceArticle
from scripts.prompts import prepare_source_context
from scripts.topic_utils import extract_named_entities, sanitize_topic_keywords

FALLBACK_TOPIC_TITLE = "Manual source article"
MAX_TOPIC_KEYWORDS = 7


class TopicMetadataResponse(BaseModel):
    """Public-safe topic metadata extracted from source material."""

    title: str = Field(default="", description="Concise public topic title")
    keywords: List[str] = Field(default_factory=list, description="Short public topic keywords")
    category: str = Field(default="Nachrichten", description="Public news category, e.g. Verkehr, Politik, Kultur, Stadtleben, Wirtschaft, Wissenschaft")
    description: str = Field(default="", description="Concise public news summary for SEO (140-160 characters)")


class TopicMetadataExtractor:
    """Use the configured LLM and SpaCy NER to extract non-private topic title, category, description, and keywords."""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild("TopicMetadataExtractor")
        self.llm_config = config.llm.model_dump()
        self.max_words_per_source = config.sources.max_words_per_source
        self.spacy_model = getattr(config.language, "spacy_model", "de_core_news_sm")
        self.temperature = self.llm_config.get(
            "quality_temperature",
            self.llm_config.get("temperature", 0.1),
        )
        self._init_chain()

    def extract(self, sources: List[SourceArticle]) -> TopicMetadataResponse:
        """Return sanitized topic metadata with NER keywords, falling back to blank metadata on failure."""
        prompt = self._build_prompt(sources)

        try:
            response = self._call_llm(prompt)
            metadata = self._sanitize_response(response, sources)
        except Exception as exc:
            self.logger.warning(
                "Topic metadata extraction failed; using fallback metadata: %s",
                exc,
            )
            return self._fallback_metadata()

        if not metadata.title.strip():
            self.logger.warning("Topic metadata extraction returned an empty title; using fallback")
            return self._fallback_metadata()

        return metadata

    def _init_chain(self) -> None:
        models = self.llm_config["models"]
        model_name = models.get("topic_extraction") or models["generation"]
        self.chain = build_structured_prompt_chain(
            self.llm_config,
            model_name,
            self.temperature,
            TopicMetadataResponse,
        )

    def _build_prompt(self, sources: List[SourceArticle]) -> str:
        source_context = prepare_source_context(self._source_excerpts(sources))
        return f"""You extract public-safe topic metadata for a learner article pipeline.

Private or fetched source material is provided below. The source text may be private.
Do not quote private text directly. Do not reveal private source labels, filenames, URLs,
or attribution details. Extract only safe public metadata that can appear in a generated post.

TASK:
1. Write a concise topic title in the same language as the source material.
2. Choose 3-7 short public keywords focusing on main named entities (locations, organizations, key topic terms).
3. Choose a public news category (e.g., "Verkehr", "Politik", "Kultur", "Stadtleben", "Wirtschaft", "Wissenschaft", "Sport").
4. Write a concise 1-2 sentence public news description (140-160 characters) summarizing the core story.
5. Avoid private identifiers, source names, URLs, generic language labels, and filler terms.
6. Never use private proper nouns, person names, internal project names, client names,
   confidential codenames, or unusually specific identifiers as keywords.
7. If every possible keyword might reveal private source text, return an empty keyword list.

OUTPUT FORMAT (return ONLY valid JSON, no markdown):
{{
  "title": "concise public topic title",
  "keywords": ["keyword one", "keyword two"],
  "category": "Verkehr",
  "description": "concise news summary"
}}

SOURCES:
{source_context}
"""

    def _source_excerpts(self, sources: List[SourceArticle]) -> List[SourceArticle]:
        excerpts: List[SourceArticle] = []
        for source in sources:
            words = source.text.split()
            excerpt_words = words[:self.max_words_per_source]
            excerpt_text = " ".join(excerpt_words)
            excerpts.append(
                source.model_copy(
                    update={
                        "text": excerpt_text,
                        "word_count": len(excerpt_words),
                    }
                )
            )
        return excerpts

    def _call_llm(self, prompt: str) -> TopicMetadataResponse:
        return cast(TopicMetadataResponse, self.chain.invoke({"prompt": prompt}))

    def _sanitize_response(
        self, response: TopicMetadataResponse, sources: List[SourceArticle] | None = None
    ) -> TopicMetadataResponse:
        payload = response.model_dump()
        raw_title = payload.get("title") or ""
        title = re.sub(r"\s+", " ", str(raw_title)).strip()

        raw_keywords = payload.get("keywords") or []
        llm_keywords = [str(kw) for kw in raw_keywords] if isinstance(raw_keywords, list) else []

        # SpaCy Named Entity Recognition on source text to pull out entities (LOC, ORG, PER, MISC)
        ner_entities: List[str] = []
        if sources:
            combined_text = "\n".join(s.text for s in sources if s and s.text)
            ner_entities = extract_named_entities(combined_text, spacy_model=self.spacy_model)

        combined_keywords = llm_keywords + ner_entities
        keywords = sanitize_topic_keywords(
            combined_keywords,
            max_keywords=MAX_TOPIC_KEYWORDS,
        )

        category = str(payload.get("category") or "Nachrichten").strip() or "Nachrichten"
        description = re.sub(r"\s+", " ", str(payload.get("description") or "")).strip()

        return TopicMetadataResponse(
            title=title,
            keywords=keywords,
            category=category,
            description=description,
        )

    def _fallback_metadata(self) -> TopicMetadataResponse:
        return TopicMetadataResponse(
            title=FALLBACK_TOPIC_TITLE,
            keywords=[],
            category="Nachrichten",
            description="",
        )


"""Reader-language translation of finished articles.

NOTE ON THE TWO LANGUAGE AXES - they never interact:

* ``language:`` in config is the SITE-FORK axis: the one language the pipeline
  *teaches*. It drives the prompt pack, the spaCy model, the glossary rules and
  the learner-facing labels. See docs/language-profile-fork-guide.md.
* ``translations:`` is the COMPREHENSION-SUPPORT axis: the languages the finished
  text is *rendered into* so a learner can read along.

This module reads none of ``language.prompt_pack``, ``language.glossary_rules``,
``language.spacy_model`` or ``language.glossary_heading``. Translated pages use
the per-language ``glossary_heading`` from ``translations.languages``.

Failure policy is FAIL-OPEN: a language that cannot be translated is dropped,
logged, and recorded in ``last_run_stats``. Publishing the German article must
never depend on a translation succeeding.
"""

from __future__ import annotations

import contextvars
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from pydantic import BaseModel, Field

from scripts.config import AppConfig
from scripts.llm_factory import build_structured_prompt_chain
from scripts.models import (
    AdaptedArticle,
    ArticleTranslation,
    TranslatedVocabularyItem,
    TranslationLanguageConfig,
    VocabularyItem,
)
from scripts.prompts import get_translation_prompt
from scripts.translation_hints import publishable_translation_hints, visible_glossary_items


class TranslationVocabularyResponse(BaseModel):
    term: str = Field(..., description="The German term, echoed back unchanged")
    translation: str = Field(..., description="The term in the target language")
    explanation: str = Field(..., description="The explanation in the target language")


class TranslationResponse(BaseModel):
    title: str = Field(..., description="Translated title")
    summary: str = Field(..., description="Translated summary")
    content: str = Field(..., description="Translated body, plain text, same paragraph count")
    vocabulary: List[TranslationVocabularyResponse] = Field(default_factory=list)


class ArticleTranslator:
    """Translates a finished AdaptedArticle into every configured language."""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger.getChild("ArticleTranslator")
        self.settings = config.translations
        self.llm_config: Dict[str, Any] = config.llm.model_dump()
        self.model_name: Optional[str] = None
        self.chain: Any = None
        self.last_run_stats: Dict[str, Any] = {
            "translated_languages": [],
            "failed_languages": [],
            "paragraph_mismatches": [],
        }

    # -- public API ---------------------------------------------------------

    def translate_article(self, article: AdaptedArticle) -> AdaptedArticle:
        """Return the article with its ``translations`` populated.

        Never raises: a total failure yields the article unchanged so the German
        post still publishes.
        """
        self.last_run_stats = {
            "translated_languages": [],
            "failed_languages": [],
            "paragraph_mismatches": [],
        }

        if not self.settings.enabled:
            self.logger.debug("Translations disabled; skipping")
            return article

        languages = self.settings.for_level(article.level)
        if not languages:
            self.logger.info("No translation languages configured for level %s", article.level)
            return article

        try:
            self._init_chain()
        except Exception as exc:  # pragma: no cover - config/credential failure
            self.logger.error("Could not initialize translation chain: %s", exc)
            self.last_run_stats["failed_languages"] = [lang.code for lang in languages]
            return article

        hints = publishable_translation_hints(article)
        glossary = visible_glossary_items(hints)

        self.logger.info(
            "Translating '%s' (%s) into %d languages: %s",
            article.title,
            article.level,
            len(languages),
            ", ".join(lang.code for lang in languages),
        )

        # LangChain's usage accounting (scripts/usage_report.collect_run_usage)
        # lives in a context var, and worker threads do NOT inherit context vars.
        # Submitting through a copied context is what keeps the translation spend
        # in the run cost report.
        def run(language: TranslationLanguageConfig) -> Optional[ArticleTranslation]:
            ctx = contextvars.copy_context()
            return ctx.run(self._translate_one_safely, article, language, glossary)

        with ThreadPoolExecutor(max_workers=self.settings.max_workers) as pool:
            results = list(pool.map(run, languages))

        translations = [item for item in results if item is not None]
        self.last_run_stats["translated_languages"] = [item.lang for item in translations]

        if self.last_run_stats["failed_languages"]:
            self.logger.warning(
                "Translation failed for: %s (article still publishes)",
                ", ".join(self.last_run_stats["failed_languages"]),
            )

        return article.model_copy(update={"translations": translations})

    def translate_to_language(
        self,
        article: AdaptedArticle,
        language: TranslationLanguageConfig,
    ) -> ArticleTranslation:
        """Translate into a single language. Raises on failure."""
        if self.chain is None:
            self._init_chain()
        hints = publishable_translation_hints(article)
        glossary = visible_glossary_items(hints)
        prompt = get_translation_prompt(article, language, glossary)
        response = cast(TranslationResponse, self.chain.invoke({"prompt": prompt}))
        return self._build_translation(response, article, language, glossary)

    # -- internals ----------------------------------------------------------

    def _init_chain(self) -> None:
        models = self.llm_config["models"]
        self.model_name = (
            self.settings.model
            or models.get("translation")
            or models.get("adaptation")
            or models["generation"]
        )
        self.chain = build_structured_prompt_chain(
            self.llm_config,
            self.model_name,
            self.settings.temperature,
            TranslationResponse,
        )

    def _translate_one_safely(
        self,
        article: AdaptedArticle,
        language: TranslationLanguageConfig,
        glossary: Sequence[Tuple[str, VocabularyItem]],
    ) -> Optional[ArticleTranslation]:
        prompt = get_translation_prompt(article, language, glossary)

        for attempt in range(1, self.settings.max_attempts + 1):
            try:
                response = cast(TranslationResponse, self.chain.invoke({"prompt": prompt}))
                return self._build_translation(response, article, language, glossary)
            except Exception as exc:
                if attempt >= self.settings.max_attempts:
                    self.logger.error(
                        "Translation to %s failed after %d attempts: %s",
                        language.code,
                        attempt,
                        exc,
                    )
                    self.last_run_stats["failed_languages"].append(language.code)
                    return None
                self.logger.warning(
                    "Translation to %s attempt %d failed (%s); retrying",
                    language.code,
                    attempt,
                    exc,
                )
                time.sleep(0.5 * attempt)
        return None

    def _build_translation(
        self,
        response: TranslationResponse,
        article: AdaptedArticle,
        language: TranslationLanguageConfig,
        glossary: Sequence[Tuple[str, VocabularyItem]],
    ) -> ArticleTranslation:
        content = self._clean_body(response.content)

        expected = len([p for p in article.content.split("\n\n") if p.strip()])
        actual = len([p for p in content.split("\n\n") if p.strip()])
        if expected != actual:
            # Accepted anyway: a dropped language is worse for the reader than an
            # imperfect paragraph split.
            self.logger.warning(
                "Paragraph count mismatch for %s: German %d vs translated %d",
                language.code,
                expected,
                actual,
            )
            self.last_run_stats["paragraph_mismatches"].append(language.code)

        return ArticleTranslation(
            lang=language.code,
            glossary_heading=language.glossary_heading,
            title=self._clean_inline(response.title) or article.title,
            summary=self._clean_inline(response.summary),
            content=content,
            vocabulary=self._align_vocabulary(response.vocabulary, glossary),
            reading_time=article.reading_time,
            model=self.model_name,
        )

    def _align_vocabulary(
        self,
        rows: Sequence[TranslationVocabularyResponse],
        glossary: Sequence[Tuple[str, VocabularyItem]],
    ) -> List[TranslatedVocabularyItem]:
        """Match model rows back onto the source glossary BY GERMAN TERM.

        Rows the model invented are dropped; rows it omitted are re-emitted with
        an empty translation. The parallel glossary must keep the same rows, in
        the same order, as the German page.
        """
        by_term: Dict[str, TranslationVocabularyResponse] = {}
        for row in rows:
            key = (row.term or "").strip().casefold()
            if key and key not in by_term:
                by_term[key] = row

        aligned: List[TranslatedVocabularyItem] = []
        for _, item in glossary:
            matched: Optional[TranslationVocabularyResponse] = by_term.get(item.term.casefold())
            if matched is None:
                self.logger.warning("Model omitted glossary term '%s'", item.term)
            aligned.append(
                TranslatedVocabularyItem(
                    term=item.term,  # always the German headword, never the model's echo
                    translation=self._clean_inline(matched.translation) if matched else "",
                    explanation=self._clean_inline(matched.explanation) if matched else "",
                )
            )
        return aligned

    @staticmethod
    def _clean_inline(value: Optional[str]) -> str:
        if not value:
            return ""
        return value.replace("**", "").replace("<", "").replace(">", "").strip()

    @staticmethod
    def _clean_body(value: str) -> str:
        # The published body is plain text; any markup the model added would be
        # escaped or, worse, collide with the publisher's own hint markup.
        cleaned = (value or "").replace("**", "").replace("<", "").replace(">", "")
        paragraphs = [p.strip() for p in cleaned.split("\n\n")]
        return "\n\n".join(p for p in paragraphs if p)

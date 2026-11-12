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

Two backends share this one public API, selected lazily by
``translations.provider``: the cloud structured-output chain (default, provider
null) and the native local Ollama adapter (provider ``ollama``, see
scripts/ollama_translation.py). Both public methods use the same backend.

Failure policy is FAIL-OPEN: a language that cannot be translated is dropped,
logged, and recorded in ``last_run_stats``. Publishing the German article must
never depend on a translation succeeding.

The local backend translates deterministic units (title, nonempty summary, each
body paragraph, visible glossary fields) sequentially per language and assembles
the :class:`ArticleTranslation` in Python, so paragraph structure and German
glossary headwords survive byte-for-byte. Glossary labels pivot through an
existing English gloss when one exists (translated explicitly from English);
without one, the German headword itself is translated from German, and German
explanations are always translated from German. This sense-preserving pivot
trades full-article context and all-direct-German translation for stability - a
documented quality tradeoff, not a hidden semantic claim.
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
from scripts.ollama_translation import OllamaChatAdapter, OllamaTranslationError, clean_unit_text
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


class _TranslationUnit:
    """One local translation request in deterministic source order."""

    __slots__ = ("kind", "index", "source_name", "source_code", "text")

    def __init__(
        self,
        kind: str,
        index: int,
        source_name: str,
        source_code: str,
        text: str,
    ) -> None:
        self.kind = kind
        self.index = index
        self.source_name = source_name
        self.source_code = source_code
        self.text = text


class ArticleTranslator:
    """Translates a finished AdaptedArticle into every configured language."""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger.getChild("ArticleTranslator")
        self.settings = config.translations
        self.llm_config: Dict[str, Any] = config.llm.model_dump()
        self.model_name: Optional[str] = None
        self.chain: Any = None
        self.adapter: Optional[OllamaChatAdapter] = None
        self.last_run_stats: Dict[str, Any] = {
            "translated_languages": [],
            "failed_languages": [],
            "paragraph_mismatches": [],
        }

    # -- public API ---------------------------------------------------------

    @property
    def local_backend(self) -> bool:
        """True when translations route to the local Ollama backend."""
        return self.settings.provider == "ollama"

    def translate_article(self, article: AdaptedArticle) -> AdaptedArticle:
        """Return the article with its ``translations`` populated.

        Never raises: a total failure yields the article unchanged so the German
        post still publishes.
        """
        self.last_run_stats = {
            "translated_languages": [],
            "failed_languages": [],
            "paragraph_mismatches": [],
            "backend": "ollama" if self.local_backend else "cloud",
            "languages": {},
        }

        if not self.settings.enabled:
            self.logger.debug("Translations disabled; skipping")
            return article

        languages = self.settings.for_level(article.level)
        if not languages:
            self.logger.info("No translation languages configured for level %s", article.level)
            return article

        try:
            self._init_backend()
        except Exception as exc:  # config/credential failure stays fail-open
            self.logger.error("Could not initialize translation backend: %s", exc)
            self.last_run_stats["failed_languages"] = [lang.code for lang in languages]
            return article

        if self.local_backend:
            return self._translate_article_local(article, languages)

        return self._translate_article_cloud(article, languages)

    def translate_to_language(
        self,
        article: AdaptedArticle,
        language: TranslationLanguageConfig,
    ) -> ArticleTranslation:
        """Translate into a single language. Raises on failure."""
        if self.local_backend:
            if self.adapter is None:
                self._init_backend()
            glossary = visible_glossary_items(publishable_translation_hints(article))
            translation, stats = self._translate_language_local(article, language, glossary)
            # Per-call semantics: one complete, coherent observation per
            # successful direct translation (the bulk path records the same
            # fields in last_run_stats instead). Labelled fields keep the
            # record parseable as a scoped diagnostic observation.
            self.logger.info(
                "Direct translation completed: target_language=%s provider=%s "
                "model=%s level=%s requests=%s retries=%s elapsed_seconds=%s "
                "request_durations_ns=%s",
                stats["language"],
                stats["provider"],
                stats["model"],
                stats["level"],
                stats["requests"],
                stats["retries"],
                stats["elapsed_seconds"],
                stats["request_durations_ns"],
            )
            return translation

        if self.chain is None:
            self._init_chain()
        glossary = visible_glossary_items(publishable_translation_hints(article))
        prompt = get_translation_prompt(article, language, glossary)
        response = cast(TranslationResponse, self.chain.invoke({"prompt": prompt}))
        return self._build_translation(response, article, language, glossary)

    # -- backend selection --------------------------------------------------

    def _init_backend(self) -> None:
        if self.local_backend:
            self._init_local_adapter()
        else:
            self._init_chain()

    def _init_local_adapter(self) -> None:
        model = (self.settings.model or "").strip()
        if not model:
            raise OllamaTranslationError(
                "Local Ollama translation requires translations.model to be set explicitly",
                category="missing_model",
            )
        self.model_name = model
        self.adapter = OllamaChatAdapter(
            base_url=self.settings.ollama.base_url,
            model=model,
            temperature=self.settings.temperature,
            timeout_seconds=self.settings.ollama.timeout_seconds,
            max_attempts=self.settings.max_attempts,
            logger=self.logger,
        )

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

    # -- local backend ------------------------------------------------------

    def _translate_article_local(
        self,
        article: AdaptedArticle,
        languages: List[TranslationLanguageConfig],
    ) -> AdaptedArticle:
        glossary = visible_glossary_items(publishable_translation_hints(article))

        self.logger.info(
            "Translating article (%s) into %d languages: %s",
            article.level,
            len(languages),
            ", ".join(lang.code for lang in languages),
        )

        # Usage accounting (scripts/usage_report.collect_run_usage) lives in a
        # context var, and worker threads do NOT inherit context vars, so each
        # task has to run inside a copy of the SUBMITTING thread's context or
        # its records vanish from the run cost report. The copies must be made
        # HERE, in the calling thread. One copy per task, because a Context
        # cannot be entered twice concurrently.
        tasks = [(language, contextvars.copy_context()) for language in languages]

        def run(
            task: Tuple[TranslationLanguageConfig, contextvars.Context],
        ) -> Tuple[Optional[ArticleTranslation], Dict[str, Any]]:
            language, ctx = task
            return ctx.run(self._translate_one_local_safely, article, language, glossary)

        with ThreadPoolExecutor(max_workers=self.settings.max_workers) as pool:
            outcomes = list(pool.map(run, tasks))

        translations = [item for item, _stats in outcomes if item is not None]
        self.last_run_stats["translated_languages"] = [item.lang for item in translations]
        self.last_run_stats["failed_languages"] = [
            language.code
            for language, (item, _stats) in zip(languages, outcomes)
            if item is None
        ]
        self.last_run_stats["languages"] = {
            language.code: stats for language, (_item, stats) in zip(languages, outcomes)
        }

        if self.last_run_stats["failed_languages"]:
            self.logger.warning(
                "Translation failed for: %s (article still publishes)",
                ", ".join(self.last_run_stats["failed_languages"]),
            )

        return article.model_copy(update={"translations": translations})

    def _translate_one_local_safely(
        self,
        article: AdaptedArticle,
        language: TranslationLanguageConfig,
        glossary: Sequence[Tuple[str, VocabularyItem]],
    ) -> Tuple[Optional[ArticleTranslation], Dict[str, Any]]:
        try:
            return self._translate_language_local(article, language, glossary)
        except OllamaTranslationError as exc:
            stats = exc.language_stats or {}
            self.logger.error(
                "Translation to %s failed (category=%s, attempts=%s, unit=%s, index=%s)",
                language.code,
                exc.category,
                exc.attempts,
                stats.get("unit"),
                stats.get("index"),
            )
            return None, stats

    def _translate_language_local(
        self,
        article: AdaptedArticle,
        language: TranslationLanguageConfig,
        glossary: Sequence[Tuple[str, VocabularyItem]],
    ) -> Tuple[ArticleTranslation, Dict[str, Any]]:
        stats: Dict[str, Any] = {
            "provider": "ollama",
            "model": self.model_name,
            "level": article.level,
            "language": language.code,
            "requests": 0,
            "retries": 0,
            "request_durations_ns": [],
        }
        started = time.monotonic()
        try:
            translation = self._run_local_units(article, language, glossary, stats)
        except OllamaTranslationError as exc:
            stats["elapsed_seconds"] = round(time.monotonic() - started, 6)
            exc.language_stats = stats
            raise
        stats["elapsed_seconds"] = round(time.monotonic() - started, 6)
        return translation, stats

    def _build_local_units(
        self,
        article: AdaptedArticle,
        language: TranslationLanguageConfig,
        glossary: Sequence[Tuple[str, VocabularyItem]],
    ) -> Tuple[List[_TranslationUnit], List[Dict[str, Any]]]:
        """Deterministic unit list plus the parallel glossary row slots."""
        units: List[_TranslationUnit] = []
        units.append(_TranslationUnit("title", 0, "German", "de", article.title))
        if (article.summary or "").strip():
            units.append(_TranslationUnit("summary", 0, "German", "de", article.summary))

        paragraph_position = 0
        for paragraph in article.content.split("\n\n"):
            if paragraph.strip():
                units.append(
                    _TranslationUnit("paragraph", paragraph_position, "German", "de", paragraph)
                )
                paragraph_position += 1

        rows: List[Dict[str, Any]] = []
        for item_index, (_hint_id, item) in enumerate(glossary):
            english_gloss = (item.english or "").strip()
            # English reuses an existing nonempty gloss outright; other targets
            # translate it explicitly from English (sense-preserving pivot).
            reuse_english = language.code == "en" and english_gloss
            rows.append(
                {
                    "term": item.term,
                    "translation": clean_unit_text(item.english) if reuse_english else "",
                    "explanation": "",
                }
            )
            if not reuse_english:
                if english_gloss:
                    units.append(
                        _TranslationUnit("glossary", item_index, "English", "en", item.english)
                    )
                else:
                    units.append(
                        _TranslationUnit("glossary", item_index, "German", "de", item.term)
                    )
            if (item.explanation or "").strip():
                units.append(
                    _TranslationUnit(
                        "explanation", item_index, "German", "de", item.explanation
                    )
                )

        return units, rows

    def _run_local_units(
        self,
        article: AdaptedArticle,
        language: TranslationLanguageConfig,
        glossary: Sequence[Tuple[str, VocabularyItem]],
        stats: Dict[str, Any],
    ) -> ArticleTranslation:
        adapter = self.adapter
        if adapter is None:  # pragma: no cover - defensive, initialized upstream
            raise OllamaTranslationError(
                "Local translation backend was not initialized", category="missing_model"
            )

        units, rows = self._build_local_units(article, language, glossary)
        title = ""
        summary = ""
        paragraphs: Dict[int, str] = {}

        for unit in units:
            try:
                outcome = adapter.translate_unit(
                    unit.source_name,
                    unit.source_code,
                    language.name,
                    language.code,
                    unit.text,
                )
            except OllamaTranslationError as exc:
                stats["requests"] += exc.attempts
                stats["retries"] += exc.attempts - 1
                stats["request_durations_ns"].extend(exc.durations_ns)
                stats["unit"] = unit.kind
                stats["index"] = unit.index
                stats["category"] = exc.category
                raise
            stats["requests"] += outcome.attempts
            stats["retries"] += outcome.attempts - 1
            stats["request_durations_ns"].extend(outcome.durations_ns)
            text = clean_unit_text(outcome.text)
            if not text:
                stats["unit"] = unit.kind
                stats["index"] = unit.index
                stats["category"] = "empty"
                raise OllamaTranslationError(
                    "Ollama returned an empty translation after cleaning",
                    category="empty",
                    attempts=outcome.attempts,
                )
            if unit.kind == "title":
                title = text
            elif unit.kind == "summary":
                summary = text
            elif unit.kind == "paragraph":
                paragraphs[unit.index] = text
            elif unit.kind == "glossary":
                rows[unit.index]["translation"] = text
            elif unit.kind == "explanation":
                rows[unit.index]["explanation"] = text

        content_parts: List[str] = []
        paragraph_position = 0
        for paragraph in article.content.split("\n\n"):
            if paragraph.strip():
                content_parts.append(paragraphs[paragraph_position])
                paragraph_position += 1
            else:
                content_parts.append(paragraph)

        vocabulary = [
            TranslatedVocabularyItem(
                term=row["term"], translation=row["translation"], explanation=row["explanation"]
            )
            for row in rows
        ]
        return ArticleTranslation(
            lang=language.code,
            glossary_heading=language.glossary_heading,
            title=title,
            summary=summary,
            content="\n\n".join(content_parts),
            vocabulary=vocabulary,
            reading_time=article.reading_time,
            model=self.model_name,
        )

    # -- cloud backend ------------------------------------------------------

    def _translate_article_cloud(
        self,
        article: AdaptedArticle,
        languages: List[TranslationLanguageConfig],
    ) -> AdaptedArticle:
        glossary = visible_glossary_items(publishable_translation_hints(article))

        self.logger.info(
            "Translating '%s' (%s) into %d languages: %s",
            article.title,
            article.level,
            len(languages),
            ", ".join(lang.code for lang in languages),
        )

        tasks = [(language, contextvars.copy_context()) for language in languages]

        def run(
            task: Tuple[TranslationLanguageConfig, contextvars.Context],
        ) -> Optional[ArticleTranslation]:
            language, ctx = task
            return ctx.run(self._translate_one_safely, article, language, glossary)

        with ThreadPoolExecutor(max_workers=self.settings.max_workers) as pool:
            results = list(pool.map(run, tasks))

        translations = [item for item in results if item is not None]
        self.last_run_stats["translated_languages"] = [item.lang for item in translations]

        if self.last_run_stats["failed_languages"]:
            self.logger.warning(
                "Translation failed for: %s (article still publishes)",
                ", ".join(self.last_run_stats["failed_languages"]),
            )

        return article.model_copy(update={"translations": translations})

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
        # Preserve the cloud body's historical minimum after cleaning. Local
        # unit assembly only requires nonempty results and bypasses this path.
        if len(content) < 20:
            raise ValueError("Cloud translated body must contain at least 20 characters")

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

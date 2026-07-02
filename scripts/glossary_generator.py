"""
Generate and validate glossary entries after the article text is approved.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import spacy
from pydantic import BaseModel, ConfigDict, Field

from scripts import prompts
from scripts.config import AppConfig
from scripts.llm_factory import build_structured_prompt_chain
from scripts.models import AdaptedArticle, VocabularyItem, coerce_vocabulary_items
from scripts.text_utils import (
    ensure_vocabulary_bolded,
    normalize_vocabulary_term,
    slugify_text,
    vocabulary_term_present,
)

REJECT_ENTITY_LABELS = {"PER", "PERSON", "GPE", "LOC"}
MAX_CLICKABLE_TERM_WORDS = 3
ORGANIZATION_OR_GROUP_TOKENS = {
    "agencia",
    "banco",
    "brigada",
    "comision",
    "comite",
    "congreso",
    "consejo",
    "corte",
    "ejercito",
    "estado",
    "fuerza",
    "frente",
    "gobierno",
    "guardia",
    "grupo",
    "ministerio",
    "movimiento",
    "organizacion",
    "partido",
    "policia",
    "presidencia",
    "tribunal",
    "union",
}
PLACE_DESIGNATOR_TOKENS = {
    "capital",
    "ciudad",
    "estado",
    "isla",
    "islas",
    "pais",
    "provincia",
    "region",
    "reino",
    "republica",
}
PLACE_CLUE_TOKENS = {
    "capital",
    "capitol",
    "ciudad",
    "city",
    "continent",
    "continente",
    "country",
    "estado",
    "isla",
    "island",
    "nation",
    "nacion",
    "pais",
    "province",
    "provincia",
    "region",
    "reino",
    "republic",
    "republica",
    "state",
}
PERSON_CLUE_TOKENS = {
    "actor",
    "actriz",
    "cantante",
    "expresidente",
    "former",
    "gobernante",
    "king",
    "leader",
    "lider",
    "ministro",
    "politician",
    "politico",
    "president",
    "presidente",
    "queen",
    "rey",
}
ORGANIZATION_CLUE_TOKENS = ORGANIZATION_OR_GROUP_TOKENS | {
    "committee",
    "commission",
    "congress",
    "council",
    "court",
    "cross",
    "force",
    "forces",
    "government",
    "group",
    "guard",
    "ministry",
    "movement",
    "nations",
    "organization",
    "organisation",
    "party",
    "police",
    "tribunal",
    "union",
}
NAME_CONNECTOR_TOKENS = {
    "da",
    "de",
    "del",
    "di",
    "e",
    "el",
    "la",
    "las",
    "lo",
    "los",
    "van",
    "von",
    "y",
}
COMMON_PLACE_TERMS = {
    "berlin",
    "brandenburg",
    "america latina",
    "china",
    "deutschland",
    "estados unidos",
    "europa",
    "frankreich",
    "iran",
    "israel",
    "paris",
    "rusia",
    "teheran",
    "ucrania",
    "ukraine",
    "usa",
    "washington",
    "yemen",
}
COMMON_PERSON_TERMS = {
    "donald trump",
}
TERM_STOPWORDS = {
    "a",
    "al",
    "am",
    "an",
    "auf",
    "aus",
    "bei",
    "con",
    "das",
    "de",
    "dem",
    "den",
    "der",
    "del",
    "des",
    "die",
    "el",
    "en",
    "für",
    "im",
    "in",
    "la",
    "las",
    "lo",
    "los",
    "mit",
    "para",
    "por",
    "und",
    "su",
    "sus",
    "un",
    "una",
    "unos",
    "unas",
    "von",
    "zu",
    "y",
}
ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "of",
    "or",
    "the",
    "to",
}
COGNATE_SUFFIX_MAP = (
    ("aciones", "ations"),
    ("acion", "ation"),
    ("ciones", "tions"),
    ("cion", "tion"),
    ("siones", "sions"),
    ("sion", "sion"),
    ("dades", "ties"),
    ("dad", "ty"),
    ("mente", "ly"),
    ("ismos", "isms"),
    ("ismo", "ism"),
    ("istas", "ists"),
    ("ista", "ist"),
    ("ivos", "ives"),
    ("ivo", "ive"),
    ("ivas", "ives"),
    ("iva", "ive"),
    ("icos", "ic"),
    ("icas", "ic"),
    ("ico", "ic"),
    ("ica", "ic"),
    ("arios", "ary"),
    ("arias", "ary"),
    ("ario", "ary"),
    ("aria", "ary"),
    ("ables", "able"),
    ("able", "able"),
    ("ibles", "ible"),
    ("ible", "ible"),
    ("kturen", "ctures"),
    ("ktur", "cture"),
    ("turen", "tures"),
    ("tur", "ture"),
    ("ionen", "ions"),
    ("ion", "ion"),
    ("tionen", "tions"),
    ("tion", "tion"),
    ("ik", "ic"),
    ("isch", "ic"),
    ("ische", "ic"),
    ("ischen", "ic"),
    ("ischer", "ic"),
    ("isches", "ic"),
    ("osas", "ous"),
    ("osos", "ous"),
    ("osa", "ous"),
    ("oso", "ous"),
    ("ales", "al"),
    ("al", "al"),
)
ADJECTIVE_SUFFIXES = (
    "al",
    "ales",
    "aria",
    "arias",
    "ario",
    "arios",
    "ible",
    "ibles",
    "ig",
    "ige",
    "igen",
    "iger",
    "iges",
    "isch",
    "ische",
    "ischen",
    "ischer",
    "isches",
    "ica",
    "icas",
    "ico",
    "icos",
    "iva",
    "ivas",
    "ivo",
    "ivos",
    "oria",
    "orio",
    "sible",
    "taria",
    "tario",
)
PREDICATIVE_PREVIOUS_TOKENS = {
    "bastante",
    "era",
    "eran",
    "es",
    "esta",
    "estaba",
    "estaban",
    "estan",
    "fue",
    "fueron",
    "ist",
    "mas",
    "menos",
    "muy",
    "parece",
    "parecen",
    "resulta",
    "resultan",
    "seguia",
    "sigue",
    "siguen",
    "son",
    "sind",
    "tan",
}
NON_NOUN_FOLLOWER_TOKENS = {
    "aunque",
    "como",
    "cuando",
    "el",
    "la",
    "las",
    "lo",
    "los",
    "para",
    "pero",
    "por",
    "porque",
    "que",
    "si",
    "un",
    "una",
    "unas",
    "unos",
    "y",
}
SHORTLIST_TOKEN_PATTERN = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’-]*")


class RawGlossaryItem(BaseModel):
    """Lenient local item model used after the provider returns a payload."""

    term: Any = None
    english: Any = None
    explanation: Any = None
    gloss: Any = None
    default_glossary: Any = None

    model_config = ConfigDict(extra="allow")


class GlossaryResponse(BaseModel):
    """Lenient local glossary payload model used outside provider schema enforcement."""

    vocabulary: List[RawGlossaryItem] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class StructuredOutputDegradedError(RuntimeError):
    """Raised when a structured-output LLM call yields no usable glossary payload.

    The model either returned no tool call (``mode="no_payload"``) or a tool call with
    no vocabulary entries (``mode="empty_vocabulary"``). Both usually mean the model
    cannot satisfy the strict tool-calling structured-output contract, which is common
    with some local/OpenAI-compatible models (e.g. Gemma via Ollama). Raising here turns
    a previously silent empty result into a loud, actionable failure.
    """

    def __init__(self, mode: str, detail: str = "") -> None:
        self.mode = mode
        message = f"structured glossary output degraded (mode={mode})"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


GLOSSARY_RESPONSE_SCHEMA = {
    "title": "GlossaryResponse",
    "description": "Structured glossary entries extracted from the approved article text.",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "vocabulary": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "term": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "english": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "explanation": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "gloss": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "default_glossary": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
                },
                "required": ["term", "english", "explanation", "gloss", "default_glossary"],
            },
        },
    },
    "required": ["vocabulary"],
}


class GlossaryGenerator:
    """Generate glossary entries from the final approved article text."""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild("GlossaryGenerator")
        self.llm_config = config.llm.model_dump()
        self.temperature = min(self.llm_config.get("temperature", 0.3), 0.2)
        self.glossary_config = config.glossary
        self.retry_on_empty = self.glossary_config.retry_on_empty
        self.debug_dump = self.glossary_config.debug_dump
        self.metrics_output_dir = Path("output/metrics/glossary")
        self.last_run_stats = self._empty_run_stats()
        self._nlp: Any = None
        self._init_chain()
        self._init_nlp()

    def generate(self, article: AdaptedArticle) -> List[VocabularyItem]:
        """Generate glossary candidates from the final approved text."""
        prompt = prompts.get_glossary_generation_prompt(article)
        return self._generate_candidates_from_prompt(prompt)

    def validate(
        self,
        content: str,
        vocabulary: List[VocabularyItem],
    ) -> tuple[List[VocabularyItem], Dict[str, str]]:
        """Filter glossary candidates using deterministic learner-focused rules."""
        accepted: List[VocabularyItem] = []
        dropped: Dict[str, str] = {}
        seen_terms = set()
        doc = self._analyze_content(content)

        for raw_item in vocabulary:
            term = normalize_vocabulary_term(raw_item.term)
            english = raw_item.english.strip()
            explanation = raw_item.explanation.strip()
            display_term = term or raw_item.term or "<empty>"

            # Generated glossary entries must include a term plus at least one learner-facing
            # gloss field. The publisher stays more tolerant to avoid breaking legacy or mixed
            # stored data during render.
            if not term or (not english and not explanation):
                dropped[display_term] = "missing required glossary fields"
                continue

            normalized_key = term.casefold()
            if normalized_key in seen_terms:
                dropped[display_term] = "duplicate term"
                continue

            if not vocabulary_term_present(content, term):
                dropped[display_term] = "term not present literally in article text"
                continue

            matched_term = self._match_term_casing_from_content(content, term)
            if matched_term:
                term = matched_term
                display_term = matched_term

            if self._is_rejected_named_entity(doc, content, term, english, explanation):
                dropped[display_term] = "named entity or common place/person name"
                continue

            if self._is_transparent_term(term, english):
                dropped[display_term] = "transparent term for English-speaking learners"
                continue

            if self._is_overlong_phrase(term):
                dropped[display_term] = "phrase is too long; prefer standalone words or short expressions"
                continue

            accepted.append(
                VocabularyItem(
                    term=term,
                    english=english,
                    explanation=explanation,
                    default_glossary=raw_item.default_glossary,
                )
            )
            seen_terms.add(normalized_key)

        return accepted, dropped

    def apply_bolding(self, content: str, vocabulary: List[VocabularyItem]) -> str:
        """Bold accepted glossary terms in the final article text."""
        if not vocabulary:
            return content

        term_map = {item.term: item.english or item.explanation for item in vocabulary}
        cleaned_content = content.replace("**", "")
        return ensure_vocabulary_bolded(cleaned_content, term_map)

    def enrich_article(self, article: AdaptedArticle) -> AdaptedArticle:
        """Attach a validated glossary to an approved article without blocking publication."""
        self.last_run_stats = self._empty_run_stats(article)
        try:
            initial_candidates = self.generate(article)
            accepted, dropped = self.validate(article.content, initial_candidates)
            retry_candidates: List[VocabularyItem] = []
            retry_dropped: Dict[str, str] = {}
            retried = False

            self.last_run_stats["glossary_candidates_initial"] = len(initial_candidates)
            self._log_validation_stage(
                article.title,
                "initial",
                initial_candidates,
                accepted,
                dropped,
            )

            if not accepted and self.retry_on_empty:
                retried = True
                retry_candidates = self._retry_generate(article, dropped)
                self.last_run_stats["glossary_candidates_retry"] = len(retry_candidates)
                self.last_run_stats["retry_used"] = True

                if retry_candidates:
                    accepted, retry_dropped = self.validate(article.content, retry_candidates)
                    self._log_validation_stage(
                        article.title,
                        "retry",
                        retry_candidates,
                        accepted,
                        retry_dropped,
                    )
                else:
                    self.logger.warning(
                        f"Retry glossary generation returned no candidates for '{article.title}'"
                    )

            visible_glossary = self.select_default_glossary(article.level, accepted)
            visible_terms = {item.term.casefold() for item in visible_glossary}
            translation_hints = [
                item.model_copy(update={"default_glossary": item.term.casefold() in visible_terms})
                for item in accepted
            ]

            self.last_run_stats["translation_hints_accepted"] = len(translation_hints)
            self.last_run_stats["glossary_accepted"] = len(visible_glossary)
            self.last_run_stats["glossary_empty_after_retry"] = retried and not accepted

            if self.debug_dump:
                try:
                    self._write_debug_artifact(
                        article=article,
                        initial_candidates=initial_candidates,
                        initial_dropped=dropped,
                        retry_candidates=retry_candidates,
                        retry_dropped=retry_dropped,
                        accepted=visible_glossary,
                        translation_hints=translation_hints,
                        retried=retried,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Glossary debug dump failed for '%s': %s. Continuing without artifact.",
                        article.title,
                        exc,
                    )

            if not accepted:
                self.logger.warning(
                    f"No glossary entries survived validation for '{article.title}' "
                    f"(glossary_candidates_initial={len(initial_candidates)}, "
                    f"glossary_candidates_retry={len(retry_candidates)}, "
                    f"glossary_accepted={len(accepted)}); publishing text without glossary"
                )
                return article.model_copy(update={"vocabulary": [], "translation_hints": []})

            content = self.apply_bolding(article.content, visible_glossary)
            self.logger.info(
                f"Accepted {len(translation_hints)} translation hints and "
                f"{len(visible_glossary)} visible glossary entries for '{article.title}': "
                f"{', '.join(item.term for item in visible_glossary)}"
            )
            return article.model_copy(
                update={
                    "content": content,
                    "vocabulary": visible_glossary,
                    "translation_hints": translation_hints,
                }
            )
        except Exception as exc:
            self.last_run_stats["glossary_empty_after_retry"] = bool(
                self.last_run_stats.get("retry_used")
            )
            self.logger.error(
                "Glossary generation failed for '%s': %s. Publishing without glossary.",
                article.title,
                exc,
            )
            return article.model_copy(update={"vocabulary": [], "translation_hints": []})

    def select_default_glossary(
        self,
        level: str,
        candidates: List[VocabularyItem],
    ) -> List[VocabularyItem]:
        """Return the visible glossary subset from the broader translation hints."""
        if not candidates:
            return []

        max_items = {"A2": 8, "B1": 9}.get(level, 8)
        selected = [item for item in candidates if item.default_glossary]

        if not selected:
            selected = candidates[:max_items]

        return [
            item.model_copy(update={"default_glossary": True})
            for item in selected[:max_items]
        ]

    def _generate_candidates_from_prompt(self, prompt: str) -> List[VocabularyItem]:
        response = self._call_llm(prompt)
        if response is None:
            raise StructuredOutputDegradedError(
                mode="no_payload",
                detail=(
                    "the model returned no structured tool call; it likely cannot satisfy "
                    "strict tool-calling structured output (common with some local/Ollama "
                    "models such as Gemma). Try a tool-capable model such as qwen2.5."
                ),
            )
        if isinstance(response, BaseModel):
            payload = response.model_dump(exclude_none=True)
        elif isinstance(response, dict):
            payload = response
        else:
            payload = {}
        vocabulary = payload.get("vocabulary") or []
        if not vocabulary:
            raise StructuredOutputDegradedError(
                mode="empty_vocabulary",
                detail=(
                    "the structured tool call returned no vocabulary entries; the model "
                    "likely cannot follow the strict structured-output schema. Try a "
                    "tool-capable model such as qwen2.5."
                ),
            )
        return coerce_vocabulary_items(vocabulary)

    def _retry_generate(self, article: AdaptedArticle, dropped: Dict[str, str]) -> List[VocabularyItem]:
        shortlist = self._build_retry_shortlist(article.content)
        self.logger.info(
            f"Retrying glossary generation for '{article.title}' after zero accepted initial candidates "
            f"with {len(shortlist)} shortlist hints"
        )
        retry_prompt = prompts.get_glossary_retry_prompt(article, dropped, shortlist)
        return self._generate_candidates_from_prompt(retry_prompt)

    def _log_validation_stage(
        self,
        article_title: str,
        stage: str,
        candidates: List[VocabularyItem],
        accepted: List[VocabularyItem],
        dropped: Dict[str, str],
    ) -> None:
        reason_summary = self._format_reason_summary(dropped)
        message = (
            f"{stage.capitalize()} glossary validation for '{article_title}': "
            f"candidates={len(candidates)}, accepted={len(accepted)}, dropped={len(dropped)}"
        )
        if reason_summary:
            message += f", reasons={reason_summary}"
        self.logger.info(message)

        if dropped:
            self.logger.warning(
                f"Dropped {stage} glossary terms for '{article_title}': "
                + ", ".join(f"{term} ({reason})" for term, reason in dropped.items())
            )

    def _format_reason_summary(self, dropped: Dict[str, str]) -> str:
        if not dropped:
            return ""
        counts = Counter(dropped.values())
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return ", ".join(f"{reason}={count}" for reason, count in ordered)

    def _empty_run_stats(self, article: AdaptedArticle | None = None) -> Dict[str, Any]:
        return {
            "article_title": article.title if article else None,
            "article_level": article.level if article else None,
            "glossary_candidates_initial": 0,
            "glossary_candidates_retry": 0,
            "translation_hints_accepted": 0,
            "glossary_accepted": 0,
            "glossary_empty_after_retry": False,
            "retry_used": False,
        }

    def _write_debug_artifact(
        self,
        article: AdaptedArticle,
        initial_candidates: List[VocabularyItem],
        initial_dropped: Dict[str, str],
        retry_candidates: List[VocabularyItem],
        retry_dropped: Dict[str, str],
        accepted: List[VocabularyItem],
        translation_hints: List[VocabularyItem],
        retried: bool,
    ) -> None:
        self.metrics_output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-{slugify_text(article.title)}-{article.level.lower()}.json"
        payload = {
            "article_title": article.title,
            "level": article.level,
            "retry_used": retried,
            "counts": {
                "initial_candidates": len(initial_candidates),
                "retry_candidates": len(retry_candidates),
                "translation_hints": len(translation_hints),
                "accepted": len(accepted),
                "initial_dropped": len(initial_dropped),
                "retry_dropped": len(retry_dropped),
            },
            "initial_candidates": [item.model_dump() for item in initial_candidates],
            "retry_candidates": [item.model_dump() for item in retry_candidates],
            "translation_hints": [item.model_dump() for item in translation_hints],
            "accepted": [item.model_dump() for item in accepted],
            "dropped": {
                "initial": [
                    {"term": term, "reason": reason}
                    for term, reason in initial_dropped.items()
                ],
                "retry": [
                    {"term": term, "reason": reason}
                    for term, reason in retry_dropped.items()
                ],
            },
        }

        with open(self.metrics_output_dir / filename, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def _build_retry_shortlist(self, content: str, limit: int = 18) -> List[str]:
        doc = self._analyze_content(content)
        seen: set[str] = set()
        shortlist: List[str] = []

        if doc is not None:
            for chunk in doc.noun_chunks:
                candidate = chunk.text.strip()
                if self._add_shortlist_candidate(shortlist, seen, doc, content, candidate, limit):
                    if len(shortlist) >= limit:
                        return shortlist
            for token in doc:
                if token.pos_ not in {"NOUN", "ADJ"}:
                    continue
                candidate = token.text.strip()
                if self._add_shortlist_candidate(shortlist, seen, doc, content, candidate, limit):
                    if len(shortlist) >= limit:
                        return shortlist

        for segment in re.split(r"[.!?;\n]+", content):
            words = SHORTLIST_TOKEN_PATTERN.findall(segment)
            for size in (3, 2, 1):
                for index in range(0, len(words) - size + 1):
                    candidate = " ".join(words[index:index + size]).strip()
                    if self._add_shortlist_candidate(shortlist, seen, doc, content, candidate, limit):
                        if len(shortlist) >= limit:
                            return shortlist

        return shortlist

    def _add_shortlist_candidate(
        self,
        shortlist: List[str],
        seen: set[str],
        doc,
        content: str,
        candidate: str,
        limit: int,
    ) -> bool:
        normalized = normalize_vocabulary_term(candidate)
        if not normalized or len(shortlist) >= limit:
            return False
        if len(normalized.split()) > 3 or any(char.isdigit() for char in normalized):
            return False

        folded = normalized.casefold()
        if folded in seen:
            return False

        tokens = self._tokenize(normalized)
        if not tokens or max(len(token) for token in tokens) < 4:
            return False
        if all(token in TERM_STOPWORDS or token in NAME_CONNECTOR_TOKENS for token in tokens):
            return False
        if normalized.isupper():
            return False
        if not vocabulary_term_present(content, normalized):
            return False
        if self._is_rejected_named_entity(doc, content, normalized, "", ""):
            return False
        if self._is_isolated_modifier(doc, content, normalized):
            return False

        matched = self._match_term_casing_from_content(content, normalized) or normalized
        seen.add(matched.casefold())
        shortlist.append(matched)
        return True

    def _init_chain(self) -> None:
        model_name = self.llm_config["models"].get(
            "adaptation",
            self.llm_config["models"]["generation"],
        ) or self.llm_config["models"]["generation"]
        self.chain = build_structured_prompt_chain(
            self.llm_config,
            model_name,
            self.temperature,
            GLOSSARY_RESPONSE_SCHEMA,
            strict=True,
        )

    def _init_nlp(self) -> None:
        model_name = self.config.language.spacy_model
        try:
            self._nlp = spacy.load(model_name)
        except Exception as exc:
            self.logger.warning(
                "SpaCy model '%s' unavailable for glossary validation; falling back to lightweight rules: %s",
                model_name,
                exc,
            )
            self._nlp = None

    def _call_llm(self, prompt: str) -> Any:
        return self.chain.invoke({"prompt": prompt})

    def _analyze_content(self, content: str):
        if self._nlp is None:
            return None
        return self._nlp(content)

    def _is_rejected_named_entity(
        self,
        doc,
        content: str,
        term: str,
        english: str,
        explanation: str,
    ) -> bool:
        folded_term = self._fold_text(term)
        if folded_term in COMMON_PLACE_TERMS or folded_term in COMMON_PERSON_TERMS:
            return True

        if english and term == english and self._looks_like_title_case_name(term):
            return True

        if doc is None:
            return self._looks_like_rejected_named_entity_without_nlp(
                content,
                term,
                english,
                explanation,
            )

        for span in self._find_matching_spans(doc, term):
            for ent in doc.ents:
                if ent.start <= span.start and span.end <= ent.end:
                    if ent.label_ in REJECT_ENTITY_LABELS:
                        return True
        return False

    def _is_transparent_term(self, term: str, english: str) -> bool:
        term_tokens = [
            token
            for token in self._tokenize(term)
            if token not in TERM_STOPWORDS and len(token) >= 4
        ]
        english_tokens = [
            token
            for token in self._tokenize(english)
            if token not in ENGLISH_STOPWORDS and len(token) >= 4
        ]

        if not term_tokens or not english_tokens:
            return False

        matches = 0
        for term_token in term_tokens:
            if any(self._tokens_look_transparent(term_token, english_token) for english_token in english_tokens):
                matches += 1

        return matches >= len(term_tokens)

    def _is_isolated_modifier(self, doc, content: str, term: str) -> bool:
        stripped_term = term.strip()
        if " " in stripped_term:
            return False

        if doc is None:
            folded_term = self._fold_text(stripped_term)
            if not any(folded_term.endswith(suffix) for suffix in ADJECTIVE_SUFFIXES):
                return False
            for match in self._find_term_matches(content, stripped_term):
                previous_word, next_word = self._neighbor_words(content, match.start(), match.end())
                if previous_word in PREDICATIVE_PREVIOUS_TOKENS:
                    continue
                if next_word and next_word not in NON_NOUN_FOLLOWER_TOKENS:
                    return True
                if previous_word:
                    return True
            return False

        for span in self._find_matching_spans(doc, term):
            if len(span) != 1:
                continue
            token = span[0]
            if token.pos_ == "ADJ" and token.dep_ == "amod":
                return True
        return False

    def _is_overlong_phrase(self, term: str) -> bool:
        return len(self._tokenize(term)) > MAX_CLICKABLE_TERM_WORDS

    def _find_matching_spans(self, doc, term: str):
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        matches = []
        for match in pattern.finditer(doc.text):
            span = doc.char_span(match.start(), match.end(), alignment_mode="expand")
            if span is None:
                continue
            if span.text.strip().casefold() != term.casefold():
                continue
            matches.append(span)
        return matches

    def _match_term_casing_from_content(self, content: str, term: str) -> str | None:
        match = self._find_first_term_match(content, term)
        if match is None:
            return None
        return content[match.start():match.end()]

    def _tokenize(self, text: str) -> List[str]:
        folded = self._fold_text(text)
        return re.findall(r"[a-z]+", folded)

    def _fold_text(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text)
        without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return without_accents.casefold()

    def _tokens_look_transparent(self, term_token: str, english_token: str) -> bool:
        if term_token == english_token:
            return True

        transformed = self._apply_cognate_suffix_map(term_token)
        if transformed == english_token:
            return True

        singular_term = self._singularize(term_token)
        singular_english = self._singularize(english_token)
        if singular_term == singular_english:
            return True

        if transformed == singular_english:
            return True

        transformed_singular = self._apply_cognate_suffix_map(singular_term)
        if transformed_singular == singular_english:
            return True

        return False

    def _apply_cognate_suffix_map(self, token: str) -> str:
        for source_suffix, target_suffix in COGNATE_SUFFIX_MAP:
            if token.endswith(source_suffix):
                return f"{token[:-len(source_suffix)]}{target_suffix}"
        return token

    def _singularize(self, token: str) -> str:
        if token.endswith("es") and len(token) > 4:
            return token[:-2]
        if token.endswith("s") and len(token) > 3:
            return token[:-1]
        return token

    def _looks_like_title_case_name(self, text: str) -> bool:
        significant_parts = self._significant_name_parts(text)
        if not significant_parts:
            return False
        return len(significant_parts) >= 2 and all(part[:1].isupper() for part in significant_parts)

    def _looks_like_rejected_named_entity_without_nlp(
        self,
        content: str,
        term: str,
        english: str,
        explanation: str,
    ) -> bool:
        term_parts = [part for part in term.split() if part]
        if not term_parts:
            return False

        folded_term_parts = {self._fold_text(part) for part in term_parts}
        english_tokens = set(self._tokenize(english))
        explanation_tokens = set(self._tokenize(explanation))
        semantic_tokens = english_tokens | explanation_tokens
        significant_parts = self._significant_name_parts(term)
        title_cased = significant_parts and all(part[:1].isupper() for part in significant_parts)
        explicit_place_clue = bool(semantic_tokens & PLACE_CLUE_TOKENS)
        person_clue = bool(semantic_tokens & PERSON_CLUE_TOKENS)
        term_organization_tokens = folded_term_parts & ORGANIZATION_OR_GROUP_TOKENS
        semantic_organization_tokens = semantic_tokens & ORGANIZATION_CLUE_TOKENS
        organization_clue = bool(
            term_organization_tokens or semantic_organization_tokens
        )
        term_place_designator = bool(folded_term_parts & PLACE_DESIGNATOR_TOKENS)

        if explicit_place_clue and (title_cased or term_place_designator):
            return True

        if person_clue and title_cased:
            return True

        if len(significant_parts) >= 2 and title_cased:
            if organization_clue:
                return False
            return True

        if len(significant_parts) == 1 and title_cased:
            if organization_clue:
                return False
            if term_place_designator:
                return True

        return False

    def _significant_name_parts(self, text: str) -> List[str]:
        parts = [part for part in text.split() if part]
        return [
            part
            for part in parts
            if self._fold_text(part) not in NAME_CONNECTOR_TOKENS and part[:1].isalpha()
        ]

    def _find_first_term_match(self, content: str, term: str):
        return self._term_pattern(term).search(content)

    def _find_term_matches(self, content: str, term: str):
        return self._term_pattern(term).finditer(content)

    def _term_pattern(self, term: str) -> re.Pattern[str]:
        return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)

    def _neighbor_words(self, content: str, start: int, end: int) -> tuple[str | None, str | None]:
        previous_match = re.search(r"(\w+)\W*$", content[:start], re.UNICODE)
        next_match = re.search(r"^\W*(\w+)", content[end:], re.UNICODE)
        previous_word = self._fold_text(previous_match.group(1)) if previous_match else None
        next_word = self._fold_text(next_match.group(1)) if next_match else None
        return previous_word, next_word

    def _appears_title_cased_mid_sentence(self, content: str, term: str) -> bool:
        for match in self._find_term_matches(content, term):
            matched_text = content[match.start():match.end()]
            if not matched_text[:1].isupper():
                continue
            if not self._is_sentence_boundary(content, match.start()):
                return True
        return False

    def _is_sentence_boundary(self, content: str, index: int) -> bool:
        cursor = index - 1
        while cursor >= 0 and content[cursor].isspace():
            cursor -= 1
        if cursor < 0:
            return True
        return content[cursor] in ".!?\n"

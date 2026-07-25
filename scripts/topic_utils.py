"""
Topic and keyword utilities shared across discovery and publishing.
"""

import re
from typing import Final

_LETTER_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]")


def is_noisy_topic_keyword(keyword: str) -> bool:
    """
    Heuristically detect HTML/URL artefacts that should not be treated as topics.

    This is used in both topic discovery (SpaCy keyword extraction) and
    publisher frontmatter generation as a defence-in-depth filter.
    """
    if not keyword:
        return True

    lower = keyword.lower()

    # Obvious HTML / attribute fragments
    if "href=" in lower or "src=" in lower or "<" in keyword or ">" in keyword:
        return True

    # Bare URLs or hostnames
    if lower.startswith(("http://", "https://")) or "://" in lower or "www." in lower:
        return True

    # Overly long or mostly non-word garbage
    if not (3 <= len(keyword) <= 60):
        return True

    # Require at least one letter to avoid pure symbols / numbers
    if not _LETTER_PATTERN.search(keyword):
        return True

    # Generic language/level labels or noisy fillers
    if lower in {
        "deutsch", "german", "englisch", "english", "a2", "b1", "artikel",
        "vokabeln", "lernzwecken", "mittwoch", "donnerstag", "freitag",
        "samstag", "sonntag", "montag", "dienstag", "im jahr", "letztes"
    }:
        return True

    return False



def sanitize_topic_keywords(
    keywords: list[str],
    *,
    max_keywords: int | None = None,
    lowercase: bool = False,
) -> list[str]:
    """Normalize, deduplicate, and filter topic keywords."""
    sanitized: list[str] = []
    seen: set[str] = set()

    for raw_keyword in keywords:
        keyword = re.sub(r"\s+", " ", str(raw_keyword)).strip()
        if not keyword or is_noisy_topic_keyword(keyword):
            continue

        key = keyword.casefold()
        if key in seen:
            continue

        seen.add(key)
        sanitized.append(keyword.lower() if lowercase else keyword)

        if max_keywords is not None and len(sanitized) >= max_keywords:
            break

    return sanitized


_NLP_CACHE: dict[str, str] = {}


def extract_named_entities(text: str, spacy_model: str = "de_core_news_sm") -> list[str]:
    """Extract Named Entities (LOC, ORG, PER, MISC) from text using SpaCy."""
    if not text or not text.strip():
        return []

    try:
        import spacy

        if spacy_model not in _NLP_CACHE:
            _NLP_CACHE[spacy_model] = spacy.load(spacy_model)
        nlp = _NLP_CACHE[spacy_model]
        doc = nlp(text)
        entities: list[str] = []
        for ent in doc.ents:
            if ent.label_ in ("LOC", "ORG", "PER", "MISC") and len(ent.text.strip()) > 2:
                entities.append(ent.text.strip())
        return entities
    except Exception:
        return []


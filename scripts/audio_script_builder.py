"""
Build provider-neutral narration scripts from approved articles.
"""

from __future__ import annotations

import re
from typing import List

from scripts.models import AdaptedArticle, SpeechScript, VocabularyItem, coerce_vocabulary_items

_EMPHASIS_PATTERN = re.compile(r"\*\*(.+?)\*\*")


def _strip_markdown(text: str) -> str:
    """Remove the limited markdown formatting produced by the article pipeline."""
    cleaned = _EMPHASIS_PATTERN.sub(r"\1", text)
    cleaned = cleaned.replace("*", "")
    return cleaned.strip()


def build_speech_script(article: AdaptedArticle, include_vocabulary: bool = False) -> SpeechScript:
    """Convert an adapted article into a narration-friendly plain-text script."""
    raw_vocabulary = article.vocabulary or []
    if all(isinstance(item, VocabularyItem) for item in raw_vocabulary):
        normalized_vocabulary = raw_vocabulary
    else:
        normalized_vocabulary = coerce_vocabulary_items(raw_vocabulary)

    vocabulary_items = [
        item for item in normalized_vocabulary if item.explanation or item.english
    ]
    vocabulary_included = bool(include_vocabulary and vocabulary_items)
    sections: List[str] = [f"{article.title}. {article.summary}".strip()]

    paragraphs = [paragraph.strip() for paragraph in article.content.split("\n\n") if paragraph.strip()]
    sections.extend(_strip_markdown(paragraph) for paragraph in paragraphs)

    if vocabulary_included:
        vocabulary_lines = [
            (
                f"{item.term} bedeutet {item.explanation}."
                if item.explanation
                else f"{item.term} heißt auf Englisch {item.english}."
            )
            for item in vocabulary_items
        ]
        sections.append("Vokabeln. " + " ".join(_strip_markdown(line) for line in vocabulary_lines))

    sections.append("Ende des Artikels.")
    narration = "\n\n".join(section for section in sections if section)

    return SpeechScript(
        title=article.title,
        sections=sections,
        narration=narration,
        includes_vocabulary=vocabulary_included,
    )

"""
Build provider-neutral narration scripts from approved articles.
"""

from __future__ import annotations

import re
from typing import List, Literal

from scripts.models import (
    AdaptedArticle,
    SpeechBlock,
    SpeechScript,
    VocabularyItem,
    coerce_vocabulary_items,
)

_EMPHASIS_PATTERN = re.compile(r"\*\*(.+?)\*\*")


def _strip_markdown(text: str) -> str:
    """Remove the limited markdown formatting produced by the article pipeline."""
    cleaned = _EMPHASIS_PATTERN.sub(r"\1", text)
    cleaned = cleaned.replace("*", "")
    return cleaned.strip()


def _normalized_spoken_text(text: str) -> str:
    """Normalize narration text enough to compare summary/body overlap."""
    return re.sub(r"\s+", " ", _strip_markdown(text)).strip().casefold()


def build_speech_script(
    article: AdaptedArticle,
    include_vocabulary: bool = False,
    glossary_heading: str = "Vokabeln",
) -> SpeechScript:
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
    paragraphs = [paragraph.strip() for paragraph in article.content.split("\n\n") if paragraph.strip()]
    normalized_summary = _normalized_spoken_text(article.summary)
    normalized_body = _normalized_spoken_text("\n\n".join(paragraphs))
    block_values: list[
        tuple[
            str,
            Literal["title", "summary", "body", "vocabulary", "closing"],
            str,
        ]
    ] = [("title", "title", article.title.strip())]
    if normalized_summary and not normalized_body.startswith(normalized_summary):
        block_values.append(("summary", "summary", _strip_markdown(article.summary)))
    block_values.extend(
        (f"body-{index}", "body", _strip_markdown(paragraph))
        for index, paragraph in enumerate(paragraphs)
    )

    if vocabulary_included:
        vocabulary_lines = [
            (
                f"{item.term} bedeutet {item.explanation}."
                if item.explanation
                else f"{item.term} heißt auf Englisch {item.english}."
            )
            for item in vocabulary_items
        ]
        block_values.append(
            (
                "vocabulary",
                "vocabulary",
                f"{glossary_heading}. "
                + " ".join(_strip_markdown(line) for line in vocabulary_lines),
            )
        )

    block_values.append(("closing", "closing", "Ende des Artikels."))
    sections: List[str] = [text for _block_id, _kind, text in block_values if text]
    narration = "\n\n".join(sections)
    blocks: list[SpeechBlock] = []
    cursor = 0
    for block_id, kind, text in block_values:
        if not text:
            continue
        blocks.append(
            SpeechBlock(
                id=block_id,
                kind=kind,
                text=text,
                text_start=cursor,
                text_end=cursor + len(text),
            )
        )
        cursor += len(text) + 2

    return SpeechScript(
        title=article.title,
        sections=sections,
        blocks=blocks,
        narration=narration,
        includes_vocabulary=vocabulary_included,
    )

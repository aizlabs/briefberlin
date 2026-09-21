"""Shared derivation of the article's clickable translation-hint list.

The publisher assigns ``term-N`` ids by POSITION in a deduplicated hint list.
Those ids are written into three places that must agree:

* the ``<button data-term-id="term-N">`` spans in the rendered German body,
* the ``article-glossary-data`` JSON payload the popup JavaScript reads,
* anything downstream that wants to line a translated glossary row up with the
  German page.

This module exists so the ordering is computed in exactly one place. Rebuilding
it independently anywhere else silently renumbers the ids and breaks the
pairing with no error.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from scripts.models import AdaptedArticle, VocabularyItem, coerce_vocabulary_items
from scripts.text_utils import normalize_vocabulary_term


def hint_id(index: int) -> str:
    """Stable DOM id for the hint at ``index`` in the deduplicated list."""
    return f"term-{index + 1}"


def publishable_translation_hints(article: AdaptedArticle) -> List[VocabularyItem]:
    """Deduplicated, normalized hints in the order the publisher numbers them.

    Falls back to the visible vocabulary when no broad hint set was generated.
    """
    hints = coerce_vocabulary_items(article.translation_hints)
    visible_terms = {
        item.term.casefold()
        for item in coerce_vocabulary_items(article.vocabulary)
    }
    if not hints:
        hints = [
            item.model_copy(update={"default_glossary": True})
            for item in coerce_vocabulary_items(article.vocabulary)
        ]

    deduped: List[VocabularyItem] = []
    seen = set()
    for item in hints:
        normalized_term = normalize_vocabulary_term(item.term)
        if not normalized_term:
            continue
        key = normalized_term.casefold()
        if key in seen:
            continue
        definition = item.english or item.explanation
        if not definition:
            continue
        seen.add(key)
        deduped.append(
            item.model_copy(
                update={
                    "term": normalized_term,
                    "default_glossary": item.default_glossary or key in visible_terms,
                }
            )
        )
    return deduped


def visible_glossary_items(
    hints: Sequence[VocabularyItem],
) -> List[Tuple[str, VocabularyItem]]:
    """``(hint_id, item)`` for the rows that appear in the visible glossary.

    The id reflects the item's position in the FULL hint list, not in the
    filtered result, so it still matches the German page's ``data-term-id``.

    Only these rows are worth translating: the remaining click-only hints exist
    to attach to German words in the German body, and a translated body has no
    German words for them to attach to.
    """
    return [
        (hint_id(index), item)
        for index, item in enumerate(hints)
        if item.default_glossary
    ]

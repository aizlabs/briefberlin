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

    return False


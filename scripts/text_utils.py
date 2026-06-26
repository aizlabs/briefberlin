"""
Text utilities for the pipeline.

Includes vocabulary normalization, presence checks, and bold marking used after
level adaptation.
"""

import re
from typing import Dict


def _is_word_char(c: str) -> bool:
    """True if c is alphanumeric or underscore (part of a token)."""
    return len(c) == 1 and (c.isalnum() or c == "_")


def _term_at_word_boundary(content: str, start: int, term: str) -> bool:
    """
    True if content[start:start+len(term)] equals term and is a whole word.

    Whole word: not preceded and not followed by a word character (so we do
    not bold "tasa" inside "tasas" or "año" inside "años").
    """
    if not content[start:].startswith(term):
        return False
    end = start + len(term)
    if start > 0 and _is_word_char(content[start - 1]):
        return False
    if end < len(content) and _is_word_char(content[end]):
        return False
    return True


def normalize_vocabulary_term(term: str) -> str:
    """
    Normalize a glossary term to plain text.

    Terms are trimmed and repeatedly stripped of wrapping markdown bold markers,
    so values like "**Begriff**" and "****Begriff****" are stored as "Begriff".
    Internal punctuation and accents are preserved.
    """
    normalized = term.strip()

    while len(normalized) >= 4 and normalized.startswith("**") and normalized.endswith("**"):
        normalized = normalized[2:-2].strip()

    return normalized


def slugify_text(text: str) -> str:
    """
    Convert text into a stable ASCII slug used across publishing surfaces.

    This preserves the repo's existing language-specific replacements so
    publisher filenames, future media keys, and other derived URLs stay aligned.
    """
    normalized = text.lower()

    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        "ü": "u",
        "¿": "",
        "¡": "",
        "?": "",
        "!": "",
    }

    for old, new in replacements.items():
        normalized = normalized.replace(old, new)

    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")


def vocabulary_term_present(content: str, term: str) -> bool:
    """
    Return True if term appears literally in content as a whole word or phrase.

    This exact-match check is case-insensitive and works for both plain and
    markdown-bolded terms because the surrounding `**` markers are treated as
    non-word characters.
    """
    if not term:
        return False

    folded_content = content.lower()
    folded_term = term.lower()
    max_start = len(folded_content) - len(folded_term)
    for start in range(max_start + 1):
        if _term_at_word_boundary(folded_content, start, folded_term):
            return True

    return False


def filter_vocabulary_to_content(
    content: str,
    vocabulary: Dict[str, str],
) -> tuple[Dict[str, str], list[str]]:
    """
    Keep only glossary entries whose terms appear literally in content.

    Returns:
        A tuple of (filtered_vocabulary, dropped_terms).
    """
    filtered: Dict[str, str] = {}
    dropped: list[str] = []

    for term, gloss in vocabulary.items():
        if vocabulary_term_present(content, term):
            filtered[term] = gloss
        else:
            dropped.append(term)

    return filtered, dropped


def normalize_existing_vocabulary_bolding(content: str, vocabulary: Dict[str, str]) -> str:
    """
    Collapse malformed repeated bold markers around known glossary terms.

    This preserves the original casing from the content while converting values
    like "****tasa****" into the standard markdown form "**tasa**" before the
    re-bolding pass runs.
    """
    terms = sorted(
        {term for term in vocabulary if term},
        key=len,
        reverse=True,
    )
    if not terms:
        return content

    term_pattern = "|".join(re.escape(term) for term in terms)
    pattern = re.compile(rf"(\*{{4,}})({term_pattern})(\*{{4,}})", re.IGNORECASE)

    def replace(match: re.Match[str]) -> str:
        opening, term_text, closing = match.groups()

        if len(opening) % 2 != 0 or len(closing) % 2 != 0:
            return match.group(0)

        start = match.start()
        end = match.end()
        if start > 0 and _is_word_char(content[start - 1]):
            return match.group(0)
        if end < len(content) and _is_word_char(content[end]):
            return match.group(0)

        return f"**{term_text}**"

    return pattern.sub(replace, content)


def ensure_vocabulary_bolded(content: str, vocabulary: Dict[str, str]) -> str:
    """
    Ensure every vocabulary term appears bolded in content.

    Single-pass FSA: track position and inside_bold state. When we see '**',
    toggle inside_bold. When not inside_bold, if content at current position
    starts with any term (longest first) at a word boundary, wrap it in **
    and advance by term length. Otherwise emit one character and advance.

    Terms are matched on word boundaries only (no prefix match): e.g. "tasa"
    in "las tasas suben" is not bolded, to avoid corrupting inflected/derived
    forms and to keep glossed terms in their original form.

    Args:
        content: Article body (may already contain some **bold** terms).
        vocabulary: Glossary dict (keys = German terms to bold).

    Returns:
        Content with every vocabulary term wrapped in ** when not already bolded.
    """
    if not vocabulary:
        return content

    # Terms sorted by length descending so longer phrases match before substrings
    terms = sorted(
        (t for t in vocabulary if t),
        key=len,
        reverse=True,
    )
    if not terms:
        return content

    i = 0
    inside_bold = False
    result: list[str] = []

    while i < len(content):
        if i + 2 <= len(content) and content[i : i + 2] == "**":
            result.append("**")
            inside_bold = not inside_bold
            i += 2
            continue

        if not inside_bold:
            matched = False
            for term in terms:
                if _term_at_word_boundary(content, i, term):
                    result.append("**")
                    result.append(term)
                    result.append("**")
                    i += len(term)
                    matched = True
                    break
            if matched:
                continue

        result.append(content[i])
        i += 1

    return "".join(result)

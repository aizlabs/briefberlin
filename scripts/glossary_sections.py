"""Helpers for locating public glossary sections in generated posts."""

from __future__ import annotations

import re
from typing import Sequence

from scripts.language_profiles import DEFAULT_GLOSSARY_HEADING, DEFAULT_LEGACY_GLOSSARY_HEADINGS

DEFAULT_GLOSSARY_HEADINGS = [
    DEFAULT_GLOSSARY_HEADING,
    *DEFAULT_LEGACY_GLOSSARY_HEADINGS,
]


def normalize_glossary_headings(
    glossary_headings: Sequence[str] | None = None,
) -> list[str]:
    """Return non-empty glossary headings without duplicates, preserving order."""
    headings: list[str] = []
    for heading in glossary_headings or DEFAULT_GLOSSARY_HEADINGS:
        cleaned = heading.strip()
        if cleaned and cleaned not in headings:
            headings.append(cleaned)
    return headings or list(DEFAULT_GLOSSARY_HEADINGS)


def split_at_glossary_heading(
    body: str,
    glossary_headings: Sequence[str] | None = None,
    *,
    strip_before: bool = False,
) -> tuple[str, str]:
    """Split Markdown body at the first configured glossary h2 heading."""
    for heading in normalize_glossary_headings(glossary_headings):
        pattern = re.compile(rf"(?m)^##\s+{re.escape(heading)}\s*$")
        match = pattern.search(body)
        if match:
            before = body[: match.start()]
            return before.rstrip() if strip_before else before, body[match.end() :]
    return body, ""

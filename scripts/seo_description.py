"""Search-snippet descriptions for published posts.

Every page's ``description:`` front matter becomes ``<meta name="description">``,
``og:description`` and ``twitter:description`` (output/_includes/seo.html). Two
rules apply in every language:

* The snippet says the story is about Berlin. Many stories only name a district
  or a street (Ku'damm, Neukölln, Zehlendorf), which tells a searcher outside
  Berlin nothing.
* The snippet fits in a search result (about 155 characters) instead of being
  cut off mid-word by the search engine.

The LLM is asked to follow both rules; :func:`finalize_seo_description` enforces
them deterministically so a model slip never reaches the page.

NOTE: A2 and B1 posts of one story share the German ``description`` and the
templates use it to pair them (level-switch.html, language-edition.html), so this
function must stay deterministic: same input, same output.
"""

from __future__ import annotations

import re
from typing import Optional

MAX_DESCRIPTION_CHARS = 155

# Label put in front of a description that does not name the city. "Berlin news"
# rather than a bare "Berlin:" because some stories are national (Bundestag,
# Rentenreform) and only reported from Berlin. Wording matches the news-xx
# landing pages. Languages missing here fall back to the English label.
CITY_LABELS = {
    "de": "Berlin aktuell",
    "en": "Berlin news",
    "es": "Noticias de Berlín",
    "fr": "Actualités de Berlin",
    "it": "Notizie da Berlino",
    "pl": "Wiadomości z Berlina",
    "tr": "Berlin haberleri",
    "uk": "Новини Берліна",
    "ru": "Новости Берлина",
    "ar": "أخبار برلين",
}
DEFAULT_CITY_LABEL = "Berlin news"

# Stems cover inflected and derived forms: Berliner, Berlins, Berlinie, Berlina,
# berlińskie, Berlin'de, Берлине, Берліні, Берлинский, ببرلين.
_CITY_PATTERN = re.compile(r"berl[iíń]|берл[иі]|برلين", re.IGNORECASE)

_ELLIPSIS = "…"


def city_label(lang: str) -> str:
    return CITY_LABELS.get(lang, DEFAULT_CITY_LABEL)


def mentions_city(text: str) -> bool:
    return bool(_CITY_PATTERN.search(text or ""))


def finalize_seo_description(
    text: Optional[str],
    lang: str,
    max_chars: int = MAX_DESCRIPTION_CHARS,
) -> str:
    """Return ``text`` as a search snippet that names Berlin and fits ``max_chars``.

    Empty input stays empty so callers can apply their own fallback.
    """
    # Snippets are plain text; markdown emphasis only wastes characters.
    cleaned = (text or "").replace("**", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""

    if not mentions_city(cleaned):
        separator = " : " if lang == "fr" else ": "
        cleaned = f"{city_label(lang)}{separator}{cleaned}"

    return _truncate(cleaned, max_chars)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    # Prefer ending on a full sentence when one ends reasonably late.
    window = text[:max_chars]
    sentence_end = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence_end >= max_chars * 0.6:
        return window[: sentence_end + 1]

    cut = window[: max_chars - len(_ELLIPSIS)]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip(" ,;:–-") + _ELLIPSIS

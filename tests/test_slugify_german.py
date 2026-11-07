"""German umlauts and ß become their standard ASCII spellings in slugs and URLs."""

import unicodedata
from datetime import datetime

import pytest

from scripts.text_utils import slugify_text


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Probleme im Stadtbad Schöneberg", "probleme-im-stadtbad-schoeneberg"),
        ("Kalle Halle in Neukölln kämpft weiter", "kalle-halle-in-neukoelln-kaempft-weiter"),
        ("Berlin bereitet sich auf heiße Tage vor", "berlin-bereitet-sich-auf-heisse-tage-vor"),
        ("Drei Brüder vor Gericht", "drei-brueder-vor-gericht"),
        ("ÄRGER ÜBER ÖFFNUNGSZEITEN", "aerger-ueber-oeffnungszeiten"),
        ("Was kostet das? Wer zahlt!", "was-kostet-das-wer-zahlt"),
    ],
)
def test_german_titles_get_readable_slugs(title, slug):
    assert slugify_text(title) == slug


def test_decomposed_umlauts_match_composed_ones():
    composed = "Schöneberg"
    decomposed = unicodedata.normalize("NFD", composed)
    assert decomposed != composed
    assert slugify_text(decomposed) == slugify_text(composed) == "schoeneberg"


def test_existing_spanish_replacements_still_apply():
    assert slugify_text("¿Qué pasó en la estación?") == "que-paso-en-la-estacion"


def test_post_url_uses_readable_german_slug():
    from types import SimpleNamespace

    from scripts.publisher import Publisher

    article = SimpleNamespace(title="Probleme im Stadtbad Schöneberg", level="A2")
    ref = Publisher._post_ref(SimpleNamespace(_jekyll_slugify=Publisher._jekyll_slugify), article, datetime(2026, 11, 7, 16, 13, 6))
    assert ref == "161306-probleme-im-stadtbad-schoeneberg-a2"

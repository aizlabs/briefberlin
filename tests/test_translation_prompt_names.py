"""The translation prompt gives one consistent rule for German names."""

from scripts.models import AdaptedArticle, Topic, TranslationLanguageConfig
from scripts.prompts import get_translation_prompt


def _prompt(code, name):
    article = AdaptedArticle.model_construct(
        title="Neukölln baut Radwege", summary="Kurz.", content="Text.", level="A2",
        vocabulary=[], topic=Topic.model_construct(title="t", sources=[]),
    )
    language = TranslationLanguageConfig(code=code, name=name, glossary_heading="Glossary")
    return get_translation_prompt(article, language, [])


def test_names_keep_german_spelling_with_transliteration_in_brackets():
    prompt = _prompt("ru", "Russian")
    assert "Hermannplatz (Германплац)" in prompt
    assert "first time it appears" in prompt
    assert "Karl-Marx-Straße" in prompt


def test_the_old_contradictory_rule_is_gone():
    prompt = _prompt("uk", "Ukrainian")
    assert "Do NOT leave a" not in prompt
    assert "Latin-script word sitting inside" not in prompt


def test_latin_alphabet_languages_keep_the_german_spelling_alone():
    assert "uses the Latin alphabet, write the German spelling alone" in _prompt("pl", "Polish")


def test_name_rule_is_generic_with_a_lookup_test():
    prompt = _prompt("es", "Spanish")
    assert "find it on a map, a sign or a website" in prompt
    assert "Gemeinschaftshaus" in prompt and "Gropiusstadt" in prompt


def test_roles_are_translated_not_kept_as_names():
    prompt = _prompt("tr", "Turkish")
    assert "Job titles, roles and descriptions are NOT names" in prompt
    assert "Bezirksstadträtin" in prompt

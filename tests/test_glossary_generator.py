import json
from unittest.mock import MagicMock

import pytest
from langchain_core.utils.function_calling import convert_to_openai_function

from scripts.glossary_generator import GLOSSARY_RESPONSE_SCHEMA, GlossaryGenerator, GlossaryResponse
from scripts.models import VocabularyItem

FRUEHLING_A2_CONTENT = (
    "Der Frühling in Deutschland beginnt dieses Jahr mit mildem Wetter. Der Deutsche Wetterdienst "
    "sagt, dass die Temperaturen stabil bleiben. Viele Stadtfeste können draußen stattfinden. "
    "In Berlin und Brandenburg werden 18 bis 22 Grad erwartet. In einigen Regionen gibt es Wind, "
    "aber das wird wahrscheinlich kein großes Problem.\n\n"
    "Stadtfeste sind für viele Menschen wichtig. Es geht nicht nur um Freizeit, sondern auch um "
    "Kultur und Nachbarschaft. In Berlin ist das Frühlingsfest im Park sehr beliebt. Viele "
    "Menschen gehen dorthin und hören Musik.\n\n"
    "Auch die Energiepolitik ist ein Thema. Deutschland will mehr Windstrom nutzen. Das "
    "Bundeswirtschaftsministerium sagt, dass schnellere Genehmigungen helfen. Die Regierung "
    "möchte den Netzausbau beschleunigen.\n\n"
    "Im Verkehr plant Berlin neue Angebote. Eine Mobilitätskarte soll Bus, Bahn und Leihräder "
    "einfacher verbinden. Viele Nutzerinnen und Nutzer finden die Idee gut."
)

VERWALTUNG_B1_CONTENT = (
    "Deutschland steht bei Verwaltung, Arbeit und Verkehr vor wichtigen Entscheidungen. Die "
    "Bundesregierung möchte digitale Anträge vereinfachen, damit Bürgerinnen und Bürger weniger "
    "Zeit in Ämtern verbringen. Die Europäische Kommission beobachtet solche Reformen, weil viele "
    "Dienste grenzüberschreitend funktionieren sollen.\n\n"
    "Auf dem Arbeitsmarkt sind Selbstständige ein wichtiger Teil der Wirtschaft. Ein neuer Bericht "
    "zeigt, dass viele Menschen flexible Arbeitsmodelle nutzen. Der Bereich hat aber Probleme, "
    "weil Versicherungen, Steuern und Altersvorsorge kompliziert bleiben.\n\n"
    "Auch beim Bahnverkehr gibt es Kritik. Neue Züge und alte Schienennetze passen nicht immer "
    "gut zusammen. Das betrifft Fahrgäste und den Güterverkehr. Unternehmen fordern deshalb "
    "einen klaren Plan für Investitionen und bessere europäische Standards.\n\n"
    "In Berlin testet die Verwaltung zusätzlich eine Mobilitätskarte. Sie soll Bus, Bahn und "
    "Leihräder verbinden. Fachleute sehen darin eine Chance, den Alltag einfacher zu machen."
)


@pytest.fixture
def glossary_generator(monkeypatch, base_config, mock_logger):
    monkeypatch.setattr(GlossaryGenerator, "_init_chain", lambda self: None)
    monkeypatch.setattr(GlossaryGenerator, "_init_nlp", lambda self: setattr(self, "_nlp", None))
    generator = GlossaryGenerator(base_config, mock_logger)
    monkeypatch.setattr(generator, "_call_llm", MagicMock(return_value=GlossaryResponse()))
    return generator


def test_validate_rejects_named_entities_transparent_terms_and_fragments(glossary_generator):
    content = (
        "Berlin testete Drohnen nach einem Sturm. Angela Merkel sprach mit Deutschland über Energie. "
        "Die Migrationspolitik änderte sich. Auch einseitige Entscheidungen wurden kritisiert."
    )
    candidates = [
        VocabularyItem(term="Berlin", english="Berlin", explanation="capital city in Germany"),
        VocabularyItem(
            term="Deutschland",
            english="Germany",
            explanation="country in Europe",
        ),
        VocabularyItem(
            term="Angela Merkel",
            english="Angela Merkel",
            explanation="former chancellor of Germany",
        ),
        VocabularyItem(term="drones", english="drones", explanation="unmanned aircraft"),
        VocabularyItem(
            term="migrantisch",
            english="migratory",
            explanation="related to movement between countries",
        ),
        VocabularyItem(
            term="einseitig",
            english="unilateral",
            explanation="done by one side",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert accepted == []
    assert set(dropped) == {
        "Berlin",
        "Deutschland",
        "Angela Merkel",
        "drones",
        "migrantisch",
        "einseitig",
    }


def test_generate_keeps_valid_items_when_structured_output_contains_null_term(
    glossary_generator,
    sample_a2_text_article,
    monkeypatch,
):
    monkeypatch.setattr(
        glossary_generator,
        "_call_llm",
        MagicMock(
            return_value=GlossaryResponse(
                vocabulary=[
                    {
                        "term": None,
                        "english": "ignored",
                        "explanation": "invalid entry",
                    },
                    {
                        "term": "Sturmschäden",
                        "english": "storm damage",
                        "explanation": "Schäden durch starken Wind und Regen",
                    },
                ]
            )
        ),
    )

    generated = glossary_generator.generate(sample_a2_text_article)

    assert generated == [
        VocabularyItem(
            term="Sturmschäden",
            english="storm damage",
            explanation="Schäden durch starken Wind und Regen",
        )
    ]


def test_generate_keeps_valid_items_when_raw_response_contains_extra_keys(
    glossary_generator,
    sample_a2_text_article,
    monkeypatch,
):
    monkeypatch.setattr(
        glossary_generator,
        "_call_llm",
        MagicMock(
            return_value={
                "vocabulary": [
                    {
                        "term": "Sturmschäden",
                        "english": "storm damage",
                        "explanation": "Schäden durch starken Wind und Regen",
                        "difficulty": "medium",
                    },
                    {
                        "term": None,
                        "english": "ignored",
                        "explanation": "invalid entry",
                        "unexpected": {"nested": True},
                    },
                ]
            }
        ),
    )

    generated = glossary_generator.generate(sample_a2_text_article)

    assert generated == [
        VocabularyItem(
            term="Sturmschäden",
            english="storm damage",
            explanation="Schäden durch starken Wind und Regen",
        )
    ]


def test_glossary_response_schema_is_closed_for_openai_structured_output():
    schema = GLOSSARY_RESPONSE_SCHEMA
    item_properties = schema["properties"]["vocabulary"]["items"]["properties"]

    assert schema["title"] == "GlossaryResponse"
    assert schema["description"] == (
        "Structured glossary entries extracted from the approved article text."
    )
    assert schema["additionalProperties"] is False
    assert schema["properties"]["vocabulary"]["items"]["additionalProperties"] is False
    assert schema["properties"]["vocabulary"]["items"]["required"] == [
        "term",
        "english",
        "explanation",
        "gloss",
    ]
    for field_name in ("term", "english", "explanation", "gloss"):
        assert item_properties[field_name] == {
            "anyOf": [{"type": "string"}, {"type": "null"}]
        }


def test_glossary_response_schema_converts_with_langchain_strict_mode():
    function = convert_to_openai_function(GLOSSARY_RESPONSE_SCHEMA, strict=True)

    assert function["name"] == "GlossaryResponse"
    assert function["description"] == (
        "Structured glossary entries extracted from the approved article text."
    )
    assert function["strict"] is True
    assert function["parameters"]["required"] == ["vocabulary"]


def test_validate_keeps_high_value_terms_and_context_phrases(glossary_generator):
    content = (
        "Die Sturmschäden nahmen in der Region zu. Die Deichhelfer kritisierten die Antwort. "
        "Der Feuerwehrverband mobilisierte mehr Einsatzkräfte. Hilfsgruppen unterstützten die Aktion. "
        "Die Migrationspolitik änderte sich nach dem Abkommen."
    )
    candidates = [
        VocabularyItem(
            term="Sturmschäden",
            english="storm damage",
            explanation="Schäden durch starken Wind und Regen",
        ),
        VocabularyItem(
            term="Deichhelfer",
            english="levee helpers",
            explanation="Menschen, die an Schutzwällen helfen",
        ),
        VocabularyItem(
            term="Feuerwehrverband",
            english="fire service association",
            explanation="Organisation von Feuerwehren",
        ),
        VocabularyItem(
            term="Hilfsgruppen",
            english="aid groups",
            explanation="Gruppen, die Unterstützung organisieren",
        ),
        VocabularyItem(
            term="Migrationspolitik",
            english="migration policy",
            explanation="Regeln des Staates zur Einwanderung",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert [item.term for item in accepted] == [
        "Sturmschäden",
        "Deichhelfer",
        "Feuerwehrverband",
        "Hilfsgruppen",
        "Migrationspolitik",
    ]
    assert dropped == {}


def test_validate_accepts_generated_items_with_one_gloss_field(glossary_generator):
    content = "Die Sturmschäden nahmen zu und die Migrationspolitik änderte sich."
    candidates = [
        VocabularyItem(
            term="Sturmschäden",
            english="storm damage",
            explanation="",
        ),
        VocabularyItem(
            term="Migrationspolitik",
            english="",
            explanation="Regeln des Staates zur Einwanderung",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert [item.term for item in accepted] == ["Sturmschäden", "Migrationspolitik"]
    assert dropped == {}


def test_validate_without_nlp_rejects_people_and_places_but_keeps_organizations(glossary_generator):
    content = (
        "Betroffene Orte: Deutschland und Berlin. Angela Merkel sprach danach. "
        "Brandenburg bat um Hilfe. "
        "Der Feuerwehrverband antwortete zusammen mit Vereinte Nationen und Rotes Kreuz."
    )
    candidates = [
        VocabularyItem(
            term="Angela Merkel",
            english="angela merkel",
            explanation="former chancellor of Germany",
        ),
        VocabularyItem(
            term="Deutschland",
            english="germany",
            explanation="country in Europe",
        ),
        VocabularyItem(
            term="Berlin",
            english="berlin",
            explanation="capital city of Germany",
        ),
        VocabularyItem(
            term="Brandenburg",
            english="brandenburg",
            explanation="state around Berlin",
        ),
        VocabularyItem(
            term="Feuerwehrverband",
            english="fire service association",
            explanation="Organisation von Feuerwehren",
        ),
        VocabularyItem(
            term="Vereinte Nationen",
            english="united nations",
            explanation="international organization of countries",
        ),
        VocabularyItem(
            term="Rotes Kreuz",
            english="red cross",
            explanation="international aid organization",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert [item.term for item in accepted] == [
        "Feuerwehrverband",
        "Vereinte Nationen",
        "Rotes Kreuz",
    ]
    assert dropped["Angela Merkel"] == "named entity or common place/person name"
    assert dropped["Deutschland"] == "named entity or common place/person name"
    assert dropped["Berlin"] == "named entity or common place/person name"
    assert dropped["Brandenburg"] == "named entity or common place/person name"


def test_validate_uses_article_casing_for_dropped_term_keys(glossary_generator):
    content = "Deutschland kündigte neue Maßnahmen an."
    candidates = [
        VocabularyItem(
            term="deutschland",
            english="germany",
            explanation="country in Europe",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert accepted == []
    assert "Deutschland" in dropped
    assert "deutschland" not in dropped
    assert dropped["Deutschland"] == "named entity or common place/person name"


def test_validate_without_nlp_keeps_generic_terms_when_explanation_mentions_a_country(glossary_generator):
    content = "Der Haushaltsplan änderte sich nach der Debatte."
    candidates = [
        VocabularyItem(
            term="Haushaltsplan",
            english="budget",
            explanation="Plan des Staates für Ausgaben",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert [item.term for item in accepted] == ["Haushaltsplan"]
    assert dropped == {}


def test_apply_bolding_marks_only_accepted_terms(glossary_generator):
    content = "Die Migrationspolitik änderte sich nach den Sturmschäden."
    items = [
        VocabularyItem(
            term="Migrationspolitik",
            english="migration policy",
            explanation="Regeln des Staates zur Einwanderung",
        ),
        VocabularyItem(
            term="Sturmschäden",
            english="storm damage",
            explanation="Schäden durch starken Wind und Regen",
        ),
    ]

    bolded = glossary_generator.apply_bolding(content, items)

    assert "**Migrationspolitik**" in bolded
    assert "**Sturmschäden**" in bolded


def test_validate_normalizes_term_casing_to_match_article_text(glossary_generator):
    content = "Die Sturmschäden nahmen in der Nacht zu."
    candidates = [
        VocabularyItem(
            term="sturmschäden",
            english="storm damage",
            explanation="Schäden durch starken Wind und Regen",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)
    bolded = glossary_generator.apply_bolding(content, accepted)

    assert dropped == {}
    assert [item.term for item in accepted] == ["Sturmschäden"]
    assert "**Sturmschäden**" in bolded


def test_transparent_token_matching_handles_plural_cognates_before_singularizing(glossary_generator):
    assert glossary_generator._tokens_look_transparent("notables", "notable") is True
    assert glossary_generator._tokens_look_transparent("visibles", "visible") is True


def test_transparent_token_matching_handles_ous_cognates_before_singularizing_english(glossary_generator):
    assert glossary_generator._tokens_look_transparent("famosa", "famous") is True


def test_isolated_modifier_fallback_allows_predicative_adjectives(glossary_generator):
    assert glossary_generator._is_isolated_modifier(None, "Das System ist fragil.", "fragil") is False
    assert (
        glossary_generator._is_isolated_modifier(
            None,
            "Die Energie ist nachhaltig.",
            "nachhaltig",
        )
        is False
    )
    assert (
        glossary_generator._is_isolated_modifier(
            None,
            "Die migrantische Politik änderte sich.",
            "migrantische",
        )
        is True
    )


def test_isolated_modifier_allows_predicative_adjectives_with_nlp(glossary_generator):
    class FakeHead:
        def __init__(self, pos_):
            self.pos_ = pos_

    class FakeToken:
        def __init__(self, pos_, dep_, head_pos_):
            self.pos_ = pos_
            self.dep_ = dep_
            self.head = FakeHead(head_pos_)

    predicative = [FakeToken("ADJ", "ROOT", "VERB")]
    attributive = [FakeToken("ADJ", "amod", "NOUN")]

    glossary_generator._find_matching_spans = MagicMock(
        side_effect=[[[predicative[0]]], [[attributive[0]]]]
    )

    assert glossary_generator._is_isolated_modifier(object(), "Das System ist fragil.", "fragil") is False
    assert glossary_generator._is_isolated_modifier(
        object(),
        "Die migrantische Politik änderte sich.",
        "migrantische",
    ) is True


def test_enrich_article_publishes_without_glossary_when_all_items_are_rejected(
    glossary_generator,
    sample_a2_text_article,
    monkeypatch,
):
    monkeypatch.setattr(
        glossary_generator,
        "generate",
        MagicMock(
            return_value=[
                VocabularyItem(
                    term="drones",
                    english="drones",
                    explanation="unmanned aircraft",
                )
            ]
        ),
    )

    article = sample_a2_text_article.model_copy(
        update={"content": "Drohnen flogen in der Nacht über die Stadt."}
    )
    enriched = glossary_generator.enrich_article(article)

    assert enriched.vocabulary == []
    assert enriched.content == article.content
    assert any(
        "glossary_candidates_initial=1" in str(call.args[0])
        for call in glossary_generator.logger.warning.call_args_list
    )


def test_enrich_article_without_retry_does_not_mark_empty_after_retry(
    glossary_generator,
    sample_a2_text_article,
    monkeypatch,
):
    glossary_generator.retry_on_empty = False
    monkeypatch.setattr(
        glossary_generator,
        "generate",
        MagicMock(
            return_value=[
                VocabularyItem(
                    term="drones",
                    english="drones",
                    explanation="unmanned aircraft",
                )
            ]
        ),
    )

    article = sample_a2_text_article.model_copy(
        update={"content": "Drohnen flogen in der Nacht über die Stadt."}
    )

    enriched = glossary_generator.enrich_article(article)

    assert enriched.vocabulary == []
    assert glossary_generator.last_run_stats["retry_used"] is False
    assert glossary_generator.last_run_stats["glossary_empty_after_retry"] is False


def test_enrich_article_retries_when_initial_candidates_all_fail_for_spring_a2(
    glossary_generator,
    sample_a2_text_article,
    monkeypatch,
):
    article = sample_a2_text_article.model_copy(
        update={
            "title": "Milder Frühling in Deutschland",
            "content": FRUEHLING_A2_CONTENT,
        }
    )
    monkeypatch.setattr(
        glossary_generator,
        "_call_llm",
        MagicMock(
            side_effect=[
                GlossaryResponse(
                    vocabulary=[
                        {"term": "Deutschland", "english": "Germany", "explanation": "country in Europe"},
                        {
                            "term": "Berlin",
                            "english": "Berlin",
                            "explanation": "capital city of Germany",
                        },
                        {"term": "Brandenburg", "english": "Brandenburg", "explanation": "state around Berlin"},
                        {
                            "term": "Deutscher Wetterdienst",
                            "english": "German Weather Service",
                            "explanation": "federal weather authority",
                        },
                        {
                            "term": "Olaf Scholz",
                            "english": "Olaf Scholz",
                            "explanation": "German politician",
                        },
                    ]
                ),
                GlossaryResponse(
                    vocabulary=[
                        {
                            "term": "Stadtfeste",
                            "english": "public events",
                            "explanation": "Veranstaltungen im Freien",
                        },
                        {
                            "term": "Genehmigungen",
                            "english": "permits",
                            "explanation": "offizielle Erlaubnisse",
                        },
                        {
                            "term": "Netzausbau",
                            "english": "grid expansion",
                            "explanation": "Ausbau von Stromleitungen",
                        },
                        {
                            "term": "Mobilitätskarte",
                            "english": "mobility card",
                            "explanation": "Karte für verschiedene Verkehrsmittel",
                        },
                    ]
                ),
            ]
        ),
    )

    enriched = glossary_generator.enrich_article(article)

    assert [item.term for item in enriched.vocabulary] == [
        "Stadtfeste",
        "Genehmigungen",
        "Netzausbau",
        "Mobilitätskarte",
    ]
    assert glossary_generator.last_run_stats["retry_used"] is True
    assert glossary_generator.last_run_stats["glossary_candidates_initial"] == 5
    assert glossary_generator.last_run_stats["glossary_candidates_retry"] == 4
    assert glossary_generator.last_run_stats["glossary_accepted"] == 4


def test_enrich_article_retries_when_initial_candidates_all_fail_for_administration_b1(
    glossary_generator,
    sample_b1_text_article,
    monkeypatch,
):
    article = sample_b1_text_article.model_copy(
        update={
            "title": "Deutschland digitalisiert Verwaltung und Verkehr",
            "content": VERWALTUNG_B1_CONTENT,
        }
    )
    monkeypatch.setattr(
        glossary_generator,
        "_call_llm",
        MagicMock(
            side_effect=[
                GlossaryResponse(
                    vocabulary=[
                        {"term": "Deutschland", "english": "Germany", "explanation": "country in Europe"},
                        {
                            "term": "Angela Merkel",
                            "english": "Angela Merkel",
                            "explanation": "former chancellor of Germany",
                        },
                        {"term": "Berlin", "english": "Berlin", "explanation": "capital city of Germany"},
                        {"term": "Olaf Scholz", "english": "Olaf Scholz", "explanation": "German politician"},
                        {
                            "term": "drones",
                            "english": "drones",
                            "explanation": "unmanned aircraft",
                        },
                    ]
                ),
                GlossaryResponse(
                    vocabulary=[
                        {
                            "term": "Selbstständige",
                            "english": "self-employed workers",
                            "explanation": "Menschen, die auf eigene Rechnung arbeiten",
                        },
                        {
                            "term": "Schienennetze",
                            "english": "rail networks",
                            "explanation": "Netze aus Bahnstrecken",
                        },
                        {
                            "term": "Güterverkehr",
                            "english": "freight transport",
                            "explanation": "Transport von Waren",
                        },
                        {
                            "term": "Mobilitätskarte",
                            "english": "mobility card",
                            "explanation": "Karte für verschiedene Verkehrsmittel",
                        },
                    ]
                ),
            ]
        ),
    )

    enriched = glossary_generator.enrich_article(article)

    assert [item.term for item in enriched.vocabulary] == [
        "Selbstständige",
        "Schienennetze",
        "Güterverkehr",
        "Mobilitätskarte",
    ]
    assert glossary_generator.last_run_stats["retry_used"] is True
    assert glossary_generator.last_run_stats["glossary_accepted"] == 4


def test_debug_dump_writes_glossary_artifact(glossary_generator, sample_a2_text_article, tmp_path, monkeypatch):
    glossary_generator.debug_dump = True
    glossary_generator.metrics_output_dir = tmp_path / "glossary"
    monkeypatch.setattr(
        glossary_generator,
        "_call_llm",
        MagicMock(
            return_value=GlossaryResponse(
                vocabulary=[
                    {
                        "term": "Sturmschäden",
                        "english": "storm damage",
                        "explanation": "Schäden durch starken Wind und Regen",
                    }
                ]
            )
        ),
    )

    article = sample_a2_text_article.model_copy(
        update={"content": "Die Sturmschäden nahmen in der Nacht zu."}
    )
    glossary_generator.enrich_article(article)

    artifact_paths = list((tmp_path / "glossary").glob("*.json"))
    assert len(artifact_paths) == 1

    payload = json.loads(artifact_paths[0].read_text(encoding="utf-8"))
    assert payload["article_title"] == article.title
    assert payload["level"] == article.level
    assert payload["retry_used"] is False
    assert payload["counts"]["initial_candidates"] == 1
    assert payload["counts"]["accepted"] == 1
    assert payload["accepted"][0]["term"] == "Sturmschäden"
    assert payload["dropped"]["initial"] == []


def test_debug_dump_failure_does_not_discard_accepted_glossary(
    glossary_generator,
    sample_a2_text_article,
    monkeypatch,
):
    glossary_generator.debug_dump = True
    monkeypatch.setattr(
        glossary_generator,
        "_call_llm",
        MagicMock(
            return_value=GlossaryResponse(
                vocabulary=[
                    {
                        "term": "Sturmschäden",
                        "english": "storm damage",
                        "explanation": "Schäden durch starken Wind und Regen",
                    }
                ]
            )
        ),
    )
    monkeypatch.setattr(
        glossary_generator,
        "_write_debug_artifact",
        MagicMock(side_effect=OSError("disk full")),
    )

    article = sample_a2_text_article.model_copy(
        update={"content": "Die Sturmschäden nahmen in der Nacht zu."}
    )

    enriched = glossary_generator.enrich_article(article)

    assert [item.term for item in enriched.vocabulary] == ["Sturmschäden"]
    assert "**Sturmschäden**" in enriched.content
    assert any(
        "Glossary debug dump failed for '%s': %s. Continuing without artifact."
        in str(call.args[0])
        for call in glossary_generator.logger.warning.call_args_list
    )

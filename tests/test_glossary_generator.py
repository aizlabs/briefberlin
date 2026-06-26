import json
from unittest.mock import MagicMock

import pytest
from langchain_core.utils.function_calling import convert_to_openai_function

from scripts.glossary_generator import GLOSSARY_RESPONSE_SCHEMA, GlossaryGenerator, GlossaryResponse
from scripts.models import VocabularyItem

SEMANA_SANTA_A2_CONTENT = (
    "La Semana Santa en España este año tiene buen clima. La Agencia Estatal de Meteorología "
    "dice que el tiempo será estable. Las procesiones serán bonitas. En Andalucía y Levante, "
    "hará entre 20 y 25 grados. En el centro y norte, entre 15 y 20 grados. Algunas zonas del "
    "norte y Mediterráneo tendrán viento, pero no será un problema.\n\n"
    "La Semana Santa es importante en España. No es solo religión, también es arte y tradición. "
    "En Sevilla, la ‘Madrugá’ es muy especial. Muchas personas van a ver las procesiones en "
    "silencio. En Zamora, las celebraciones son más simples, pero también bonitas.\n\n"
    "En noticias internacionales, España ha cerrado su espacio aéreo a aviones de Estados Unidos. "
    "La ministra de Defensa, Margarita Robles, dice que España no quiere más problemas en el "
    "conflicto con Irán. España ha comunicado esto a Estados Unidos.\n\n"
    "En deportes, la selección española de fútbol se prepara para el Mundial. El entrenador es "
    "Luis de la Fuente. El equipo juega bien, pero perdió contra Escocia. A pesar de esto, "
    "España es favorita. Tiene jugadores buenos como Oyarzabal y Zubimendi."
)

MIGRACION_B1_CONTENT = (
    "España está en un momento importante en varios aspectos, como la migración, el trabajo y el "
    "deporte. El gobierno español ha decidido regularizar a muchos inmigrantes, lo que preocupa a "
    "la Comisión Europea. Magnus Brunner, encargado de Migración, dice que vivir en España no "
    "significa poder mudarse a otros países de la Unión Europea. Esto podría causar problemas si "
    "los inmigrantes quieren ir a otros lugares del bloque.\n\n"
    "En el trabajo, los autónomos son muy importantes para la economía española. Un informe "
    "reciente muestra que representan el 14,58% del empleo total en España, más que la media "
    "europea. Sin embargo, este sector tiene retos, como atraer a jóvenes, ya que muchos "
    "autónomos tienen más de 45 años. También se destaca el aumento de mujeres y extranjeros que "
    "trabajan por cuenta propia desde 2021.\n\n"
    "Por otro lado, el sistema de trenes en España recibe críticas porque no es compatible con "
    "los sistemas europeos. Empresas como Ouigo e Iryo están preocupadas por la competitividad "
    "debido a los diferentes anchos de vía. Esto afecta tanto a los pasajeros como al transporte "
    "de mercancías. Las empresas piden un plan claro para adaptarse a los estándares europeos.\n\n"
    "En deportes, el equipo de fútbol de España, dirigido por Luis de la Fuente, se prepara para "
    "el Mundial. Aunque ha tenido algunas derrotas recientes, como contra Escocia y Colombia, "
    "sigue siendo uno de los favoritos. Esto se debe a jugadores importantes como Unai Simón, "
    "Pedri y Oyarzabal. España quiere seguir teniendo éxito en el escenario internacional, "
    "enfrentando los desafíos y cambios en el equipo."
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
        "Irán lanzó bombardeos con drones. Donald Trump habló con Estados Unidos sobre Israel. "
        "La política migratoria cambió. También hubo decisiones unilaterales."
    )
    candidates = [
        VocabularyItem(term="Irán", english="Iran", explanation="país en el Medio Oriente"),
        VocabularyItem(
            term="Estados Unidos",
            english="United States",
            explanation="país en América del Norte",
        ),
        VocabularyItem(
            term="Donald Trump",
            english="Donald Trump",
            explanation="expresidente de Estados Unidos",
        ),
        VocabularyItem(term="drones", english="drones", explanation="aviones no tripulados"),
        VocabularyItem(
            term="migratoria",
            english="migratory",
            explanation="relacionada con el movimiento de personas entre países",
        ),
        VocabularyItem(
            term="unilaterales",
            english="unilateral",
            explanation="hechas por un solo lado",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert accepted == []
    assert set(dropped) == {
        "Irán",
        "Estados Unidos",
        "Donald Trump",
        "drones",
        "migratoria",
        "unilaterales",
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
                        "explanation": "entrada inválida",
                    },
                    {
                        "term": "bombardeos",
                        "english": "bombings",
                        "explanation": "ataques con bombas desde el aire",
                    },
                ]
            )
        ),
    )

    generated = glossary_generator.generate(sample_a2_text_article)

    assert generated == [
        VocabularyItem(
            term="bombardeos",
            english="bombings",
            explanation="ataques con bombas desde el aire",
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
                        "term": "bombardeos",
                        "english": "bombings",
                        "explanation": "ataques con bombas desde el aire",
                        "difficulty": "medium",
                    },
                    {
                        "term": None,
                        "english": "ignored",
                        "explanation": "entrada inválida",
                        "unexpected": {"nested": True},
                    },
                ]
            }
        ),
    )

    generated = glossary_generator.generate(sample_a2_text_article)

    assert generated == [
        VocabularyItem(
            term="bombardeos",
            english="bombings",
            explanation="ataques con bombas desde el aire",
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
        "Los bombardeos aumentaron en la región. Los ayatolás criticaron la respuesta. "
        "La Guardia Revolucionaria movilizó más tropas. Los hutíes apoyaron la operación. "
        "La política migratoria cambió después del acuerdo."
    )
    candidates = [
        VocabularyItem(
            term="bombardeos",
            english="bombings",
            explanation="ataques con bombas desde el aire",
        ),
        VocabularyItem(
            term="ayatolás",
            english="ayatollahs",
            explanation="líderes religiosos en Irán",
        ),
        VocabularyItem(
            term="Guardia Revolucionaria",
            english="Revolutionary Guard",
            explanation="fuerza militar de élite en Irán",
        ),
        VocabularyItem(
            term="hutíes",
            english="Houthis",
            explanation="grupo rebelde en Yemen",
        ),
        VocabularyItem(
            term="política migratoria",
            english="migration policy",
            explanation="reglas del gobierno sobre la inmigración",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert [item.term for item in accepted] == [
        "bombardeos",
        "ayatolás",
        "Guardia Revolucionaria",
        "hutíes",
        "política migratoria",
    ]
    assert dropped == {}


def test_validate_accepts_generated_items_with_one_gloss_field(glossary_generator):
    content = "Los bombardeos aumentaron y la política migratoria cambió."
    candidates = [
        VocabularyItem(
            term="bombardeos",
            english="bombings",
            explanation="",
        ),
        VocabularyItem(
            term="política migratoria",
            english="",
            explanation="reglas del gobierno sobre la inmigración",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert [item.term for item in accepted] == ["bombardeos", "política migratoria"]
    assert dropped == {}


def test_validate_without_nlp_rejects_people_and_places_but_keeps_organizations(glossary_generator):
    content = (
        "Países afectados: Francia y París. Pedro Sánchez habló después. "
        "La República Dominicana pidió ayuda. "
        "La Guardia Revolucionaria respondió junto con Naciones Unidas y la Cruz Roja."
    )
    candidates = [
        VocabularyItem(
            term="Pedro Sánchez",
            english="pedro sanchez",
            explanation="presidente del gobierno de España",
        ),
        VocabularyItem(
            term="Francia",
            english="france",
            explanation="país europeo",
        ),
        VocabularyItem(
            term="París",
            english="paris",
            explanation="capital de Francia",
        ),
        VocabularyItem(
            term="República Dominicana",
            english="dominican republic",
            explanation="país del Caribe",
        ),
        VocabularyItem(
            term="Guardia Revolucionaria",
            english="revolutionary guard",
            explanation="fuerza militar de élite en Irán",
        ),
        VocabularyItem(
            term="Naciones Unidas",
            english="united nations",
            explanation="organización internacional de países",
        ),
        VocabularyItem(
            term="Cruz Roja",
            english="red cross",
            explanation="organización humanitaria internacional",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert [item.term for item in accepted] == [
        "Guardia Revolucionaria",
        "Naciones Unidas",
        "Cruz Roja",
    ]
    assert dropped["Pedro Sánchez"] == "named entity or common place/person name"
    assert dropped["Francia"] == "named entity or common place/person name"
    assert dropped["París"] == "named entity or common place/person name"
    assert dropped["República Dominicana"] == "named entity or common place/person name"


def test_validate_uses_article_casing_for_dropped_term_keys(glossary_generator):
    content = "Francia anunció nuevas medidas."
    candidates = [
        VocabularyItem(
            term="francia",
            english="france",
            explanation="país europeo",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert accepted == []
    assert "Francia" in dropped
    assert "francia" not in dropped
    assert dropped["Francia"] == "named entity or common place/person name"


def test_validate_without_nlp_keeps_generic_terms_when_explanation_mentions_a_country(glossary_generator):
    content = "El presupuesto cambió después del debate."
    candidates = [
        VocabularyItem(
            term="presupuesto",
            english="budget",
            explanation="plan del gobierno para gastar dinero en el país",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)

    assert [item.term for item in accepted] == ["presupuesto"]
    assert dropped == {}


def test_apply_bolding_marks_only_accepted_terms(glossary_generator):
    content = "La política migratoria cambió después de los bombardeos."
    items = [
        VocabularyItem(
            term="política migratoria",
            english="migration policy",
            explanation="reglas del gobierno sobre la inmigración",
        ),
        VocabularyItem(
            term="bombardeos",
            english="bombings",
            explanation="ataques con bombas desde el aire",
        ),
    ]

    bolded = glossary_generator.apply_bolding(content, items)

    assert "**política migratoria**" in bolded
    assert "**bombardeos**" in bolded


def test_validate_normalizes_term_casing_to_match_article_text(glossary_generator):
    content = "Los bombardeos aumentaron durante la noche."
    candidates = [
        VocabularyItem(
            term="Bombardeos",
            english="bombings",
            explanation="ataques con bombas desde el aire",
        ),
    ]

    accepted, dropped = glossary_generator.validate(content, candidates)
    bolded = glossary_generator.apply_bolding(content, accepted)

    assert dropped == {}
    assert [item.term for item in accepted] == ["bombardeos"]
    assert "**bombardeos**" in bolded


def test_transparent_token_matching_handles_plural_cognates_before_singularizing(glossary_generator):
    assert glossary_generator._tokens_look_transparent("notables", "notable") is True
    assert glossary_generator._tokens_look_transparent("visibles", "visible") is True


def test_transparent_token_matching_handles_ous_cognates_before_singularizing_english(glossary_generator):
    assert glossary_generator._tokens_look_transparent("famosa", "famous") is True


def test_isolated_modifier_fallback_allows_predicative_adjectives(glossary_generator):
    assert glossary_generator._is_isolated_modifier(None, "El sistema es frágil.", "frágil") is False
    assert (
        glossary_generator._is_isolated_modifier(
            None,
            "Es sostenible la energía del país.",
            "sostenible",
        )
        is False
    )
    assert (
        glossary_generator._is_isolated_modifier(
            None,
            "La política migratoria cambió.",
            "migratoria",
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

    assert glossary_generator._is_isolated_modifier(object(), "El sistema es frágil.", "frágil") is False
    assert glossary_generator._is_isolated_modifier(
        object(),
        "La política migratoria cambió.",
        "migratoria",
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
                    explanation="aviones no tripulados",
                )
            ]
        ),
    )

    article = sample_a2_text_article.model_copy(
        update={"content": "Los drones volaron sobre la ciudad durante la noche."}
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
                    explanation="aviones no tripulados",
                )
            ]
        ),
    )

    article = sample_a2_text_article.model_copy(
        update={"content": "Los drones volaron sobre la ciudad durante la noche."}
    )

    enriched = glossary_generator.enrich_article(article)

    assert enriched.vocabulary == []
    assert glossary_generator.last_run_stats["retry_used"] is False
    assert glossary_generator.last_run_stats["glossary_empty_after_retry"] is False


def test_enrich_article_retries_when_initial_candidates_all_fail_for_march_31_a2(
    glossary_generator,
    sample_a2_text_article,
    monkeypatch,
):
    article = sample_a2_text_article.model_copy(
        update={
            "title": "Semana Santa Soleada en España",
            "content": SEMANA_SANTA_A2_CONTENT,
        }
    )
    monkeypatch.setattr(
        glossary_generator,
        "_call_llm",
        MagicMock(
            side_effect=[
                GlossaryResponse(
                    vocabulary=[
                        {"term": "España", "english": "Spain", "explanation": "país europeo"},
                        {
                            "term": "Estados Unidos",
                            "english": "United States",
                            "explanation": "país de América del Norte",
                        },
                        {"term": "Irán", "english": "Iran", "explanation": "país de Asia"},
                        {
                            "term": "Margarita Robles",
                            "english": "Margarita Robles",
                            "explanation": "ministra española",
                        },
                        {
                            "term": "Luis de la Fuente",
                            "english": "Luis de la Fuente",
                            "explanation": "entrenador español",
                        },
                    ]
                ),
                GlossaryResponse(
                    vocabulary=[
                        {
                            "term": "procesiones",
                            "english": "processions",
                            "explanation": "desfiles religiosos en la calle",
                        },
                        {
                            "term": "espacio aéreo",
                            "english": "airspace",
                            "explanation": "zona del cielo de un país para aviones",
                        },
                        {
                            "term": "selección",
                            "english": "national team",
                            "explanation": "equipo que representa a un país",
                        },
                        {
                            "term": "conflicto",
                            "english": "conflict",
                            "explanation": "situación de lucha o problema entre grupos",
                        },
                    ]
                ),
            ]
        ),
    )

    enriched = glossary_generator.enrich_article(article)

    assert [item.term for item in enriched.vocabulary] == [
        "procesiones",
        "espacio aéreo",
        "selección",
        "conflicto",
    ]
    assert glossary_generator.last_run_stats["retry_used"] is True
    assert glossary_generator.last_run_stats["glossary_candidates_initial"] == 5
    assert glossary_generator.last_run_stats["glossary_candidates_retry"] == 4
    assert glossary_generator.last_run_stats["glossary_accepted"] == 4


def test_enrich_article_retries_when_initial_candidates_all_fail_for_march_31_b1(
    glossary_generator,
    sample_b1_text_article,
    monkeypatch,
):
    article = sample_b1_text_article.model_copy(
        update={
            "title": "España enfrenta desafíos en migración, trabajo y deportes",
            "content": MIGRACION_B1_CONTENT,
        }
    )
    monkeypatch.setattr(
        glossary_generator,
        "_call_llm",
        MagicMock(
            side_effect=[
                GlossaryResponse(
                    vocabulary=[
                        {"term": "España", "english": "Spain", "explanation": "país europeo"},
                        {
                            "term": "Magnus Brunner",
                            "english": "Magnus Brunner",
                            "explanation": "político europeo",
                        },
                        {"term": "Ouigo", "english": "Ouigo", "explanation": "empresa de trenes"},
                        {"term": "Iryo", "english": "Iryo", "explanation": "empresa de trenes"},
                        {
                            "term": "Luis de la Fuente",
                            "english": "Luis de la Fuente",
                            "explanation": "entrenador español",
                        },
                    ]
                ),
                GlossaryResponse(
                    vocabulary=[
                        {
                            "term": "autónomos",
                            "english": "self-employed workers",
                            "explanation": "personas que trabajan por cuenta propia",
                        },
                        {
                            "term": "anchos de vía",
                            "english": "track gauges",
                            "explanation": "distancias entre los rieles del tren",
                        },
                        {
                            "term": "mercancías",
                            "english": "goods",
                            "explanation": "productos que se transportan para vender",
                        },
                        {
                            "term": "mudarse",
                            "english": "to move",
                            "explanation": "cambiar de lugar para vivir",
                        },
                    ]
                ),
            ]
        ),
    )

    enriched = glossary_generator.enrich_article(article)

    assert [item.term for item in enriched.vocabulary] == [
        "autónomos",
        "anchos de vía",
        "mercancías",
        "mudarse",
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
                        "term": "bombardeos",
                        "english": "bombings",
                        "explanation": "ataques con bombas desde el aire",
                    }
                ]
            )
        ),
    )

    article = sample_a2_text_article.model_copy(
        update={"content": "Los bombardeos aumentaron durante la noche."}
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
    assert payload["accepted"][0]["term"] == "bombardeos"
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
                        "term": "bombardeos",
                        "english": "bombings",
                        "explanation": "ataques con bombas desde el aire",
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
        update={"content": "Los bombardeos aumentaron durante la noche."}
    )

    enriched = glossary_generator.enrich_article(article)

    assert [item.term for item in enriched.vocabulary] == ["bombardeos"]
    assert "**bombardeos**" in enriched.content
    assert any(
        "Glossary debug dump failed for '%s': %s. Continuing without artifact."
        in str(call.args[0])
        for call in glossary_generator.logger.warning.call_args_list
    )

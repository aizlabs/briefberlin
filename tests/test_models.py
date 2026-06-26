import pytest
from pydantic import ValidationError

from scripts.models import (
    AdaptedArticle,
    LLMConfig,
    LLMModelsConfig,
    VocabularyItem,
    coerce_vocabulary_items,
)


def _valid_models() -> LLMModelsConfig:
    return LLMModelsConfig(
        generation="gpt-4o",
        adaptation="gpt-4o",
        quality_check="gpt-4o-mini",
    )


@pytest.mark.parametrize(
    "field_name, value",
    [
        ("temperature", 1.1),
        ("quality_temperature", 1.5),
    ],
)
def test_llm_config_enforces_temperature_upper_bound(field_name, value):
    base_kwargs = dict(
        provider="openai",
        models=_valid_models(),
        temperature=0.3,
        quality_temperature=0.1,
        max_tokens=4096,
    )

    base_kwargs[field_name] = value

    with pytest.raises(ValidationError):
        LLMConfig(**base_kwargs)


def test_adapted_article_coerces_legacy_vocabulary_dict():
    article = AdaptedArticle(
        title="Título",
        content="Texto suficiente para pasar la validación. " * 4,
        summary="Resumen suficientemente largo.",
        reading_time=2,
        level="A2",
        vocabulary={
            "cambio climático": "climate change - cambios en el clima del planeta",
        },
    )

    assert article.vocabulary == [
        VocabularyItem(
            term="cambio climático",
            english="climate change",
            explanation="cambios en el clima del planeta",
        )
    ]


def test_adapted_article_coerces_legacy_term_gloss_items():
    article = AdaptedArticle(
        title="Título",
        content="Texto suficiente para pasar la validación. " * 4,
        summary="Resumen suficientemente largo.",
        reading_time=2,
        level="B1",
        vocabulary=[
            {"term": "bombardeos", "gloss": "bombings - ataques con bombas desde el aire"},
        ],
    )

    assert article.vocabulary == [
        VocabularyItem(
            term="bombardeos",
            english="bombings",
            explanation="ataques con bombas desde el aire",
        )
    ]


def test_coerce_vocabulary_items_prefers_structured_fields_over_null_gloss():
    items = coerce_vocabulary_items(
        [
            {
                "term": "bombardeos",
                "english": "bombings",
                "explanation": "ataques con bombas desde el aire",
                "gloss": None,
            }
        ]
    )

    assert items == [
        VocabularyItem(
            term="bombardeos",
            english="bombings",
            explanation="ataques con bombas desde el aire",
        )
    ]

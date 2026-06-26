"""
Pytest configuration and shared fixtures for test suite
"""

import json
from typing import List
from unittest.mock import MagicMock

import pytest

from scripts.config import AppConfig
from scripts.models import (
    AdaptedArticle,
    BaseArticle,
    SourceArticle,
    SourceMetadata,
    Topic,
    VocabularyItem,
)

# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def base_config() -> AppConfig:
    """Base configuration dict for testing"""
    config_dict = {
        'environment': 'test',
        'generation': {
            'articles_per_run': 2,
            'levels': ['A2', 'B1'],
            'target_word_count': {
                'A2': 200,
                'B1': 300
            },
            'two_step_synthesis': {
                'enabled': True,
                'save_base_article': False,
                'base_article_path': './output/base_articles/',
                'regeneration_strategy': 'adaptation_only'
            }
        },
        'llm': {
            'provider': 'openai',
            'models': {
                'generation': 'gpt-4o',
                'adaptation': 'gpt-4o',
                'quality_check': 'gpt-4o-mini'
            },
            'openai_api_key': 'test-key-123',
            'temperature': 0.3,
            'quality_temperature': 0.1,
            'max_tokens': 4096
        },
        'quality_gate': {
            'min_score': 7.5,
            'max_attempts': 3
        },
        'glossary': {
            'retry_on_empty': True,
            'debug_dump': False,
        },
        'sources': {
            'max_words_per_source': 300,
            'min_words_per_source': 100,
            'max_sources_per_topic': 5
        },
        'output': {
            'path': 'output/_posts'
        },
        'alerts': {}
    }
    return AppConfig(**config_dict)


@pytest.fixture
def mock_logger():
    """Mock logger for testing"""
    logger = MagicMock()
    logger.getChild.return_value = logger
    logger.info = MagicMock()
    logger.debug = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger


# =============================================================================
# Topic & Source Fixtures
# =============================================================================


@pytest.fixture
def sample_topic() -> Topic:
    """Sample topic object"""
    return Topic(
        title='España reduce emisiones de CO2',
        sources=['El País', 'BBC Mundo', 'El Mundo'],
        mentions=5,
        score=25.0,
        urls=['https://elpais.com/test', 'https://bbc.com/test', 'https://elmundo.es/test']
    )


@pytest.fixture
def sample_sources() -> List[SourceArticle]:
    """Sample source articles"""
    return [
        SourceArticle(
            source='El País',
            text='España ha reducido sus emisiones de CO2 en un 15% este año. '
                 'El gobierno atribuye esta reducción al aumento del uso de energías renovables. '
                 'Los expertos consideran que es un paso importante en la lucha contra el cambio climático.',
            word_count=150,
            url='https://elpais.com/test'
        ),
        SourceArticle(
            source='BBC Mundo',
            text='Las nuevas medidas implementadas por el gobierno español están dando resultados. '
                 'La reducción de emisiones alcanza el 15% comparado con el año anterior. '
                 'Los paneles solares y la energía eólica han sido clave en este logro.',
            word_count=140,
            url='https://bbc.com/test'
        ),
        SourceArticle(
            source='El Mundo',
            text='Expertos ambientales celebran los datos de España. '
                 'El país ha logrado reducir significativamente sus emisiones contaminantes. '
                 'La inversión en tecnologías limpias ha sido fundamental.',
            word_count=120,
            url='https://elmundo.es/test'
        )
    ]


@pytest.fixture
def sample_source_metadata(sample_sources: List[SourceArticle]) -> List[SourceMetadata]:
    """Structured source metadata derived from sample sources"""
    return [SourceMetadata(name=s.source, url=s.url) for s in sample_sources]


# =============================================================================
# Article Fixtures
# =============================================================================


@pytest.fixture
def sample_base_article(sample_topic: Topic, sample_source_metadata: List[SourceMetadata]) -> BaseArticle:
    """Sample base article (native Spanish) - matches real ArticleSynthesizer output"""
    return BaseArticle(
        title='España logra reducir sus emisiones de CO2 en un 15% este año',
        content='España ha conseguido reducir sus emisiones de dióxido de carbono en un 15% '
                'durante el presente año, según datos publicados por el Ministerio de Transición Ecológica. '
                'Este descenso se atribuye principalmente al incremento en el uso de energías renovables, '
                'especialmente la energía solar y eólica.\n\n'
                'El gobierno español ha invertido significativamente en infraestructuras de energías limpias '
                'durante los últimos años. Los paneles solares y los parques eólicos han proliferado '
                'por todo el territorio nacional, contribuyendo a una matriz energética más sostenible.\n\n'
                'Los expertos en medio ambiente consideran que estos resultados son un paso importante '
                'en la lucha contra el cambio climático. Sin embargo, advierten que aún queda mucho '
                'trabajo por hacer para alcanzar los objetivos establecidos en el Acuerdo de París.',
        summary='España reduce sus emisiones de CO2 un 15% gracias al aumento de energías renovables.',
        reading_time=3,
        # Metadata added by ArticleSynthesizer (these fields are CRITICAL for downstream components)
        topic=sample_topic,
        sources=sample_source_metadata
    )


@pytest.fixture
def sample_base_article_minimal() -> BaseArticle:
    """Minimal base article without optional metadata - tests edge cases"""
    return BaseArticle(
        title='Test Article',
        content='Test content for minimal article. This content needs to be at least 100 characters long to pass Pydantic validation. So, I am adding more text here to meet the requirement.',
        summary='Test summary.',
        reading_time=2
        # No 'topic' or 'sources' - simulates edge case
    )


@pytest.fixture
def sample_a2_article(sample_base_article: BaseArticle) -> AdaptedArticle:
    """Sample A2-adapted article"""
    return AdaptedArticle(
        title='España tiene menos contaminación',
        content='España reduce sus emisiones de CO2. El gobierno dice que la contaminación baja un 15%. '
                'Esto es bueno para el **medio ambiente**.\n\n'
                'El país usa más **energías renovables**. Los **paneles solares** y el viento producen electricidad. '
                'Estas energías son limpias.\n\n'
                'Los expertos están contentos. Dicen que España va por buen camino. '
                'Pero necesita hacer más para ayudar al planeta.',
        vocabulary=[
            VocabularyItem(
                term='medio ambiente',
                english='environment',
                explanation='el aire, agua y naturaleza que nos rodea',
            ),
            VocabularyItem(
                term='energías renovables',
                english='renewable energy',
                explanation='energía del sol, viento y agua',
            ),
            VocabularyItem(
                term='paneles solares',
                english='solar panels',
                explanation='aparatos que capturan la energía del sol',
            ),
        ],
        summary='España contamina menos gracias a las energías limpias.',
        reading_time=2,
        level='A2',
        base_article=sample_base_article,
        topic=sample_base_article.topic,
        sources=sample_base_article.sources
    )


@pytest.fixture
def sample_b1_article(sample_base_article: BaseArticle) -> AdaptedArticle:
    """Sample B1-adapted article"""
    return AdaptedArticle(
        title='España reduce sus emisiones de CO2 gracias a energías limpias',
        content='España ha logrado reducir sus **emisiones de dióxido de carbono** en un 15% este año. '
                'El **Ministerio de Transición Ecológica** publicó estos datos positivos. '
                'El aumento de **energías renovables** explica esta mejora.\n\n'
                'El gobierno invirtió mucho dinero en infraestructuras de energías limpias. '
                'Los **paneles solares** y **parques eólicos** se multiplicaron en todo el país. '
                'Esto creó una matriz energética más **sostenible**.\n\n'
                'Los expertos ambientales celebran estos resultados. Consideran que es un avance importante '
                'contra el **cambio climático**. Sin embargo, advierten que España debe hacer más '
                'para cumplir los objetivos del **Acuerdo de París**.',
        vocabulary=[
            VocabularyItem(
                term='emisiones de dióxido de carbono',
                english='carbon dioxide emissions',
                explanation='gases contaminantes del aire',
            ),
            VocabularyItem(
                term='Ministerio de Transición Ecológica',
                english='Ministry of Ecological Transition',
                explanation='departamento del gobierno español',
            ),
            VocabularyItem(
                term='energías renovables',
                english='renewable energy',
                explanation='energía del sol, viento y agua que no se agota',
            ),
            VocabularyItem(
                term='paneles solares',
                english='solar panels',
                explanation='dispositivos que convierten luz solar en electricidad',
            ),
            VocabularyItem(
                term='parques eólicos',
                english='wind farms',
                explanation='lugares con muchas turbinas de viento',
            ),
            VocabularyItem(
                term='sostenible',
                english='sustainable',
                explanation='que se puede mantener sin dañar el medio ambiente',
            ),
            VocabularyItem(
                term='cambio climático',
                english='climate change',
                explanation='alteración del clima global por actividad humana',
            ),
            VocabularyItem(
                term='Acuerdo de París',
                english='Paris Agreement',
                explanation='tratado internacional sobre cambio climático',
            ),
        ],
        summary='España reduce emisiones de CO2 en 15% mediante energías renovables.',
        reading_time=3,
        level='B1',
        base_article=sample_base_article,
        topic=sample_base_article.topic,
        sources=sample_base_article.sources
    )


@pytest.fixture
def sample_a2_text_article(sample_base_article: BaseArticle) -> AdaptedArticle:
    """Sample A2 article after text adaptation but before glossary generation."""
    return AdaptedArticle(
        title='España tiene menos contaminación',
        content='España reduce sus emisiones de CO2. El gobierno dice que la contaminación baja un 15%.\n\n'
                'El país usa más energía limpia. Los paneles solares y el viento producen electricidad.\n\n'
                'Los expertos están contentos. Dicen que España va por buen camino.',
        vocabulary=[],
        summary='España contamina menos gracias a las energías limpias.',
        reading_time=2,
        level='A2',
        base_article=sample_base_article,
        topic=sample_base_article.topic,
        sources=sample_base_article.sources,
    )


@pytest.fixture
def sample_b1_text_article(sample_base_article: BaseArticle) -> AdaptedArticle:
    """Sample B1 article after text adaptation but before glossary generation."""
    return AdaptedArticle(
        title='España reduce sus emisiones de CO2 gracias a energías limpias',
        content='España ha logrado reducir sus emisiones de dióxido de carbono en un 15% este año.\n\n'
                'El Ministerio de Transición Ecológica publicó estos datos positivos y explicó que el '
                'aumento de energías renovables ayudó mucho.\n\n'
                'Los expertos consideran que es un avance importante contra el cambio climático.',
        vocabulary=[],
        summary='España reduce emisiones de CO2 en 15% mediante energías renovables.',
        reading_time=3,
        level='B1',
        base_article=sample_base_article,
        topic=sample_base_article.topic,
        sources=sample_base_article.sources,
    )


# =============================================================================
# LLM Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client"""
    client = MagicMock()

    # Mock response structure
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
        'title': 'Test Article',
        'content': 'Test content',
        'summary': 'Test summary',
        'reading_time': 2
    })

    client.chat.completions.create.return_value = mock_response

    return client


@pytest.fixture
def mock_anthropic_client():
    """Mock Anthropic client"""
    client = MagicMock()

    # Mock response structure
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = json.dumps({
        'title': 'Test Article',
        'content': 'Test content',
        'summary': 'Test summary',
        'reading_time': 2
    })

    client.messages.create.return_value = mock_response

    return client


@pytest.fixture
def mock_quality_response():
    """Mock quality gate response"""
    return {
        'grammar_score': 4,
        'educational_score': 3,
        'content_score': 2,
        'level_score': 1,
        'total_score': 8.5,
        'issues': [],
        'strengths': ['Good grammar', 'Appropriate level'],
        'recommendation': 'PASS'
    }


# =============================================================================
# Helper Functions
# =============================================================================


def create_mock_llm_response(response_dict):
    """Helper to create mock LLM response with JSON"""
    return json.dumps(response_dict)


@pytest.fixture
def json_response_helper():
    """Helper fixture for creating JSON responses"""
    return create_mock_llm_response

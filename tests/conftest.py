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
        'language': {
            'target_language': 'German',
            'target_language_code': 'de',
            'locale': 'de-DE',
            'learner_native_language': 'English',
            'spacy_model': 'de_core_news_sm',
            'glossary_heading': 'Vokabeln',
            'legacy_glossary_headings': ['Vokabeln'],
            'prompt_pack': 'german',
            'glossary_rules': 'german',
            'site_name': 'BriefBerlin',
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
        title='Deutschland baut mehr Windenergie aus',
        sources=['Tagesschau', 'RBB24', 'Zeit Online'],
        mentions=5,
        score=25.0,
        urls=['https://tagesschau.de/test', 'https://rbb24.de/test', 'https://zeit.de/test']
    )


@pytest.fixture
def sample_sources() -> List[SourceArticle]:
    """Sample source articles"""
    return [
        SourceArticle(
            source='Tagesschau',
            text='Deutschland hat im ersten Halbjahr mehr Strom aus Windenergie erzeugt. '
                 'Die Bundesregierung sieht darin einen wichtigen Schritt für die Energiewende. '
                 'Fachleute sagen, dass schnellere Genehmigungen den Ausbau unterstützen.',
            word_count=150,
            url='https://tagesschau.de/test'
        ),
        SourceArticle(
            source='RBB24',
            text='In Brandenburg entstehen neue Windräder, die auch Berlin mit sauberem Strom versorgen sollen. '
                 'Mehrere Gemeinden prüfen neue Flächen und sprechen mit Bürgerinnen und Bürgern. '
                 'Der Netzausbau bleibt eine wichtige Aufgabe.',
            word_count=140,
            url='https://rbb24.de/test'
        ),
        SourceArticle(
            source='Zeit Online',
            text='Energieexperten bewerten die neuen Zahlen positiv. '
                 'Deutschland kann mit mehr Windstrom unabhängiger von fossilen Brennstoffen werden. '
                 'Für Verbraucher bleiben stabile Preise ein zentrales Ziel.',
            word_count=120,
            url='https://zeit.de/test'
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
    """Sample base article - matches real ArticleSynthesizer output."""
    return BaseArticle(
        title='Deutschland baut mehr Windenergie aus',
        content='Deutschland hat im ersten Halbjahr deutlich mehr Strom aus Windenergie erzeugt. '
                'Nach Angaben der zuständigen Behörden helfen schnellere Genehmigungen und neue Flächen '
                'beim Ausbau. Besonders in Brandenburg entstehen zusätzliche Anlagen, die auch Berlin '
                'mit sauberem Strom versorgen sollen.\n\n'
                'Die Bundesregierung investiert in Netze, Speicher und Planungsverfahren. Gemeinden '
                'sprechen mit Bürgerinnen und Bürgern über neue Standorte. Fachleute sagen, dass der '
                'Ausbau wichtig ist, damit Deutschland unabhängiger von fossilen Brennstoffen wird.\n\n'
                'Energieexperten sehen in den aktuellen Zahlen einen Fortschritt für die Energiewende. '
                'Gleichzeitig warnen sie, dass Stromnetze schneller modernisiert werden müssen. Nur dann '
                'können Haushalte und Unternehmen zuverlässig von mehr erneuerbarer Energie profitieren.',
        summary='Deutschland erzeugt mehr Windstrom und will den Ausbau der Netze beschleunigen.',
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
        title='Deutschland baut mehr Windenergie aus',
        content='Deutschland baut mehr **Windenergie** aus. Neue Windräder produzieren Strom. '
                'Das hilft bei der **Energiewende**.\n\n'
                'Besonders in Brandenburg gibt es neue **Windräder**. Sie können auch Berlin mit Strom versorgen. '
                'Der Strom ist sauber.\n\n'
                'Fachleute sind zufrieden. Sie sagen, Deutschland ist auf einem guten Weg. '
                'Aber die Stromnetze müssen schneller besser werden.',
        vocabulary=[
            VocabularyItem(
                term='Windenergie',
                english='environment',
                explanation='Strom aus der Kraft des Windes',
            ),
            VocabularyItem(
                term='Energiewende',
                english='energy transition',
                explanation='Wechsel zu sauberer Energie',
            ),
            VocabularyItem(
                term='Windräder',
                english='wind turbines',
                explanation='große Anlagen, die mit Wind Strom machen',
            ),
        ],
        summary='Deutschland baut mehr Windräder und produziert mehr sauberen Strom.',
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
        title='Deutschland baut Windenergie für die Energiewende aus',
        content='Deutschland hat in diesem Jahr mehr **Windstrom** erzeugt. '
                'Das **Bundeswirtschaftsministerium** sieht darin einen wichtigen Erfolg. '
                'Neue Flächen und schnellere **Genehmigungen** erklären diese Entwicklung.\n\n'
                'Der Staat investiert Geld in Stromnetze und Speicher. '
                'Viele **Windparks** entstehen in Brandenburg und anderen Bundesländern. '
                'Dadurch wird die Energieversorgung **nachhaltiger**.\n\n'
                'Fachleute begrüßen den Ausbau. Sie halten ihn für wichtig gegen den **Klimawandel**. '
                'Sie warnen aber, dass Deutschland mehr Tempo beim **Netzausbau** braucht.',
        vocabulary=[
            VocabularyItem(
                term='Windstrom',
                english='wind power',
                explanation='Strom, der mit Wind erzeugt wird',
            ),
            VocabularyItem(
                term='Bundeswirtschaftsministerium',
                english='Federal Ministry for Economic Affairs',
                explanation='Ministerium der Bundesregierung für Wirtschaft und Energie',
            ),
            VocabularyItem(
                term='Genehmigungen',
                english='permits',
                explanation='offizielle Erlaubnisse für ein Projekt',
            ),
            VocabularyItem(
                term='Windparks',
                english='wind farms',
                explanation='Gebiete mit mehreren Windrädern',
            ),
            VocabularyItem(
                term='nachhaltiger',
                english='more sustainable',
                explanation='besser für Umwelt und Zukunft',
            ),
            VocabularyItem(
                term='Klimawandel',
                english='climate change',
                explanation='langfristige Veränderung des Klimas',
            ),
            VocabularyItem(
                term='Netzausbau',
                english='grid expansion',
                explanation='Ausbau der Leitungen für Strom',
            ),
        ],
        summary='Deutschland erzeugt mehr Windstrom und muss die Stromnetze weiter ausbauen.',
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
        title='Deutschland baut mehr Windenergie aus',
        content='Deutschland baut mehr Windenergie aus. Neue Windräder produzieren Strom.\n\n'
                'Besonders in Brandenburg entstehen neue Anlagen. Sie können auch Berlin helfen.\n\n'
                'Fachleute sind zufrieden. Sie sagen, die Energiewende kommt voran.',
        vocabulary=[],
        summary='Deutschland baut mehr Windräder und produziert mehr sauberen Strom.',
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
        title='Deutschland baut Windenergie für die Energiewende aus',
        content='Deutschland hat in diesem Jahr mehr Windstrom erzeugt.\n\n'
                'Das Bundeswirtschaftsministerium bewertet die neuen Zahlen positiv und erklärt, dass '
                'schnellere Genehmigungen beim Ausbau helfen.\n\n'
                'Fachleute halten den Fortschritt für wichtig gegen den Klimawandel.',
        vocabulary=[],
        summary='Deutschland erzeugt mehr Windstrom und muss die Stromnetze weiter ausbauen.',
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

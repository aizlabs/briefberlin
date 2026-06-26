"""
Pydantic models for type-safe data structures.

These models ensure data integrity throughout the pipeline and provide
automatic validation, serialization, and clear type hints.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scripts.text_utils import normalize_vocabulary_term

# =============================================================================
# Topic Discovery Models
# =============================================================================


class Topic(BaseModel):
    """Topic from discovery phase"""
    title: str = Field(..., min_length=1, description="Topic title")
    sources: List[str] = Field(..., min_length=1, description="Source names")
    mentions: int = Field(..., ge=1, description="Number of mentions across sources")
    score: float = Field(..., ge=0, description="Ranking score")
    keywords: Optional[List[str]] = Field(default=None, description="Optional keywords")
    urls: List[str] = Field(default_factory=list, description="URLs for fetching article content")

    model_config = ConfigDict(frozen=False)  # Allow mutation during pipeline


class SourceArticle(BaseModel):
    """Fetched source article"""
    source: str = Field(..., min_length=1, description="Source name (e.g., 'El País')")
    text: str = Field(..., min_length=50, description="Article text content")
    word_count: int = Field(..., ge=0, description="Word count")
    url: Optional[str] = Field(default=None, description="Optional source URL")

    model_config = ConfigDict(frozen=False)


class SourceMetadata(BaseModel):
    """Structured source metadata for articles"""

    name: str = Field(..., min_length=1, description="Source name")
    url: Optional[str] = Field(default=None, description="Optional source URL")

    model_config = ConfigDict(frozen=False)


# =============================================================================
# Article Models
# =============================================================================


class BaseArticle(BaseModel):
    """Native-level German article from ArticleSynthesizer (Step 1)"""
    title: str = Field(..., min_length=1, max_length=200, description="Article title")
    content: str = Field(..., min_length=100, description="Full article content")
    summary: str = Field(..., min_length=10, max_length=500, description="One-sentence summary")
    reading_time: int = Field(..., ge=1, le=30, description="Estimated reading time in minutes")

    # Metadata from synthesis
    topic: Optional[Topic] = Field(default=None, description="Source topic")
    sources: List[SourceMetadata] = Field(default_factory=list, description="Source metadata used")

    @field_validator('reading_time', mode='before')
    @classmethod
    def coerce_reading_time(cls, v):
        """Convert string to int if needed"""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return 3  # Default fallback
        return v

    @field_validator('sources', mode='before')
    @classmethod
    def coerce_sources(cls, v):
        """Normalize legacy or mixed source inputs into structured metadata.

        Accepts older payloads (e.g., list of strings) and mixed dicts from
        serialized `SourceArticle` data, and coerces them into `{name, url}`
        mappings so Pydantic can build `SourceMetadata` consistently.
        """
        if v is None:
            return []

        def to_metadata(item: Union[str, Dict, 'SourceMetadata']):
            if isinstance(item, str):
                return {'name': item}
            if isinstance(item, dict) and 'source' in item and 'text' in item:
                # Handle accidental SourceArticle dicts
                name = item.get('source') or item.get('name')
                url = item.get('url')
                return {'name': name, 'url': url}
            if isinstance(item, dict):
                return item
            return item

        if isinstance(v, list):
            return [to_metadata(item) for item in v]

        return v

    model_config = ConfigDict(frozen=False)


class VocabularyItem(BaseModel):
    """Single vocabulary glossary item."""

    term: str = Field(..., min_length=1, description="German term from the article")
    english: str = Field(default="", description="English translation")
    explanation: str = Field(default="", description="German learner-facing explanation")

    @field_validator("term", "english", "explanation", mode="before")
    @classmethod
    def coerce_string_fields(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()


def split_legacy_gloss(gloss: str) -> tuple[str, str]:
    """Split legacy 'english - explanation' strings into structured fields."""
    cleaned = str(gloss).strip()
    if not cleaned:
        return "", ""
    if " - " not in cleaned:
        return cleaned, ""

    english, explanation = cleaned.split(" - ", 1)
    return english.strip(), explanation.strip()


def coerce_vocabulary_items(value: Any) -> List["VocabularyItem"]:
    """Coerce legacy and structured vocabulary payloads into VocabularyItem objects."""
    if value is None:
        return []

    if isinstance(value, dict):
        iterable: Any = [
            {"term": term, "gloss": gloss}
            for term, gloss in value.items()
        ]
    elif isinstance(value, list):
        iterable = value
    else:
        return []

    items: List[VocabularyItem] = []
    for raw_item in iterable:
        if isinstance(raw_item, VocabularyItem):
            items.append(raw_item)
            continue

        if not isinstance(raw_item, dict):
            continue

        term = raw_item.get("term")
        if not term:
            continue

        normalized_term = normalize_vocabulary_term(str(term))
        if not normalized_term:
            continue

        english = str(raw_item.get("english") or "").strip()
        explanation = str(raw_item.get("explanation") or "").strip()

        # Prefer explicit structured fields when present. Fall back to legacy `gloss`
        # only when the item does not already carry usable structured values.
        if not english and not explanation and "gloss" in raw_item:
            english, explanation = split_legacy_gloss(str(raw_item.get("gloss") or ""))

        items.append(
            VocabularyItem(
                term=normalized_term,
                english=english,
                explanation=explanation,
            )
        )

    return items


class SpeechScript(BaseModel):
    """Provider-neutral narration payload derived from an article."""

    title: str = Field(..., min_length=1, description="Spoken title for the article")
    sections: List[str] = Field(default_factory=list, description="Ordered narration blocks")
    narration: str = Field(..., min_length=1, description="Flattened narration text")
    includes_vocabulary: bool = Field(default=False, description="Whether glossary terms are narrated")


class AudioAsset(BaseModel):
    """Audio metadata for website and future multi-channel delivery."""

    url: Optional[str] = Field(default=None, description="Public audio URL")
    storage_key: Optional[str] = Field(default=None, description="Canonical object key in media storage")
    provider: Optional[str] = Field(default=None, description="TTS provider identifier")
    voice: Optional[str] = Field(default=None, description="Selected voice identifier")
    format: str = Field(default="mp3", pattern="^(mp3|m4a|wav)$", description="Container format")
    mime_type: Optional[str] = Field(default=None, description="MIME type for playback")
    local_script_path: Optional[str] = Field(default=None, description="Local narration script path")
    local_audio_path: Optional[str] = Field(default=None, description="Local synthesized audio path")
    manifest_path: Optional[str] = Field(default=None, description="Local audio manifest path")
    duration_seconds: Optional[float] = Field(default=None, ge=0, description="Audio duration")


class AudioManifest(BaseModel):
    """Local manifest describing the audio preparation state for an article."""

    article_slug: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    level: str = Field(..., pattern="^(A2|B1)$")
    created_at: str = Field(..., min_length=1, description="ISO timestamp")
    status: str = Field(default="pending", pattern="^(pending|ready)$")
    script: SpeechScript
    asset: AudioAsset


class AdaptedArticle(BaseModel):
    """Level-adapted article from LevelAdapter (Step 2)"""
    title: str = Field(..., min_length=1, max_length=150, description="Adapted title")
    content: str = Field(..., min_length=50, description="Level-adapted content")
    summary: str = Field(..., min_length=10, max_length=500, description="Level-adapted summary")
    reading_time: int = Field(..., ge=1, le=30, description="Reading time in minutes")

    # Vocabulary glossary, generated after text validation.
    vocabulary: List[VocabularyItem] = Field(
        default_factory=list,
        description="Structured glossary entries for the approved article",
    )

    # Level and metadata
    level: str = Field(..., pattern="^(A2|B1)$", description="CEFR level")
    topic: Optional[Topic] = Field(default=None, description="Source topic")
    sources: List[SourceMetadata] = Field(default_factory=list, description="Source metadata")

    # Base article stored for regeneration
    base_article: Optional[BaseArticle] = Field(default=None, description="Base article for regeneration")
    audio: Optional[AudioAsset] = Field(default=None, description="Audio metadata for delivery surfaces")

    @field_validator('reading_time', mode='before')
    @classmethod
    def coerce_reading_time(cls, v):
        """Convert string to int if needed"""
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                # Default based on level if available
                return 2  # Fallback
        return v

    @field_validator('sources', mode='before')
    @classmethod
    def coerce_sources(cls, v):
        """Normalize legacy or mixed source inputs into structured metadata.

        Accepts older payloads (e.g., list of strings) and mixed dicts from
        serialized `SourceArticle` data, and coerces them into `{name, url}`
        mappings so Pydantic can build `SourceMetadata` consistently.
        """
        if v is None:
            return []

        def to_metadata(item: Union[str, Dict, 'SourceMetadata']):
            if isinstance(item, str):
                return {'name': item}
            if isinstance(item, dict) and 'source' in item and 'text' in item:
                name = item.get('source') or item.get('name')
                url = item.get('url')
                return {'name': name, 'url': url}
            if isinstance(item, dict):
                return item
            return item

        if isinstance(v, list):
            return [to_metadata(item) for item in v]

        return v

    @field_validator("vocabulary", mode="before")
    @classmethod
    def coerce_vocabulary(cls, v):
        return coerce_vocabulary_items(v)

    model_config = ConfigDict(frozen=False)


# =============================================================================
# Quality Gate Models
# =============================================================================


class QualityResult(BaseModel):
    """Result from quality evaluation"""
    passed: bool = Field(..., description="Whether article passed quality gate")
    score: float = Field(..., ge=0, le=10, description="Overall quality score (0-10)")
    issues: List[str] = Field(default_factory=list, description="Issues found")
    strengths: List[str] = Field(default_factory=list, description="Article strengths")
    attempts: int = Field(..., ge=1, description="Number of generation attempts")

    # Detailed scores (optional)
    grammar_score: Optional[float] = Field(default=None, ge=0, le=4)
    educational_score: Optional[float] = Field(default=None, ge=0, le=3)
    content_score: Optional[float] = Field(default=None, ge=0, le=2)
    level_score: Optional[float] = Field(default=None, ge=0, le=1)

    model_config = ConfigDict(frozen=False)


# =============================================================================
# Configuration Models
# =============================================================================


class TwoStepSynthesisConfig(BaseModel):
    """Configuration for two-step synthesis"""
    enabled: bool = Field(default=True, description="Enable two-step synthesis")
    save_base_article: bool = Field(default=False, description="Save base articles to disk")
    base_article_path: str = Field(default="./output/base_articles/", description="Path for base articles")
    regeneration_strategy: str = Field(
        default="adaptation_only",
        pattern="^(adaptation_only|full_pipeline)$",
        description="Regeneration strategy"
    )


class LLMModelsConfig(BaseModel):
    """LLM model configuration"""
    generation: str = Field(..., description="Model for synthesis (Step 1)")
    adaptation: str = Field(..., description="Model for adaptation (Step 2)")
    quality_check: str = Field(..., description="Model for quality evaluation")


class LLMConfig(BaseModel):
    """LLM configuration"""
    provider: str = Field(
        ...,
        # Allow additional providers in the future (e.g., mistral, qwen)
        description="LLM provider identifier (e.g., openai, anthropic)"
    )
    models: LLMModelsConfig
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    anthropic_api_key: Optional[str] = Field(default=None, description="Anthropic API key")
    temperature: float = Field(default=0.3, ge=0, le=1, description="Temperature for generation")
    quality_temperature: float = Field(
        default=0.1, ge=0, le=1, description="Temperature for quality checks"
    )
    max_tokens: int = Field(default=4096, ge=100, le=100000, description="Max tokens")


class SMTPConfig(BaseModel):
    """SMTP settings for sending email alerts."""

    host: str = Field(default="smtp.gmail.com", description="SMTP host for outbound mail")
    port: int = Field(default=587, ge=1, description="SMTP port")
    username: Optional[str] = Field(default=None, description="SMTP username (if required)")
    password: Optional[str] = Field(default=None, description="SMTP password (if required)")


class EmailConfig(BaseModel):
    """Email alert configuration."""

    model_config = ConfigDict(populate_by_name=True)

    from_email: str = Field(
        default="bot@briefberlin.de",
        alias="from",
        description="Sender address used for alerts",
    )
    smtp: SMTPConfig = Field(default_factory=SMTPConfig)


class TelegramConfig(BaseModel):
    """Telegram alert configuration."""

    enabled: bool = False
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


class AlertsConfig(BaseModel):
    """Alert delivery configuration."""

    enabled: bool = False
    email: Optional[str] = Field(default=None, description="Recipient email for alerts")
    email_config: Optional[EmailConfig] = None
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    cooldown_hours: int = Field(default=6, ge=0, description="Hours to suppress duplicate alerts")


class AudioStorageConfig(BaseModel):
    """Cloud storage configuration for generated audio assets."""

    bucket: Optional[str] = Field(default=None, description="S3 bucket for canonical audio storage")
    region: Optional[str] = Field(default=None, description="AWS region for uploads")
    prefix: str = Field(default="articles", description="Key prefix inside the bucket")


class AudioWebsiteConfig(BaseModel):
    """Website playback feature flags."""

    enabled: bool = Field(default=True, description="Render website audio player when audio exists")


class AudioConfig(BaseModel):
    """Configuration for TTS preparation and future upload/delivery."""

    enabled: bool = Field(default=False, description="Enable audio preparation for approved articles")
    provider: Optional[str] = Field(default=None, description="TTS provider identifier")
    voice: Optional[str] = Field(default=None, description="Voice identifier")
    format: str = Field(default="mp3", pattern="^(mp3|m4a|wav)$", description="Primary output format")
    output_path: str = Field(default="./output/audio", description="Local working directory for audio files")
    include_vocabulary: bool = Field(
        default=False,
        description="Whether narrated scripts should include glossary terms",
    )
    upload_enabled: bool = Field(
        default=False,
        description="Enable object-storage uploads once the AWS side is provisioned",
    )
    public_base_url: Optional[str] = Field(
        default=None,
        description="Public CDN base URL",
    )
    s3: AudioStorageConfig = Field(default_factory=AudioStorageConfig)
    website: AudioWebsiteConfig = Field(default_factory=AudioWebsiteConfig)


class GlossaryConfig(BaseModel):
    """Configuration for post-validation glossary generation."""

    retry_on_empty: bool = Field(
        default=True,
        description="Retry glossary generation once when all initial candidates are rejected",
    )
    debug_dump: bool = Field(
        default=False,
        description="Write glossary candidate/validation artifacts to disk for investigation",
    )


# =============================================================================
# Helper Functions
# =============================================================================


def dict_to_topic(data: Dict) -> Topic:
    """Convert dict to Topic model with validation"""
    return Topic(**data)


def dict_to_base_article(data: Dict) -> BaseArticle:
    """Convert dict to BaseArticle model with validation"""
    # Convert nested topic if present
    if 'topic' in data and isinstance(data['topic'], dict):
        data['topic'] = Topic(**data['topic'])
    return BaseArticle(**data)


def dict_to_adapted_article(data: Dict) -> AdaptedArticle:
    """Convert dict to AdaptedArticle model with validation"""
    # Convert nested structures
    if 'topic' in data and data['topic'] and isinstance(data['topic'], dict):
        data['topic'] = Topic(**data['topic'])
    if 'base_article' in data and data['base_article'] and isinstance(data['base_article'], dict):
        data['base_article'] = BaseArticle(**data['base_article'])
    if 'audio' in data and data['audio'] and isinstance(data['audio'], dict):
        data['audio'] = AudioAsset(**data['audio'])
    return AdaptedArticle(**data)

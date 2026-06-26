"""
Publisher Component

Saves approved articles as Jekyll markdown files with YAML frontmatter.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from scripts.config import AppConfig
from scripts.models import AdaptedArticle, coerce_vocabulary_items
from scripts.text_utils import normalize_vocabulary_term, slugify_text
from scripts.topic_utils import is_noisy_topic_keyword


class Publisher:
    """Publishes articles to Jekyll format"""

    def __init__(self, config: AppConfig, logger: logging.Logger, dry_run: bool = False):
        self.config = config
        self.logger = logger.getChild('Publisher')
        self.dry_run = dry_run

        # Output directory
        self.output_dir = Path(config.output['path'])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.source_url_map = self._build_source_url_map()

        self.logger.info(f"Publisher initialized (dry_run={dry_run}, output={self.output_dir})")

    def save_article(self, article: AdaptedArticle) -> bool:
        """
        Save article as Jekyll markdown file

        Args:
            article: Article dict with all fields

        Returns:
            True if saved successfully
        """
        try:
            # Generate timestamp once for consistency between filename and frontmatter
            timestamp = datetime.now()

            # Generate filename
            filename = self._generate_filename(article, timestamp)
            filepath = self.output_dir / filename

            # Generate markdown content
            markdown = self._generate_markdown(article, timestamp)

            if self.dry_run:
                self.logger.info(f"[DRY RUN] Would save: {filename}")
                self.logger.debug(f"Content preview:\n{markdown[:200]}...")
                return True

            # Write file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(markdown)

            self.logger.info(f"✅ Saved: {filename}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to save article: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return False

    def _generate_filename(self, article: AdaptedArticle, timestamp: datetime) -> str:
        """
        Generate Jekyll filename

        Format: YYYY-MM-DD-HHMMSS-title-slug-level.md
        Includes timestamp to prevent collisions when multiple articles
        with similar titles are generated on the same day.

        Args:
            article: Article dict with title and level
            timestamp: datetime object for consistent timestamping
        """
        timestamp_str = timestamp.strftime("%Y-%m-%d-%H%M%S")

        # Create slug from title
        title = article.title
        slug = slugify_text(title)[:50]  # Max 50 chars

        level = article.level.lower()

        return f"{timestamp_str}-{slug}-{level}.md"

    def _escape_yaml_string(self, text: str) -> str:
        """
        Escape a string for safe use in YAML double-quoted strings

        Args:
            text: String to escape

        Returns:
            Escaped string safe for YAML
        """
        # Escape backslashes first
        text = text.replace('\\', '\\\\')
        # Escape double quotes
        text = text.replace('"', '\\"')
        return text

    def _build_source_url_map(self) -> Dict[str, str]:
        """Create lookup map of normalized source names to URLs from config."""
        source_map: Dict[str, str] = {}

        for source in self.config.sources_list:
            name = source.get('name') if isinstance(source, dict) else None
            url = source.get('url') if isinstance(source, dict) else None

            if not name or not url:
                continue

            normalized_name = self._normalize_source_key(name)
            normalized_url = self._normalize_url(url, include_path=True)

            if normalized_name and normalized_url:
                source_map[normalized_name] = normalized_url
                host_key = self._normalize_host_key(normalized_url)
                if host_key:
                    source_map.setdefault(host_key, normalized_url)

        return source_map

    def _normalize_url(self, url: str, include_path: bool) -> Optional[str]:
        """Normalize URL, inferring scheme when missing."""
        if not url:
            return None

        cleaned_url = url.strip()
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', cleaned_url):
            cleaned_url = f"https://{cleaned_url}"

        parsed = urlparse(cleaned_url)
        if not parsed.scheme:
            return None

        host = parsed.netloc or parsed.path
        if not host:
            return None

        path = parsed.path.rstrip('/') if include_path else ""

        normalized = f"{parsed.scheme}://{host}"
        if include_path and path:
            normalized = f"{normalized}{path}"

        return normalized

    def _normalize_host_key(self, url: str) -> Optional[str]:
        """Normalize a URL string into a host-only lookup key."""
        parsed = urlparse(url)
        host = parsed.netloc or parsed.path
        if not host:
            return None
        return host.casefold()

    def _normalize_source_key(self, source: str) -> str:
        """Normalize source identifier for consistent de-duplication."""
        cleaned = source.strip().rstrip('/')

        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', cleaned):
            parsed = urlparse(cleaned)
            host = parsed.netloc or parsed.path
            path = parsed.path.rstrip('/')
            return f"{host}{path}".casefold()

        return cleaned.casefold()

    def _resolve_source_url(self, source: str) -> Optional[str]:
        """Resolve source to a best-effort URL if available."""
        if not source:
            return None

        cleaned_source = source.strip()

        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', cleaned_source):
            return self._normalize_url(cleaned_source, include_path=True)

        if re.match(r'^[\w.-]+\.[a-zA-Z]{2,}(/.*)?$', cleaned_source):
            return self._normalize_url(f"https://{cleaned_source}", include_path=True)

        normalized_key = self._normalize_source_key(cleaned_source)
        return self.source_url_map.get(normalized_key)

    def _normalize_sources(self, sources: List[str]) -> List[Tuple[str, Optional[str]]]:
        """Return ordered, de-duplicated list of (source, url?) tuples."""
        normalized_sources: List[Tuple[str, Optional[str]]] = []
        seen_keys = set()

        for source in sources:
            if not source:
                continue

            cleaned_source = source.strip()
            if not cleaned_source:
                continue

            key = self._normalize_source_key(cleaned_source)
            if not key:
                continue

            if key in seen_keys:
                continue

            seen_keys.add(key)
            normalized_sources.append((cleaned_source, self._resolve_source_url(cleaned_source)))

        return normalized_sources

    def _render_source(self, source: str, url: Optional[str]) -> str:
        """Render a source as markdown link when URL is available."""
        if url:
            escaped_source = self._escape_markdown_link_text(source)
            return f"[{escaped_source}]({url})"
        return source

    def _escape_markdown_link_text(self, text: str) -> str:
        """Escape markdown link text to prevent malformed links."""
        escaped = text.replace('\\', '\\\\')
        for char in ['[', ']', '(', ')']:
            escaped = escaped.replace(char, f"\\{char}")
        return escaped

    def _generate_markdown(self, article: AdaptedArticle, timestamp: datetime) -> str:
        """
        Generate Jekyll markdown with frontmatter

        Args:
            article: Article dict with all content
            timestamp: datetime object for consistent timestamping
        """

        # Escape title for YAML
        escaped_title = self._escape_yaml_string(article.title)

        # YAML frontmatter
        # Use Jekyll-compatible date format (without microseconds)
        date_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        frontmatter = f"""---
title: "{escaped_title}"
date: {date_str}
level: {article.level}
topics: {self._format_topics(article)}
{self._format_sources(article.sources)}
{self._format_audio(article)}
reading_time: {article.reading_time}
---

"""

        # Article content
        content = article.content

        # Vocabulary section
        vocabulary = self._format_vocabulary(article.vocabulary, article.title)

        # Attribution
        attribution = self._format_attribution(article.sources)

        # Combine all parts
        markdown = frontmatter + content + vocabulary + attribution

        return markdown

    def _format_topics(self, article: AdaptedArticle) -> str:
        """Extract and format topics from article as valid YAML"""
        import json

        # Try to infer topics from article topic data
        # Use 'or []' to handle None keywords (model default)
        topic_data = article.topic
        raw_keywords = (topic_data.keywords or []) if topic_data else []
        filtered_keywords = [k for k in raw_keywords if not is_noisy_topic_keyword(k)]

        if filtered_keywords:
            # Take first 3 keywords, lowercased
            topics = [k.lower() for k in filtered_keywords[:3]]
            # Use JSON serialization for proper YAML compatibility
            # This handles apostrophes, quotes, and special characters correctly
            return json.dumps(topics)

        # Fallback: generic topic
        return '["general"]'

    def _format_vocabulary(self, vocabulary, article_title: str) -> str:
        """Format vocabulary section"""
        items = coerce_vocabulary_items(vocabulary)
        if not items:
            return ""

        rendered_lines = []

        for item in items:
            normalized_term = normalize_vocabulary_term(item.term)
            if not normalized_term:
                continue
            if normalized_term != item.term:
                self.logger.warning(
                    "Normalized vocabulary term during publish for article '%s': '%s' -> '%s'",
                    article_title,
                    item.term,
                    normalized_term,
                )

            definition_parts = [part for part in (item.english, item.explanation) if part]
            definition = " - ".join(definition_parts)
            if not definition:
                self.logger.warning(
                    "Skipping vocabulary term without definition during publish for article '%s': '%s'",
                    article_title,
                    normalized_term,
                )
                continue
            rendered_lines.append(f"- **{normalized_term}** - {definition}")

        if not rendered_lines:
            return ""

        vocab_lines = ["", "## Vokabeln", "", *rendered_lines]
        return '\n'.join(vocab_lines)

    def _deduplicate_sources(self, sources) -> List[Any]:
        """Deduplicate sources using normalized keys, preserving order and first occurrence."""
        if not sources:
            return []

        def get_name_and_url(source):
            if hasattr(source, 'name'):
                return source.name, getattr(source, 'url', None)
            if isinstance(source, dict):
                return source.get('name') or source.get('source', ''), source.get('url')
            return str(source), None

        seen_keys = set()
        deduplicated = []

        for source in sources:
            name, url = get_name_and_url(source)
            if not name or not name.strip():
                continue

            # Use normalized key for deduplication (same logic as old _normalize_sources)
            key = self._normalize_source_key(name)
            if not key or key in seen_keys:
                continue

            seen_keys.add(key)
            deduplicated.append(source)

        return deduplicated

    def _format_sources(self, sources) -> str:
        """Suppress private/manual source metadata in public frontmatter."""
        return 'sources: []'

    def _format_audio(self, article: AdaptedArticle) -> str:
        """Format website audio metadata for YAML frontmatter."""
        if not self.config.audio.website.enabled:
            return 'audio: null'

        audio = article.audio
        if not audio or not audio.url:
            return 'audio: null'

        lines = ['audio:']
        lines.append(f'  url: "{self._escape_yaml_string(audio.url)}"')
        if audio.format:
            lines.append(f'  format: "{self._escape_yaml_string(audio.format)}"')
        if audio.mime_type:
            lines.append(f'  mime_type: "{self._escape_yaml_string(audio.mime_type)}"')
        if audio.provider:
            lines.append(f'  provider: "{self._escape_yaml_string(audio.provider)}"')
        if audio.voice:
            lines.append(f'  voice: "{self._escape_yaml_string(audio.voice)}"')
        if audio.duration_seconds is not None:
            lines.append(f'  duration_seconds: {audio.duration_seconds}')
        return '\n'.join(lines)

    def _format_attribution(self, sources) -> str:
        """Return a public-safe footer without private/manual source details."""
        return """

---
*Vereinfachter Artikel zu Lernzwecken.*
"""

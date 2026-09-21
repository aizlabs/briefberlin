"""
Publisher Component

Saves approved articles as Jekyll markdown files with YAML frontmatter.
"""

import json
import logging
import re
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from scripts.config import AppConfig
from scripts.models import (
    AdaptedArticle,
    ArticleTranslation,
    VocabularyItem,
    coerce_vocabulary_items,
)
from scripts.text_utils import normalize_vocabulary_term, slugify_text
from scripts.topic_utils import sanitize_topic_keywords
from scripts.translation_hints import hint_id, publishable_translation_hints


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

        # Reader-language translations live in their own Jekyll collection, NOT in
        # _posts: collection documents are structurally absent from site.posts, so
        # they cannot leak into pagination, jekyll-feed, the Telegram broadcaster,
        # the SEO backfill glob or the audio post-processor.
        self.translations_dir: Optional[Path] = None
        if config.translations.enabled:
            self.translations_dir = Path(config.translations.output_path)
            self.translations_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Publisher initialized (dry_run={dry_run}, output={self.output_dir})")

    def save_article(self, article: AdaptedArticle, timestamp: Optional[datetime] = None) -> bool:
        """
        Save article as Jekyll markdown file

        Args:
            article: Article dict with all fields

        Returns:
            True if saved successfully
        """
        try:
            # Generate timestamp once for consistency between filename and frontmatter.
            timestamp = timestamp or datetime.now()

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

            # A translation write failure must NOT flip this return value: False
            # here triggers alert_manager.send_error("Publishing failed") upstream,
            # even though the German article was written successfully.
            try:
                self.save_translations(article, timestamp)
            except Exception as exc:
                self.logger.error(f"Failed to save translations for {filename}: {exc}")

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
        return f"{timestamp.strftime('%Y-%m-%d')}-{self._post_ref(article, timestamp)}.md"

    @staticmethod
    def _jekyll_slugify(value: str) -> str:
        """Reproduce Jekyll's default slugify, which derives a post's `:title`.

        Jekyll collapses each run of non-alphanumeric characters into a single
        hyphen. That matters: `slugify_text(title)[:50]` can end on a hyphen, and
        appending `-b1` then yields `...unter--b1` in the FILENAME while Jekyll
        publishes `...unter-b1` in the URL. Deriving the ref with the same rule is
        what keeps every translation URL and back-link from 404ing.
        """
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    def _post_ref(self, article: AdaptedArticle, timestamp: datetime) -> str:
        """The post's Jekyll `:title` - its filename stem minus the date prefix.

        This is the shared key between the German post's URL
        (/articles/<ref>/) and its translations (/articles/<ref>/<lang>/).
        """
        slug = slugify_text(article.title)[:50]
        stem = f"{timestamp.strftime('%H%M%S')}-{slug}-{article.level.lower()}"
        return self._jekyll_slugify(stem)

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
        author = str(
            article.author or self.config.output.get("default_author") or ""
        ).strip()
        author_frontmatter = (
            f'author: "{self._escape_yaml_string(author)}"\n'
            if author
            else ""
        )

        category = (
            getattr(article, "category", None)
            or (getattr(article.topic, "category", None) if article.topic else None)
            or "Nachrichten"
        )
        description = (
            getattr(article, "description", None)
            or (getattr(article.topic, "description", None) if article.topic else None)
            or getattr(article, "summary", "")
        )
        description_frontmatter = (
            f'description: "{self._escape_yaml_string(description)}"\n'
            if description
            else ""
        )
        keywords_json = self._format_topics(article)

        frontmatter = f"""---
title: "{escaped_title}"
date: {date_str}
{author_frontmatter}level: {article.level}
category: "{self._escape_yaml_string(category)}"
summary: "{self._escape_yaml_string(article.summary)}"
{description_frontmatter}topics: {keywords_json}
keywords: {keywords_json}
{self._format_sources(article.sources)}
{self._format_audio(article)}
reading_time: {article.reading_time}
{self._format_translations_map(article, self._post_ref(article, timestamp))}---

"""

        translation_hints = self._translation_hints_for_publish(article)

        # Article content
        content = self._render_content_with_translation_hints(article.content, translation_hints)

        # Vocabulary section
        vocabulary = self._format_vocabulary(article.vocabulary, article.title)
        translation_hint_data = self._format_translation_hints_data(translation_hints)

        # Attribution
        attribution = self._format_attribution(article.sources)

        # Keep the first body block textual so Jekyll-derived excerpts remain useful.
        content_with_hint_data = (
            f"{content}\n\n{translation_hint_data}"
            if translation_hint_data
            else content
        )

        # Combine all parts
        markdown = frontmatter + content_with_hint_data + vocabulary + attribution

        return markdown

    def _format_topics(self, article: AdaptedArticle) -> str:
        """Extract and format topics from article as valid YAML"""
        import json

        # Try to infer topics from article topic data
        # Use 'or []' to handle None keywords (model default)
        topic_data = article.topic
        raw_keywords = (topic_data.keywords or []) if topic_data else []
        filtered_keywords = sanitize_topic_keywords(
            [str(keyword) for keyword in raw_keywords],
            max_keywords=7,
            lowercase=False,
        )

        if filtered_keywords:
            # Use JSON serialization for proper YAML compatibility
            # This handles apostrophes, quotes, and special characters correctly
            return json.dumps(filtered_keywords)

        return '[]'


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

        vocab_lines = ["", f"## {self.config.language.glossary_heading}", "", *rendered_lines]
        return '\n'.join(vocab_lines)

    def _translation_hints_for_publish(self, article: AdaptedArticle) -> List[VocabularyItem]:
        """Return the broad clickable hint set, falling back to visible vocabulary.

        Delegates to scripts.translation_hints so the translator numbers terms
        identically - see that module's docstring.
        """
        return publishable_translation_hints(article)

    def _format_translation_hints_data(self, translation_hints: List[VocabularyItem]) -> str:
        """Embed precomputed translation hints as static JSON for article JavaScript."""
        if not translation_hints:
            return ""

        payload = [
            {
                "id": self._translation_hint_id(index),
                "term": item.term,
                "english": item.english,
                "explanation": item.explanation,
                "defaultGlossary": item.default_glossary,
            }
            for index, item in enumerate(translation_hints)
        ]
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
        glossary_heading = html_escape(self.config.language.glossary_heading, quote=True)
        glossary_locale = html_escape(self.config.language.locale, quote=True)
        return (
            '<script type="application/json" class="article-glossary-data" '
            f'data-glossary-heading="{glossary_heading}" '
            f'data-glossary-locale="{glossary_locale}">'
            f"{encoded}"
            "</script>\n\n"
        )

    # -- reader-language translations --------------------------------------

    def save_translations(self, article: AdaptedArticle, timestamp: datetime) -> List[str]:
        """Write one Jekyll document per completed translation.

        Path is ``<output>/<ref>/<lang>.md``, where ``ref`` is the German post's
        Jekyll `:title`. With the collection permalink ``/articles/:path/`` that
        yields ``/articles/<ref>/<lang>/`` by construction, so no ``permalink:``
        key is written and the URL has exactly one source of truth.

        Filenames are NEVER derived from the translated title: slugify_text is
        ASCII-only, so every Arabic/Russian/Ukrainian title collapses to "" and
        the files would collide.
        """
        if not article.translations or self.translations_dir is None:
            return []

        ref = self._post_ref(article, timestamp)
        target_dir = self.translations_dir / ref
        written: List[str] = []

        if self.dry_run:
            self.logger.info(
                "[DRY RUN] Would save %d translations under %s",
                len(article.translations),
                target_dir,
            )
            return []

        target_dir.mkdir(parents=True, exist_ok=True)
        for translation in article.translations:
            path = target_dir / f"{translation.lang}.md"
            path.write_text(
                self._generate_translation_markdown(article, translation, timestamp, ref),
                encoding="utf-8",
            )
            written.append(str(path))

        self.logger.info("✅ Saved %d translations: %s", len(written), ref)
        return written

    def _translations_map(self, article: AdaptedArticle, ref: str) -> Dict[str, str]:
        """Bare language code -> root-relative URL.

        Includes ``de`` AND every translated language, and is written IDENTICALLY
        into the German post and all of its translations. That is what makes the
        rendered hreflang set self-referential and reciprocal with no branching
        in the templates.
        """
        urls = {"de": f"/articles/{ref}/"}
        for translation in article.translations:
            urls[translation.lang] = f"/articles/{ref}/{translation.lang}/"
        return urls

    def _format_translations_map(self, article: AdaptedArticle, ref: str) -> str:
        """YAML block for the frontmatter, or "" when nothing was translated."""
        if not article.translations:
            return ""
        lines = ["translations:"]
        lines.extend(
            f"  {code}: {url}" for code, url in self._translations_map(article, ref).items()
        )
        return "\n".join(lines) + "\n"

    def _format_translated_vocabulary(self, translation: ArticleTranslation) -> str:
        """Static glossary list for a translated page.

        The German headword is wrapped in ``lang="de" dir="ltr"`` so it stays
        readable inside a right-to-left page.

        No JSON payload and no clickable spans: the translated body contains no
        German words for them to attach to.
        """
        rows = []
        for item in translation.vocabulary:
            definition = " - ".join(p for p in (item.translation, item.explanation) if p)
            if not definition:
                continue
            rows.append(
                f'- <strong lang="de" dir="ltr">{item.term}</strong> - {definition}'
            )
        if not rows:
            return ""
        return "\n".join(["", f"## {translation.glossary_heading}", "", *rows]) + "\n"

    def _generate_translation_markdown(
        self,
        article: AdaptedArticle,
        translation: ArticleTranslation,
        timestamp: datetime,
        ref: str,
    ) -> str:
        esc = self._escape_yaml_string
        category = (
            getattr(article, "category", None)
            or (getattr(article.topic, "category", None) if article.topic else None)
            or "Nachrichten"
        )
        author = str(
            article.author or self.config.output.get("default_author") or ""
        ).strip()
        author_line = f'author: "{esc(author)}"\n' if author else ""
        summary_line = f'summary: "{esc(translation.summary)}"\n' if translation.summary else ""
        description = translation.summary or translation.title

        frontmatter = (
            "---\n"
            f"lang: {translation.lang}\n"
            f"ref: {ref}\n"
            f'title: "{esc(translation.title)}"\n'
            f"date: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{author_line}"
            f"level: {article.level}\n"
            f'category: "{esc(category)}"\n'
            f"{summary_line}"
            f'description: "{esc(description)}"\n'
            f'source_title: "{esc(article.title)}"\n'
            f"reading_time: {translation.reading_time}\n"
            f'glossary_heading: "{esc(translation.glossary_heading)}"\n'
            # Audio is deliberately the GERMAN track: the reader listens in German
            # while reading their own language.
            f"{self._format_audio(article)}\n"
            f"{self._format_translations_map(article, ref)}"
            "---\n\n"
        )

        # NOTE: never _render_content_with_translation_hints here. It scans for
        # German terms case-insensitively; over English text it wraps incidental
        # matches, and its _is_word_char check is meaningless for Arabic.
        return frontmatter + translation.content + "\n" + self._format_translated_vocabulary(translation)

    def _render_content_with_translation_hints(
        self,
        content: str,
        translation_hints: List[VocabularyItem],
    ) -> str:
        """Render the article body with deterministic clickable hint spans."""
        if not translation_hints:
            return content

        clean_content = content.replace("**", "")
        terms = sorted(
            enumerate(translation_hints),
            key=lambda item: len(item[1].term),
            reverse=True,
        )
        result: List[str] = []
        index = 0

        while index < len(clean_content):
            match = self._find_translation_hint_match(clean_content, index, terms)
            if match is None:
                result.append(clean_content[index])
                index += 1
                continue

            hint_index, item = match
            matched_text = clean_content[index:index + len(item.term)]
            classes = ["article-term"]
            if item.default_glossary:
                classes.append("article-term--default")
            result.append(
                '<button type="button" '
                f'class="{" ".join(classes)}" '
                f'data-term-id="{self._translation_hint_id(hint_index)}">'
                f"{html_escape(matched_text)}</button>"
            )
            index += len(item.term)

        return "".join(result)

    def _find_translation_hint_match(
        self,
        content: str,
        index: int,
        terms: List[Tuple[int, VocabularyItem]],
    ) -> Optional[Tuple[int, VocabularyItem]]:
        for hint_index, item in terms:
            if self._term_matches_at(content, index, item.term):
                return hint_index, item
        return None

    def _term_matches_at(self, content: str, index: int, term: str) -> bool:
        if not term:
            return False
        if not content[index:index + len(term)].casefold() == term.casefold():
            return False

        end = index + len(term)
        if index > 0 and self._is_word_char(content[index - 1]):
            return False
        if end < len(content) and self._is_word_char(content[end]):
            return False
        return True

    def _is_word_char(self, char: str) -> bool:
        return len(char) == 1 and (char.isalnum() or char == "_")

    def _translation_hint_id(self, index: int) -> str:
        return hint_id(index)

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
        if audio.timings_url:
            lines.append(f'  timings_url: "{self._escape_yaml_string(audio.timings_url)}"')
            if audio.timing_granularity:
                lines.append(
                    f'  timing_granularity: "{self._escape_yaml_string(audio.timing_granularity)}"'
                )
            if audio.highlight_context:
                lines.append(
                    f'  highlight_context: "{self._escape_yaml_string(audio.highlight_context)}"'
                )
        if audio.duration_seconds is not None:
            lines.append(f'  duration_seconds: {audio.duration_seconds}')
        return '\n'.join(lines)

    def _format_attribution(self, sources) -> str:
        """Return a public-safe footer without private/manual source details."""
        return """

---
*Vereinfachter Artikel zu Lernzwecken.*
"""

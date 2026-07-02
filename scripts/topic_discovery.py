"""
Topic Discovery Component

Discovers newsworthy topics from multiple sources using:
- RSS feeds
- Wikipedia trending
- Google Trends
- SpaCy NER for entity extraction
"""

import html
import logging
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List
from urllib.parse import quote

import feedparser
import requests
import spacy

from scripts.language_profiles import DEFAULT_SPACY_MODEL
from scripts.models import Topic
from scripts.topic_utils import sanitize_topic_keywords


class TopicDiscoverer:
    """Discovers topics from multiple German sources"""

    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger.getChild('TopicDiscoverer')

        # Handle both Pydantic model and dict
        if hasattr(config, 'sources_list'):
            self.sources = config.sources_list
            discovery_config = config.discovery if hasattr(config, 'discovery') else {}
            ranking_config = config.ranking if hasattr(config, 'ranking') else {}
        else:
            self.sources = config.get('sources_list', [])
            discovery_config = config.get('discovery', {})
            ranking_config = config.get('ranking', {})

        self.min_sources = discovery_config.get('min_sources', 3) if isinstance(discovery_config, dict) else getattr(discovery_config, 'min_sources', 3)

        # Ranking configuration
        self.source_weight = ranking_config.get('source_weight', 3) if isinstance(ranking_config, dict) else getattr(ranking_config, 'source_weight', 3)
        self.mention_weight = ranking_config.get('mention_weight', 2) if isinstance(ranking_config, dict) else getattr(ranking_config, 'mention_weight', 2)
        self.mention_cap = ranking_config.get('mention_cap', 10) if isinstance(ranking_config, dict) else getattr(ranking_config, 'mention_cap', 10)
        self.cultural_bonus = ranking_config.get('cultural_bonus', 5) if isinstance(ranking_config, dict) else getattr(ranking_config, 'cultural_bonus', 5)
        self.avoid_penalty = ranking_config.get('avoid_penalty', -10) if isinstance(ranking_config, dict) else getattr(ranking_config, 'avoid_penalty', -10)

        if hasattr(config, 'language'):
            language_config = config.language
        else:
            language_config = config.get('language', {})
        if isinstance(language_config, dict):
            spacy_model = language_config.get('spacy_model', DEFAULT_SPACY_MODEL)
        else:
            spacy_model = getattr(language_config, 'spacy_model', DEFAULT_SPACY_MODEL)
        try:
            self.nlp = spacy.load(spacy_model)
        except OSError:
            self.logger.error(
                "SpaCy model not found. Install with: python -m spacy download %s",
                spacy_model,
            )
            raise

        # Learner-friendly topics
        self.friendly_keywords = {
            'cultura', 'arte', 'música', 'deporte', 'fútbol', 'cine', 'festival',
            'comida', 'gastronomía', 'turismo', 'viaje', 'historia', 'tradición',
            'celebración', 'familia', 'educación', 'libro', 'película'
        }

        # Topics to avoid
        self.avoid_keywords = {
            'guerra', 'ataque', 'militar', 'bomba', 'terrorismo',
            'blockchain', 'criptomoneda', 'algoritmo'
        }

    def discover(self, limit: int = 10) -> List[Topic]:
        """
        Main entry point: discover topics

        Returns: List of ranked Topic objects
        """
        self.logger.info(f"Starting topic discovery from {len(self.sources)} sources")

        # Step 1: Fetch all headlines in parallel
        all_headlines = []

        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit all fetch tasks
            future_to_source = {
                executor.submit(self._fetch_source, source): source
                for source in self.sources
            }

            # Collect results as they complete
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    headlines = future.result()
                    all_headlines.extend(headlines)
                    self.logger.debug(f"Fetched {len(headlines)} headlines from {source['name']}")
                except Exception as e:
                    self.logger.warning(f"Failed to fetch {source.get('name', 'unknown')}: {e}")

        self.logger.info(f"Fetched {len(all_headlines)} total headlines")

        if not all_headlines:
            return []

        # Step 2: Extract entities
        entities_by_headline = {}
        for headline in all_headlines:
            entities = self._extract_entities(headline['text'])
            # Use composite key to prevent collisions when different sources report same story
            composite_key = f"{headline['source']}:{headline['id']}"
            entities_by_headline[composite_key] = {
                'headline': headline,
                'entities': entities
            }

        # Step 3: Cluster topics
        topics = self._cluster_topics(entities_by_headline)
        self.logger.info(f"Found {len(topics)} candidate topics")

        # Step 4: Rank topics
        ranked_topics = self._rank_topics(topics)

        # Convert to Topic objects
        topic_objects = []
        for topic_dict in ranked_topics[:limit]:
            # Extract URLs from headlines
            urls = [h['url'] for h in topic_dict.get('headlines', [])]
            topic_objects.append(Topic(
                title=topic_dict['title'],
                sources=topic_dict['sources'],
                mentions=topic_dict['mentions'],
                score=topic_dict['score'],
                keywords=topic_dict.get('keywords'),
                urls=urls
            ))

        return topic_objects

    def _fetch_source(self, source: Dict) -> List[Dict]:
        """Fetch headlines from one source"""
        source_type = source['type']

        if source_type == 'rss':
            return self._fetch_rss(source)
        elif source_type == 'wikipedia_trending':
            return self._fetch_wikipedia_trending(source)
        elif source_type == 'google_trends':
            return self._fetch_google_trends(source)
        else:
            self.logger.warning(f"Unknown source type: {source_type}")
            return []

    def _fetch_rss(self, source: Dict) -> List[Dict]:
        """Fetch from RSS feed"""
        try:
            feed = feedparser.parse(source['url'])
            headlines = []

            for entry in feed.entries[:20]:
                # Skip entries missing required fields
                title = getattr(entry, 'title', None)
                link = getattr(entry, 'link', None)
                if not title or not link:
                    continue

                headlines.append({
                    'id': entry.get('id', link),
                    'text': title,
                    'url': link,
                    'source': source['name'],
                    'published': entry.get('published_parsed', None),
                    'summary': entry.get('summary', '')[:200]
                })

            return headlines
        except Exception as e:
            self.logger.warning(f"RSS fetch error for {source['name']}: {e}")
            return []

    def _fetch_wikipedia_trending(self, source: Dict) -> List[Dict]:
        """Fetch trending Wikipedia articles"""
        lang = source.get('lang', 'es')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y/%m/%d')
        url = f"https://{lang}.wikipedia.org/api/rest_v1/feed/featured/{yesterday}"

        try:
            # Wikipedia API requires a User-Agent header
            headers = {
                'User-Agent': 'BriefBerlinBot/1.0 (Educational content bot)'
            }
            response = requests.get(url, timeout=10, headers=headers)
            response.raise_for_status()
            data = response.json()

            headlines = []
            if 'mostread' in data and 'articles' in data['mostread']:
                for article in data['mostread']['articles'][:10]:
                    # Skip articles missing required fields
                    title = article.get('title')
                    if not title:
                        continue

                    # URL encode the title to handle spaces and special characters
                    encoded_title = quote(title.replace(' ', '_'), safe='')
                    headlines.append({
                        'id': title,
                        'text': title,
                        'url': f"https://{lang}.wikipedia.org/wiki/{encoded_title}",
                        'source': source['name'],  # Use configured source name
                        'published': None,
                        'summary': article.get('extract', '')[:200]
                    })

            return headlines
        except Exception as e:
            self.logger.warning(f"Wikipedia trending error: {e}")
            return []

    def _fetch_google_trends(self, source: Dict) -> List[Dict]:
        """Fetch Google Trends RSS"""
        geo = source.get('geo', 'ES')
        url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"

        try:
            feed = feedparser.parse(url)
            headlines = []

            for entry in feed.entries[:15]:
                # Skip entries missing required fields
                title = getattr(entry, 'title', None)
                link = getattr(entry, 'link', None)
                if not title or not link:
                    continue

                headlines.append({
                    'id': title,
                    'text': title,
                    'url': link,
                    'source': f'Google Trends {geo}',
                    'published': None,
                    'summary': entry.get('description', '')[:200]
                })

            return headlines
        except Exception as e:
            self.logger.warning(f"Google Trends error: {e}")
            return []

    def _extract_entities(self, text: str) -> List[str]:
        """Extract named entities using SpaCy"""
        doc = self.nlp(text)

        entities = []
        for ent in doc.ents:
            # Only relevant entity types
            if ent.label_ in ['PER', 'LOC', 'ORG', 'MISC']:
                if len(ent.text) > 2:  # Filter very short
                    entities.append(ent.text)

        return entities

    def _cluster_topics(self, entities_by_headline: Dict) -> List[Dict]:
        """Find topics appearing in multiple sources"""
        entity_to_headlines = defaultdict(set)  # Use set to avoid duplicates
        entity_to_sources = defaultdict(set)

        for headline_id, data in entities_by_headline.items():
            headline = data['headline']
            entities = data['entities']

            # Deduplicate entities within the same headline
            unique_entities = set(entity.lower() for entity in entities)

            for normalized in unique_entities:
                # Use headline_id to ensure unique headlines
                entity_to_headlines[normalized].add(headline_id)
                entity_to_sources[normalized].add(headline['source'])

        # Find entities in min_sources+ sources
        topics = []
        for entity, headline_ids in entity_to_headlines.items():
            sources = entity_to_sources[entity]

            if len(sources) >= self.min_sources:  # Cross-source validation
                # Convert headline_ids back to headline objects
                headlines = [entities_by_headline[hid]['headline'] for hid in headline_ids]

                topics.append({
                    'title': entity.title(),
                    'mentions': len(headlines),  # Now accurate count
                    'sources': list(sources),
                    'headlines': headlines,
                    'keywords': self._extract_keywords(headlines),
                    'score': 0.0  # Will be set by _rank_topics
                })

        return topics

    def _extract_keywords(self, headlines: List[Dict]) -> List[str]:
        """Extract common keywords from headlines"""
        def _strip_html(text: str) -> str:
            """Best-effort removal of HTML tags and decoding of entities."""
            if not text:
                return ""
            # Decode basic HTML entities first
            text = html.unescape(text)
            # Remove all tags like <a ...>, </p>, <img ...>, etc.
            text = re.sub(r"<[^>]+>", " ", text)
            # Collapse excessive whitespace
            return re.sub(r"\s+", " ", text).strip()

        parts = []
        for h in headlines:
            title = h.get("text", "")
            summary = _strip_html(h.get("summary", ""))
            if title:
                parts.append(title)
            if summary:
                parts.append(summary)

        all_text = " ".join(parts)
        doc = self.nlp(all_text)

        # Get entities
        entities = [ent.text for ent in doc.ents if len(ent.text) > 2]

        # Count and return top 10, then filter with shared topic keyword sanitizer
        counter = Counter(entities)
        raw_keywords = [word for word, count in counter.most_common(10)]
        return sanitize_topic_keywords(raw_keywords)

    def _rank_topics(self, topics: List[Dict]) -> List[Dict]:
        """Rank topics by learnability"""
        for topic in topics:
            score = 0

            # Base: more sources = more important
            score += len(topic['sources']) * self.source_weight

            # Mentions matter (capped)
            score += min(topic['mentions'], self.mention_cap) * self.mention_weight

            # Check keywords (use word boundaries to avoid partial matches)
            keywords_lower = set(k.lower() for k in topic['keywords'])

            # Split keywords into individual words for matching
            keyword_words = set()
            for keyword in keywords_lower:
                keyword_words.update(keyword.split())

            # Learner-friendly bonus (exact word match, not substring)
            if any(kw in keyword_words for kw in self.friendly_keywords):
                score += self.cultural_bonus

            # Avoid penalty (exact word match, not substring)
            if any(kw in keyword_words for kw in self.avoid_keywords):
                score += self.avoid_penalty  # avoid_penalty is already negative

            topic['score'] = score

        # Sort by score
        return sorted(topics, key=lambda t: t['score'], reverse=True)

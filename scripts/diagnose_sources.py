#!/usr/bin/env python3
"""
Diagnostic script to test individual RSS feeds and sources
"""

import sys
from pathlib import Path

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).parent))

from config import load_config  # type: ignore[attr-defined]


def test_rss_feed(url: str, name: str):
    """Test an RSS feed"""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"URL: {url}")
    print('='*60)

    try:
        # Test with feedparser
        feed = feedparser.parse(url)

        if hasattr(feed, 'bozo_exception'):
            print(f"⚠️  Feed has parsing issues: {feed.bozo_exception}")

        if hasattr(feed, 'status'):
            print(f"HTTP Status: {feed.status}")

        entries = feed.entries if hasattr(feed, 'entries') else []
        print(f"Entries found: {len(entries)}")

        if len(entries) > 0:
            print(f"✓ SUCCESS - Found {len(entries)} entries")
            print("\nFirst entry:")
            entry = entries[0]
            print(f"  Title: {entry.get('title', 'N/A')[:80]}")
            print(f"  Link: {entry.get('link', 'N/A')[:80]}")
            return True
        else:
            print("✗ FAILED - No entries found")

            # Try direct HTTP request to see what we get
            print("\nTrying direct HTTP request...")
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            print(f"Response status: {response.status_code}")
            print(f"Content-Type: {response.headers.get('content-type', 'unknown')}")
            print(f"Content length: {len(response.content)} bytes")
            print(f"First 200 chars: {response.text[:200]}")
            return False

    except Exception as e:
        print(f"✗ ERROR: {e}")
        return False


def test_wikipedia_api():
    """Test Wikipedia API"""
    print(f"\n{'='*60}")
    print("Testing: Wikipedia ES Trending API")
    print('='*60)

    from datetime import datetime, timedelta

    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y/%m/%d')
    url = f"https://es.wikipedia.org/api/rest_v1/feed/featured/{yesterday}"

    print(f"URL: {url}")

    # Try without user agent
    print("\n1. Without User-Agent:")
    try:
        response = requests.get(url, timeout=10)
        print(f"   Status: {response.status_code}")
        if response.status_code == 403:
            print("   ✗ 403 Forbidden")
    except Exception as e:
        print(f"   ✗ Error: {e}")

    # Try with user agent
    print("\n2. With User-Agent:")
    try:
        headers = {
            'User-Agent': 'BriefBerlinBot/1.0 (contact@example.com)'
        }
        response = requests.get(url, timeout=10, headers=headers)
        print(f"   Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            if 'mostread' in data and 'articles' in data['mostread']:
                articles = data['mostread']['articles']
                print(f"   ✓ SUCCESS - Found {len(articles)} trending articles")
                if articles:
                    print(f"   First article: {articles[0].get('title', 'N/A')}")
                return True
        else:
            print(f"   ✗ Failed with status {response.status_code}")

    except Exception as e:
        print(f"   ✗ Error: {e}")

    return False


def test_google_trends():
    """Test Google Trends RSS"""
    print(f"\n{'='*60}")
    print("Testing: Google Trends RSS")
    print('='*60)

    geo_codes = ['ES', 'MX', 'AR']

    for geo in geo_codes:
        url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"
        print(f"\nTrying {geo}: {url}")

        try:
            feed = feedparser.parse(url)
            entries = feed.entries if hasattr(feed, 'entries') else []

            if len(entries) > 0:
                print(f"✓ Found {len(entries)} entries")
                print(f"  First: {entries[0].get('title', 'N/A')[:50]}")
            else:
                print("✗ No entries")

                # Try direct request
                response = requests.get(url, timeout=10, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
                })
                print(f"  HTTP Status: {response.status_code}")
                print(f"  Content-Type: {response.headers.get('content-type')}")

        except Exception as e:
            print(f"✗ Error: {e}")


def main():
    """Run diagnostics on failing sources"""

    print("=" * 60)
    print("RSS FEED DIAGNOSTICS")
    print("=" * 60)

    config = load_config('local')
    sources = config.sources_list

    # Failing RSS feeds to investigate
    failing_sources = [
        'RTVE Noticias',
        'El Universal',
        'Infobae',
        'National Geographic ES',
        'El Mundo Deportes',
    ]

    results = {}

    for source in sources:
        if source['name'] in failing_sources and source['type'] == 'rss':
            success = test_rss_feed(source['url'], source['name'])
            results[source['name']] = success

    # Test Wikipedia API
    print("\n")
    wiki_success = test_wikipedia_api()
    results['Wikipedia API'] = wiki_success

    # Test Google Trends
    print("\n")
    trends_success = test_google_trends()
    results['Google Trends'] = trends_success

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)

    for name, success in results.items():
        status = "✓ WORKING" if success else "✗ FAILED"
        print(f"{status:12} {name}")


if __name__ == "__main__":
    main()

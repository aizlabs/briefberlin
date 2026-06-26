# AutoSpanishBlog — Complete System Design Document

**Version:** 1.1  
**Date:** March 18, 2026  
**Purpose:** Automated Spanish language learning content generation and publishing

> Current-state note: this document remains the foundational architecture reference, but parts of the original roadmap are now historical. For the current monetization strategy and feasibility review, see [docs/monetization-roadmap.md](docs/monetization-roadmap.md).

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Architecture](#system-architecture)
3. [Component Design](#component-design)
4. [Content Pipeline](#content-pipeline)
5. [Quality Assurance](#quality-assurance)
6. [Execution & Deployment](#execution--deployment)
7. [Observability & Monitoring](#observability--monitoring)
8. [Development Workflow](#development-workflow)
9. [Cost Analysis](#cost-analysis)
10. [Implementation Roadmap](#implementation-roadmap)
11. [Technical Specifications](#technical-specifications)

---

## Executive Summary

### Goals
- **Primary:** Automatically generate 10-12 high-quality Spanish learning articles daily
- **Revenue direction:** Prioritize web ads first, then distribution-led monetization
- **Legal:** Ensure content originality through multi-source synthesis
- **Quality:** Maintain 7.5+/10 quality score through automated gates

### Core Metrics
- **Target:** 12 articles/day (360/month)
- **Cost:** $10-20/month (LLM + infrastructure)
- **Revenue target:** Deferred until traffic, consent, and policy readiness are in place
- **Quality bar:** 7.5/10 minimum score
- **Success rate:** 80%+ articles pass quality gate

### Current Repository State

- The content pipeline is implemented end to end, including generation, quality gate, publishing, and scheduled deployment.
- Generation is now a **two-step flow**: native-level synthesis followed by A2/B1 adaptation.
- The production site config points to `https://spaili.com`.
- Telegram channel publishing exists as an optional post-deploy workflow.
- Monetization is not implemented yet.

### Key Constraints
- **Budget:** Minimize infrastructure costs (prefer free tiers)
- **Legal:** Multi-source synthesis only, no single-source copying
- **Automation:** Fully autonomous operation with human oversight
- **Reliability:** 99%+ uptime for daily generation

---

## System Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    DISCOVERY PHASE (Daily)                       │
│  Input: RSS feeds + Wikipedia trending (20+ active sources)     │
│  Output: 10-15 ranked topics worth writing about                │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CONTENT SOURCING PHASE                         │
│  Input: Topics from discovery                                   │
│  Process: Fetch 3-5 source articles per topic                   │
│  Output: Clean text from multiple sources                       │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   GENERATION PHASE                               │
│  Input: Topic + source texts                                    │
│  Process: LLM synthesizes into A2 + B1 articles                 │
│  Output: 2 articles (A2 and B1) per topic                       │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   QUALITY GATE PHASE                             │
│  Input: Generated article                                       │
│  Process: Score article, regenerate if needed (up to 3x)        │
│  Output: High-quality article (≥7.5/10) OR reject               │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PUBLISHING PHASE                               │
│  Input: Approved articles                                       │
│  Process: Save as Jekyll markdown, commit to git                │
│  Output: Files in /output/_posts/ ready for GitHub Pages        │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   DEPLOYMENT PHASE                               │
│  Input: New markdown files in git                               │
│  Process: GitHub Pages builds static site                       │
│  Output: Live website with new articles                         │
└─────────────────────────────────────────────────────────────────┘
```

### Technology Stack

**Backend:**
- Python 3.11+
- SpaCy (Spanish NER)
- Trafilatura (web scraping)
- Feedparser (RSS)
- Requests (HTTP)

**LLMs:**
- Current default provider: OpenAI
- Generation: GPT-4o
- Adaptation: GPT-4o
- Quality checking: GPT-4o-mini
- Anthropic remains supported as an alternate provider

**Static Site:**
- Jekyll (static site generator)
- GitHub Pages (hosting - free)
- Cloudflare CDN (optional)

**Infrastructure:**
- Docker (containerization)
- GitHub Actions (scheduling - free)
- Git (version control + content storage)

**Monetization Direction:**
- Google AdSense for the web property
- Telegram for audience growth and possible later channel revenue
- Facebook / Meta only as an optional republishing channel
- See [docs/monetization-roadmap.md](docs/monetization-roadmap.md)

---

## Component Design

### 1. Topic Discovery Engine

**Purpose:** Find newsworthy, learner-appropriate topics

**Implementation:** `TopicDiscoverer` class

**Process:**
1. Fetch headlines from active RSS feeds and Wikipedia trending
2. Extract named entities using SpaCy Spanish NER
3. Cluster topics appearing in 3+ different sources
4. Rank by "learnability" score
5. Return top 10-15 topics

**Sources (current config):**

```yaml
# Spanish News
- El País (ES)
- El Mundo (ES)
- ABC España (ES)
- 20 Minutos (ES)
- La Vanguardia (ES)

# Latin America
- Clarín (AR)
- La Nación (AR)
- El Universal (MX)
- La Jornada (MX)
- El Tiempo (CO)

# International Spanish
- BBC Mundo
- Deutsche Welle ES
- VOA Noticias
- Noticias ONU

# Educational/Open
- Wikinews ES
- Wikipedia Trending ES
- RTVE Noticias

# Culture/Lifestyle
- National Geographic ES
- El País Cultura
- El Mundo Deportes

# Tech/Science
- Xataka
- Genbeta
- El País Ciencia

# Google Trends
# Currently disabled in config because the old RSS approach is no longer active
```

**Ranking Algorithm:**
```
Score = (source_count × 3) + (mentions × 2) + cultural_bonus - avoid_penalty

cultural_bonus = +5 if topic contains:
  - cultura, arte, música, deporte, fútbol, cine
  - comida, gastronomía, turismo, viaje
  - historia, tradición, celebración

avoid_penalty = -10 if topic contains:
  - guerra, terrorismo, militar
  - blockchain, criptomoneda (too technical)
```

**Output Example:**
```json
{
  "title": "Lionel Messi",
  "mentions": 12,
  "sources": ["VOA", "El País", "Wikipedia", "Google Trends ES"],
  "keywords": ["Inter Miami", "Argentina", "Fútbol", "Copa"],
  "score": 28,
  "headlines": [...]
}
```

---

### 2. Content Fetcher

**Purpose:** Extract clean article text from source URLs

**Implementation:** `ContentFetcher` class

**Process:**
1. Take topic with list of source URLs
2. Fetch each URL with timeout and retries
3. Extract clean text using Trafilatura library
4. Truncate to first 300 words per source
5. Return 3-5 sources minimum

**Why Trafilatura:**
- Better than BeautifulSoup at handling news sites
- Removes ads, navigation, comments automatically
- Handles paywalls better (gets preview content)

**Truncation Strategy:**
- Only send first 300 words to LLM
- Reduces token costs by 70%
- Forces synthesis (can't copy full articles)
- Legal: Using facts for context, not reproduction

**Special Handling:**
```python
# Wikipedia: Use API for clean extraction
GET https://es.wikipedia.org/api/rest_v1/page/summary/{title}

# RSS feeds: Already have clean text
# News sites: Trafilatura extraction
```

**Output Example:**
```python
[
  {
    "url": "https://elpais.com/...",
    "text": "[First 300 words about Messi]",
    "source": "El País",
    "word_count": 300
  },
  {
    "url": "https://bbc.com/mundo/...",
    "text": "[First 300 words about Messi]",
    "source": "BBC Mundo",
    "word_count": 300
  },
  ...
]
```

---

### 3. Content Generator

**Purpose:** Synthesize original articles from multiple sources

**Implementation:** `ContentGenerator` class

**Key Features:**
- Generates both A2 and B1 levels
- Structured JSON output
- Feedback-aware regeneration
- Multi-source synthesis prompting

**Level Requirements:**

**A2 (Beginner):**
- Present tense only
- Simple sentences (max 12 words)
- Vocabulary from 1000 most common Spanish words
- No subjunctive mood
- ~200 words

**B1 (Intermediate):**
- Mixed tenses (present, preterite, imperfect)
- Complex sentences with subordinate clauses
- Intermediate vocabulary
- Subjunctive in common expressions
- ~300 words

**Generation Prompt Structure:**
```
You are a Spanish language teacher creating content for {level} learners.

TOPIC: {topic_title}

REFERENCE SOURCES (synthesize, don't copy):
Source 1 (El País): [300 words]
Source 2 (BBC): [300 words]
Source 3 (Wikipedia): [300 words]

REQUIREMENTS:
- Level: {level} with specific grammar rules
- Length: ~{word_count} words
- 3 paragraphs with clear flow
- Original synthesis from sources
- Cultural context for Spanish speakers

OUTPUT (valid JSON):
{
  "title": "engaging title (5-8 words)",
  "content": "full article text",
  "vocabulary": {
    "word1": "translation",
    (10 words total)
  },
  "summary": "one sentence",
  "reading_time": minutes
}

Attribution: "Fuentes: El País, BBC Mundo, Wikipedia"
```

**Regeneration with Feedback:**
If quality check fails, regenerate with additional context:
```
PREVIOUS ATTEMPT HAD ISSUES:

Previous Title: {old_title}
Previous Content: {first_200_words}...

SPECIFIC ISSUES TO FIX:
- Grammar error in paragraph 2 with subjunctive
- Vocabulary too advanced for A2
- Sentence structure too complex

Generate IMPROVED version addressing these issues.
```

---

### 4. Quality Gate

**Purpose:** Ensure only high-quality content gets published

**Implementation:** `QualityGate` class

**Scoring System (0-10 points):**
- Grammar & Language (0-4): Correct grammar, level-appropriate
- Educational Value (0-3): Interesting, useful, culturally relevant
- Content Quality (0-2): Well-structured, coherent, flows naturally
- Vocabulary (0-1): Appropriate difficulty and relevance

**Minimum Score:** 7.5/10

**Process:**
```
1. Generate article
   ↓
2. LLM judges article → score 0-10
   ↓
3. If score >= 7.5 → PASS → Publish
   ↓
4. If score < 7.5 → Regenerate with feedback
   ↓
5. Repeat up to 3 attempts total
   ↓
6. If still < 7.5 after 3 attempts → REJECT
```

**Judge Prompt:**
```
Evaluate this Spanish article for {level} learners.

ARTICLE:
Title: {title}
Content: {content}
Vocabulary: {vocab_count} words

SCORING:
- Grammar & Language (0-4)
- Educational Value (0-3)  
- Content Quality (0-2)
- Vocabulary (0-1)

Return JSON:
{
  "grammar_score": 0-4,
  "educational_score": 0-3,
  "content_score": 0-2,
  "vocabulary_score": 0-1,
  "total_score": sum,
  "issues": ["specific issue 1", "specific issue 2"],
  "strengths": ["strength 1", "strength 2"]
}

Be strict. 7.5+ means genuinely good content.
```

**Expected Results:**
```
Starting with 10 topic attempts × 2 levels = 20 articles

Round 1: Initial generation
- Pass: ~12 articles (60%)
- Fail: ~8 articles

Round 2: Regeneration with feedback
- Pass: ~5 more articles (60% of failures)
- Still failing: ~3 articles

Round 3: Final attempt
- Pass: ~2 more articles
- Final failures: ~1 article

Total published: 19/20 (95%)
```

**Cost per Article (with regeneration):**
```
Scenario 1: Pass first try (70%)
- Generation: $0.015
- Quality check: $0.008
- Total: $0.023

Scenario 2: Pass second try (20%)
- Total: $0.046

Scenario 3: Pass third try (5%)
- Total: $0.069

Scenario 4: Fail all (5%)
- Total: $0.069 (wasted)

Average: $0.031 per article
300 articles/month = $9.30
```

---

### 5. Publisher

**Purpose:** Convert approved articles to Jekyll format

**Implementation:** `Publisher` class

**Jekyll Markdown Format:**
```yaml
---
title: "Messi Juega en Estados Unidos"
date: 2025-11-11T10:23:45Z
level: A2
topics: [deportes, fútbol]
sources: "El País, BBC Mundo, Wikipedia"
reading_time: 3
---

[Article content in Spanish - 200 words for A2]

## Vocabulario

- **juega** - plays
- **equipo** - team
- **partido** - match
- **gol** - goal
- **jugadores** - players
- **estadio** - stadium
- **aficionados** - fans
- **entrenador** - coach
- **campeonato** - championship
- **victoria** - victory

---
*Fuentes: El País, BBC Mundo, Wikipedia*  
*Artículo educativo generado con fines de aprendizaje de idiomas.*
```

**File Naming:**
```
output/_posts/2025-11-11-messi-estados-unidos-a2.md
output/_posts/2025-11-11-messi-estados-unidos-b1.md
```

**Git Operations:**
```bash
git add output/_posts/
git commit -m "Generate articles - 2025-11-11"
git push origin main
```

Triggers automatic Jekyll rebuild on GitHub Pages.

---

## Content Pipeline

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TOPIC DISCOVERY                                  │
│  TopicDiscoverer → Finds trending topics from 22+ Spanish news sources  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                        CONTENT FETCHING                                  │
│  ContentFetcher → Fetches 3-5 full articles per topic (Trafilatura)    │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 ↓
                 ┌───────────────────────────────┐
                 │   FOR EACH LEVEL (A2, B1)     │
                 └───────────┬───────────────────┘
                             │
                             ↓
        ╔════════════════════════════════════════════════════╗
        ║          STEP 1: SYNTHESIS                         ║
        ║  ArticleSynthesizer.synthesize()                   ║
        ║                                                     ║
        ║  Input:  Topic + 3-5 source articles               ║
        ║  Model:  gpt-4o (config: generation)               ║
        ║  Prompt: get_synthesis_prompt()                    ║
        ║                                                     ║
        ║  Output: BASE ARTICLE (native Spanish)             ║
        ║    • title (8-12 words)                            ║
        ║    • content (300-400 words, native-level)         ║
        ║    • summary (1 sentence)                          ║
        ║    • reading_time                                  ║
        ║                                                     ║
        ║  Focus: Factual accuracy, natural Spanish          ║
        ║  No CEFR constraints                               ║
        ╚════════════════════════════════════════════════════╝
                             │
                             ↓
                   [Optional: Save to disk]
                   ./output/base_articles/
                             │
                             ↓
        ╔════════════════════════════════════════════════════╗
        ║          STEP 2: ADAPTATION                        ║
        ║  LevelAdapter.adapt_to_level()                     ║
        ║                                                     ║
        ║  Input:  Base article + target level (A2/B1)       ║
        ║  Model:  gpt-4o (config: adaptation)               ║
        ║  Prompt: get_a2_adaptation_prompt() OR             ║
        ║          get_b1_adaptation_prompt()                ║
        ║                                                     ║
        ║  A2 Processing:                                    ║
        ║    • Simplify to present/preterite tenses          ║
        ║    • Break long sentences (max 20 words)           ║
        ║    • Use only 1,500 most common words              ║
        ║    • Gloss 10-15 advanced terms with **bold**      ║
        ║    • Target: ~200 words                            ║
        ║                                                     ║
        ║  B1 Processing:                                    ║
        ║    • Allow mixed tenses (presente/pretérito/       ║
        ║      imperfecto/futuro)                            ║
        ║    • Light simplification only                     ║
        ║    • Gloss 8-12 specialized terms                  ║
        ║    • Target: ~300 words                            ║
        ║                                                     ║
        ║  Output: ADAPTED ARTICLE                           ║
        ║    • title (level-appropriate)                     ║
        ║    • content (with **bold** glossed terms)         ║
        ║    • vocabulary (glossary with translations)       ║
        ║    • summary (level-appropriate)                   ║
        ║    • reading_time                                  ║
        ║    • base_article (stored for regeneration)        ║
        ╚════════════════════════════════════════════════════╝
                             │
                             ↓
        ┌────────────────────────────────────────────────────┐
        │          QUALITY GATE                              │
        │  QualityGate.check_and_improve()                   │
        │                                                     │
        │  LLM Judge evaluates (4 criteria, 0-10 score):     │
        │    • Grammar & Language (0-4 pts)                  │
        │    • Educational Value (0-3 pts)                   │
        │    • Content Quality (0-2 pts)                     │
        │    • Level Appropriateness (0-1 pt)                │
        │                                                     │
        │  If score < 7.5: REGENERATE                        │
        └────────────────┬────────────┬──────────────────────┘
                         │            │
                    PASS │            │ FAIL (attempts < 3)
                         │            │
                         │            ↓
                         │   ╔═══════════════════════════════════╗
                         │   ║  REGENERATION (configurable)      ║
                         │   ║                                   ║
                         │   ║  Strategy: adaptation_only        ║
                         │   ║  • Reuse base_article             ║
                         │   ║  • Re-adapt with feedback         ║
                         │   ║  • 1 LLM call (faster, cheaper)   ║
                         │   ║                                   ║
                         │   ║  OR: full_pipeline                ║
                         │   ║  • Re-synthesize base             ║
                         │   ║  • Re-adapt to level              ║
                         │   ║  • 2 LLM calls (more thorough)    ║
                         │   ╚════════════════════════════════════
                         │            │
                         │            ↓
                         │      [Back to Quality Gate]
                         │
                         ↓
        ┌────────────────────────────────────────────────────┐
        │            PUBLISHING                              │
        │  Publisher.save_article()                          │
        │                                                     │
        │  Saves to: ./output/_posts/YYYY-MM-DD-slug.md     │
        │  Format: Jekyll markdown with frontmatter          │
        └────────────────────────────────────────────────────┘
```

### Configuration

```yaml
# config/base.yaml
generation:
  two_step_synthesis:
    enabled: true                      # Enable two-step process
    save_base_article: false           # Save native articles for debugging
    base_article_path: ./output/base_articles/
    regeneration_strategy: adaptation_only  # Fast regeneration

llm:
  models:
    generation: gpt-4o       # Step 1: Synthesis
    adaptation: gpt-4o       # Step 2: Adaptation (can use gpt-4o-mini)
    quality_check: gpt-4o-mini
```

### Single Run Execution

**Trigger:** Cron schedule (3x daily: 2am, 10am, 6pm UTC)

**Duration:** ~10-13 minutes per run

**Target Output:** 4 articles (2 topics × 2 levels)

**Detailed Timeline:**

```
00:00 - Pipeline starts
00:15 - Load config, initialize components
00:45 - Topic discovery begins
        ├─ Fetch from 30 sources
        ├─ Extract entities with SpaCy
        ├─ Cluster and rank topics
01:30 - 15 topics discovered, top 10 selected

[For each topic until 4 articles published]

01:45 - Topic 1: "Lionel Messi"
        ├─ Fetch 5 source articles
        ├─ Extract and truncate text
02:30 - Sources ready (4 sources, 1200 words total)

02:45 - Generate A2 article
        ├─ LLM call with sources + prompt
        ├─ Parse JSON response
03:30 - A2 article generated (198 words)

03:45 - Quality check A2
        ├─ LLM judges article
        ├─ Score: 7.9/10 → PASS
04:00 - A2 approved

04:15 - Generate B1 article
        ├─ LLM call with sources + prompt
04:45 - B1 article generated (287 words)

05:00 - Quality check B1
        ├─ Score: 6.8/10 → FAIL
        ├─ Issues: "vocabulary too simple"
05:15 - Regenerate B1 with feedback
        ├─ LLM call with previous + issues
06:00 - B1 regenerated (294 words)

06:15 - Quality check B1 (attempt 2)
        ├─ Score: 7.7/10 → PASS
06:30 - B1 approved

06:45 - Save both articles to Jekyll
07:00 - Topic 1 complete (2 articles)

[Repeat for topics 2-3...]

10:30 - 4 articles published (2 topics)
10:45 - Commit to git
11:00 - Push to GitHub
11:30 - Jekyll rebuild triggered
12:00 - Articles live on website

Total: ~12 minutes
```

**Daily Schedule:**
```
2am UTC (3 articles/run)
10am UTC (3 articles/run)
6pm UTC (3 articles/run)
= 9-12 articles/day
```

---

## Execution & Deployment

### Infrastructure Choice: GitHub Actions

**Why GitHub Actions:**
- ✅ **FREE** for your use case (2000 min/month)
- ✅ Zero infrastructure management
- ✅ Native git integration
- ✅ Built-in secrets management
- ✅ Automatic Jekyll rebuild
- ✅ Email notifications on failure
- ✅ Manual trigger button

**Usage:**
- 3 runs/day × 12 min/run × 30 days = 1080 min/month
- Well under 2000 min free tier

**Cost:** $0/month

**Alternative Options Evaluated:**

| Option | Cost | Pros | Cons |
|--------|------|------|------|
| **GitHub Actions** | **$0** | **Free, simple, native** | **2000 min limit** |
| AWS Lambda | $0-2 | Serverless, fast | Setup complexity |
| GCP Cloud Run | $0-3 | Good timeouts | Cold starts |
| Hetzner VPS | $5 | Full control | Always running |
| Oracle Free Tier | $0 | Powerful | Setup, maintenance |

### GitHub Actions Workflow

**File:** `.github/workflows/generate.yml`

```yaml
name: Generate Articles

on:
  schedule:
    - cron: '0 2 * * *'   # 2am UTC
    - cron: '0 10 * * *'  # 10am UTC  
    - cron: '0 18 * * *'  # 6pm UTC
  workflow_dispatch:      # Manual trigger button

jobs:
  generate:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    
    permissions:
      contents: write     # Needed to commit files
    
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
      
      - name: Cache Docker layers
        uses: actions/cache@v3
        with:
          path: /tmp/.buildx-cache
          key: ${{ runner.os }}-buildx-${{ github.sha }}
          restore-keys: |
            ${{ runner.os }}-buildx-
      
      - name: Run generation
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          docker compose run generator
      
      - name: Commit generated articles
        run: |
          git config user.name "AutoSpanishBot"
          git config user.email "bot@github.com"
          git add output/
          
          if git diff --staged --quiet; then
            echo "No new articles"
            exit 0
          fi
          
          git commit -m "Articles $(date -u +%Y-%m-%d_%H:%M)"
          git push
      
      - name: Notify on failure
        if: failure()
        uses: dawidd6/action-send-mail@v3
        with:
          server_address: smtp.gmail.com
          server_port: 465
          username: ${{ secrets.EMAIL_USERNAME }}
          password: ${{ secrets.EMAIL_PASSWORD }}
          subject: "❌ Article generation failed"
          to: your@email.com
          from: bot@autospanish.com
          body: "Check logs: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"

# Prevent overlapping runs
concurrency:
  group: article-generation
  cancel-in-progress: false
```

---

## Observability & Monitoring

### Design Philosophy

**Principles:**
- Structured logging (JSON in production)
- File-based metrics (git-tracked, free)
- Actionable alerts only
- Environment-aware (local vs production)

### Logging System

**Production (JSON):**
```json
{
  "timestamp": "2025-11-11T10:23:45.123Z",
  "level": "INFO",
  "component": "ContentGenerator",
  "run_id": "prod-20251111-102345",
  "topic_id": "messi-20251111",
  "message": "Generated article",
  "metadata": {
    "level": "A2",
    "word_count": 203,
    "sources": 4
  },
  "duration_ms": 2341
}
```

**Local Development (Human-readable):**
```
[10:23:45] INFO  ContentGenerator | Generated article | level=A2 words=203 (2.3s)
```

**Log Levels:**

| Event | Level | When |
|-------|-------|------|
| Pipeline started/completed | INFO | Always |
| Topic discovered | INFO | Always |
| Article generated | INFO | Always |
| Quality check passed | INFO | Always |
| Regeneration triggered | WARN | Needs improvement |
| Article rejected | WARN | Quality failed |
| API error (retryable) | WARN | Temporary issue |
| API error (fatal) | ERROR | Blocking issue |
| Pipeline failed | ERROR | Critical |

**Log Files:**
```
# Local
logs/local.log                    # All local runs

# Production (git-tracked)
output/logs/production.log        # All production runs
output/logs/rejections.jsonl      # Rejected articles only
```

### Metrics System

**Per-Run Metrics:**
```yaml
run_id: "prod-20251111-102345"
started_at: "2025-11-11T10:23:45Z"
ended_at: "2025-11-11T10:35:12Z"
duration_seconds: 687
environment: "production"

discovery:
  topics_found: 12
  topics_selected: 5
  duration_seconds: 45

fetching:
  topics_processed: 5
  sources_fetched: 23
  sources_failed: 2
  duration_seconds: 87

generation:
  articles_attempted: 10
  articles_generated: 10
  total_words: 2430
  duration_seconds: 420

quality:
  articles_checked: 10
  passed_first_attempt: 7
  regenerations: 3
  final_passed: 9
  final_rejected: 1
  avg_score: 7.8
  duration_seconds: 125

publishing:
  articles_published: 9
  files_written: 9
  duration_seconds: 10

costs:
  llm_calls: 23
  estimated_cost_usd: 0.18

errors:
  api_errors: 1
  fetch_errors: 2
  parse_errors: 0
```

**Storage:**
```
output/metrics/20251111-102345.json       # Per run
output/metrics/daily/2025-11-11.json      # Daily aggregate
output/metrics/summary.json                # Rolling 30 days
```

**Health Check:**
```json
// output/health.json (updated after each run)
{
  "last_successful_run": "2025-11-11T10:35:12Z",
  "last_run_status": "success",
  "articles_published_today": 12,
  "consecutive_failures": 0,
  "uptime_last_7d": 0.99,
  "avg_quality_score_7d": 7.8
}
```

### Alert System

**Alert Triggers:**

| Condition | Severity | Action |
|-----------|----------|--------|
| Zero articles published | CRITICAL | Immediate email |
| <50% pass rate | ERROR | Email |
| API error rate >20% | ERROR | Email |
| Cost spike (>2x) | WARNING | Daily digest |
| Avg quality <7.0 | WARNING | Daily digest |
| Run duration >30min | WARNING | Log only |

**Alert Channels:**
- **Local:** Console only
- **Production:** Email + optional Telegram

**Alert Cooldown:** Max 1 alert per condition per 6 hours

**Critical Alert Example:**
```
Subject: 🚨 CRITICAL: Zero articles published

Run ID: prod-20251111-102345
Time: 2025-11-11 10:35:12 UTC
Status: FAILED
Articles: 0/10 (0%)

Issues:
- 8 articles failed quality gate (avg: 5.2)
- 2 articles had API errors

Action:
1. Check logs: [GitHub Actions link]
2. Review metrics: output/metrics/...
3. Possible causes:
   - LLM prompt degradation
   - Source quality issues
   - API rate limiting

Last success: 6 hours ago
```

**Warning Alert Example (Daily Digest):**
```
Subject: ⚠️ Daily Digest - Quality Issues

Date: 2025-11-11
Articles: 9/12 (75%)
Avg quality: 6.9 (below 7.5 target)
Regenerations: 8 (high)

Trends:
- Quality down 0.6 from yesterday
- Rejection rate up to 25%

Top issues:
1. Grammar errors (4)
2. Vocabulary too simple (3)

Recommendation: Review LLM prompts
```

---

## Development Workflow

### Project Structure

```
autospanishblog/
├── .github/
│   └── workflows/
│       ├── generate.yml           # Main production
│       ├── test.yml               # PR testing
│       └── metrics-report.yml     # Weekly reports
│
├── config/
│   ├── base.yaml                  # Shared config
│   ├── local.yaml                 # Dev overrides
│   ├── production.yaml            # Prod overrides
│   └── secrets.yaml.example       # Template
│
├── scripts/
│   ├── main.py                    # Entry point
│   ├── config.py                  # Config loader
│   ├── logger.py                  # Logging setup
│   ├── metrics.py                 # Metrics
│   ├── alerts.py                  # Alerts
│   ├── topic_discovery.py         # Discovery
│   ├── content_fetcher.py         # Fetching
│   ├── content_generator.py       # Generation
│   ├── quality_gate.py            # Quality
│   ├── publisher.py               # Publishing
│   └── analyze_metrics.py         # Analysis
│
├── output/                        # Git-tracked
│   ├── _posts/                    # Articles
│   ├── _config.yml                # Jekyll
│   ├── index.html                 # Homepage
│   ├── logs/                      # Production logs
│   ├── metrics/                   # Metrics
│   └── health.json                # Health status
│
├── logs/                          # Gitignored
│   └── local.log
│
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── Makefile                       # Dev commands
└── README.md
```

### Configuration System

**Hierarchical Loading:**
```
base.yaml
  ↓ (merge)
{local|production}.yaml
  ↓ (merge)
Environment variables (API keys)
  ↓
Final config
```

**base.yaml:**
```yaml
environment: base

sources:
  max_headlines_per_source: 20
  fetch_timeout: 10

generation:
  articles_per_run: 4
  levels: [A2, B1]
  target_word_count:
    A2: 200
    B1: 300

quality_gate:
  min_score: 7.5
  max_attempts: 3

llm:
  provider: anthropic
  models:
    generation: claude-sonnet-4-20250514
    quality_check: claude-haiku-4-20250323
  temperature: 0.3
```

**local.yaml:**
```yaml
environment: local

logging:
  level: DEBUG
  format: console  # Colored
  file: logs/local.log

metrics:
  enabled: false

alerts:
  enabled: false

generation:
  articles_per_run: 2  # Faster testing
```

**production.yaml:**
```yaml
environment: production

logging:
  level: INFO
  format: json  # Structured
  file: output/logs/production.log

metrics:
  enabled: true
  output: output/metrics/

alerts:
  enabled: true
  email: your@email.com

generation:
  articles_per_run: 4
```

In GitHub Actions, alert settings are overridden from environment variables (`ALERTS_ENABLED`, `ALERT_EMAIL`, `ALERT_SMTP_*`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`), so AlertManager can send failure emails without a separate secrets YAML.

### Local Development

**Setup:**
```bash
# Clone repo
git clone https://github.com/yourusername/autospanishblog.git
cd autospanishblog

# Copy secrets template
cp config/secrets.yaml.example config/secrets.yaml
vim config/secrets.yaml  # Add API keys

# Build Docker
docker compose build
```

**Run Commands:**
```bash
# Full pipeline
make run

# With options
make run ARTICLES=2 DRY_RUN=true

# Test specific component
make test-discovery
make test-quality

# View logs
make logs
tail -f logs/local.log

# Analyze metrics
python scripts/analyze_metrics.py
```

**Makefile:**
```makefile
.PHONY: run test-discovery logs

run:
	docker compose run generator

test-discovery:
	docker compose run generator python -c \
	  "from topic_discovery import *; test()"

logs:
	tail -f logs/local.log

clean:
	rm -rf logs/*.log output/_posts/*
```

**Local Output:**
```
🚀 AutoSpanishBlog - Local Development
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[10:23:45] INFO  Pipeline started
[10:24:12] INFO  Found 12 topics
[10:24:13] INFO  Processing: Messi
[10:24:22] INFO    ✅ A2 passed (7.9)
[10:24:36] INFO    🔄 B1 regenerating (6.8)
[10:24:42] INFO    ✅ B1 passed (7.7)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✨ Summary:
   Published: 8/10 (80%)
   Avg quality: 7.8
   Duration: 11m 27s
   Cost: $0.14
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Docker Configuration

**Dockerfile:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# SpaCy model
RUN python -m spacy download es_core_news_sm

# Copy code
COPY scripts/ ./scripts/
COPY config/ ./config/

CMD ["python", "scripts/main.py"]
```

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  generator:
    build: .
    volumes:
      - ./output:/app/output
      - ./logs:/app/logs
      - ./config:/app/config
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ENVIRONMENT=${ENVIRONMENT:-local}
```

**requirements.txt:**
```
anthropic>=0.40.0
openai>=1.50.0
spacy>=3.7.0
trafilatura>=1.6.0
feedparser>=6.0.0
requests>=2.31.0
requests-cache>=1.1.0
beautifulsoup4>=4.12.0
pyyaml>=6.0
python-dotenv>=1.0.0
langdetect>=1.0.9
```

---

## Cost Analysis

### Monthly Operating Costs

**LLM Costs (300 articles/month):**

```
Per Article with Regeneration:

Scenario 1: Pass first try (70% of articles)
- Generation: $0.015
- Quality check: $0.008
- Total: $0.023

Scenario 2: Pass second try (20%)
- Generation × 2: $0.030
- Quality check × 2: $0.016
- Total: $0.046

Scenario 3: Pass third try (5%)
- Total: $0.069

Scenario 4: Fail all attempts (5%)
- Total: $0.069 (wasted)

Weighted Average per Article:
(0.70 × $0.023) + (0.20 × $0.046) + (0.10 × $0.069)
= $0.031 per article

300 articles/month × $0.031 = $9.30/month
```

**Infrastructure:**
- GitHub Actions: $0 (under free tier)
- GitHub Pages: $0 (free)
- Domain: $12/year = $1/month
- Email (SendGrid): $0 (free tier)

**Total: ~$10-11/month**

### Revenue Projections

**Month 1: Launch**
- Visitors: 50-100/day
- Pageviews: 1.5-3k/month
- AdSense: $3-10
- Net: -$8

**Month 2: Early Growth**
- Visitors: 200-400/day
- Pageviews: 6-12k/month
- AdSense: $15-30
- Newsletter subs: 50
- Net: $5-20

**Month 3: Traction**
- Visitors: 500-1000/day
- Pageviews: 15-30k/month
- AdSense: $40-80
- Newsletter subs: 150
- Net: $30-70

**Month 6: Established**
- Visitors: 2000/day
- Pageviews: 60k/month
- AdSense: $150-250
- Premium subs: 20 × $5 = $100
- Net: $240-340

**Break-even:** Month 2-3

---

## Implementation Roadmap

This section documents the original build-and-launch sequence. The current monetization implementation plan is maintained separately in [docs/monetization-roadmap.md](docs/monetization-roadmap.md).

### Phase 1: MVP Core (Weeks 1-2)

**Goal:** End-to-end pipeline working locally

**Week 1: Core Components**
- Day 1-2: Project setup
  - Docker environment
  - Config system
  - Logging framework
- Day 3-4: Topic Discovery
  - RSS fetching from 10 sources
  - SpaCy entity extraction
  - Basic ranking
- Day 5-6: Content Fetcher
  - Trafilatura integration
  - Source truncation
  - Error handling
- Day 7: Testing & Integration

**Week 2: Generation & Quality**
- Day 8-9: Content Generator
  - LLM prompt templates
  - A2/B1 generation
  - JSON parsing
- Day 10-11: Quality Gate
  - Scoring system
  - Regeneration logic
  - Feedback integration
- Day 12-13: Publisher
  - Jekyll markdown output
  - Git operations
- Day 14: End-to-end testing

**Success Criteria:**
- ✅ Run `make run` locally
- ✅ Generate 4 articles in `output/_posts/`
- ✅ Articles readable Spanish at correct levels
- ✅ Quality scores average 7.5+
- ✅ Total cost per run < $0.20

**Cost:** $1-2 for testing (50-100 test articles)

---

### Phase 2: Automation & Launch (Week 3)

**Goal:** Automated generation + live website

**Day 15-16: GitHub Actions**
- Configure workflows (3x daily)
- Set up secrets
- Test manual trigger
- Configure notifications

**Day 17-18: Jekyll Site**
- Choose minimal theme
- Configure layouts
- Add Google AdSense code
- Create homepage

**Day 19-20: Deployment**
- Configure GitHub Pages
- Set up custom domain
- Add analytics (Plausible/GA)
- SSL certificate

**Day 21: Launch Day**
- Generate initial batch (20 articles)
- Test entire flow
- Monitor first automated run
- Fix any issues

**Success Criteria:**
- ✅ 3 automated runs/day working
- ✅ Website live and accessible
- ✅ Ads showing
- ✅ No critical errors for 3 days
- ✅ 12 new articles appearing daily

**Cost:** $10/month starts

---

### Phase 3: Growth & Marketing (Weeks 4-8)

**Goal:** 500 visitors/day, first revenue

**Week 4: Content Quality**
- Analyze published articles
- Adjust prompts based on feedback
- Add more sources (30 total)
- Improve topic selection

**Week 5-6: SEO & Marketing**
- Submit to Google Search Console
- Optimize meta tags
- Schema markup
- Reddit strategy (r/Spanish)
- Create TikTok/Reels (5/week)

**Week 7-8: Growth Tactics**
- Discord/Slack seeding
- Newsletter setup
- Reach out to Spanish teachers
- Create printable worksheets

**Success Criteria:**
- ✅ 500 visitors/day
- ✅ 100 email subscribers
- ✅ $30-50 AdSense revenue
- ✅ Breaking even on costs

**Timeline:** 4-6 weeks of consistent marketing

---

### Phase 4: Scaling (Month 3+)

**Goal:** $200-500/month revenue

**Potential Additions:**
1. TTS audio for articles
2. Quizzes and flashcards
3. Premium subscription tier
4. More levels (A1, C1)
5. Additional languages (French, German)

**Success Criteria:**
- ✅ 2000+ visitors/day
- ✅ $200+ monthly revenue
- ✅ Profitable operation
- ✅ Consistent quality (7.8+ avg)

---

## Technical Specifications

### System Requirements

**Development:**
- Docker & Docker Compose
- Git
- 2GB RAM minimum
- 5GB disk space

**Production:**
- GitHub account
- GitHub Actions (free tier)
- Custom domain (optional)

### API Requirements

**Required:**
- Anthropic API key (Claude)
  - Model access: claude-sonnet-4, claude-haiku-4
  - Rate limit: 50 requests/minute

**Optional:**
- OpenAI API key (fallback)
  - Model: gpt-4o-mini

### Performance Targets

**Per Run:**
- Duration: <15 minutes
- Articles: 4 published
- Success rate: >80%
- Average quality: >7.5/10
- Cost: <$0.20

**Daily:**
- Total articles: 12
- Total cost: <$0.60
- Total duration: <45 minutes compute

**Reliability:**
- Uptime: >99%
- Failed runs: <1% (max 1/month)
- Data loss: 0 (git-tracked)

### Security Considerations

**API Keys:**
- Never commit to git
- Use GitHub Secrets in CI
- Use environment variables locally
- Rotate every 90 days

**Content Security:**
- Multi-source synthesis (no copying)
- Clear attribution
- Respect robots.txt
- Rate limit scraping (10 req/min)

**Data Privacy:**
- No user data collected (static site)
- Analytics: privacy-friendly (Plausible)
- GDPR: No cookies needed for core site

### Legal Compliance

**Copyright:**
- ✅ Multi-source synthesis
- ✅ Substantial transformation
- ✅ Educational purpose
- ✅ Clear attribution
- ✅ <300 words per source

**Attribution:**
```
Fuentes consultadas: El País, BBC Mundo, Wikipedia
Artículo educativo generado con fines de aprendizaje de idiomas.
```

**Takedown Process:**
- Contact form on website
- Response within 24 hours
- Remove content within 48 hours if valid

---

## Key Design Decisions

### Critical Choices

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| **GitHub Actions** | Free, simple, native git integration | 2000 min/month limit |
| **Jekyll + GitHub Pages** | Free hosting, zero maintenance | Static only, no user accounts |
| **Multi-source synthesis** | Legal safety, originality | More complex than single source |
| **7.5/10 quality threshold** | High quality bar | Lower volume, higher cost |
| **Auto-publish with quality gate** | Speed to market, passive income | Risk of bad content |
| **Regeneration with feedback** | Higher success rate (95% vs 60%) | 2-3x cost for some articles |
| **SpaCy for NER** | Free, fast, accurate | Requires model download |
| **Docker containers** | Portable, reproducible | Slightly more complex setup |
| **File-based metrics** | Free, git-tracked, no external deps | Manual analysis required |

### Flexible Aspects

**Can change without major refactoring:**
- LLM provider (Anthropic ↔ OpenAI)
- Static site generator (Jekyll → Hugo)
- Hosting platform (GitHub → AWS/Cloudflare)
- Number of runs per day
- Article levels (add A1, C1, etc.)
- Source list (add/remove feeds)

---

## Success Metrics

### Week 1 (MVP):
- ✅ Pipeline runs end-to-end
- ✅ 4 articles generated
- ✅ Quality > 7.5 average
- ✅ Cost per article < $0.05

### Week 3 (Launch):
- ✅ Website live
- ✅ 3 automated runs/day
- ✅ 12 articles/day published
- ✅ Zero critical errors

### Month 1:
- ✅ 360 articles published
- ✅ 100 visitors/day
- ✅ Cost: $10/month
- ✅ Revenue: $5-15

### Month 3 (Break-even):
- ✅ 1000 articles total
- ✅ 500 visitors/day
- ✅ 100 email subscribers
- ✅ Revenue: $50-100
- ✅ Break-even or profitable

### Month 6 (Established):
- ✅ 2000 articles total
- ✅ 2000 visitors/day
- ✅ 500 email subscribers
- ✅ Revenue: $250-400
- ✅ Profitable operation

---

## Risk Mitigation

### Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| API rate limits | Medium | High | Exponential backoff, retry logic |
| Quality degradation | Medium | High | Daily quality monitoring, prompt tuning |
| GitHub Actions downtime | Low | Medium | Manual trigger available, cached content |
| Source site changes | High | Low | Multiple sources per topic |
| LLM output changes | Medium | Medium | Version pinning, prompt testing |

### Business Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Low traffic | High | High | SEO focus, active marketing |
| AdSense rejection | Low | High | Quality content, clear attribution |
| Copyright claims | Low | High | Multi-source synthesis, takedown process |
| Cost overruns | Low | Medium | Hard budget limits, monitoring |
| Competition | Medium | Low | Focus on quality, learner experience |

### Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Burnout (marketing) | Medium | High | Automate everything possible |
| Technical debt | Medium | Medium | Modular design, refactor early |
| Dependency issues | Low | Low | Docker isolation, version pinning |

---

## Appendix

### Glossary

- **A2/B1:** CEFR language proficiency levels (Beginner/Intermediate)
- **Jekyll:** Static site generator (converts markdown to HTML)
- **SpaCy:** NLP library for named entity recognition
- **Trafilatura:** Web scraping library optimized for news articles
- **CEFR:** Common European Framework of Reference for Languages
- **NER:** Named Entity Recognition (extracting people, places, orgs)

### References

- **CEFR Levels:** https://www.coe.int/en/web/common-european-framework-reference-languages
- **Jekyll Documentation:** https://jekyllrb.com/docs/
- **GitHub Actions:** https://docs.github.com/actions
- **Anthropic API:** https://docs.anthropic.com
- **SpaCy Spanish Models:** https://spacy.io/models/es

### Future Enhancements

**Short-term (Month 3-6):**
- Add TTS audio using Edge TTS or ElevenLabs
- Create quiz/flashcard system
- Premium newsletter tier
- Mobile app (optional)

**Long-term (Month 6+):**
- Multiple languages (French, German, Italian)
- User accounts and progress tracking
- Community features (comments, forums)
- Mobile apps (iOS/Android)
- API for third-party integrations

---

## Contact & Support

**Repository:** https://github.com/yourusername/autospanishblog  
**Issues:** https://github.com/yourusername/autospanishblog/issues  
**Email:** your@email.com

---

**Document Version:** 1.1  
**Last Updated:** March 18, 2026  
**Author:** Alex  
**Status:** Ready for Implementation

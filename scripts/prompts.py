"""
Centralized LLM Prompts

All prompts for content generation and quality evaluation in one place
for easy iteration and A/B testing.
"""

from typing import List, Optional

from scripts.models import (
    AdaptedArticle,
    BaseArticle,
    SourceArticle,
    Topic,
)

# Level-specific grammar rules
LEVEL_GENERATION_RULES = {
    'A2': """
- Use mostly Präsens
- Use Perfekt only for completed past events when needed
- Simple sentences (max 12 words per sentence)
- Vocabulary: common everyday German words; explain unavoidable news terms simply
- Avoid Konjunktiv I/II and heavy nominal style
- Short, clear sentences
""",
    'B1': """
- Mix tenses naturally: Präsens, Perfekt, Präteritum for common reporting verbs, Futur with werden sparingly
- Varied sentence length (8-18 words)
- Intermediate vocabulary
- Avoid dense nominalizations and long bracket constructions
- Some complex sentences with subordinate clauses
"""
}

LEVEL_EVALUATION_CRITERIA = {
    'A2': """
A2 Level Grammar Expectations:
- Präsens should be primary
- Perfekt only for completed actions when needed
- No Konjunktiv I/II
- Simple sentence structures
- Basic connectors (und, aber, weil, wenn, dann)
""",
    'B1': """
B1 Level Grammar Expectations:
- Mixed tenses: Präsens, Perfekt, common Präteritum forms, simple Futur
- More complex sentences with subordinate clauses
- Varied connectors (obwohl, während, deshalb, trotzdem, weil)
"""
}

# A2 News Processing Instructions (text adaptation only)
A2_NEWS_PROCESSING_INSTRUCTIONS = """
You are a German language education specialist tasked with adapting news articles to A2 CEFR level while maintaining their informational value. Your job is to produce a clean A2 German article. Glossary creation happens later in a separate stage, so do not create glossary entries or markdown emphasis.

=== STEP 1: VOCABULARY ASSESSMENT ===

1.1 Identify ALL words/phrases outside common A2 German vocabulary
1.2 Categorize identified words/phrases:
    - Category A: Essential for understanding the main story
    - Category B: Important but secondary information
    - Category C: Can be eliminated or simplified without loss
1.3 From Category A and B, rank by importance for the article's main message
1.4 Simplify or rewrite Category B and C terms whenever possible
1.5 For Category A terms, explain them naturally in the article instead of preserving them for a glossary
1.6 Do not add markdown bolding, glossary markers, or vocabulary notes anywhere in the article
1.7 Do not rely on later glossary support to justify keeping difficult wording in the text

=== STEP 2: STRUCTURAL MODIFICATIONS ===

2.1 SENTENCE RESTRUCTURING
    - Break any sentence exceeding 20 words into 2-3 shorter sentences
    - Target length: 10-15 words per sentence
    - Maximum length: 20 words (hard limit)
    - Minimum length: 8 words (for substance)

2.2 VERB TENSE SIMPLIFICATION
    Allowed tenses:
    - Präsens
    - Perfekt for completed past events when needed
    - simple future with werden only when needed

    Required conversions:
    - Konjunktiv I/II → simple indicative wording
    - passive voice → active voice where possible
    - dense nominal style → verb-based clauses
    - long verb brackets → shorter sentences

2.3 SYNTACTIC SIMPLIFICATION
    - Convert ALL passive voice to active voice
    - Replace subordinate clauses with simple sentences
    - Use basic conjunctions only: und, aber, weil, wenn, dann
    - Ensure subject-verb proximity (maximum 5 words between)
    - Maintain chronological order when possible

2.4 TRANSITION WORDS
    Add these connectors for flow:
    - Sequence: zuerst, dann, danach, am Ende
    - Addition: auch, außerdem
    - Contrast: aber, trotzdem
    - Cause: weil, deshalb
    - Time: wenn, als, vor, nach

=== STEP 3: CONTENT ORGANIZATION ===

3.1 ARTICLE STRUCTURE
    Title: Maximum 10 words, clear and direct

    Lead paragraph (2-3 sentences):
    - WHO is involved?
    - WHAT happened/will happen?
    - WHEN did/will it occur?
    - WHERE did/will it take place?

    Body paragraphs (3-4 sentences each):
    - One main idea per paragraph
    - Supporting details in simple sentences
    - Clear topic sentence for each paragraph

    Conclusion (1-2 sentences, optional):
    - Summary or future implications
    - Keep very simple

3.2 PARAGRAPH GUIDELINES
    - Maximum 5 sentences per paragraph
    - Start with clearest, simplest statement
    - Add supporting details progressively
    - End with transition to next paragraph

=== STEP 4: QUALITY VERIFICATION ===

Before finalizing, verify:

□ VOCABULARY
  - Most words are within A2-level German
  - Difficult terms are simplified or explained naturally in the text
  - No glossary markers or markdown emphasis appear in the article

□ STRUCTURE
  - No sentence exceeds 20 words
  - Average sentence length is 10-15 words
  - Mostly Präsens, with Perfekt only when needed
  - No passive voice constructions
  - No Konjunktiv I/II

□ CONTENT
  - Main news value is preserved
  - Facts remain accurate
  - Key actors are clearly identified
  - Temporal sequence is clear
  - Cause-effect relationships are simplified but maintained

□ READABILITY
  - Text flows naturally in German
  - Transitions between sentences are smooth
  - Paragraphs are clearly organized
  - Cultural references are explained

=== STEP 5: OUTPUT FORMAT ===

Format the final article as follows:

# [Simplified Headline - max 10 words]

[Lead paragraph - 2-3 sentences summarizing key facts]

[Body paragraph 1 - main development]

[Body paragraph 2 - additional information]

[Optional body paragraph 3 - context or implications]

SPECIAL HANDLING:

For Complex Political Terms:
1. Explain institutions by function in the body text
2. Simplify political processes to basic cause-effect
3. Avoid complex political ideology or theory
4. Focus on concrete actions rather than abstract policies

For Economic/Financial Content:
1. Replace percentages with simple descriptions when possible
2. Simplify large numbers
3. Rewrite economic terminology into simpler German when possible
4. Focus on human impact rather than abstract markets

For Cultural References:
1. Always provide context inside the article
2. Compare to universal concepts when possible
3. Don't assume cultural knowledge
4. Keep explanations factual and neutral

For Breaking News or Crises:
1. Maintain factual accuracy absolutely
2. Simplify emotional language
3. Focus on facts over speculation
4. Avoid sensationalism in simplification

ERROR HANDLING:

If vocabulary simplification conflicts with meaning:
- Priority: Preserve meaning over strict A2 compliance
- Solution: explain the complex term in simple German rather than using inaccurate wording

If sentence cannot be shortened:
- Accept sentences up to 25 words if absolutely necessary
- Must be clearly structured with simple vocabulary
- Should be rare exceptions

If the article remains too dense:
- Prioritize simplification of the most important concepts
- Reduce secondary detail
- Consider whether the article needs stronger condensation to fit A2

VALIDATION EXAMPLES:

Good Simplification:
❌ Original: "Die Bundesregierung äußerte Besorgnis über den deutlichen Anstieg der Inflationsrate."
✅ Simplified: "Die Regierung ist besorgt. Viele Preise steigen stark."

Good Vocabulary Choice:
✅ Keep: "Die Preise steigen stark."
❌ Don't keep: "Inflationsrate" if simple wording can replace it

Good Sentence Breaking:
❌ Original: "Der Minister, der gestern aus Brüssel zurückkam, wo er an einem Klimagipfel teilnahm, kündigte neue Investitionen in erneuerbare Energien an."
✅ Simplified: "Der Minister war gestern in Brüssel. Dort gab es ein Treffen zum Klima. Er sagte: Deutschland will mehr Geld für saubere Energie ausgeben."
"""

# B1 Adaptation Instructions (text adaptation only)
B1_ADAPTATION_INSTRUCTIONS = """
You are a German language education specialist tasked with adapting news articles to B1 CEFR level while maintaining their informational value. Keep authentic news style but make the language accessible to solid intermediate learners. Glossary creation happens later in a separate stage, so do not create glossary entries or markdown emphasis.

=== B1 ADAPTATION GUIDELINES ===

STEP 1: VOCABULARY ASSESSMENT
1.1 Identify words/phrases outside common B1 German vocabulary.
1.2 Keep only terminology that is necessary for the story's meaning and simplify the rest.
1.3 Explain cultural, institutional, and technical terms naturally in context when needed.
1.4 Do not add **bold** formatting, glossary entries, or vocabulary notes.
1.5 Do not preserve difficult wording just because a future glossary could explain it.

STEP 2: STRUCTURE AND GRAMMAR TUNING
2.1 Sentence shaping
    - Target average length: 12-20 words; absolute maximum: 25 words
    - One main idea per sentence; split clauses that stack multiple actions
    - Use varied connectors: obwohl, während, deshalb, trotzdem, außerdem
2.2 Tense and mood guidance
    - Mix Präsens, Perfekt, common Präteritum forms, and simple Futur
    - Maintain chronological flow when narrating events
    - Avoid Konjunktiv I/II and heavy passive voice; convert to active voice where possible
2.3 Complexity reduction
    - Replace nested subordinate clauses with clearer sentences
    - Convert passive to active when it keeps meaning intact
    - Prefer concrete, direct constructions over abstract phrasing

STEP 3: CONTENT ORGANIZATION AND VOICE
- Title: Clear and engaging (8-10 words)
- Lead paragraph: WHO, WHAT, WHEN, WHERE
- Body: 3-4 paragraphs with clear topic sentences
- Use connectors to show cause, contrast, and sequence
- Preserve all key facts and maintain chronological order
- Tone: informative and accessible; do not oversimplify general vocabulary

STEP 4: QUALITY VERIFICATION BEFORE OUTPUT
□ Word count is ~300 words (acceptable range 270-330)
□ Sentences average 12-20 words; none exceed 25 words
□ Mixed tenses appear naturally; subjunctive limited to common expressions
□ Passive voice avoided unless meaning requires it
□ Difficult terms are explained naturally in context when needed
□ No glossary markers or markdown emphasis appear
□ Facts, chronology, and nuance from the base article are preserved
□ Connectors and paragraph structure create clear flow
"""


def validate_level(level: str) -> None:
    """
    Validate that the level exists in both rule dictionaries

    Args:
        level: CEFR level to validate

    Raises:
        ValueError: If level is not supported
    """
    if level not in LEVEL_GENERATION_RULES:
        raise ValueError(
            f"Unsupported level '{level}'. "
            f"Supported levels: {', '.join(LEVEL_GENERATION_RULES.keys())}"
        )
    if level not in LEVEL_EVALUATION_CRITERIA:
        raise ValueError(
            f"Level '{level}' missing evaluation criteria. "
            f"Available criteria for: {', '.join(LEVEL_EVALUATION_CRITERIA.keys())}"
        )


def prepare_source_context(sources: List[SourceArticle]) -> str:
    """
    Prepare source text for prompt with XML-like structure

    Args:
        sources: List of SourceArticle objects with 'source' and 'text' keys

    Returns:
        Formatted source context string with XML-like tags
    """
    context = []

    for i, source in enumerate(sources[:5], 1):
        source_name = f" ({source.source})" if source.source else ""
        context.append(f"""<source_{i}{source_name}>
{source.text}
</source_{i}>""")

    return '\n\n'.join(context)


def get_generation_prompt(
    topic: Topic,
    sources: List[SourceArticle],
    level: str,
    word_count: int
) -> str:
    """
    Prompt for initial article generation

    Generates an original German article by synthesizing multiple sources.
    Uses level-specific grammar rules and vocabulary constraints.

    Args:
        topic: Topic dict with 'title' key
        sources: List of source content dicts
        level: CEFR level ('A2' or 'B1')
        word_count: Target word count (200 for A2, 300 for B1)

    Returns:
        Complete prompt string for LLM

    Raises:
        ValueError: If level is not supported
    """
    validate_level(level)
    source_context = prepare_source_context(sources)

    prompt = f"""You are a German language teacher creating educational content for {level} level students.

TOPIC: {topic.title}

REFERENCE SOURCES (synthesize information, DO NOT copy text):
{source_context}

TASK: Create an ORIGINAL article in German that:
1. Synthesizes information from the sources above in your own words
2. Is appropriate for {level} German learners
3. Is approximately {word_count} words long
4. Has 3 clear paragraphs with good flow
5. Includes cultural context relevant to German learners when useful
6. Is engaging and educational

LEVEL REQUIREMENTS for {level}:
{LEVEL_GENERATION_RULES[level]}

OUTPUT FORMAT (return ONLY valid JSON, no markdown):
{{
  "title": "Engaging title in German (5-8 words)",
  "content": "Full article text in German (~{word_count} words, 3 paragraphs)",
  "vocabulary": {{
    "word1": "English translation",
    "word2": "English translation"
  }},
  "summary": "One sentence summary in German",
  "reading_time": estimated_minutes_as_integer
}}

CRITICAL RULES:
- Write ORIGINAL content - synthesize ideas but use your own words
- DO NOT copy phrases from the sources
- This is educational fair use - transform the information
- DO NOT add source attribution or source details
"""

    return prompt


def get_regeneration_prompt(
    topic: Topic,
    sources: List[SourceArticle],
    level: str,
    word_count: int,
    previous_attempt: AdaptedArticle,
    issues: List[str]
) -> str:
    """
    Prompt for article regeneration with feedback

    Used when quality check fails. Includes previous attempt and specific
    issues that need to be fixed.

    Args:
        topic: Topic dict with 'title' key
        sources: List of source content dicts
        level: CEFR level ('A2' or 'B1')
        word_count: Target word count
        feedback: Dict with 'previous_title', 'previous_content', 'issues'

    Returns:
        Complete prompt string with feedback section
    """
    # Get base prompt
    base_prompt = get_generation_prompt(topic, sources, level, word_count)

    # Truncate previous content to first 200 words for context
    first_200 = ' '.join(previous_attempt.content.split()[:200])

    # Add feedback section
    feedback_section = f"""

⚠️ IMPORTANT: PREVIOUS ATTEMPT HAD ISSUES - YOU MUST FIX THEM

Previous Title: {previous_attempt.title}

Previous Content (first 200 words):
{first_200}...

SPECIFIC ISSUES TO FIX:
{chr(10).join("- " + issue for issue in issues)}

Generate a NEW, IMPROVED version that specifically addresses these issues.
Make sure to fix the problems mentioned above.
"""

    return base_prompt + feedback_section


def get_quality_judge_prompt(article: AdaptedArticle, level: str) -> str:
    """
    Prompt for quality evaluation

    LLM judge scores article on 4 criteria (0-10 total):
    - Grammar & Language (0-4)
    - Educational Value (0-3)
    - Content Quality (0-2)
    - Level Appropriateness (0-1)

    Args:
        article: Article dict with 'title', 'content', and text metadata
        level: CEFR level ('A2' or 'B1')

    Returns:
        Complete prompt string for quality judge

    Raises:
        ValueError: If level is not supported
    """
    validate_level(level)
    prompt = f"""You are a German language teaching expert. Evaluate this article for {level} level learners.

ARTICLE:
Title: {article.title}
Level: {level}
Content:
{article.content}

EVALUATION CRITERIA (total 0-10 points):

1. Grammar & Language (0-4 points):
{LEVEL_EVALUATION_CRITERIA[level]}
- Are there any grammar errors?
- Is the grammar appropriate for {level}?

2. Educational Value (0-3 points):
- Is this interesting and useful for German learners?
- Does it teach cultural concepts?
- Is the article itself useful as a learning text?

3. Content Quality (0-2 points):
- Is the information accurate and coherent?
- Is it well-structured (clear paragraphs)?
- Does it flow naturally?

4. Level Appropriateness (0-1 point):
- Is vocabulary suitable for {level}?
- Is sentence complexity appropriate?
- Would this engage {level} learners?

OUTPUT FORMAT (return ONLY valid JSON, no markdown):
{{
  "grammar_score": 0-4,
  "grammar_issues": ["specific issue 1", "specific issue 2"] or [],

  "educational_score": 0-3,
  "educational_notes": "brief comment",

  "content_score": 0-2,
  "content_issues": ["issue1"] or [],

  "level_score": 0-1,

  "total_score": sum_of_all_scores,

  "issues": ["All specific issues that need fixing"],
  "strengths": ["What the article does well"],

  "recommendation": "PASS or FAIL with reason"
}}

BE STRICT. A score of 7.5+ means genuinely good educational content.
Lower scores should identify specific, actionable issues to fix.
"""

    return prompt


def get_news_processing_prompt(article_text: str, source_url: Optional[str] = None, source_date: Optional[str] = None) -> str:
    """
    Prompt for processing news articles to A2 level with glossing

    Adapts existing news content to A2 CEFR level while preserving
    informational value through strategic glossing of key terminology.

    Args:
        article_text: Original German news article text
        source_url: Optional URL of the original article
        source_date: Optional publication date

    Returns:
        Complete prompt string for news processing
    """
    source_info = ""
    if source_url:
        source_info += f"\nSource URL: {source_url}"
    if source_date:
        source_info += f"\nPublication Date: {source_date}"

    prompt = f"""{A2_NEWS_PROCESSING_INSTRUCTIONS}

=== ARTICLE TO PROCESS ===
{source_info}

{article_text}

=== YOUR TASK ===
Process the above article following ALL steps (1-5) in the instructions above.
Ensure you verify quality (Step 4) before outputting the final formatted article (Step 5).

Remember:
- Process in multiple passes (vocabulary → structure → verification)
- Maintain factual accuracy absolutely
- Preserve the core news value
- Make it accessible to A2 learners while maintaining authenticity
"""

    return prompt


# ============================================================================
# TWO-STEP SYNTHESIS PROMPTS
# ============================================================================


def get_synthesis_prompt(topic: Topic, sources: List[SourceArticle]) -> str:
    """
    Step 1: Native-level synthesis without CEFR constraints

    Synthesizes multiple source articles into one coherent native-level
    German article. No vocabulary limitations or grammar simplification.
    Focus is on factual accuracy and natural German expression.

    Args:
        topic: Topic dict with 'title' key
        sources: List of source content dicts with 'source' and 'text' keys

    Returns:
        Complete prompt string for native-level synthesis
    """
    source_context = prepare_source_context(sources)

    prompt = f"""You are a professional German journalist. Synthesize the following sources into ONE coherent news article in natural, native-level German.

TOPIC: {topic.title}

TASK: Write an ORIGINAL article in German that:
1. Synthesizes facts from all sources into a coherent narrative
2. Uses natural, native-level German (no simplification)
3. Is approximately 300-400 words
4. Has 3-4 well-structured paragraphs
5. Maintains journalistic objectivity and accuracy
6. Flows naturally with good transitions

CRITICAL RULES:
- Write ORIGINAL content - synthesize ideas in your own words
- DO NOT copy phrases directly from sources
- Cross-validate facts across sources (prioritize information from multiple sources)
- Use natural German vocabulary and grammar (no CEFR constraints)
- Focus on FACTUAL ACCURACY above all else
- DO NOT add source attribution or source details
- Maintain a neutral, journalistic tone

OUTPUT FORMAT (return ONLY valid JSON, no markdown):
{{
  "title": "Engaging headline in German (8-12 words)",
  "content": "Full article in natural German (300-400 words, 3-4 paragraphs)",
  "summary": "One sentence summary in German",
  "reading_time": estimated_minutes_as_integer
}}

Remember: This is native-level German. Write naturally and accurately without any simplification.

SOURCES TO SYNTHESIZE:
{source_context}
"""

    return prompt


def get_a2_adaptation_prompt(
    base_article: BaseArticle,
    feedback: Optional[List[str]] = None
) -> str:
    """
    Step 2: Adapt base article to A2 level using glossing strategy

    Adapts a native-level German article to A2 CEFR level while preserving
    informational value through strategic glossing of key terminology.
    Uses existing A2_NEWS_PROCESSING_INSTRUCTIONS.

    Args:
        base_article: Base article dict from ArticleSynthesizer with native German
        feedback: Optional list of issues from quality gate (for regeneration)

    Returns:
        Complete prompt string for A2 adaptation
    """
    feedback_section = ""
    if feedback:
        issues_list = chr(10).join("- " + issue for issue in feedback)
        feedback_section = f"""
⚠️ PREVIOUS ATTEMPT HAD ISSUES - FIX THEM:
{issues_list}

Make sure to specifically address these issues in your adaptation.
"""

    prompt = f"""{A2_NEWS_PROCESSING_INSTRUCTIONS}



=== YOUR TASK ===

Adapt the below NATIVE-LEVEL article to A2 CEFR level following ALL steps (1-5) in the instructions above.

    Key points:
    - This is already a well-written, factually accurate article
    - Your job is to make it A2-accessible while preserving the information
    - Simplify grammar and sentence structure
    - Maintain factual accuracy absolutely
    - Target word count: ~200 words
    - Do not include vocabulary lists or markdown emphasis

OUTPUT FORMAT (return ONLY valid JSON, no markdown):
{{
  "title": "Simplified title (max 10 words)",
  "content": "A2-adapted content in plain text only (~200 words), with no markdown emphasis and no glossary",
  "summary": "One sentence summary in simple German",
  "reading_time": 2
}}

IMPORTANT: Follow the above A2 processing instructions exactly. Verify all requirements in Step 4 before outputting.

=== ARTICLE TO ADAPT ===

Title: {base_article.title}

Content:
{base_article.content}

{feedback_section}
"""

    return prompt


def get_b1_adaptation_prompt(
    base_article: BaseArticle,
    feedback: Optional[List[str]] = None
) -> str:
    """
    Step 2: Adapt base article to B1 level (light adaptation)

    Adapts a native-level German article to B1 CEFR level.
    Similar structure to A2 but less restrictive.
    This is designed to be similar to A2 prompt but will be refined externally.

    Args:
        base_article: Base article dict from ArticleSynthesizer with native German
        feedback: Optional list of issues from quality gate (for regeneration)

    Returns:
        Complete prompt string for B1 adaptation
    """
    feedback_section = ""
    if feedback:
        issues_list = chr(10).join("- " + issue for issue in feedback)
        feedback_section = f"""
⚠️ PREVIOUS ATTEMPT HAD ISSUES - FIX THEM:
{issues_list}

Make sure to specifically address these issues in your adaptation.
"""

    prompt = f"""{B1_ADAPTATION_INSTRUCTIONS}

=== BASE ARTICLE ===

Title: {base_article.title}

Content:
{base_article.content}

{feedback_section}

=== YOUR TASK ===
Adapt the above native-level article to B1 CEFR level following ALL steps in the B1 Adaptation Guidelines.

Key goals:
- Preserve the article's facts and chronology
- Make specialized terminology accessible through context and clearer wording
- Keep authentic tone while keeping sentences clear and within length limits
- Target word count: ~300 words (acceptable range 270-330)
- Do not include vocabulary lists or markdown emphasis

OUTPUT FORMAT (return ONLY valid JSON, no markdown):
{{
  "title": "Engaging title in German (8-10 words)",
  "content": "B1-adapted content in plain text only (~300 words), with no markdown emphasis and no glossary",
  "summary": "One sentence summary in German",
  "reading_time": 3
}}

QUALITY VERIFICATION (must check BEFORE outputting JSON):
□ All checklist items in STEP 4 are satisfied
□ Word count within range and sentences under 25 words
□ Mixed tenses and appropriate connectors are present
□ Facts and nuance from the base article are preserved

Remember: B1 learners have solid intermediate skills. Maintain authenticity while ensuring clarity and support through the article text itself.
"""

    return prompt


def get_glossary_generation_prompt(article: AdaptedArticle) -> str:
    """Prompt for broad clickable translation hints from the final approved article text."""
    validate_level(article.level)

    target_counts = {"A2": "20-40", "B1": "25-55"}
    default_counts = {"A2": "4-8", "B1": "5-9"}
    max_words = {"A2": 15, "B1": 20}
    explanation_style = {
        "A2": "Use only very simple German vocabulary.",
        "B1": "Use clear intermediate German vocabulary.",
    }

    return f"""You are generating clickable translation hints for an English-speaking learner reading this German article.

Use ONLY the exact final article text below. The article itself is already approved, so do not rewrite it.

SELECTION RULES:
- Choose many words or phrases that are useful for an English-speaking learner.
- Be broad and systematic: scan every sentence for learner-useful terms, not only the main news nouns.
- Prefer standalone words, separable German compounds, and short reusable expressions.
- Include a balanced mix of nouns, compound nouns, verbs, adjectives, adverbs, and short fixed expressions.
- Include useful verbs and adjectives even when they are not important enough for the default visible glossary.
- Use phrases only when the complete phrase has a meaning a learner would not understand from the individual words.
- Keep phrase terms short: usually 1 word, sometimes 2 words, never more than 3 words.
- Do not select long sentence fragments such as adjective + noun + prepositional phrase.
- Include enough useful terms that a learner can click through much of the article text.
- Avoid proper names, country names, common place names, and famous people.
- Avoid obvious cognates and transparent loanwords that an English speaker can easily guess.
- Do not select German words that look very similar to English and have the same meaning, such as Temperaturen/temperatures or Infrastruktur/infrastructure.
- Avoid isolated modifiers when the real useful unit is a longer phrase.
- Mark only the strongest learner terms as default_glossary=true.
- Mark all other useful click-only terms as default_glossary=false.
- If the article only contains a few useful candidates, return only those. Do not add filler terms.

LEVEL GUIDANCE:
- Target {target_counts[article.level]} clickable translation hints when possible.
- Target {default_counts[article.level]} default glossary entries when possible.
- {explanation_style[article.level]}
- Maximum {max_words[article.level]} words per German explanation.

OUTPUT FORMAT (return ONLY valid JSON, no markdown):
{{
  "vocabulary": [
    {{
      "term": "exact word or phrase from the article text",
      "english": "natural English translation",
      "explanation": "short German explanation for the learner",
      "default_glossary": true
    }}
  ]
}}

ARTICLE:
Title: {article.title}
Level: {article.level}
Content:
{article.content}
"""


def get_glossary_retry_prompt(
    article: AdaptedArticle,
    rejected_terms: dict[str, str],
    shortlist: list[str],
) -> str:
    """Prompt for retrying glossary generation after deterministic validation rejects everything."""
    validate_level(article.level)

    target_counts = {"A2": "20-40", "B1": "25-55"}
    default_counts = {"A2": "4-8", "B1": "5-9"}
    max_words = {"A2": 15, "B1": 20}
    explanation_style = {
        "A2": "Use only very simple German vocabulary.",
        "B1": "Use clear intermediate German vocabulary.",
    }
    rejected_lines = "\n".join(
        f"- {term}: {reason}"
        for term, reason in rejected_terms.items()
    ) or "- No rejected terms recorded"
    shortlist_lines = "\n".join(f"- {term}" for term in shortlist) or "- No shortlist available"

    return f"""You are retrying clickable translation hint generation for an English-speaking learner reading this German article.

The previous glossary attempt failed deterministic validation. Generate a NEW set of candidates from the exact article text below.

HARD RULES:
- Do NOT return any rejected term again.
- Do NOT rewrite the article.
- Every term must appear literally in the article text.
- Be broad and systematic: scan every sentence for learner-useful terms, not only the main news nouns.
- Prefer standalone words, separable German compounds, domain nouns, and short reusable expressions.
- Include a balanced mix of nouns, compound nouns, verbs, adjectives, adverbs, and short fixed expressions.
- Include useful verbs and adjectives even when they are not important enough for the default visible glossary.
- Use phrases only when the complete phrase has a meaning a learner would not understand from the individual words.
- Keep phrase terms short: usually 1 word, sometimes 2 words, never more than 3 words.
- Do not select long sentence fragments such as adjective + noun + prepositional phrase.
- Avoid names, countries, famous people, obvious cognates, transparent loanwords, and isolated modifiers.
- Do not select German words that look very similar to English and have the same meaning, such as Temperaturen/temperatures or Infrastruktur/infrastructure.
- Mark only the strongest learner terms as default_glossary=true.
- Mark all other useful click-only terms as default_glossary=false.
- If only a few strong terms remain, return only those. Do not add filler terms.

PREVIOUSLY REJECTED TERMS:
{rejected_lines}

SUGGESTED LITERAL SPANS FROM THE ARTICLE:
{shortlist_lines}

LEVEL GUIDANCE:
- Target {target_counts[article.level]} clickable translation hints when possible.
- Target {default_counts[article.level]} default glossary entries when possible.
- {explanation_style[article.level]}
- Maximum {max_words[article.level]} words per German explanation.

OUTPUT FORMAT (return ONLY valid JSON, no markdown):
{{
  "vocabulary": [
    {{
      "term": "exact word or phrase from the article text, and not one of the rejected terms",
      "english": "natural English translation",
      "explanation": "short German explanation for the learner",
      "default_glossary": true
    }}
  ]
}}

ARTICLE:
Title: {article.title}
Level: {article.level}
Content:
{article.content}
"""

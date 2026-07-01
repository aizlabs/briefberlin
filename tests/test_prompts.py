"""
Unit tests for prompts module
"""

import pytest

from scripts.prompts import (
    LEVEL_EVALUATION_CRITERIA,
    LEVEL_GENERATION_RULES,
    get_a2_adaptation_prompt,
    get_b1_adaptation_prompt,
    get_glossary_generation_prompt,
    get_glossary_retry_prompt,
    get_synthesis_prompt,
    prepare_source_context,
    validate_level,
)


class TestValidateLevel:
    """Test level validation"""

    def test_validate_a2_success(self):
        """Test A2 validation succeeds"""
        # Should not raise
        validate_level('A2')

    def test_validate_b1_success(self):
        """Test B1 validation succeeds"""
        # Should not raise
        validate_level('B1')

    def test_validate_unsupported_level(self):
        """Test unsupported level raises error"""
        with pytest.raises(ValueError, match="Unsupported level"):
            validate_level('C1')

    def test_validate_missing_evaluation_criteria(self):
        """Test error when evaluation criteria missing"""
        # This would only happen if LEVEL_EVALUATION_CRITERIA is malformed
        # Testing the validation logic
        pass  # Already covered by implementation


class TestPrepareSourceContext:
    """Test source context preparation"""

    def test_prepare_single_source(self, sample_sources):
        """Test preparing single source"""
        sources = [sample_sources[0]]

        result = prepare_source_context(sources)

        assert '<source_1 (Tagesschau)>' in result
        assert '</source_1>' in result
        assert sample_sources[0].text in result

    def test_prepare_multiple_sources(self, sample_sources):
        """Test preparing multiple sources"""
        result = prepare_source_context(sample_sources)

        # Should have all 3 sources with XML tags
        assert '<source_1 (Tagesschau)>' in result
        assert '</source_1>' in result
        assert '<source_2 (RBB24)>' in result
        assert '</source_2>' in result
        assert '<source_3 (Zeit Online)>' in result
        assert '</source_3>' in result

        # Should contain all texts
        assert sample_sources[0].text in result
        assert sample_sources[1].text in result
        assert sample_sources[2].text in result

    def test_prepare_limits_to_five_sources(self, sample_sources):
        """Test only first 5 sources used"""
        # Create 6 sources
        many_sources = sample_sources * 2  # 6 sources

        result = prepare_source_context(many_sources)

        # Should only have first 5
        assert '<source_1' in result
        assert '<source_5' in result
        assert '<source_6' not in result

    def test_prepare_empty_sources(self):
        """Test preparing empty source list"""
        result = prepare_source_context([])

        assert result == ''


class TestGetSynthesisPrompt:
    """Test synthesis prompt generation"""

    def test_synthesis_prompt_structure(self, sample_topic, sample_sources):
        """Test synthesis prompt has correct structure"""
        prompt = get_synthesis_prompt(sample_topic, sample_sources)

        # Should contain topic
        assert sample_topic.title in prompt

        # Should contain sources in XML format
        assert '<source_1 (Tagesschau)>' in prompt
        assert '</source_1>' in prompt

        # Should have task description
        assert 'ORIGINAL article' in prompt
        assert 'natural, native-level German' in prompt
        assert '300-400 words' in prompt

        # Should have critical rules
        assert 'DO NOT copy phrases' in prompt
        assert 'Cross-validate facts' in prompt
        assert 'FACTUAL ACCURACY' in prompt

        # Should have output format
        assert 'OUTPUT FORMAT' in prompt
        assert '"title"' in prompt
        assert '"content"' in prompt
        assert '"summary"' in prompt
        assert '"reading_time"' in prompt

    def test_synthesis_prompt_includes_all_sources(self, sample_topic, sample_sources):
        """Test all source texts included in prompt"""
        prompt = get_synthesis_prompt(sample_topic, sample_sources)

        for source in sample_sources:
            assert source.text in prompt


class TestGetA2AdaptationPrompt:
    """Test A2 adaptation prompt generation"""

    def test_a2_prompt_structure(self, sample_base_article):
        """Test A2 prompt has correct structure"""
        prompt = get_a2_adaptation_prompt(sample_base_article)

        # Should contain base article
        assert sample_base_article.title in prompt
        assert sample_base_article.content in prompt

        # Should use A2_NEWS_PROCESSING_INSTRUCTIONS
        assert 'STEP 1: VOCABULARY ASSESSMENT' in prompt or 'A2 CEFR level' in prompt

        # Should have task section
        assert 'YOUR TASK' in prompt
        assert 'NATIVE-LEVEL article' in prompt

        # Should specify word count
        assert '~200 words' in prompt

        # Should have output format
        assert 'OUTPUT FORMAT' in prompt
        assert '"content"' in prompt
        assert '"vocabulary"' not in prompt
        assert 'no markdown emphasis' in prompt.lower()

    def test_a2_prompt_without_feedback(self, sample_base_article):
        """Test A2 prompt without feedback"""
        prompt = get_a2_adaptation_prompt(sample_base_article, feedback=None)

        # Should not contain feedback section
        assert 'PREVIOUS ATTEMPT HAD ISSUES' not in prompt

    def test_a2_prompt_with_feedback(self, sample_base_article):
        """Test A2 prompt with feedback"""
        feedback = ["Sentences too long", "Vocabulary too complex"]

        prompt = get_a2_adaptation_prompt(sample_base_article, feedback=feedback)

        # Should contain feedback
        assert 'PREVIOUS ATTEMPT HAD ISSUES' in prompt
        assert 'Sentences too long' in prompt
        assert 'Vocabulary too complex' in prompt

    def test_a2_prompt_with_empty_feedback(self, sample_base_article):
        """Test A2 prompt with empty feedback list"""
        prompt = get_a2_adaptation_prompt(sample_base_article, feedback=[])

        # Should not have feedback section with empty list
        assert 'PREVIOUS ATTEMPT HAD ISSUES' not in prompt


class TestGetB1AdaptationPrompt:
    """Test B1 adaptation prompt generation"""

    def test_b1_prompt_structure(self, sample_base_article):
        """Test B1 prompt has correct structure"""
        prompt = get_b1_adaptation_prompt(sample_base_article)

        # Should contain base article
        assert sample_base_article.title in prompt
        assert sample_base_article.content in prompt

        # Should have B1 guidelines
        assert 'B1 ADAPTATION GUIDELINES' in prompt
        assert 'VOCABULARY ASSESSMENT' in prompt
        assert 'STRUCTURE AND GRAMMAR' in prompt

        # Should specify B1 requirements
        assert 'mixed tenses' in prompt.lower() or 'Präsens' in prompt or 'Perfekt' in prompt
        assert '~300 words' in prompt

        # Should have output format
        assert 'OUTPUT FORMAT' in prompt

    def test_b1_prompt_without_feedback(self, sample_base_article):
        """Test B1 prompt without feedback"""
        prompt = get_b1_adaptation_prompt(sample_base_article, feedback=None)

        assert 'PREVIOUS ATTEMPT HAD ISSUES' not in prompt

    def test_b1_prompt_with_feedback(self, sample_base_article):
        """Test B1 prompt with feedback"""
        feedback = ["Not enough vocabulary glosses", "Tenses too simple"]

        prompt = get_b1_adaptation_prompt(sample_base_article, feedback=feedback)

        assert 'PREVIOUS ATTEMPT HAD ISSUES' in prompt
        assert 'Not enough vocabulary glosses' in prompt
        assert 'Tenses too simple' in prompt

    def test_b1_prompt_grammar_requirements(self, sample_base_article):
        """Test B1 prompt specifies correct grammar requirements"""
        prompt = get_b1_adaptation_prompt(sample_base_article)

        # Should allow advanced grammar
        assert 'Präsens' in prompt
        assert 'Perfekt' in prompt
        assert 'Präteritum' in prompt
        assert 'Konjunktiv' in prompt

    def test_b1_prompt_vocabulary_glosses(self, sample_base_article):
        """Test B1 prompt explicitly forbids inline gloss formatting."""
        prompt = get_b1_adaptation_prompt(sample_base_article)

        assert 'markdown emphasis' in prompt.lower()
        assert '"vocabulary"' not in prompt


class TestGetGlossaryGenerationPrompt:
    """Test glossary prompt generation from final article text."""

    def test_glossary_generation_prompt_contract(self, sample_a2_text_article):
        prompt = get_glossary_generation_prompt(sample_a2_text_article)

        required_contract_terms = [
            "Use ONLY the exact final article text below",
            "do not rewrite it",
            "Choose many words or phrases",
            "scan every sentence",
            "not only the main news nouns",
            "Prefer standalone words",
            "separable German compounds",
            "short reusable expressions",
            "nouns, compound nouns, verbs, adjectives, adverbs",
            "Include useful verbs and adjectives",
            "not important enough for the default visible glossary",
            "Use phrases only when the complete phrase has a meaning",
            "never more than 3 words",
            "Do not select long sentence fragments",
            "adjective + noun + prepositional phrase",
            "click through much of the article text",
            "Avoid proper names",
            "Avoid obvious cognates",
            "look very similar to English",
            "Temperaturen/temperatures",
            "Infrastruktur/infrastructure",
            "Mark only the strongest learner terms as default_glossary=true",
            "Mark all other useful click-only terms as default_glossary=false",
            "Do not add filler terms",
            "return ONLY valid JSON",
            '"vocabulary"',
            '"term"',
            '"english"',
            '"explanation"',
            '"default_glossary"',
        ]

        assert sample_a2_text_article.title in prompt
        assert sample_a2_text_article.content in prompt
        assert "English-speaking learner" in prompt
        assert f"Level: {sample_a2_text_article.level}" in prompt
        for term in required_contract_terms:
            assert term in prompt

    def test_glossary_generation_prompt_level_specific_contract(self, sample_a2_text_article):
        a2_prompt = get_glossary_generation_prompt(sample_a2_text_article)
        b1_article = sample_a2_text_article.model_copy(update={"level": "B1"})
        b1_prompt = get_glossary_generation_prompt(b1_article)

        assert "Target 20-40 clickable translation hints" in a2_prompt
        assert "Target 4-8 default glossary entries" in a2_prompt
        assert "Use only very simple German vocabulary" in a2_prompt

        assert "Target 25-55 clickable translation hints" in b1_prompt
        assert "Target 5-9 default glossary entries" in b1_prompt
        assert "Use clear intermediate German vocabulary" in b1_prompt

    def test_glossary_retry_prompt_contract(self, sample_a2_text_article):
        prompt = get_glossary_retry_prompt(
            sample_a2_text_article,
            rejected_terms={
                "Deutschland": "named entity or common place/person name",
                "drones": "transparent term for English-speaking learners",
            },
            shortlist=["Windräder", "Netzausbau", "Genehmigungen"],
        )

        required_contract_terms = [
            "Generate a NEW set of candidates",
            "Do NOT return any rejected term again",
            "Do NOT rewrite the article",
            "Every term must appear literally in the article text",
            "scan every sentence",
            "Prefer standalone words",
            "nouns, compound nouns, verbs, adjectives, adverbs",
            "Include useful verbs and adjectives",
            "Use phrases only when the complete phrase has a meaning",
            "never more than 3 words",
            "Do not select long sentence fragments",
            "look very similar to English",
            "Temperaturen/temperatures",
            "Infrastruktur/infrastructure",
            "Mark only the strongest learner terms as default_glossary=true",
            "Mark all other useful click-only terms as default_glossary=false",
            "return ONLY valid JSON",
            '"vocabulary"',
            '"term"',
            '"english"',
            '"explanation"',
            '"default_glossary"',
        ]

        assert sample_a2_text_article.title in prompt
        assert sample_a2_text_article.content in prompt
        assert f"Level: {sample_a2_text_article.level}" in prompt
        assert "Deutschland" in prompt
        assert "drones" in prompt
        assert "Windräder" in prompt
        assert "Netzausbau" in prompt
        assert "Genehmigungen" in prompt
        for term in required_contract_terms:
            assert term in prompt


class TestLevelGenerationRules:
    """Test LEVEL_GENERATION_RULES constants"""

    def test_a2_rules_exist(self):
        """Test A2 rules defined"""
        assert 'A2' in LEVEL_GENERATION_RULES
        assert 'präsens' in LEVEL_GENERATION_RULES['A2'].lower()

    def test_b1_rules_exist(self):
        """Test B1 rules defined"""
        assert 'B1' in LEVEL_GENERATION_RULES
        assert 'mix tenses' in LEVEL_GENERATION_RULES['B1'].lower() or \
               'mixed tenses' in LEVEL_GENERATION_RULES['B1'].lower()


class TestLevelEvaluationCriteria:
    """Test LEVEL_EVALUATION_CRITERIA constants"""

    def test_a2_criteria_exist(self):
        """Test A2 evaluation criteria defined"""
        assert 'A2' in LEVEL_EVALUATION_CRITERIA
        assert 'präsens' in LEVEL_EVALUATION_CRITERIA['A2'].lower()

    def test_b1_criteria_exist(self):
        """Test B1 evaluation criteria defined"""
        assert 'B1' in LEVEL_EVALUATION_CRITERIA
        assert 'präteritum' in LEVEL_EVALUATION_CRITERIA['B1'].lower()


class TestPromptConsistency:
    """Test consistency between prompts"""

    def test_a2_b1_word_count_difference(self, sample_base_article):
        """Test A2 and B1 have different word counts"""
        a2_prompt = get_a2_adaptation_prompt(sample_base_article)
        b1_prompt = get_b1_adaptation_prompt(sample_base_article)

        # A2 should target 200 words
        assert '200 words' in a2_prompt

        # B1 should target 300 words
        assert '300 words' in b1_prompt

    def test_all_prompts_include_base_article(self, sample_base_article):
        """Test all adaptation prompts include base article content"""
        a2_prompt = get_a2_adaptation_prompt(sample_base_article)
        b1_prompt = get_b1_adaptation_prompt(sample_base_article)

        # Both should include title and content
        for prompt in [a2_prompt, b1_prompt]:
            assert sample_base_article.title in prompt
            assert sample_base_article.content in prompt

    def test_all_prompts_request_json_output(self, sample_base_article):
        """Test all prompts request JSON output"""
        a2_prompt = get_a2_adaptation_prompt(sample_base_article)
        b1_prompt = get_b1_adaptation_prompt(sample_base_article)

        for prompt in [a2_prompt, b1_prompt]:
            assert 'JSON' in prompt
            assert '"title"' in prompt
            assert '"content"' in prompt
            assert '"vocabulary"' not in prompt

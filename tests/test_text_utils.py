"""
Unit tests for text_utils.ensure_vocabulary_bolded (FSA vocabulary bold marking).
"""

from scripts.text_utils import (
    ensure_vocabulary_bolded,
    filter_vocabulary_to_content,
    normalize_existing_vocabulary_bolding,
    normalize_vocabulary_term,
    vocabulary_term_present,
)


class TestNormalizeVocabularyTerm:
    """Normalization for glossary terms."""

    def test_strips_wrapping_bold_markers(self):
        assert normalize_vocabulary_term("**término**") == "término"

    def test_strips_multiple_wrapping_bold_marker_layers(self):
        assert normalize_vocabulary_term("****término****") == "término"

    def test_trims_surrounding_whitespace(self):
        assert normalize_vocabulary_term("  **término**  ") == "término"

    def test_preserves_internal_punctuation_and_accents(self):
        assert normalize_vocabulary_term("**índice (IPC)**") == "índice (IPC)"


class TestNormalizeExistingVocabularyBolding:
    """Normalization for malformed body bold markers."""

    def test_collapses_repeated_bold_markers_for_known_term(self):
        assert (
            normalize_existing_vocabulary_bolding("La ****tasa**** sube.", {"tasa": "rate"})
            == "La **tasa** sube."
        )

    def test_preserves_original_case_when_collapsing_repeated_markers(self):
        assert (
            normalize_existing_vocabulary_bolding("El ****Gobierno**** actúa.", {"gobierno": "government"})
            == "El **Gobierno** actúa."
        )


class TestEnsureVocabularyBoldedBasic:
    """Basic unit tests for the helper."""

    def test_empty_vocabulary_returns_content_unchanged(self):
        assert ensure_vocabulary_bolded("la tasa sube", {}) == "la tasa sube"

    def test_term_already_bolded_unchanged(self):
        assert (
            ensure_vocabulary_bolded("la **tasa** sube", {"tasa": "rate"})
            == "la **tasa** sube"
        )

    def test_term_not_bolded_gets_wrapped(self):
        assert (
            ensure_vocabulary_bolded("la tasa sube", {"tasa": "rate"})
            == "la **tasa** sube"
        )

    def test_two_terms_longer_first(self):
        vocab = {"tasa de desempleo": "unemployment rate", "tasa": "rate"}
        content = "La tasa de desempleo y la tasa suben."
        got = ensure_vocabulary_bolded(content, vocab)
        assert got == "La **tasa de desempleo** y la **tasa** suben."

    def test_term_with_special_chars_exact_match(self):
        content = "El índice (IPC) sube."
        vocab = {"índice (IPC)": "index (CPI)"}
        assert (
            ensure_vocabulary_bolded(content, vocab)
            == "El **índice (IPC)** sube."
        )

    def test_inflected_form_in_vocab_bolds_whole_word_only(self):
        content = "las tasas suben"
        vocab = {"tasas": "rates"}
        # Glossary has "tasas"; match whole word only → bold "tasas"
        assert (
            ensure_vocabulary_bolded(content, vocab)
            == "las **tasas** suben"
        )


class TestEnsureVocabularyBoldedEdgeCases:
    """Tricky edge cases (FSA and string match)."""

    def test_empty_content_returns_empty_string(self):
        assert ensure_vocabulary_bolded("", {"tasa": "rate"}) == ""

    def test_vocabulary_with_empty_string_key_skipped(self):
        # Should not advance by 0 (infinite loop); empty key skipped
        content = "la tasa sube"
        vocab = {"": "nope", "tasa": "rate"}
        assert ensure_vocabulary_bolded(content, vocab) == "la **tasa** sube"

    def test_term_only_inside_already_bold_span_unchanged(self):
        content = "**la tasa sube**"
        vocab = {"tasa": "rate"}
        assert ensure_vocabulary_bolded(content, vocab) == "**la tasa sube**"

    def test_term_appears_both_bolded_and_plain(self):
        content = "La **tasa** y la tasa suben."
        vocab = {"tasa": "rate"}
        assert (
            ensure_vocabulary_bolded(content, vocab)
            == "La **tasa** y la **tasa** suben."
        )

    def test_four_asterisks_toggles_state_correctly(self):
        content = "****"
        vocab = {}
        assert ensure_vocabulary_bolded(content, vocab) == "****"

    def test_consecutive_bold_markers_no_erroneous_match(self):
        content = "**a** **b**"
        vocab = {"a": "x"}
        # 'a' is inside bold, so not wrapped again
        assert ensure_vocabulary_bolded(content, vocab) == "**a** **b**"

    def test_unclosed_bold_no_wrap_inside(self):
        content = "**tasa sube"
        vocab = {"tasa": "rate"}
        # We are inside_bold after **, so "tasa" is not wrapped
        assert ensure_vocabulary_bolded(content, vocab) == "**tasa sube"

    def test_term_as_prefix_of_longer_word_no_match(self):
        content = "las tasas suben"
        vocab = {"tasa": "rate"}
        # Word boundary: "tasa" is prefix of "tasas", so do not bold (keep original form)
        assert ensure_vocabulary_bolded(content, vocab) == "las tasas suben"

    def test_unicode_accents_prefix_of_longer_word_no_match(self):
        content = "años"
        vocab = {"año": "year"}
        # Word boundary: "año" is prefix of "años", so do not bold
        assert ensure_vocabulary_bolded(content, vocab) == "años"

    def test_unicode_accents_separate_word(self):
        content = "el año pasado"
        vocab = {"año": "year"}
        assert ensure_vocabulary_bolded(content, vocab) == "el **año** pasado"

    def test_content_starts_with_term(self):
        content = "tasa sube"
        vocab = {"tasa": "rate"}
        assert ensure_vocabulary_bolded(content, vocab) == "**tasa** sube"

    def test_content_ends_with_term(self):
        content = "sube la tasa"
        vocab = {"tasa": "rate"}
        assert ensure_vocabulary_bolded(content, vocab) == "sube la **tasa**"

    def test_term_longer_than_content_no_match(self):
        content = "ab"
        vocab = {"abcd": "x"}
        assert ensure_vocabulary_bolded(content, vocab) == "ab"

    def test_nested_terms_longest_first_phrase_only(self):
        content = "la tasa de desempleo sube"
        vocab = {"tasa de desempleo": "unemployment rate", "tasa": "rate"}
        assert (
            ensure_vocabulary_bolded(content, vocab)
            == "la **tasa de desempleo** sube"
        )

    def test_nested_terms_short_only_when_long_not_present(self):
        content = "la tasa sube"
        vocab = {"tasa de desempleo": "unemployment rate", "tasa": "rate"}
        assert (
            ensure_vocabulary_bolded(content, vocab)
            == "la **tasa** sube"
        )


class TestVocabularyPresenceFiltering:
    """Exact presence checks for glossary/body consistency."""

    def test_term_present_as_plain_text(self):
        assert vocabulary_term_present("la tasa sube", "tasa") is True

    def test_term_present_as_bold_text(self):
        assert vocabulary_term_present("la **tasa** sube", "tasa") is True

    def test_term_present_is_case_insensitive_for_sentence_initial_words(self):
        assert vocabulary_term_present("Gobierno anuncia cambios.", "gobierno") is True

    def test_term_present_is_case_insensitive_for_acronyms(self):
        assert vocabulary_term_present("La UE busca un acuerdo.", "ue") is True

    def test_term_not_present_is_false(self):
        assert vocabulary_term_present("la inflación sube", "tasa") is False

    def test_inflected_variant_does_not_count_as_present(self):
        assert vocabulary_term_present("España reconoció al Estado", "reconocer") is False

    def test_filter_keeps_only_terms_present_in_content(self):
        vocabulary = {
            "energía eólica": "wind energy",
            "SEPE": "employment office",
        }

        filtered, dropped = filter_vocabulary_to_content(
            "España usa **energía eólica**.",
            vocabulary,
        )

        assert filtered == {"energía eólica": "wind energy"}
        assert dropped == ["SEPE"]

    def test_filter_keeps_terms_when_article_only_differs_by_case(self):
        vocabulary = {
            "gobierno": "government",
            "ue": "European Union",
        }

        filtered, dropped = filter_vocabulary_to_content(
            "Gobierno y UE presentan el plan.",
            vocabulary,
        )

        assert filtered == vocabulary
        assert dropped == []

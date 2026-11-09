"""The quality judge must only request changes the article rewrite can make."""

from types import SimpleNamespace

from scripts.prompts import get_quality_judge_prompt


def test_judge_prompt_excludes_what_the_pipeline_handles_elsewhere():
    article = SimpleNamespace(title="Titel", content="Text.")
    prompt = get_quality_judge_prompt(article, "A2")
    for phrase in ("publication date", "glossary", "content warnings", "comprehension questions"):
        assert phrase in prompt
    assert "added automatically after this check" in prompt
    assert "SCOPE OF THIS EVALUATION" in prompt


def test_judge_points_add_up_to_ten_and_favour_language_and_level():
    prompt = get_quality_judge_prompt(SimpleNamespace(title="Titel", content="Text."), "A2")
    for line in (
        "Grammar & Language (0-5 points)",
        "Educational Value (0-1 point)",
        "Content Quality (0-1 point)",
        "Level Appropriateness (0-3 points)",
    ):
        assert line in prompt

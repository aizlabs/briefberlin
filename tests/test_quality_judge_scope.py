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

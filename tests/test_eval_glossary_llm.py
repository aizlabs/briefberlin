import os
from argparse import Namespace

from scripts.eval_glossary_llm import (
    FIXTURES,
    apply_preload_env_overrides,
    compute_metrics,
    evaluate_thresholds,
    main,
)
from scripts.models import VocabularyItem


def test_eval_metrics_report_expected_recall_and_standalone_ratio():
    fixture = FIXTURES["berlin-heat"]
    accepted = [
        VocabularyItem(term="erreichen", english="reach", explanation="bis zu einem Wert kommen"),
        VocabularyItem(term="bisherige", english="previous", explanation="bis jetzt gültige"),
        VocabularyItem(
            term="steht Berlin bevor",
            english="is ahead for Berlin",
            explanation="kommt bald auf Berlin zu",
        ),
        VocabularyItem(term="Schatten", english="shade", explanation="Bereich ohne Sonne"),
    ]
    visible = [accepted[0].model_copy(update={"default_glossary": True})]

    metrics = compute_metrics(
        fixture=fixture,
        generated=accepted,
        accepted=accepted,
        dropped={"Temperaturen": "transparent term for English-speaking learners"},
        visible_glossary=visible,
    )

    assert metrics["generated_candidates"] == 4
    assert metrics["accepted_hints"] == 4
    assert metrics["default_glossary"] == 1
    assert metrics["rejected"] == 1
    assert metrics["standalone_ratio"] == 0.75
    assert metrics["overlong_accepted"] == 0
    assert metrics["expected_recall"] == 0.222
    assert metrics["expected_found"] == [
        "steht Berlin bevor",
        "erreichen",
        "bisherige",
        "Schatten",
    ]


def test_eval_threshold_failures_are_reported():
    args = Namespace(
        min_accepted=20,
        min_expected_recall=0.6,
        min_standalone_ratio=0.6,
        max_overlong_accepted=0,
    )
    metrics = {
        "accepted_hints": 4,
        "expected_recall": 0.267,
        "standalone_ratio": 0.5,
        "overlong_accepted": 1,
    }

    failures = evaluate_thresholds(metrics, args)

    assert failures == [
        "accepted_hints 4 < min_accepted 20",
        "expected_recall 0.267 < min_expected_recall 0.6",
        "standalone_ratio 0.5 < min_standalone_ratio 0.6",
        "overlong_accepted 1 > max_overlong_accepted 0",
    ]


def test_eval_preload_overrides_map_to_normal_llm_env(monkeypatch):
    for key in ("LLM_PROVIDER", "LLM_ADAPTATION_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    args = Namespace(
        provider="openai",
        model="local-model",
        base_url="http://localhost:11434/v1",
    )

    try:
        apply_preload_env_overrides(args)

        assert os.environ["LLM_PROVIDER"] == "openai"
        assert os.environ["LLM_ADAPTATION_MODEL"] == "local-model"
        assert os.environ["LLM_BASE_URL"] == "http://localhost:11434/v1"
    finally:
        for key in ("LLM_PROVIDER", "LLM_ADAPTATION_MODEL", "LLM_BASE_URL"):
            monkeypatch.delenv(key, raising=False)


def test_eval_lists_fixtures_without_loading_config(capsys):
    result = main(["--list-fixtures"])

    assert result == 0
    assert "berlin-heat" in capsys.readouterr().out


def test_eval_returns_one_and_diagnoses_degraded_output(monkeypatch, capsys):
    from scripts.glossary_generator import GlossaryGenerator, StructuredOutputDegradedError

    def mock_generate(self, article):
        raise StructuredOutputDegradedError(mode="no_payload", detail="mock no payload")

    monkeypatch.setattr(GlossaryGenerator, "generate", mock_generate)

    exit_code = main(["--fixture", "berlin-heat"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "structured glossary output degraded (mode=no_payload): mock no payload" in captured.err


def test_eval_returns_one_and_diagnoses_degraded_output_json(monkeypatch, capsys):
    import json

    from scripts.glossary_generator import GlossaryGenerator, StructuredOutputDegradedError

    def mock_generate(self, article):
        raise StructuredOutputDegradedError(mode="empty_vocabulary", detail="mock empty")

    monkeypatch.setattr(GlossaryGenerator, "generate", mock_generate)

    exit_code = main(["--fixture", "berlin-heat", "--json"])
    assert exit_code == 1

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["error"]["type"] == "StructuredOutputDegradedError"
    assert data["error"]["mode"] == "empty_vocabulary"
    assert "mock empty" in data["error"]["message"]


def test_eval_prints_warning_on_zero_accepted_hints(monkeypatch, capsys):
    from scripts.glossary_generator import GlossaryGenerator

    def mock_generate(self, article):
        return [VocabularyItem(term="nonexistent", english="none", explanation="none")]

    monkeypatch.setattr(GlossaryGenerator, "generate", mock_generate)

    exit_code = main(["--fixture", "berlin-heat"])
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Warning: Zero glossary hints were accepted" in captured.err

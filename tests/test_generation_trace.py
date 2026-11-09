"""Private history survives retries without entering public article output."""

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.config import GenerationConfig, apply_env_overrides, load_yaml
from scripts.generation_trace import GenerationTrace
from scripts.manual_pipeline import run_manual_pipeline
from scripts.topic_metadata_extractor import TopicMetadataResponse


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("value,expected", [("true", True), ("false", False)])
def test_trace_environment_overrides_yaml(monkeypatch, value, expected):
    monkeypatch.setenv("GENERATION_PRIVATE_TRACE", value)
    config = {"generation": {"private_trace": not expected}}
    apply_env_overrides(config)
    assert config["generation"]["private_trace"] is expected


def test_trace_defaults(base_config):
    generation = base_config.generation.model_dump(exclude={"private_trace"})
    assert GenerationConfig(**generation).private_trace is True
    config = load_yaml(Path(__file__).parents[1] / "config/base.yaml")
    assert config["generation"]["private_trace"] is False


def test_trace_location_permissions_and_preservation(tmp_path):
    sources = [tmp_path / "first.source.txt", tmp_path / "elsewhere" / "second.source.txt"]
    first = GenerationTrace(sources, "run-1")
    first.record("example", content="Grüße")
    second = GenerationTrace(sources, "run-1")
    assert first.path.parent == sources[0].parent
    assert first.path != second.path
    assert first.path.stat().st_mode & 0o777 == 0o600
    assert read_events(first.path)[1]["content"] == "Grüße"


@pytest.mark.parametrize("enabled,final_score", [(False, 9.0), (True, 9.0), (True, 1.0)])
def test_pipeline_preserves_all_attempts(
    monkeypatch, tmp_path, base_config, mock_logger, sample_base_article,
    sample_a2_article, enabled, final_score,
):
    from scripts.quality_gate import QualityGate

    source = tmp_path / "input.source.txt"
    source.write_text("Private source text. " * 25, encoding="utf-8")
    base_config.generation.private_trace = enabled
    base_config.generation.levels = ["A2"]
    base_config.audio.enabled = False
    base_config.translations.enabled = False
    monkeypatch.setattr("scripts.manual_pipeline.load_config", lambda env: base_config)
    monkeypatch.setattr("scripts.manual_pipeline.setup_logger", lambda config, run: mock_logger)
    extractor = MagicMock()
    extractor.extract.return_value = TopicMetadataResponse(title="Test topic", keywords=[])
    monkeypatch.setattr("scripts.manual_pipeline.TopicMetadataExtractor", lambda *args: extractor)
    synth = MagicMock()
    synth.synthesize.return_value = sample_base_article
    adapter = MagicMock()
    drafts = [
        sample_a2_article.model_copy(update={
            "title": f"Draft {i}", "base_article": sample_base_article,
        }) for i in range(1, 4)
    ]
    adapter.adapt_to_level.side_effect = drafts
    monkeypatch.setattr("scripts.content_generator.ArticleSynthesizer", lambda *args: synth)
    monkeypatch.setattr("scripts.content_generator.LevelAdapter", lambda *args: adapter)
    monkeypatch.setattr(QualityGate, "_init_llm_client", lambda self: None)
    monkeypatch.setattr(QualityGate, "_init_judge_chain", lambda self: None)
    feedback = [
        {"total_score": score, "issues": [f"Fix {i}"], "educational_notes": "Full notes"}
        for i, score in enumerate([1.0, 2.0, final_score], 1)
    ]
    monkeypatch.setattr(QualityGate, "_evaluate", MagicMock(side_effect=feedback))
    glossary = MagicMock()
    glossary.enrich_article.side_effect = lambda article: article
    monkeypatch.setattr("scripts.manual_pipeline.GlossaryGenerator", lambda *args: glossary)
    for name in ["ArticleTranslator", "AudioPipeline"]:
        monkeypatch.setattr(f"scripts.manual_pipeline.{name}", MagicMock())
    publisher = MagicMock()
    publisher.save_article.return_value = True
    monkeypatch.setattr("scripts.manual_pipeline.Publisher", lambda *args, **kw: publisher)

    result = run_manual_pipeline(Namespace(
        sources=[str(source)], level=["A2"], environment="test", dry_run=True,
    ))
    assert result == (0 if final_score == 9.0 else 1)
    assert adapter.adapt_to_level.call_args_list[1].kwargs["feedback"] == ["Fix 1"]
    assert adapter.adapt_to_level.call_args_list[2].kwargs["feedback"] == ["Fix 2"]
    traces = list(tmp_path.glob("*.generation-trace.jsonl"))
    if not enabled:
        assert traces == []
        return
    assert len(traces) == 1
    events = read_events(traces[0])
    assert [e["event"] for e in events] == [
        "run_started", "settings", "base_article", "draft", "evaluation",
        "draft", "evaluation", "draft", "evaluation", "run_completed",
    ]
    assert events[2]["article"]["content"] == sample_base_article.content
    assert [e["article"]["title"] for e in events if e["event"] == "draft"] == [
        "Draft 1", "Draft 2", "Draft 3",
    ]
    evaluations = [e for e in events if e["event"] == "evaluation"]
    assert [e["attempt"] for e in evaluations] == [1, 2, 3]
    assert [e["feedback"] for e in evaluations] == feedback
    assert evaluations[-1]["passed"] is (final_score == 9.0)
    assert "private_trace" not in drafts[0].model_dump()


def test_base_saved_before_adaptation_error(
    monkeypatch, tmp_path, base_config, mock_logger, sample_base_article, sample_topic,
    sample_sources,
):
    from scripts.content_generator import ContentGenerator

    synth = MagicMock()
    synth.synthesize.return_value = sample_base_article
    adapter = MagicMock()
    adapter.adapt_to_level.side_effect = RuntimeError("adaptation failed")
    monkeypatch.setattr("scripts.content_generator.ArticleSynthesizer", lambda *args: synth)
    monkeypatch.setattr("scripts.content_generator.LevelAdapter", lambda *args: adapter)
    trace = GenerationTrace([tmp_path / "input.source.txt"], "run")
    generator = ContentGenerator(base_config, mock_logger, trace=trace)
    with pytest.raises(RuntimeError, match="adaptation failed"):
        generator.generate_article(sample_topic, sample_sources, "A2")
    assert read_events(trace.path)[-1]["article"]["content"] == sample_base_article.content

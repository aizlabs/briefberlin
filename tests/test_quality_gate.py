# ruff: noqa: E402

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Stub LangChain modules so the quality gate can be imported without external deps.
sys.modules.setdefault("langchain_anthropic", SimpleNamespace(ChatAnthropic=MagicMock))
sys.modules.setdefault(
    "langchain_core.output_parsers", SimpleNamespace(PydanticOutputParser=MagicMock)
)
sys.modules.setdefault(
    "langchain_core.prompts", SimpleNamespace(ChatPromptTemplate=MagicMock)
)
sys.modules.setdefault("langchain_openai", SimpleNamespace(ChatOpenAI=MagicMock))

from scripts import prompts
from scripts.quality_gate import JudgeResponse, QualityGate


def test_init_judge_chain_uses_structured_output(monkeypatch, base_config, mock_logger):
    structured_llm = MagicMock(name="structured_llm")
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = structured_llm

    def _fake_init_llm_client(self):
        self.llm_client = mock_llm

    class DummyParser:
        def __init__(self, pydantic_object):
            self.pydantic_object = pydantic_object

        def get_format_instructions(self):
            return "FORMAT"

    class DummyPrompt:
        def __init__(self, messages):
            self.messages = messages
            self.piped = None

        def __or__(self, other):
            self.piped = other
            return f"chain:{other}"

    class DummyPromptTemplate:
        @classmethod
        def from_messages(cls, messages):
            return DummyPrompt(messages)

    monkeypatch.setattr(QualityGate, "_init_llm_client", _fake_init_llm_client)
    monkeypatch.setattr("scripts.quality_gate.PydanticOutputParser", DummyParser)
    monkeypatch.setattr("scripts.quality_gate.ChatPromptTemplate", DummyPromptTemplate)

    gate = QualityGate(base_config, mock_logger)

    mock_llm.with_structured_output.assert_called_once_with(JudgeResponse)
    assert gate.format_instructions == "FORMAT"
    assert gate.judge_prompt.piped is structured_llm


def _fake_init_llm_client(self):
    """Stub LLM client initialization to avoid network calls during tests."""
    self.llm_client = MagicMock()


def _fake_init_judge_chain(self):
    """Stub judge chain with deterministic format instructions."""
    self.format_instructions = "Return JSON"
    self.judge_chain = MagicMock()


@pytest.fixture
def quality_gate(base_config, mock_logger, monkeypatch):
    """QualityGate instance with mocked LLM and judge chain."""
    monkeypatch.setattr(QualityGate, "_init_llm_client", _fake_init_llm_client)
    monkeypatch.setattr(QualityGate, "_init_judge_chain", _fake_init_judge_chain)
    return QualityGate(base_config, mock_logger)


def test_call_llm_passes_prompt_and_format_instructions(quality_gate):
    response = JudgeResponse(
        grammar_score=4.0,
        grammar_issues=["Minor tense issue"],
        educational_score=4.5,
        educational_notes="Clear explanations",
        content_score=4.2,
        content_issues=["Add more detail"],
        level_score=4.0,
        total_score=4.5,
        issues=["Clarify paragraph two"],
        strengths=["Good structure"],
        recommendation="PASS",
    )
    quality_gate.judge_chain.invoke.return_value = response

    result = quality_gate._call_llm("QUALITY PROMPT")

    quality_gate.judge_chain.invoke.assert_called_once_with(
        {
            "prompt": "QUALITY PROMPT",
            "format_instructions": quality_gate.format_instructions,
        }
    )
    assert result == response


def test_init_llm_client_uses_quality_temperature(monkeypatch, base_config, mock_logger):
    captured_kwargs = {}

    class DummyOpenAI:
        def __init__(self, *args, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(QualityGate, "_init_judge_chain", lambda self: None)
    monkeypatch.setattr("scripts.quality_gate.ChatOpenAI", DummyOpenAI)

    gate = QualityGate(base_config, mock_logger)

    assert gate.quality_temperature == base_config.llm.quality_temperature
    assert captured_kwargs["temperature"] == base_config.llm.quality_temperature
    assert captured_kwargs["model_kwargs"] == {"response_format": {"type": "json_object"}}


def test_evaluate_returns_model_dump(monkeypatch, quality_gate, sample_a2_article):
    monkeypatch.setattr(prompts, "get_quality_judge_prompt", lambda article, level: "PROMPT")
    quality_gate._call_llm = MagicMock(
        return_value=JudgeResponse(
            grammar_score=4.0,
            grammar_issues=[],
            educational_score=4.5,
            educational_notes=None,
            content_score=4.2,
            content_issues=[],
            level_score=4.0,
            total_score=8.0,
            issues=["None"],
            strengths=["Clear"],
            recommendation="PASS",
        )
    )

    result = quality_gate._evaluate(sample_a2_article)

    assert result["total_score"] == 8.0
    assert result["strengths"] == ["Clear"]
    assert result["grammar_score"] == 4.0


def test_evaluate_handles_llm_error(monkeypatch, quality_gate, sample_a2_article):
    monkeypatch.setattr(prompts, "get_quality_judge_prompt", lambda article, level: "PROMPT")
    quality_gate._call_llm = MagicMock(side_effect=Exception("boom"))

    result = quality_gate._evaluate(sample_a2_article)

    assert result["total_score"] == 0
    assert "Evaluation error: boom" in result["issues"]


def test_evaluate_allows_text_only_article_with_empty_vocabulary(
    monkeypatch,
    quality_gate,
    sample_a2_text_article,
):
    monkeypatch.setattr(prompts, "get_quality_judge_prompt", lambda article, level: "PROMPT")
    quality_gate._call_llm = MagicMock(
        return_value=JudgeResponse(
            grammar_score=4.0,
            grammar_issues=[],
            educational_score=2.5,
            educational_notes="Useful text-only article",
            content_score=2.0,
            content_issues=[],
            level_score=1.0,
            total_score=8.5,
            issues=[],
            strengths=["Clear text"],
            recommendation="PASS",
        )
    )

    result = quality_gate._evaluate(sample_a2_text_article)

    assert result["total_score"] == 8.5
    assert result["issues"] == []

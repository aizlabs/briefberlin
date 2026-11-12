"""One run can use models from different providers: each model goes to its own provider."""

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from scripts.llm_factory import create_chat_model
from scripts.models import resolve_model_provider
from scripts.usage_report import RunUsageReport

MODEL_VARS = ("LLM_MODEL", "LLM_GENERATION_MODEL", "LLM_ADAPTATION_MODEL",
              "LLM_QUALITY_CHECK_MODEL", "LLM_TOPIC_EXTRACTION_MODEL", "LLM_TRANSLATION_MODEL")


@pytest.fixture
def mixed_config(monkeypatch):
    from scripts.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    for name in MODEL_VARS:
        monkeypatch.delenv(name, raising=False)
    return load_config("production")


def test_provider_comes_from_model_options_else_the_run_provider():
    options = {"claude-opus-5-5": {"provider": "anthropic"}, "gpt-6.1-terra": {"provider": "openai"}}
    assert resolve_model_provider("claude-opus-5-5", "openai", options) == "anthropic"
    assert resolve_model_provider("gpt-6.1-terra", "anthropic", options) == "openai"
    assert resolve_model_provider("llama-local", "openai", options) == "openai"
    assert resolve_model_provider("gpt-4o", "anthropic", {}) == "anthropic"


def test_every_model_in_base_config_names_its_provider(mixed_config):
    for model, options in mixed_config.llm.model_options.items():
        assert options.provider in ("openai", "anthropic"), model


def test_each_role_gets_a_client_for_its_own_provider(mixed_config):
    llm = mixed_config.llm.model_dump()
    assert isinstance(create_chat_model(llm, llm["models"]["adaptation"], 0.3), ChatAnthropic)
    assert isinstance(create_chat_model(llm, llm["models"]["translation"], 0.3), ChatOpenAI)


def test_usage_is_priced_under_the_provider_that_lists_the_model(mixed_config):
    report = RunUsageReport(mixed_config.llm.usage_reporting, "anthropic")
    report.merge_langchain_usage({
        "claude-opus-5-5": {"input_tokens": 1000, "output_tokens": 100},
        "gpt-6.1-terra": {"input_tokens": 1000, "output_tokens": 100},
    })
    rows = {row.usage.model: row for row in report.costed_rows()}
    assert rows["claude-opus-5-5"].usage.provider == "anthropic"
    assert rows["gpt-6.1-terra"].usage.provider == "openai"
    assert all(row.total_cost is not None for row in rows.values())


def test_a_missing_key_for_a_provider_in_use_is_reported(monkeypatch):
    from scripts.config import load_config

    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    for name in MODEL_VARS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY is required: translation uses gpt-6.1-terra"):
        load_config("production")

"""Claude as an optional provider: model set, request options and structured output."""

import pytest

from scripts.llm_factory import create_chat_model, with_structured_output
from scripts.quality_gate import JudgeResponse

OPUS = "claude-opus-5-5"
ROLES = ("generation", "adaptation", "translation", "quality_check")
MODEL_VARS = (
    "LLM_MODEL",
    "LLM_GENERATION_MODEL",
    "LLM_ADAPTATION_MODEL",
    "LLM_QUALITY_CHECK_MODEL",
    "LLM_TOPIC_EXTRACTION_MODEL",
    "LLM_TRANSLATION_MODEL",
)


@pytest.fixture
def anthropic_config(monkeypatch):
    from scripts.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    for name in MODEL_VARS:
        monkeypatch.delenv(name, raising=False)
    return load_config("production")


def test_switching_the_provider_uses_opus_to_write_and_grade_and_terra_to_translate(
    anthropic_config,
):
    models = anthropic_config.llm.models
    assert {models.generation, models.adaptation, models.quality_check} == {OPUS}
    assert models.translation == "gpt-6.1-terra"


def test_the_default_provider_keeps_its_own_models(monkeypatch):
    from scripts.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    for name in ("LLM_PROVIDER", *MODEL_VARS):
        monkeypatch.delenv(name, raising=False)
    cfg = load_config("production")
    assert cfg.llm.provider == "openai"
    assert not any(str(getattr(cfg.llm.models, role)).startswith("claude") for role in ROLES)


def test_one_model_for_every_role(monkeypatch, anthropic_config):
    from scripts.config import load_config

    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5-5")
    models = load_config("production").llm.models
    assert {getattr(models, role) for role in ROLES} == {"claude-sonnet-5-5"}


def test_a_single_role_can_still_be_overridden(monkeypatch, anthropic_config):
    from scripts.config import load_config

    monkeypatch.setenv("LLM_TRANSLATION_MODEL", "claude-haiku-5-5")
    cfg = load_config("production")
    assert cfg.llm.models.translation == "claude-haiku-5-5"
    assert cfg.llm.models.generation == OPUS


def test_every_claude_model_in_config_has_options_and_a_price(anthropic_config):
    llm = anthropic_config.llm
    for model in {OPUS, "claude-sonnet-5-5", "claude-haiku-5-5"}:
        assert llm.model_options[model].supports_temperature is False
        assert model in llm.usage_reporting.prices["anthropic"]


def test_opus_request_has_no_temperature_and_uses_configured_effort_and_limit(anthropic_config):
    chat = create_chat_model(anthropic_config.llm.model_dump(), OPUS, 0.3)
    payload = chat._get_request_payload([("user", "hi")])
    assert payload.get("temperature") is None
    assert payload["output_config"]["effort"] == "medium"
    assert payload["max_tokens"] == 16000


def test_claude_structured_output_uses_the_json_schema_format_not_a_forced_tool(anthropic_config):
    chat = create_chat_model(anthropic_config.llm.model_dump(), OPUS, 0.1)
    bound = with_structured_output(chat, JudgeResponse).first
    payload = chat._get_request_payload([("user", "hi")], **bound.kwargs)
    assert payload["output_config"]["format"]["type"] == "json_schema"
    assert payload["output_config"]["effort"] == "medium"
    assert not payload.get("tool_choice")
    assert not payload.get("tools")


def test_command_line_provider_and_model_reach_the_config(monkeypatch, anthropic_config):
    from scripts import manual_pipeline

    # run_manual_pipeline writes LLM_PROVIDER/LLM_MODEL into os.environ; register both
    # with monkeypatch so they are restored after this test instead of leaking.
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("LLM_MODEL", "")
    seen = {}

    def fake_load_config(environment):
        from scripts.config import load_config

        seen["config"] = load_config(environment)
        raise RuntimeError("stop after config")

    monkeypatch.setattr(manual_pipeline, "load_config", fake_load_config)
    args = manual_pipeline.parse_args(
        ["--provider", "anthropic", "--model", "claude-sonnet-5-5", "x.source.txt"]
    )
    with pytest.raises(RuntimeError, match="stop after config"):
        manual_pipeline.run_manual_pipeline(args)

    llm = seen["config"].llm
    assert llm.provider == "anthropic"
    assert {getattr(llm.models, role) for role in ROLES} == {"claude-sonnet-5-5"}


def test_command_line_provider_alone_uses_that_providers_models():
    from scripts import manual_pipeline

    args = manual_pipeline.parse_args(["--provider", "anthropic", "x.source.txt"])
    assert args.provider == "anthropic" and args.model is None

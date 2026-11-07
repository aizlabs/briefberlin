"""Per-model request options come from config (`llm.model_options`), not from model names."""

from scripts.llm_factory import create_chat_model

BASE = {"provider": "openai", "openai_api_key": "dummy", "max_tokens": 1024}


def _payload(model: str, temperature: float, model_options: dict | None = None) -> dict:
    llm = {**BASE, "model_options": model_options or {}}
    chat = create_chat_model(llm, model, temperature)
    return chat._get_request_payload([("user", "hi")])


def test_temperature_is_sent_when_the_model_has_no_options():
    assert _payload("gpt-6.1-terra", 0.3)["temperature"] == 0.3


def test_temperature_is_left_out_when_config_says_the_model_does_not_support_it():
    options = {"gpt-6.1-terra": {"supports_temperature": False}}
    assert "temperature" not in _payload("gpt-6.1-terra", 0.3, options)


def test_options_apply_only_to_the_named_model():
    options = {"gpt-6.1-terra": {"supports_temperature": False}}
    assert _payload("gpt-4o-mini", 0.1, options)["temperature"] == 0.1


def test_reasoning_effort_from_config_is_sent():
    options = {"gpt-6.1-terra": {"supports_temperature": False, "reasoning_effort": "low"}}
    payload = _payload("gpt-6.1-terra", 0.3, options)
    assert payload.get("reasoning_effort") == "low" or payload.get("reasoning", {}).get("effort") == "low"


def test_base_config_declares_options_for_the_models_it_uses(monkeypatch):
    from scripts.config import load_config

    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    cfg = load_config("production")
    used = {cfg.llm.models.generation, cfg.llm.models.adaptation, cfg.llm.models.translation}
    for model in used:
        if model.startswith(("gpt-5", "gpt-6")):
            assert model in cfg.llm.model_options, f"{model} needs an entry in llm.model_options"

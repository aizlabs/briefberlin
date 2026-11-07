"""Newer OpenAI models only accept the default temperature, so the factory must not send one."""

import pytest

from scripts.llm_factory import create_chat_model

LLM = {"provider": "openai", "openai_api_key": "dummy", "max_tokens": 1024}


def _payload(model: str, temperature: float) -> dict:
    chat = create_chat_model(LLM, model, temperature)
    return chat._get_request_payload([("user", "hi")])


@pytest.mark.parametrize("model", ["gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-luna", "gpt-5.5"])
def test_fixed_temperature_models_get_no_temperature(model):
    assert "temperature" not in _payload(model, 0.3)


@pytest.mark.parametrize("model", ["gpt-4o-mini", "gpt-4.1"])
def test_older_models_keep_the_configured_temperature(model):
    assert _payload(model, 0.3)["temperature"] == 0.3

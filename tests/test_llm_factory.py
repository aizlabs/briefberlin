from unittest.mock import MagicMock

from pydantic import SecretStr

from scripts.llm_factory import (
    build_structured_prompt_chain,
    create_chat_model,
    with_structured_output,
)


def test_with_structured_output_forwards_keyword_arguments():
    chat_model = MagicMock()
    runnable = object()
    chat_model.with_structured_output.return_value = runnable

    schema = {"type": "object", "additionalProperties": False}

    result = with_structured_output(chat_model, schema, strict=True, include_raw=True)

    assert result is runnable
    chat_model.with_structured_output.assert_called_once_with(
        schema,
        strict=True,
        include_raw=True,
    )


def test_create_chat_model_passes_openai_base_url(monkeypatch):
    chat_openai = MagicMock(return_value="chat-model")
    monkeypatch.setattr("scripts.llm_factory.ChatOpenAI", chat_openai)

    result = create_chat_model(
        {
            "provider": "openai",
            "openai_api_key": None,
            "base_url": "http://localhost:11434/v1",
            "max_tokens": 2048,
        },
        "local-model",
        0.1,
        provider_options={"model_kwargs": {"response_format": {"type": "json_object"}}},
    )

    assert result == "chat-model"
    chat_openai.assert_called_once_with(
        api_key=SecretStr("local-api-key"),
        base_url="http://localhost:11434/v1",
        model="local-model",
        max_completion_tokens=2048,
        temperature=0.1,
        model_kwargs={"response_format": {"type": "json_object"}},
    )


def test_create_chat_model_constructs_anthropic_with_shared_sdk_options(monkeypatch):
    chat_anthropic = MagicMock(return_value="chat-model")
    monkeypatch.setattr("scripts.llm_factory.ChatAnthropic", chat_anthropic)

    result = create_chat_model(
        {
            "provider": "anthropic",
            "anthropic_api_key": "anthropic-key",
            "max_tokens": 3072,
        },
        "claude-model",
        0.2,
    )

    assert result == "chat-model"
    chat_anthropic.assert_called_once_with(
        api_key=SecretStr("anthropic-key"),
        model_name="claude-model",
        max_tokens_to_sample=3072,
        temperature=0.2,
        timeout=None,
        stop=None,
    )


def test_build_structured_prompt_chain_uses_standard_prompt_wrapper(monkeypatch):
    chat_model = MagicMock()
    structured = MagicMock()
    chat_model.with_structured_output.return_value = structured
    monkeypatch.setattr("scripts.llm_factory.create_chat_model", MagicMock(return_value=chat_model))

    schema = {"type": "object", "additionalProperties": False}

    chain = build_structured_prompt_chain(
        {
            "provider": "openai",
            "openai_api_key": "test-key",
            "max_tokens": 2048,
        },
        "test-model",
        0.1,
        schema,
        strict=True,
    )

    assert chain is not None
    chat_model.with_structured_output.assert_called_once_with(schema, strict=True)

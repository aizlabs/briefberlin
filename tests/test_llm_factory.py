from unittest.mock import MagicMock

from scripts.llm_factory import create_chat_model, with_structured_output


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
    )

    assert result == "chat-model"
    chat_openai.assert_called_once_with(
        api_key="local-api-key",
        base_url="http://localhost:11434/v1",
        model="local-model",
        max_tokens=2048,
        temperature=0.1,
    )

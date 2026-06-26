from unittest.mock import MagicMock

from scripts.llm_factory import with_structured_output


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

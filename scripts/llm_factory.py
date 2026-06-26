"""
Shared LLM client factory for structured outputs.

Provides a single place to construct LangChain chat models with
Pydantic-enforced structured outputs, so all components (synthesizer,
level adapter, quality gate) can share configuration and easily support
multiple providers (OpenAI, Anthropic, etc.).
"""

from typing import Any, Dict, cast

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI


def create_chat_model(llm_config: Dict[str, Any], model_name: str, temperature: float) -> BaseChatModel:
    """
    Create a LangChain chat model instance based on provider.

    Args:
        llm_config: LLM configuration dict (typically config.llm.model_dump()).
        model_name: Model name to use (generation/adaptation/quality).
        temperature: Sampling temperature.

    Returns:
        A LangChain chat model instance.
    """
    provider = llm_config["provider"]

    if provider == "anthropic":
        api_key = llm_config.get("anthropic_api_key")
        if not api_key:
            raise ValueError("Missing ANTHROPIC_API_KEY in config/environment")

        return ChatAnthropic(
            api_key=api_key,
            model=model_name,
            max_tokens=llm_config.get("max_tokens", 4096),
            temperature=temperature,
        )

    if provider == "openai":
        api_key = llm_config.get("openai_api_key")
        if not api_key:
            raise ValueError("Missing OPENAI_API_KEY in config/environment")

        # Use OpenAI's JSON/structured output features under the hood
        return ChatOpenAI(
            api_key=api_key,
            model=model_name,
            max_tokens=llm_config.get("max_tokens", 4096),
            temperature=temperature,
        )

    # Future providers (e.g., mistral, qwen) can be added here
    raise ValueError(f"Unknown LLM provider: {provider}")


def with_structured_output(
    chat_model: BaseChatModel,
    response_model: Any,
    **kwargs: Any,
) -> Any:
    """
    Wrap a chat model with structured output.

    Uses LangChain's `with_structured_output` API so that all JSON parsing
    and validation is handled centrally instead of manual json.loads.
    """
    return cast(Any, chat_model.with_structured_output(response_model, **kwargs))

"""
Shared LLM client factory for structured outputs.

Provides a single place to construct LangChain chat models with
Pydantic-enforced structured outputs, so all components (synthesizer,
level adapter, quality gate) can share configuration and easily support
multiple providers (OpenAI, Anthropic, etc.).
"""

from typing import Any, Dict, Mapping, cast

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

# Kept under its own name so the structured-output check still works when tests
# replace `ChatAnthropic` with a stand-in.
_ANTHROPIC_CHAT_TYPE = ChatAnthropic


def create_chat_model(
    llm_config: Dict[str, Any],
    model_name: str,
    temperature: float | None,
    *,
    provider_options: Mapping[str, Any] | None = None,
) -> BaseChatModel:
    """
    Create a LangChain chat model instance based on provider.

    Args:
        llm_config: LLM configuration dict (typically config.llm.model_dump()).
        model_name: Model name to use (generation/adaptation/quality).
        temperature: Sampling temperature.
        provider_options: Extra constructor options for the selected LangChain provider.

    Returns:
        A LangChain chat model instance.
    """
    provider = llm_config["provider"]
    extra_options = dict(provider_options or {})
    # Per-model request options live in config (llm.model_options), never in code:
    # some models only accept their default temperature, reasoning models take an
    # effort level. A model without an entry gets the configured defaults.
    options = (llm_config.get("model_options") or {}).get(model_name) or {}
    if options.get("supports_temperature", True) is False:
        temperature = None
    if options.get("reasoning_effort"):
        extra_options.setdefault("reasoning_effort", options["reasoning_effort"])
    max_tokens = options.get("max_tokens") or llm_config.get("max_tokens", 4096)

    if provider == "anthropic":
        api_key = llm_config.get("anthropic_api_key")
        if not api_key:
            raise ValueError("Missing ANTHROPIC_API_KEY in config/environment")

        return ChatAnthropic(
            api_key=SecretStr(api_key),
            model_name=model_name,
            max_tokens_to_sample=max_tokens,
            temperature=temperature,
            timeout=None,
            stop=None,
            **extra_options,
        )

    if provider == "openai":
        api_key = llm_config.get("openai_api_key")
        base_url = llm_config.get("base_url")
        if not api_key and not base_url:
            raise ValueError("Missing OPENAI_API_KEY in config/environment")

        # Use OpenAI's JSON/structured output features under the hood
        return ChatOpenAI(
            api_key=SecretStr(api_key or "local-api-key"),
            base_url=base_url,
            model=model_name,
            max_completion_tokens=max_tokens,
            temperature=temperature,
            **extra_options,
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

    Claude models get the JSON-schema response format of the Anthropic API.
    The LangChain default for Claude is a forced tool call, which current
    Claude models reject.
    """
    if isinstance(chat_model, _ANTHROPIC_CHAT_TYPE):
        kwargs.setdefault("method", "json_schema")
    return cast(Any, chat_model.with_structured_output(response_model, **kwargs))


def build_structured_prompt_chain(
    llm_config: Dict[str, Any],
    model_name: str,
    temperature: float,
    response_model: Any,
    **structured_output_kwargs: Any,
) -> Any:
    """Build the standard `{prompt}` to structured-output chain."""
    chat_model = create_chat_model(llm_config, model_name, temperature)
    structured_llm = with_structured_output(
        chat_model,
        response_model,
        **structured_output_kwargs,
    )
    prompt_template = ChatPromptTemplate.from_messages([("user", "{prompt}")])
    return prompt_template | structured_llm

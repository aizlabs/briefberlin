"""Native Ollama chat adapter for local reader-language translation.

This module talks to a local Ollama server through its native ``POST /api/chat``
endpoint (not an OpenAI-compatible ``/v1`` route) with ``stream=false`` and
exactly one user message per request. It is deliberately small: there is no
generic provider framework here and no cloud structured-output route for
Ollama. The shared public API remains :class:`scripts.translator.ArticleTranslator`.

Requests use the documented timeout convention ``(min(10.0, timeout_seconds),
timeout_seconds)``: a bounded connect timeout plus the configured read
timeout. The read timeout bounds one unit request; it is not an article-wide
deadline.

Failure handling distinguishes unreachable connections, timeouts, missing
models, HTTP/API failures, malformed payloads, empty translations, incomplete
``done`` status and explicit token-limit termination. Raw response bodies are
never surfaced through errors or logs. Transient failures (connection errors
and timeouts, plus HTTP 408/429/5xx) are retried per unit;
retries wait with backoff bounded by a hard ceiling of 4.0 seconds per wait,
and there is never a sleep after the final attempt. Permanent configuration
and model errors fail promptly, and the requests transport is mounted with
zero implicit retries so per-unit attempts are never multiplied underneath
this adapter.
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter

from scripts.usage_report import ModelUsageRecord, record_direct_model_usage

GERMAN_LANGUAGE = ("German", "de")
ENGLISH_LANGUAGE = ("English", "en")

TRANSLATEGEMMA_PROMPT_TEMPLATE = (
    "You are a professional {source_name} ({source_code}) to {target_name} "
    "({target_code}) translator. Your goal is to accurately convey the meaning "
    "and nuances of the original {source_name} text while adhering to "
    "{target_name} grammar, vocabulary, and cultural sensitivities.\n"
    "Produce only the {target_name} translation, without any additional "
    "explanations or commentary. Please translate the following {source_name} "
    "text into {target_name}:\n\n\n{text}"
)

CONNECT_TIMEOUT_SECONDS = 10.0
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_CEILING_SECONDS = 4.0

_TRANSIENT_HTTP_STATUSES = frozenset({408, 429, *range(500, 600)})


class OllamaTranslationError(Exception):
    """Categorized adapter failure that never carries raw payload content."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        retryable: bool = False,
        attempts: int = 0,
        durations_ns: Tuple[int, ...] = (),
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.attempts = attempts
        self.durations_ns = durations_ns
        self.language_stats: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class OllamaUnitOutcome:
    """One successfully translated unit plus its request accounting."""

    text: str
    attempts: int
    durations_ns: Tuple[int, ...]


def build_translation_prompt(
    source_name: str,
    source_code: str,
    target_name: str,
    target_code: str,
    text: str,
) -> str:
    """Render the TranslateGemma template with the actual language names."""
    return TRANSLATEGEMMA_PROMPT_TEMPLATE.format(
        source_name=source_name,
        source_code=source_code,
        target_name=target_name,
        target_code=target_code,
        text=text,
    )


def clean_unit_text(value: str) -> str:
    """Normalize one translated unit for publication.

    Markup characters the model may have added are removed and all whitespace
    runs (including internal newlines) collapse to single spaces, so paragraph
    boundaries stay controlled by the assembling code.
    """
    cleaned = (value or "").replace("**", "").replace("<", "").replace(">", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _optional_count(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


class OllamaChatAdapter:
    """Small requests-based client for one configured local Ollama model."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        temperature: float,
        timeout_seconds: float,
        max_attempts: int,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.endpoint = f"{base_url.rstrip('/')}/api/chat"
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.logger = logger or logging.getLogger(__name__)
        self.session = requests.Session()
        transport = HTTPAdapter(max_retries=0)
        self.session.mount("https://", transport)
        self.session.mount("http://", transport)

    @property
    def request_timeout(self) -> Tuple[float, float]:
        return (min(CONNECT_TIMEOUT_SECONDS, self.timeout_seconds), self.timeout_seconds)

    def close(self) -> None:
        self.session.close()

    def translate_unit(
        self,
        source_name: str,
        source_code: str,
        target_name: str,
        target_code: str,
        text: str,
    ) -> OllamaUnitOutcome:
        """Translate one unit, retrying transient failures with bounded backoff."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": self.temperature},
            "messages": [
                {
                    "role": "user",
                    "content": build_translation_prompt(
                        source_name, source_code, target_name, target_code, text
                    ),
                }
            ],
        }
        durations: list[int] = []
        attempts = 0
        while True:
            attempts += 1
            failure: Optional[OllamaTranslationError]
            attempt_durations: Tuple[int, ...]
            try:
                response = self.session.post(
                    self.endpoint, json=payload, timeout=self.request_timeout
                )
                status_error = self._check_status(response)
                if status_error is not None:
                    raise status_error
                content, attempt_durations = self._decode_completion(response)
            except requests.Timeout as exc:
                failure = self._transport_error(
                    exc, "Ollama request timed out", "timeout", retryable=True
                )
                attempt_durations = ()
            except requests.ConnectionError as exc:
                failure = self._transport_error(
                    exc,
                    "Could not connect to the Ollama endpoint",
                    "connection",
                    retryable=True,
                )
                attempt_durations = ()
            except requests.RequestException as exc:
                failure = self._transport_error(
                    exc, "Ollama request failed at the transport layer", "connection"
                )
                attempt_durations = ()
            except OllamaTranslationError as exc:
                failure = exc
                attempt_durations = exc.durations_ns
            else:
                durations.extend(attempt_durations)
                return OllamaUnitOutcome(
                    text=content, attempts=attempts, durations_ns=tuple(durations)
                )
            durations.extend(attempt_durations)
            if failure is None or not failure.retryable or attempts >= self.max_attempts:
                raise OllamaTranslationError(
                    str(failure) if failure else "Ollama translation failed",
                    category=failure.category if failure else "http",
                    retryable=False,
                    attempts=attempts,
                    durations_ns=tuple(durations),
                ) from failure
            self.logger.debug(
                "Retrying Ollama unit request after attempt %d (category=%s)",
                attempts,
                failure.category,
            )
            time.sleep(self._backoff_delay(attempts))

    @staticmethod
    def _transport_error(
        exc: Exception,
        message: str,
        category: str,
        retryable: bool = False,
    ) -> OllamaTranslationError:
        # The original exception text may quote request/response content, so it
        # is chained (visible in tracebacks) but never rendered into messages.
        error = OllamaTranslationError(message, category=category, retryable=retryable)
        error.__cause__ = exc
        return error

    @staticmethod
    def _check_status(response: requests.Response) -> Optional[OllamaTranslationError]:
        status = response.status_code
        if status == 200:
            return None
        if status == 404:
            return OllamaTranslationError(
                "Ollama model not found (HTTP 404)", category="missing_model"
            )
        transient = status in _TRANSIENT_HTTP_STATUSES
        return OllamaTranslationError(
            f"Ollama HTTP API error (status {status})",
            category="http",
            retryable=transient,
        )

    def _decode_completion(self, response: requests.Response) -> Tuple[str, Tuple[int, ...]]:
        """Validate one completion, recording whatever usage metadata exists."""
        try:
            payload = response.json()
        except ValueError:
            raise OllamaTranslationError(
                "Malformed Ollama response: body is not JSON", category="malformed"
            ) from None
        if not isinstance(payload, dict):
            raise OllamaTranslationError(
                "Malformed Ollama response: payload is not an object", category="malformed"
            )
        durations = self._record_usage(payload)
        if payload.get("error"):
            raise OllamaTranslationError(
                "Ollama API returned an error envelope",
                category="http",
                durations_ns=durations,
            )
        done = payload.get("done")
        if done is not True:
            if isinstance(done, bool):
                raise OllamaTranslationError(
                    "Incomplete Ollama response: done is false",
                    category="incomplete",
                    durations_ns=durations,
                )
            raise OllamaTranslationError(
                "Malformed Ollama response: done must be a boolean",
                category="malformed",
                durations_ns=durations,
            )
        if payload.get("done_reason") == "length":
            raise OllamaTranslationError(
                "Ollama stopped the translation at the model token limit",
                category="length",
                durations_ns=durations,
            )
        message = payload.get("message")
        if not isinstance(message, dict):
            raise OllamaTranslationError(
                "Malformed Ollama response: message must be an object",
                category="malformed",
                durations_ns=durations,
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise OllamaTranslationError(
                "Malformed Ollama response: message.content must be a string",
                category="malformed",
                durations_ns=durations,
            )
        if not content.strip():
            raise OllamaTranslationError(
                "Ollama returned an empty translation",
                category="empty",
                durations_ns=durations,
            )
        return content, durations

    def _record_usage(self, payload: Dict[str, Any]) -> Tuple[int, ...]:
        """Record token/timing metadata under provider ``ollama`` when present."""
        input_tokens = _optional_count(payload.get("prompt_eval_count"))
        output_tokens = _optional_count(payload.get("eval_count"))
        duration_ns = _optional_count(payload.get("total_duration"))
        record_direct_model_usage(
            ModelUsageRecord(
                provider="ollama",
                model=self.model,
                modality="text",
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                usage_complete=input_tokens is not None and output_tokens is not None,
                source="ollama_chat",
            )
        )
        return (duration_ns,) if duration_ns is not None else ()

    def _backoff_delay(self, failed_attempt: int) -> float:
        delay = BACKOFF_BASE_SECONDS * (2 ** (failed_attempt - 1))
        if not math.isfinite(delay) or delay <= 0:
            return BACKOFF_CEILING_SECONDS
        return delay if delay < BACKOFF_CEILING_SECONDS else BACKOFF_CEILING_SECONDS

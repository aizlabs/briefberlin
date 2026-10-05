"""Hermetic native Ollama contracts through public translation boundaries."""

import contextvars
import copy
import json
import logging
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests
from pydantic import ValidationError

from scripts.config import AppConfig, load_config
from scripts.models import AdaptedArticle, TranslationsConfig, UsageReportingConfig, VocabularyItem
from scripts.translator import ArticleTranslator
from scripts.usage_report import collect_run_usage

MODEL = "synthetic-local:tag"
REAL_SESSION_REQUEST = requests.sessions.Session.request
SENSITIVE_FRAGMENTS = (
    "PRIVATE_BODY",
    "https://private.invalid/secret?key=credential",
    "credential",
    "PRIVATE_RESPONSE_FRAGMENT",
)
SECRET = " ".join(SENSITIVE_FRAGMENTS)


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("TRANSLATIONS_", "LLM_", "LANGUAGE_")) or key in {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        }:
            monkeypatch.delenv(key)
    monkeypatch.setattr("scripts.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr("time.sleep", Mock())
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        Mock(side_effect=AssertionError("unexpected network request")),
    )


@pytest.fixture
def local_config(base_config):
    data = base_config.model_dump()
    data["translations"].update(provider="ollama", model=MODEL, max_workers=1)
    return AppConfig.model_validate(data)


@pytest.fixture
def article():
    return AdaptedArticle(
        title="Die Wahl",
        summary="Eine Zusammenfassung.",
        content="Die Wahl ist heute.\nMit Unicode: العربية Русский.\n\nDie Straße bleibt offen.",
        level="B1",
        reading_time=3,
        translation_hints=[
            VocabularyItem(term="heute", english="today", default_glossary=False),
            VocabularyItem(
                term="Wahl",
                english="election",
                explanation="Eine Abstimmung.",
                default_glossary=True,
            ),
            VocabularyItem(
                term="Straße", explanation="Ein öffentlicher Weg.", default_glossary=True
            ),
        ],
    )


def response(content="translated", **metadata):
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps(
        {"message": {"content": content}, "done": True, **metadata}
    ).encode()
    return result


@pytest.fixture
def wire(monkeypatch):
    calls = []
    handler = Mock(side_effect=lambda *a: response())

    def request(session, method, url, **kwargs):
        calls.append((method, url, kwargs))
        return handler(kwargs["json"])

    monkeypatch.setattr("requests.sessions.Session.request", request)
    cloud = Mock(side_effect=AssertionError("Ollama must not initialize cloud"))
    monkeypatch.setattr("scripts.translator.build_structured_prompt_chain", cloud)
    return calls, handler, cloud


def prompt(source, source_code, target, target_code, text):
    return (
        f"You are a professional {source} ({source_code}) to {target} ({target_code}) translator. "
        f"Your goal is to accurately convey the meaning and nuances of the original {source} text "
        f"while adhering to {target} grammar, vocabulary, and cultural sensitivities.\n"
        f"Produce only the {target} translation, without any additional explanations or commentary. "
        f"Please translate the following {source} text into {target}:\n\n\n{text}"
    )


def test_native_provider_defaults():
    settings = TranslationsConfig().model_dump()
    assert "provider" in settings, "translations.provider must support native Ollama selection"
    assert settings["provider"] is None
    assert settings["ollama"] == {"base_url": "http://localhost:11434", "timeout_seconds": 120}
    assert (settings["enabled"], settings["model"], settings["temperature"]) == (False, None, 0.2)
    assert (settings["max_workers"], settings["max_attempts"]) == (4, 2)
    assert settings["output_path"] == "./output/_translations"


@pytest.mark.parametrize(
    "update",
    [
        {"provider": "openai"},
        {"provider": "invalid"},
        {"enabled": True, "provider": "ollama", "model": None},
        {"enabled": True, "provider": "ollama", "model": "   "},
        *[{"max_workers": x} for x in (0, 9)],
        *[{"max_attempts": x} for x in (0, 6)],
        *[{"ollama": {"timeout_seconds": x}} for x in (0, -1, float("inf"), float("nan"), "bad")],
        *[
            {"ollama": {"base_url": x}}
            for x in (
                "",
                "localhost:11434",
                "ftp://host",
                "http://",
                "http://host/v1",
                "http://host/v1/",
            )
        ],
    ],
)
def test_invalid_local_settings_rejected(update):
    with pytest.raises(ValidationError):
        TranslationsConfig.model_validate(update)


@pytest.mark.parametrize("url", ["http://localhost:11434/", "https://host.example/prefix///"])
def test_disabled_local_model_optional_and_url_validated_without_network(url):
    settings = TranslationsConfig.model_validate(
        {"provider": "ollama", "ollama": {"base_url": url}}
    )
    assert settings.model is None
    assert settings.model_dump()["provider"] == "ollama"


@pytest.mark.parametrize("level", ["A2", "B1"])
def test_exact_native_protocol_and_glossary_assembly(local_config, article, wire, level):
    calls, handler, cloud = wire
    article.level = level
    lang = next(x for x in local_config.translations.languages if x.code == "en")
    handler.side_effect = [
        response(text)
        for text in (
            "Translated title",
            "Translated summary",
            "Zeile eins\nZeile zwei",
            "Zeile eins\nZeile zwei",
            "A vote.",
            "street",
            "A public road.",
        )
    ]
    result = ArticleTranslator(local_config, logging.getLogger("contract")).translate_to_language(
        article, lang
    )
    expected = [
        ("German", "de", article.title),
        ("German", "de", article.summary),
        *[("German", "de", p) for p in article.content.split("\n\n")],
        ("German", "de", "Eine Abstimmung."),
        ("German", "de", "Straße"),
        ("German", "de", "Ein öffentlicher Weg."),
    ]
    assert len(calls) == len(expected)
    for (_, url, kwargs), (source, code, text) in zip(calls, expected, strict=True):
        assert url == "http://localhost:11434/api/chat"
        assert kwargs["timeout"] == (10.0, 120)
        assert kwargs["json"] == {
            "model": MODEL,
            "stream": False,
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "user", "content": prompt(source, code, lang.name, lang.code, text)}
            ],
        }
    assert all(method.upper() == "POST" for method, _, _ in calls)
    assert result.content == "Zeile eins Zeile zwei\n\nZeile eins Zeile zwei"
    assert [v.term for v in result.vocabulary] == ["Wahl", "Straße"]
    assert result.title == "Translated title"
    assert result.summary == "Translated summary"
    assert [v.translation for v in result.vocabulary] == ["election", "street"]
    assert [v.explanation for v in result.vocabulary] == ["A vote.", "A public road."]
    assert result.reading_time == 3 and result.model == MODEL
    cloud.assert_not_called()


def test_non_english_glossary_pivots_only_label(local_config, article, wire):
    calls, handler, cloud = wire
    lang = next(x for x in local_config.translations.languages if x.code == "ar")
    handler.side_effect = [
        response(text)
        for text in (
            "العنوان",
            "الملخص",
            "الفقرة الأولى",
            "الفقرة الثانية",
            "انتخابات",
            "تصويت",
            "شارع",
            "طريق عام",
        )
    ]
    translated = ArticleTranslator(
        local_config, logging.getLogger("contract")
    ).translate_to_language(article, lang)
    prompts = [c[2]["json"]["messages"][0]["content"] for c in calls]
    assert prompt("English", "en", lang.name, "ar", "election") in prompts
    assert prompt("German", "de", lang.name, "ar", "Eine Abstimmung.") in prompts
    assert not any(p.endswith("today") for p in prompts)
    assert [v.translation for v in translated.vocabulary] == ["انتخابات", "شارع"]
    assert [v.explanation for v in translated.vocabulary] == ["تصويت", "طريق عام"]
    cloud.assert_not_called()


@pytest.mark.parametrize("enabled,empty", [(False, False), (True, True)])
def test_bulk_noop_has_no_initialization(local_config, article, wire, enabled, empty):
    calls, _, cloud = wire
    local_config.translations.enabled = enabled
    if empty:
        local_config.translations.languages = []
    translator = ArticleTranslator(local_config, logging.getLogger("contract"))
    assert translator.translate_article(article) is article
    assert not calls
    cloud.assert_not_called()


def test_direct_request_ignores_bulk_disabled_and_empty_optional_units(local_config, article, wire):
    calls, _, cloud = wire
    local_config.translations.enabled = False
    article.summary = ""
    article.translation_hints = []
    ArticleTranslator(local_config, logging.getLogger("contract")).translate_to_language(
        article, local_config.translations.languages[0]
    )
    assert len(calls) == 3
    cloud.assert_not_called()


def test_direct_missing_model_raises_without_cloud_fallback(local_config, article, wire):
    calls, _, cloud = wire
    local_config.translations.enabled = False
    local_config.translations.model = None
    with pytest.raises(Exception):
        ArticleTranslator(local_config, logging.getLogger("contract")).translate_to_language(
            article, local_config.translations.languages[0]
        )
    assert not calls
    cloud.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"error": SECRET},
        {"done": True, "message": None},
        {"done": True, "message": {"content": 12}},
        {"done": True, "message": {"content": ""}},
        {"done": True, "message": {"content": " **<> \n "}},
        {"message": {"content": "text"}},
        {"done": "true", "message": {"content": "text"}},
        {"done": False, "message": {"content": "text"}},
        {"done": True, "done_reason": "length", "message": {"content": "text"}},
        "invalid-json",
    ],
)
def test_bad_completion_fails_promptly_and_safely(local_config, article, wire, payload, caplog):
    calls, handler, cloud = wire
    raw = response()
    raw._content = (
        (b"not-json " + SECRET.encode())
        if payload == "invalid-json"
        else json.dumps(payload).encode()
    )
    handler.side_effect = lambda _: raw
    with pytest.raises(Exception) as caught:
        ArticleTranslator(local_config, logging.getLogger("contract")).translate_to_language(
            article, local_config.translations.languages[0]
        )
    assert len(calls) == 1
    for sensitive in SENSITIVE_FRAGMENTS:
        assert sensitive not in str(caught.value) + caplog.text
    cloud.assert_not_called()


@pytest.mark.parametrize(
    "status,retry",
    [(400, False), (401, False), (404, False), (408, True), (429, True), (500, True), (503, True)],
)
def test_http_retry_budget_and_redaction(local_config, article, wire, status, retry, caplog):
    calls, handler, cloud = wire
    raw = response(error=SECRET)
    raw.status_code = status
    handler.side_effect = lambda _: raw
    with pytest.raises(Exception) as caught:
        ArticleTranslator(local_config, logging.getLogger("contract")).translate_to_language(
            article, local_config.translations.languages[0]
        )
    assert len(calls) == (2 if retry else 1)
    for sensitive in SENSITIVE_FRAGMENTS:
        assert sensitive not in str(caught.value) + caplog.text
    cloud.assert_not_called()


@pytest.mark.parametrize("error", [requests.ConnectionError, requests.Timeout])
@pytest.mark.parametrize("recover", [True, False])
def test_unit_retry_keeps_completed_title(local_config, article, wire, monkeypatch, error, recover):
    calls, handler, cloud = wire
    waits = []
    monkeypatch.setattr("time.sleep", lambda delay: waits.append((len(calls), delay)))
    handler.side_effect = [response("title"), error(SECRET)] + (
        [response("summary")] + [response()] * 10 if recover else [error(SECRET)]
    )
    translator = ArticleTranslator(local_config, logging.getLogger("contract"))
    if recover:
        result = translator.translate_to_language(article, local_config.translations.languages[0])
        assert result.title == "title"
    else:
        with pytest.raises(Exception):
            translator.translate_to_language(article, local_config.translations.languages[0])
        assert len(calls) == 3
    texts = [c[2]["json"]["messages"][0]["content"] for c in calls]
    assert sum(p.endswith(article.title) for p in texts) == 1
    assert sum(p.endswith(article.summary) for p in texts) == 2
    assert_retry_waits(waits, retry_request_numbers=[3])
    cloud.assert_not_called()


@pytest.mark.parametrize("total", [False, True])
def test_bulk_failure_preserves_german_and_success_order(
    local_config, article, wire, total, caplog
):
    calls, handler, cloud = wire

    def answer(payload):
        p = payload["messages"][0]["content"]
        if total or "to English (en)" in p:
            return response(done_reason="length")
        return response()

    handler.side_effect = answer
    translator = ArticleTranslator(local_config, logging.getLogger("contract"))
    original = article.model_dump()
    result = translator.translate_article(article)
    expected = [] if total else ["ar"]
    assert [t.lang for t in result.translations] == expected
    assert result.content == article.content and result.title == article.title
    assert article.model_dump() == original
    assert translator.last_run_stats["translated_languages"] == expected
    assert set(translator.last_run_stats["failed_languages"]) == ({"en", "ar"} if total else {"en"})
    assert calls
    assert article.title not in caplog.text
    cloud.assert_not_called()


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("workers", [1, 3])
def test_multiple_successes_retain_configured_order(local_config, wire, partial, workers):
    _, handler, cloud = wire
    local_config.translations.max_workers = workers
    # Deliberately use neither alphabetic nor reverse-alphabetic order.
    by_code = {lang.code: lang for lang in local_config.translations.languages}
    local_config.translations.languages = [by_code[code] for code in ("ru", "en", "ar")]
    body = "Heute findet eine Wahl statt. Die Menschen gehen zur Wahl."
    article = AdaptedArticle(
        title="Titel", summary="Eine Wahl findet statt.", content=body, level="A2", reading_time=1
    )
    later_body_returned = threading.Event()
    observed = []
    lock = threading.Lock()

    def answer(payload):
        text = payload["messages"][0]["content"]
        code = text.split(" to ", 1)[1].split(" (", 1)[1].split(")", 1)[0]
        if code == "ru" and workers > 1 and text.endswith("Titel"):
            assert later_body_returned.wait(30), "later language must progress independently"
        if code == "en" and partial:
            return response(done_reason="length")
        if text.endswith(body):
            with lock:
                observed.append(code)
            if code == "ar":
                later_body_returned.set()
        return response(f"A complete translated sentence for {code}.")

    handler.side_effect = answer
    translator = ArticleTranslator(local_config, logging.getLogger("contract"))
    result = translator.translate_article(article)
    expected = ["ru", "ar"] if partial else ["ru", "en", "ar"]
    assert [item.lang for item in result.translations] == expected
    assert translator.last_run_stats["translated_languages"] == expected
    assert translator.last_run_stats["failed_languages"] == (["en"] if partial else [])
    if workers > 1:
        assert observed.index("ar") < observed.index("ru")
    assert result.content == article.content
    cloud.assert_not_called()


@pytest.mark.parametrize("nested", [False, True])
def test_worker_bound_sequential_units_and_context(local_config, article, wire, nested):
    _, handler, _ = wire
    local_config.translations.max_workers = 2
    article.level = "A2"
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    probe = contextvars.ContextVar("ollama_test_probe", default="missing")
    active = 0
    peak = 0
    active_languages = set()
    seen = []
    first = set()

    def answer(payload):
        nonlocal active, peak
        p = payload["messages"][0]["content"]
        target = p.split(" to ", 1)[1].split(" translator.", 1)[0]
        with lock:
            assert target not in active_languages
            active_languages.add(target)
            active += 1
            peak = max(peak, active)
            seen.append(probe.get())
            wait = len(first) < 2 and target not in first
            first.add(target)
        if wait:
            barrier.wait(timeout=30)
        with lock:
            active -= 1
            active_languages.remove(target)
        return response()

    handler.side_effect = answer
    token = probe.set("caller")
    try:
        translator = ArticleTranslator(local_config, logging.getLogger("contract"))
        if nested:
            ctx = contextvars.copy_context()
            with ThreadPoolExecutor(1) as pool:
                result = pool.submit(ctx.run, translator.translate_article, article).result(
                    timeout=40
                )
        else:
            result = translator.translate_article(article)
    finally:
        probe.reset(token)
    assert [item.lang for item in result.translations] == ["en", "ar", "ru"]
    assert translator.last_run_stats["translated_languages"] == ["en", "ar", "ru"]
    assert peak == 2 and seen and set(seen) == {"caller"}


@pytest.mark.parametrize(
    "metadata,complete",
    [
        ({"prompt_eval_count": 11, "eval_count": 7, "total_duration": 123456789}, True),
        ({}, False),
        ({"prompt_eval_count": "bad", "eval_count": -2}, False),
    ],
)
@pytest.mark.parametrize("cloud_price", [False, True])
def test_local_usage_attribution_and_unknown_cost(
    local_config, article, wire, metadata, complete, cloud_price
):
    if cloud_price:
        local_config.llm.usage_reporting = UsageReportingConfig(
            prices={"openai": {MODEL: {"input_per_million": "1", "output_per_million": "2"}}}
        )
    calls, handler, _ = wire
    handler.side_effect = lambda _: response(**metadata)
    with collect_run_usage(local_config.llm.usage_reporting, "openai") as report:
        result = ArticleTranslator(local_config, logging.getLogger("contract")).translate_article(
            article
        )
    assert result.translations
    rows = report.as_dict()["models"]
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "ollama" and row["model"] == MODEL
    assert row["usage_complete"] is complete
    if complete:
        assert row["input_tokens"] == len(calls) * 11
        assert row["output_tokens"] == len(calls) * 7
    assert row["total_cost"] is None
    assert row["pricing_model"] is None
    assert report.as_dict()["complete"] is False
    assert Decimal(report.as_dict()["known_cost"]) == 0
    assert "N/A" in report.render_ascii() and "KNOWN SUBTOTAL" in report.render_ascii()


@pytest.fixture
def yaml_config(base_config, monkeypatch):
    data = base_config.model_dump()
    data["translations"].update(provider="ollama", model="yaml-model", enabled=False)

    def load(path):
        return copy.deepcopy(data) if path.name == "base.yaml" else {}

    monkeypatch.setattr("scripts.config.load_yaml", load)
    return data


def test_environment_precedence_and_global_isolation(yaml_config, monkeypatch):
    monkeypatch.setenv("TRANSLATIONS_PROVIDER", "ollama")
    monkeypatch.setenv("TRANSLATIONS_MODEL", MODEL)
    monkeypatch.setenv("TRANSLATIONS_MAX_WORKERS", "2")
    monkeypatch.setenv("TRANSLATIONS_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("TRANSLATIONS_OLLAMA_BASE_URL", "https://local.example/")
    monkeypatch.setenv("TRANSLATIONS_OLLAMA_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("TRANSLATIONS_LANGUAGES", "ar,xx")
    result = load_config()
    settings = result.translations.model_dump()
    assert settings["provider"] == "ollama"
    assert settings["model"] == MODEL
    assert (settings["max_workers"], settings["max_attempts"]) == (2, 4)
    assert settings["ollama"]["timeout_seconds"] == 5
    assert settings["ollama"]["base_url"].rstrip("/") == "https://local.example"
    assert [x.code for x in result.translations.languages] == ["ar"]
    assert result.llm.model_dump() == yaml_config["llm"]
    monkeypatch.setenv("TRANSLATIONS_PROVIDER", "inherit")
    monkeypatch.setenv("TRANSLATIONS_LANGUAGES", "")
    assert load_config().translations.model_dump()["provider"] is None
    assert load_config().translations.languages == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("TRANSLATIONS_PROVIDER", "bad"),
        ("TRANSLATIONS_MAX_WORKERS", "bad"),
        ("TRANSLATIONS_MAX_ATTEMPTS", "0"),
        ("TRANSLATIONS_OLLAMA_TIMEOUT_SECONDS", "nan"),
    ],
)
def test_invalid_environment_not_silently_ignored(yaml_config, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        load_config()


def test_full_run_still_requires_credentials(yaml_config):
    yaml_config["llm"].update(openai_api_key=None, anthropic_api_key=None, base_url=None)
    with pytest.raises(ValidationError):
        load_config()
    with pytest.raises(ValidationError):
        AppConfig.model_validate(yaml_config)


@pytest.fixture
def archive(yaml_config, tmp_path, monkeypatch):
    from scripts.backfill_translations import post_ref
    from tests.test_backfill_translations import POST

    posts = tmp_path / "posts"
    posts.mkdir()
    post = posts / "2026-09-21-052410-wahl-b1.md"
    post.write_text(POST, encoding="utf-8")
    translations = tmp_path / "translations"
    target = translations / post_ref(post)
    target.mkdir(parents=True)
    (target / "en.md").write_text("---\nlang: en\n---\nExisting English body\n", encoding="utf-8")
    yaml_config["output"]["path"] = str(posts)
    yaml_config["translations"]["output_path"] = str(translations)
    yaml_config["llm"].update(openai_api_key=None, anthropic_api_key=None, base_url=None)
    yaml_config["translations"]["model"] = None
    monkeypatch.setattr(
        "scripts.backfill_translations.setup_logger",
        lambda *a: logging.getLogger("backfill-contract"),
    )
    return post, target, ["--posts-dir", str(posts), "--translations-dir", str(translations)]


@pytest.mark.parametrize("dry_run", [False, True])
def test_keyless_backfill_cli_override_and_incremental_output(archive, wire, monkeypatch, dry_run):
    from scripts.backfill_translations import load_post, main

    post, target, argv = archive
    original = post.read_text(encoding="utf-8")
    original_front, original_data, original_body = load_post(post)
    calls, _, cloud = wire
    monkeypatch.setenv("TRANSLATIONS_MODEL", "environment-model")
    argv += ["--model", MODEL]
    if dry_run:
        argv += ["--dry-run"]
    assert main(argv) == 0
    if dry_run:
        assert not calls
        assert post.read_text(encoding="utf-8") == original
        assert sorted(p.name for p in target.iterdir()) == ["en.md"]
    else:
        assert calls and all(c[2]["json"]["model"] == MODEL for c in calls)
        assert all("to Arabic (ar)" in c[2]["json"]["messages"][0]["content"] for c in calls)
        front, data, body = load_post(post)
        assert body == original_body
        assert {k: v for k, v in data.items() if k != "translations"} == original_data
        for line in original_front.splitlines():
            assert line in front
        for code in ("en", "ar"):
            text = (target / f"{code}.md").read_text(encoding="utf-8")
            assert "  en:" in text and "  ar:" in text and "  de:" in text
        arabic = (target / "ar.md").read_text(encoding="utf-8")
        assert "https://media.example/a.mp3" in arabic
        assert "المفردات" in arabic
        assert "Existing English body" in (target / "en.md").read_text(encoding="utf-8")
    cloud.assert_not_called()


@pytest.mark.parametrize("model", ["", "   "])
def test_blank_cli_model_rejected_after_overrides(archive, yaml_config, wire, model):
    from scripts.backfill_translations import main

    _, _, argv = archive
    yaml_config["llm"]["openai_api_key"] = "synthetic-key"
    yaml_config["translations"]["model"] = "valid-yaml-model"
    with pytest.raises(ValueError):
        main(argv + ["--model", model, "--dry-run"])
    assert not wire[0]


@pytest.mark.parametrize("invalid", ["prompt_pack", "glossary_rules", "structure", "cloud"])
def test_backfill_narrow_validation_keeps_other_checks(archive, yaml_config, wire, invalid):
    from scripts.backfill_translations import main

    _, _, argv = archive
    if invalid in {"prompt_pack", "glossary_rules"}:
        yaml_config["language"][invalid] = "unsupported"
    elif invalid == "structure":
        yaml_config["generation"]["articles_per_run"] = 0
    else:
        yaml_config["translations"]["provider"] = None
    match = {
        "prompt_pack": "prompt_pack",
        "glossary_rules": "glossary_rules",
        "structure": "articles_per_run",
        "cloud": "API_KEY",
    }[invalid]
    with pytest.raises(ValueError, match=match):
        main(argv + ["--model", MODEL, "--dry-run"])
    assert not wire[0]


def test_backfill_failure_returns_zero_without_mutating_german(archive, wire, caplog):
    from scripts.backfill_translations import main

    post, target, argv = archive
    before = post.read_bytes()
    calls, handler, cloud = wire
    handler.side_effect = lambda _: response(done_reason="length")
    assert main(argv + ["--model", MODEL]) == 0
    assert calls and len(calls) == 1
    assert post.read_bytes() == before
    assert not (target / "ar.md").exists()
    assert "fail" in caplog.text.lower() or "no translations" in caplog.text.lower()
    cloud.assert_not_called()


@pytest.mark.parametrize("timeout", [2.5, 30])
def test_custom_endpoint_and_finite_timeout(local_config, article, wire, timeout):
    data = local_config.model_dump()
    data["translations"]["ollama"] = {
        "base_url": "http://host.example/prefix///",
        "timeout_seconds": timeout,
    }
    config = AppConfig.model_validate(data)
    ArticleTranslator(config, logging.getLogger("contract")).translate_to_language(
        article, config.translations.languages[0]
    )
    assert wire[0]
    assert all(c[1] == "http://host.example/prefix/api/chat" for c in wire[0])
    assert all(c[2]["timeout"] == (min(10.0, timeout), timeout) for c in wire[0])


def documented_backoff_ceiling():
    """Read the documented bound without prescribing a value or retry schedule.

    The adapter module documents its backoff cap/ceiling/maximum in seconds.
    No implementation retry helper supplies the expected waits.
    """
    from scripts import ollama_translation

    bounds = re.findall(
        r"(?i)backoff[^\n]*?(?:cap|ceiling|maximum|bounded|at most|max)"
        r"[^\d\n]*([0-9]+(?:\.[0-9]+)?)[ \t]*(?:seconds|secs|s)\b",
        ollama_translation.__doc__ or "",
    )
    assert bounds, "document the finite backoff ceiling in seconds in the adapter module"
    assert len(set(bounds)) == 1, "backoff ceiling documentation must be unambiguous"
    ceiling = float(bounds[0])
    assert math.isfinite(ceiling) and ceiling > 0
    return ceiling


def assert_retry_waits(waits, retry_request_numbers):
    ceiling = documented_backoff_ceiling()
    # Counts are captured before the next request; final exhaustion has no wait.
    assert [count + 1 for count, _ in waits] == retry_request_numbers
    for _, delay in waits:
        assert isinstance(delay, (int, float)) and not isinstance(delay, bool)
        assert math.isfinite(delay) and 0 < delay <= ceiling


@pytest.mark.parametrize("delays", [[0.1, 0.1], [1.5, 3.0], [4.0, 0.25]])
def test_retry_wait_assertion_accepts_bounded_schedules(monkeypatch, delays):
    monkeypatch.setitem(globals(), "documented_backoff_ceiling", lambda: 4.0)
    assert_retry_waits(list(enumerate(delays, start=1)), [2, 3])


@pytest.mark.parametrize(
    "waits",
    [
        [],
        [(1, 0.5)],
        [(1, 0.5), (2, 0.5), (3, 0.5)],
        [(0, 0.5), (2, 0.5)],
        [(1, float("nan")), (2, 0.5)],
        [(1, float("inf")), (2, 0.5)],
        [(1, 0), (2, 0.5)],
        [(1, -1), (2, 0.5)],
        [(1, 4.01), (2, 0.5)],
        [(1, "0.5"), (2, 0.5)],
        [(1, True), (2, 0.5)],
    ],
)
def test_retry_wait_assertion_rejects_unbounded_or_misplaced_waits(monkeypatch, waits):
    monkeypatch.setitem(globals(), "documented_backoff_ceiling", lambda: 4.0)
    with pytest.raises(AssertionError):
        assert_retry_waits(waits, [2, 3])


@pytest.mark.parametrize("budget", [1, 3, 5])
@pytest.mark.parametrize("public_path", ["article", "language"])
@pytest.mark.parametrize("error", [requests.Timeout, requests.ConnectionError])
def test_exhaustion_has_no_outer_language_retry(
    local_config, article, wire, monkeypatch, budget, public_path, error
):
    local_config.translations.max_attempts = budget
    local_config.translations.languages = local_config.translations.languages[:1]
    calls, handler, cloud = wire
    waits = []
    monkeypatch.setattr("time.sleep", lambda delay: waits.append((len(calls), delay)))
    handler.side_effect = error(SECRET)
    translator = ArticleTranslator(local_config, logging.getLogger("contract"))
    if public_path == "article":
        result = translator.translate_article(article)
        assert not result.translations
    else:
        with pytest.raises(Exception):
            translator.translate_to_language(article, local_config.translations.languages[0])
    assert len(calls) == budget
    texts = [c[2]["json"]["messages"][0]["content"] for c in calls]
    assert all(text.endswith(article.title) for text in texts)
    assert_retry_waits(waits, retry_request_numbers=list(range(2, budget + 1)))
    cloud.assert_not_called()


def test_rejected_completion_still_records_available_usage(local_config, article, wire):
    local_config.translations.languages = local_config.translations.languages[:1]
    wire[1].side_effect = lambda _: response(
        done_reason="length", prompt_eval_count=11, eval_count=7
    )
    with collect_run_usage(local_config.llm.usage_reporting, "openai") as report:
        result = ArticleTranslator(local_config, logging.getLogger("contract")).translate_article(
            article
        )
    assert not result.translations
    [row] = report.as_dict()["models"]
    assert row["provider"] == "ollama"
    assert row["input_tokens"] == 11 and row["output_tokens"] == 7


@pytest.mark.parametrize(
    "dry_run,rejected,total_failure",
    [(False, False, False), (True, False, False), (False, True, False), (False, False, True)],
)
def test_manual_finalized_article_boundary(
    local_config, article, wire, monkeypatch, tmp_path, dry_run, rejected, total_failure
):
    from argparse import Namespace

    from scripts.manual_pipeline import run_manual_pipeline
    from scripts.models import QualityResult
    from scripts.topic_metadata_extractor import TopicMetadataResponse
    from tests.test_manual_pipeline import _write_source

    source = _write_source(tmp_path / "private-input" / "synthetic.source.txt")
    local_config.audio.enabled = False
    local_config.output["path"] = str(tmp_path / "posts")
    local_config.translations.output_path = str(tmp_path / "translations")
    monkeypatch.setattr("scripts.manual_pipeline.load_config", lambda *a: local_config)
    monkeypatch.setattr(
        "scripts.manual_pipeline.setup_logger", lambda *a: logging.getLogger("manual-contract")
    )
    extractor = Mock()
    extractor.extract.return_value = TopicMetadataResponse(
        title="Synthetic topic", keywords=["Wahl"]
    )
    monkeypatch.setattr(
        "scripts.manual_pipeline.TopicMetadataExtractor", Mock(return_value=extractor)
    )
    generator = Mock()
    generator.generate_article.return_value = article.model_copy(
        update={"title": "UNAPPROVED_DRAFT"}
    )
    monkeypatch.setattr("scripts.manual_pipeline.ContentGenerator", Mock(return_value=generator))
    approved = article.model_copy(update={"title": "QUALITY_APPROVED"})
    enriched = approved.model_copy(update={"title": "FINAL_ENRICHED"})
    gate = Mock()
    gate.check_and_improve.return_value = (
        None if rejected else approved,
        QualityResult(passed=not rejected, score=8, issues=[], strengths=[], attempts=1),
    )
    monkeypatch.setattr("scripts.manual_pipeline.QualityGate", Mock(return_value=gate))
    glossary = Mock()
    glossary.enrich_article.return_value = enriched
    monkeypatch.setattr("scripts.manual_pipeline.GlossaryGenerator", Mock(return_value=glossary))
    monkeypatch.setattr("scripts.manual_pipeline.AudioPipeline", Mock())
    calls, handler, cloud = wire
    if total_failure:
        handler.side_effect = lambda _: response(done_reason="length")
    run_manual_pipeline(
        Namespace(sources=[str(source)], level=["B1"], environment="local", dry_run=dry_run)
    )
    if rejected:
        assert not calls
        glossary.enrich_article.assert_not_called()
        assert not list((tmp_path / "posts").glob("*.md"))
    else:
        assert calls
        prompts = [c[2]["json"]["messages"][0]["content"] for c in calls]
        assert any(p.endswith("FINAL_ENRICHED") for p in prompts)
        assert not any("UNAPPROVED_DRAFT" in p or "QUALITY_APPROVED" in p for p in prompts)
        if not total_failure:
            assert any(p.endswith("Eine Abstimmung.") for p in prompts)
        posts = list((tmp_path / "posts").glob("*.md"))
        assert len(posts) == (0 if dry_run else 1)
        if posts:
            assert "FINAL_ENRICHED" in posts[0].read_text(encoding="utf-8")
        if total_failure:
            assert not list((tmp_path / "translations").rglob("*.md"))
    cloud.assert_not_called()


@pytest.fixture
def isolated_main(monkeypatch, tmp_path):
    """Load main with restored legacy aliases and without import-path leakage."""
    import importlib
    import importlib.util
    import sys
    from pathlib import Path

    # main inserts scripts/ itself; syspath_prepend snapshots the original path.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    for name in (
        "alerts",
        "audio_pipeline",
        "content_fetcher",
        "content_generator",
        "glossary_generator",
        "logger",
        "models",
        "publisher",
        "quality_gate",
        "topic_discovery",
        "translator",
        "config",
    ):
        monkeypatch.setitem(sys.modules, name, importlib.import_module(f"scripts.{name}"))
    spec = importlib.util.spec_from_file_location(
        "scripts.main", Path(__file__).resolve().parents[1] / "scripts" / "main.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "scripts.main", module)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(module, "create_run_id", lambda: "synthetic-main-run")
    # Replace main's clock reference without changing logging/transport clocks.
    monkeypatch.setattr(module, "time", Mock(time=Mock(side_effect=[100.0, 101.0])))
    monkeypatch.setattr(module, "setup_logger", Mock(return_value=logging.Logger("main-contract")))
    return module


@pytest.mark.parametrize("outcome", ["accepted", "rejected", "total_failure"])
def test_main_finalized_article_boundary(
    isolated_main, local_config, article, wire, monkeypatch, tmp_path, outcome
):
    from types import SimpleNamespace

    from scripts.models import QualityResult
    from scripts.publisher import Publisher

    main = isolated_main
    local_config.generation.levels = ["B1"]
    local_config.generation.articles_per_run = 1
    local_config.audio.enabled = False
    local_config.output["path"] = str(tmp_path / "posts")
    local_config.translations.output_path = str(tmp_path / "translations")
    monkeypatch.setattr(main, "load_config", Mock(return_value=local_config))

    def stage_article(prefix):
        return article.model_copy(
            update={
                "title": f"{prefix}_TITLE",
                "summary": f"{prefix}_SUMMARY",
                "content": f"{prefix}_BODY",
                "translation_hints": [
                    VocabularyItem(
                        term=f"{prefix}_HEADWORD",
                        english=f"{prefix}_GLOSS",
                        explanation=f"{prefix}_EXPLANATION",
                        default_glossary=True,
                    )
                ],
            },
            deep=True,
        )

    draft = stage_article("DRAFT")
    approved = stage_article("APPROVED")
    enriched = stage_article("ENRICHED")
    topic = SimpleNamespace(title="Synthetic topic", sources=["a", "b", "c"], mentions=3)
    sources = [SimpleNamespace(source=f"synthetic-{n}", word_count=100) for n in range(3)]
    discoverer = Mock()
    discoverer.discover.return_value = [topic]
    fetcher = Mock()
    fetcher.fetch_topic_sources.return_value = sources
    generator = Mock()
    generator.generate_article.return_value = draft
    gate = Mock()
    gate.check_and_improve.return_value = (
        None if outcome == "rejected" else approved,
        QualityResult(passed=outcome != "rejected", score=8, issues=[], strengths=[], attempts=1),
    )
    glossary = Mock()
    glossary.enrich_article.return_value = enriched
    glossary.last_run_stats = dict(
        glossary_candidates_initial=1,
        glossary_candidates_retry=0,
        glossary_accepted=1,
        glossary_empty_after_retry=False,
        retry_used=False,
    )
    alerts, audio = Mock(), Mock()
    for name, component in (
        ("TopicDiscoverer", discoverer),
        ("ContentFetcher", fetcher),
        ("ContentGenerator", generator),
        ("QualityGate", gate),
        ("GlossaryGenerator", glossary),
        ("AudioPipeline", audio),
        ("AlertManager", alerts),
    ):
        monkeypatch.setattr(main, name, Mock(return_value=component))

    translator = ArticleTranslator(local_config, logging.Logger("main-translation-contract"))
    boundary = Mock(wraps=translator.translate_article)
    monkeypatch.setattr(translator, "translate_article", boundary)
    monkeypatch.setattr(main, "ArticleTranslator", Mock(return_value=translator))
    publisher = Publisher(local_config, logging.Logger("main-publication-contract"))
    publication = Mock(wraps=publisher.save_article)
    monkeypatch.setattr(publisher, "save_article", publication)
    monkeypatch.setattr(main, "Publisher", Mock(return_value=publisher))
    if outcome == "total_failure":
        wire[1].side_effect = lambda _: response(done_reason="length")

    assert main.main() == 0
    gate.check_and_improve.assert_called_once_with(draft, generator, topic, sources)
    assert gate.check_and_improve.call_args.args[0] is draft
    audio.prepare_for_publish.assert_not_called()
    alerts.send_failure_alert.assert_not_called()
    wire[2].assert_not_called()
    posts = list((tmp_path / "posts").glob("*.md"))
    if outcome == "rejected":
        glossary.enrich_article.assert_not_called()
        boundary.assert_not_called()
        publication.assert_not_called()
        assert not wire[0]
        assert not posts
        return

    glossary.enrich_article.assert_called_once_with(approved)
    assert glossary.enrich_article.call_args.args[0] is approved
    boundary.assert_called_once_with(enriched)
    assert boundary.call_args.args[0] is enriched
    prompts = [call[2]["json"]["messages"][0]["content"] for call in wire[0]]
    assert prompts
    for intermediate in (draft, approved):
        for sentinel in (
            intermediate.title,
            intermediate.summary,
            intermediate.content,
            intermediate.translation_hints[0].term,
            intermediate.translation_hints[0].english,
            intermediate.translation_hints[0].explanation,
        ):
            assert all(sentinel not in prompt_text for prompt_text in prompts)
    publication.assert_called_once()
    published = publication.call_args.args[0]
    assert (published.title, published.summary, published.content, published.translation_hints) == (
        enriched.title,
        enriched.summary,
        enriched.content,
        enriched.translation_hints,
    )
    assert len(posts) == 1
    assert enriched.title in posts[0].read_text(encoding="utf-8")
    if outcome == "total_failure":
        assert not published.translations
        assert translator.last_run_stats["failed_languages"] == ["en", "ar"]
        assert not list((tmp_path / "translations").rglob("*.md"))
    else:
        assert [translation.lang for translation in published.translations] == ["en", "ar"]
        for value in (
            enriched.title,
            enriched.summary,
            enriched.content,
            enriched.translation_hints[0].english,
            enriched.translation_hints[0].explanation,
        ):
            assert any(prompt_text.endswith(value) for prompt_text in prompts)
        assert len(list((tmp_path / "translations").rglob("*.md"))) == 2


def test_visible_headwords_and_full_hint_ids_survive_publication(
    local_config, article, wire, tmp_path
):
    from scripts.publisher import Publisher

    local_config.output["path"] = str(tmp_path / "posts")
    local_config.translations.output_path = str(tmp_path / "translations")
    translated = ArticleTranslator(local_config, logging.getLogger("contract")).translate_article(
        article
    )
    assert len(translated.translations) == 2
    assert Publisher(local_config, logging.getLogger("contract")).save_article(translated)
    [german] = (tmp_path / "posts").glob("*.md")
    body = german.read_text(encoding="utf-8")
    assert 'data-term-id="term-2">Wahl</button>' in body
    assert 'data-term-id="term-3">Straße</button>' in body
    [arabic] = (tmp_path / "translations").rglob("ar.md")
    text = arabic.read_text(encoding="utf-8")
    assert '<strong lang="de" dir="ltr">Wahl</strong>' in text
    assert '<strong lang="de" dir="ltr">Straße</strong>' in text
    assert '<strong lang="de" dir="ltr">heute</strong>' not in text


def test_disabled_empty_selection_does_not_waive_model_validation():
    with pytest.raises(ValidationError):
        TranslationsConfig.model_validate({"provider": "ollama", "enabled": True, "languages": []})


def test_duplicate_languages_still_rejected(local_config):
    data = local_config.translations.model_dump()
    data["languages"] = [data["languages"][0]] * 2
    with pytest.raises(ValidationError, match="Duplicate"):
        TranslationsConfig.model_validate(data)


def test_cloud_fallback_preserved_in_backfill(archive, yaml_config, monkeypatch):
    from scripts.backfill_translations import main

    _, _, argv = archive
    yaml_config["translations"]["provider"] = None
    yaml_config["llm"]["anthropic_api_key"] = "synthetic-anthropic-key"
    captured = []

    def translator(config, logger):
        captured.append(config)
        return Mock()

    monkeypatch.setattr("scripts.backfill_translations.ArticleTranslator", translator)
    assert main(argv + ["--dry-run"]) == 0
    assert captured[0].llm.provider == "anthropic"


def test_yaml_environment_layer_precedes_env_vars(yaml_config, monkeypatch):
    def load(path):
        if path.name == "base.yaml":
            return copy.deepcopy(yaml_config)
        if path.name == "local.yaml":
            return {"translations": {"model": "environment-yaml", "max_workers": 3}}
        return {}

    monkeypatch.setattr("scripts.config.load_yaml", load)
    assert load_config().translations.model == "environment-yaml"
    assert load_config().translations.max_workers == 3
    monkeypatch.setenv("TRANSLATIONS_MODEL", MODEL)
    assert load_config().translations.model == MODEL


@pytest.mark.parametrize("index", range(7))
def test_each_required_unit_rejects_empty_cleaned_output(local_config, article, wire, index):
    calls, handler, cloud = wire
    handler.side_effect = [response()] * index + [response(" **<> \n ")]
    with pytest.raises(Exception):
        ArticleTranslator(local_config, logging.getLogger("contract")).translate_to_language(
            article, local_config.translations.languages[0]
        )
    assert len(calls) == index + 1
    cloud.assert_not_called()


def test_empty_optional_explanation_requires_no_request(local_config, article, wire):
    article.translation_hints = [
        VocabularyItem(term="Wahl", english="election", explanation="", default_glossary=True)
    ]
    translated = ArticleTranslator(
        local_config, logging.getLogger("contract")
    ).translate_to_language(article, local_config.translations.languages[0])
    assert len(wire[0]) == 4
    assert translated.vocabulary[0].explanation == ""
    assert translated.vocabulary[0].translation == "election"


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_transient_http_recovers_without_repeating_source_units(
    local_config, article, wire, status
):
    bad = response(error=SECRET)
    bad.status_code = status
    wire[1].side_effect = [bad] + [response()] * 7
    translated = ArticleTranslator(
        local_config, logging.getLogger("contract")
    ).translate_to_language(article, local_config.translations.languages[0])
    assert translated.title == "translated"
    assert len(wire[0]) == 8


LANGUAGE_FIELDS = {"language", "lang", "target_language", "target_lang", "language_code"}
LANGUAGE_CODES = {"en", "ar", "ru"}


def explicit_language(value):
    """Only labelled target-language fields confer scope; code mentions do not."""
    if isinstance(value, dict):
        labels = [str(v) for k, v in value.items() if k in LANGUAGE_FIELDS]
    elif isinstance(value, str):
        labels = re.findall(
            r"\b(?:target_language|target_lang|language_code|language|lang)\s*[:=]\s*[\"']?([\w-]+)",
            value,
            re.I,
        )
    else:
        labels = []
    if not labels:
        return None
    if len(set(labels)) != 1 or labels[0] not in LANGUAGE_CODES:
        return "CONFLICT"
    return labels[0]


def explicit_runs(value):
    """Missing identifiers cannot authorize joining incomplete records."""
    if isinstance(value, dict):
        identifiers = [v for k, v in value.items() if k in {"run_id", "run"}]
    elif isinstance(value, str):
        # Empty labels must not consume the next line or a following field label.
        identifiers = [
            next((part for part in match if part), "")
            for match in re.findall(
                r"\b(?:run_id|run)[ \t]*[:=][ \t]*(?:\"([^\"]*)\"|'([^']*)'|([\w-]+)(?![\w-]|[ \t]*[:=]))",
                value,
            )
        ]
    else:
        identifiers = []
    return {
        str(identifier).strip()
        for identifier in identifiers
        if identifier is not None
        and str(identifier).strip()
        and str(identifier).strip().lower() not in {"null", "none"}
    }


def observation_scopes(value):
    """Inspect the entire subtree before any parent can become evidence."""
    language = explicit_language(value)
    languages = {language} if language else set()
    runs = explicit_runs(value)
    if isinstance(value, dict):
        languages.update(k for k in value if k in LANGUAGE_CODES)
        children = value.values()
    elif isinstance(value, (list, tuple)):
        children = value
    else:
        children = ()
    for child in children:
        child_languages, child_runs = observation_scopes(child)
        languages.update(child_languages)
        runs.update(child_runs)
    return languages, runs


def diagnostic_records(value, scope=None, run=None):
    """Accept complete observations, joining fragments only within an explicit run.

    Lists are separate observations. Language keys and explicit labels supply
    scope; ancestor measurements never do. Validate descendants before yielding.
    """
    declared = explicit_language(value)
    if declared == "CONFLICT" or (declared and scope and declared != scope):
        return
    scope = declared or scope
    own_runs = explicit_runs(value)
    if len(own_runs) > 1 or (run and own_runs - {run}):
        return
    run = next(iter(own_runs), run)
    if scope and not isinstance(value, (list, tuple)):
        languages, runs = observation_scopes(value)
        if languages - {scope} or len(runs) > 1 or (run and runs - {run}):
            return
    if isinstance(value, dict):
        fields = {
            key: child
            for key, child in value.items()
            if key not in LANGUAGE_CODES and not isinstance(child, (dict, list, tuple))
        }
        if scope:
            yield scope, json.dumps(fields, default=str)
            if run and not any(isinstance(child, (list, tuple)) for child in value.values()):
                yield scope, json.dumps(value, default=str)
        for key, child in value.items():
            if isinstance(child, (dict, list, tuple, str)):
                yield from diagnostic_records(child, key if key in LANGUAGE_CODES else scope, run)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from diagnostic_records(child, scope, run)
    elif isinstance(value, str) and scope:
        yield scope, value


def assert_language_diagnostics(observations, duration):
    """Require a complete explicitly attributed observation for each language."""
    records = list(diagnostic_records(observations))

    def numeric(text, field, value):
        return re.search(rf"(?i)\b(?:{field})[\"'\s:=]+(?:{value})(?![\w.])", text)

    def complete(text, code, count, retries):
        if not all(required in text for required in ("ollama", MODEL, "B1")):
            return False
        if not numeric(text, r"requests|request_count|requests_count|total_requests", count):
            return False
        if not numeric(text, r"retries|retry_count", retries):
            return False
        elapsed = re.findall(
            r"(?i)\b(elapsed(?:_seconds|_ms)?|duration_seconds|duration_ms)[\"'\s:=]+([0-9.eE+-]+)",
            text,
        )
        if not elapsed:
            return False
        seconds = [
            float(value) / (1000 if field.lower().endswith("_ms") else 1)
            for field, value in elapsed
        ]
        if not all(math.isfinite(value) and 0 < value <= duration for value in seconds):
            return False
        if code == "en":
            return bool(
                re.search(r"paragraph|body", text, re.I)
                and numeric(text, r"(?:(?:failed_)?unit_|paragraph_)?index", "2|3")
                and re.search(r"timeout|timed.out", text, re.I)
            )
        return True

    for code, count, retries in (("en", 6, 1), ("ar", 9, 0)):
        assert any(
            language == code and complete(text, code, count, retries) for language, text in records
        ), f"missing coherent explicitly attributed diagnostics for {code}"


@pytest.fixture
def diagnostic_observations():
    common = {"provider": "ollama", "model": MODEL, "level": "B1", "elapsed_ms": 20}
    return {
        "en": dict(common, requests=6, retries=1, unit="body", index=2, category="timeout"),
        "ar": dict(common, requests=9, retries=0),
    }


@pytest.mark.parametrize(
    "representation", ["keyed", "fields", "text", "nested", "seconds", "common_run"]
)
def test_diagnostic_attribution_accepts_explicit_scopes(diagnostic_observations, representation):
    observations = diagnostic_observations
    if representation == "fields":
        observations = [dict(value, target_language=code) for code, value in observations.items()]
    elif representation == "text":
        observations = [
            "language=" + code + " " + " ".join(f"{k}={v}" for k, v in value.items())
            for code, value in observations.items()
        ]
    elif representation == "nested":
        observations = {code: {"details": value} for code, value in observations.items()}
    elif representation == "common_run":
        observations = {
            code: {
                "run_id": "same-run",
                "metrics": {k: v for k, v in value.items() if k != "retries"},
                "counts": {"retries": value["retries"]},
            }
            for code, value in observations.items()
        }
    elif representation == "seconds":
        for value in observations.values():
            value["elapsed_seconds"] = value.pop("elapsed_ms") / 1000
        observations["en"]["index"] = 3
    assert_language_diagnostics(observations, 1)


@pytest.mark.parametrize(
    "corruption",
    [
        "swapped",
        "unlabelled",
        "mentions",
        "split_languages",
        "split_records",
        "conflict",
        "text_conflict",
        "nonfinite",
        "too_slow",
        "nested_text_conflict",
        "nested_field_conflict",
        "nested_key_conflict",
        "split_runs",
        "nested_run_conflict",
        "nested_text_run_conflict",
        "missing_run_fragments",
        "ancestor_measurements",
    ],
)
def test_diagnostic_attribution_rejects_misleading_observations(
    diagnostic_observations, corruption
):
    observations = diagnostic_observations
    if corruption == "swapped":
        observations = {"en": observations["ar"], "ar": observations["en"]}
    elif corruption == "unlabelled":
        observations = {"languages": "en ar", "children": list(observations.values())}
    elif corruption == "mentions":
        observations = [
            dict(value, note="unrelated en ar codes") for value in observations.values()
        ]
    elif corruption == "split_languages":
        observations["ar"]["retries"] = observations["en"].pop("retries")
    elif corruption == "split_records":
        observations["en"] = [
            {k: v for k, v in observations["en"].items() if k != "retries"},
            {"retries": 1},
        ]
    elif corruption == "conflict":
        observations["en"]["target_language"] = "ar"
    elif corruption == "text_conflict":
        observations["en"]["message"] = "target_language=ar"
    elif corruption.startswith("nested_"):
        nested = {
            "nested_text_conflict": {"details": {"message": "target_language=ar"}},
            "nested_field_conflict": {"details": {"target_language": "ar"}},
            "nested_key_conflict": {"details": {"ar": {"retries": 1}}},
            "nested_run_conflict": {"run_id": "first", "details": {"run_id": "second"}},
            "nested_text_run_conflict": {
                "run_id": "first",
                "details": {"message": "run_id=second"},
            },
        }
        observations["en"].update(nested[corruption])
    elif corruption in {"split_runs", "missing_run_fragments"}:
        value = observations["en"]
        observations["en"] = {
            "first": {k: v for k, v in value.items() if k != "retries"},
            "second": {"retries": 1},
        }
        if corruption == "split_runs":
            observations["en"]["first"]["run_id"] = "first"
            observations["en"]["second"]["run_id"] = "second"
    elif corruption == "ancestor_measurements":
        observations = {"retries": 1, "children": observations}
        observations["children"]["en"].pop("retries")
    elif corruption == "nonfinite":
        observations["en"]["elapsed_ms"] = float("inf")
    elif corruption == "too_slow":
        observations["en"]["elapsed_ms"] = 2000
    with pytest.raises(AssertionError, match="coherent explicitly attributed diagnostics"):
        assert_language_diagnostics(observations, 1)


@pytest.mark.parametrize("field", ["run_id", "run"])
@pytest.mark.parametrize("identifier", [None, "", " ", "\t\n"])
@pytest.mark.parametrize("representation", ["fields", "text"])
def test_complete_diagnostics_need_no_run(
    diagnostic_observations, field, identifier, representation
):
    observations = {
        code: dict(value, **{field: identifier}) for code, value in diagnostic_observations.items()
    }
    if representation == "text":
        observations = {
            code: " ".join(f"{k}={json.dumps(v)}" for k, v in value.items())
            for code, value in observations.items()
        }
    assert_language_diagnostics(observations, 1)


@pytest.mark.parametrize("field", ["run_id", "run"])
@pytest.mark.parametrize("identifier", [None, "", " ", "\t\n"])
@pytest.mark.parametrize("placement", ["parent", "children", "both", "text"])
def test_missing_run_cannot_join_diagnostic_fragments(
    diagnostic_observations, field, identifier, placement
):
    value = diagnostic_observations["en"]
    first = {k: v for k, v in value.items() if k != "retries"}
    second = {"retries": value["retries"]}
    parent = {"first": first, "second": second}
    if placement in {"parent", "both"}:
        parent[field] = identifier
    if placement in {"children", "both"}:
        first[field] = second[field] = identifier
    if placement == "text":
        rendered = "null" if identifier is None else '"' + identifier + '"'
        parent["message"] = f"{field}={rendered}"
        first["message"] = second["message"] = f"{field}={rendered}"
    for incomplete in (first, second, parent):
        observations = {"en": incomplete, "ar": diagnostic_observations["ar"]}
        with pytest.raises(AssertionError, match="coherent explicitly attributed diagnostics"):
            assert_language_diagnostics(observations, 1)


@pytest.mark.parametrize("field", ["run_id", "run"])
@pytest.mark.parametrize("identifier", ["same-run", "another_run-2"])
def test_valid_run_can_join_diagnostic_fragments(diagnostic_observations, field, identifier):
    observations = {
        code: {
            field: identifier,
            "first": {k: v for k, v in value.items() if k != "retries"},
            "second": {field: identifier, "retries": value["retries"]},
        }
        for code, value in diagnostic_observations.items()
    }
    assert_language_diagnostics(observations, 1)


def test_local_diagnostics_safe_and_useful(local_config, article, wire, caplog):
    caplog.set_level(logging.DEBUG, logger="contract")
    article.title = "SENSITIVE_TITLE_SENTINEL"
    article.content = "First synthetic paragraph.\n\nSecond paragraph.\n\n" + SECRET

    def reply(payload):
        message = payload["messages"][0]["content"]
        if "to English (en) translator" in message and message.endswith(SECRET):
            raise requests.Timeout(SECRET)
        return response(prompt_eval_count=2, eval_count=3, total_duration=123456789)

    wire[1].side_effect = reply
    translator = ArticleTranslator(local_config, logging.getLogger("contract"))
    started = time.monotonic()
    result = translator.translate_article(article)
    duration = time.monotonic() - started
    assert [t.lang for t in result.translations] == ["ar"]
    observations = [translator.last_run_stats]
    for record in caplog.records:
        observations.append({**record.__dict__, "message": record.getMessage()})
    # Safety includes unscoped logs, independently of attribution.
    diagnostics = json.dumps(observations, default=str, ensure_ascii=False)
    for sensitive in (
        *SENSITIVE_FRAGMENTS,
        article.title,
        article.content,
        "First synthetic paragraph.",
        "Second paragraph.",
        "test-key-123",
    ):
        assert sensitive not in diagnostics
    assert_language_diagnostics(observations, duration)
    assert "123456789" in diagnostics
    assert re.search(r"nanosecond|_ns\b", diagnostics, re.I)


@pytest.mark.parametrize("recover", [False, True])
def test_requests_transport_has_no_implicit_retries(local_config, article, monkeypatch, recover):
    # Exercise real Requests preparation and dispatch; stop at adapter.send so
    # retry configuration is observable without opening a socket.
    monkeypatch.setattr("requests.sessions.Session.request", REAL_SESSION_REQUEST)
    cloud = Mock(side_effect=AssertionError("Ollama must not initialize cloud"))
    monkeypatch.setattr("scripts.translator.build_structured_prompt_chain", cloud)
    sent = []

    def send(adapter, request, **kwargs):
        assert adapter.max_retries.total == 0, "native transport must disable implicit retries"
        sent.append(request)
        if len(sent) == 1 or not recover:
            raise requests.ConnectionError(SECRET)
        result = response()
        result.request = request
        return result

    monkeypatch.setattr("requests.adapters.HTTPAdapter.send", send)
    translator = ArticleTranslator(local_config, logging.getLogger("contract"))
    if recover:
        result = translator.translate_to_language(article, local_config.translations.languages[0])
        assert result.title == "translated"
        assert len(sent) == 8
    else:
        with pytest.raises(Exception):
            translator.translate_to_language(article, local_config.translations.languages[0])
        assert len(sent) == 2
    assert sent[0].body == sent[1].body
    cloud.assert_not_called()


def test_cloud_usage_accumulates_alongside_local_without_pricing_it(local_config, article, wire):
    from scripts.usage_report import ModelUsageRecord, record_direct_model_usage

    local_config.llm.usage_reporting = UsageReportingConfig(
        prices={"openai": {MODEL: {"input_per_million": "1", "output_per_million": "2"}}}
    )
    wire[1].side_effect = lambda _: response(prompt_eval_count=2, eval_count=3)
    with collect_run_usage(local_config.llm.usage_reporting, "openai") as report:
        record_direct_model_usage(
            ModelUsageRecord(
                provider="openai",
                model=MODEL,
                modality="text",
                input_tokens=17,
                output_tokens=19,
            )
        )
        ArticleTranslator(local_config, logging.getLogger("contract")).translate_article(article)
    rows = {r["provider"]: r for r in report.as_dict()["models"]}
    assert set(rows) == {"openai", "ollama"}
    assert rows["openai"]["input_tokens"] == 17
    assert rows["openai"]["output_tokens"] == 19
    assert rows["ollama"]["input_tokens"] == 2 * len(wire[0])
    assert rows["ollama"]["total_cost"] is None
    assert rows["ollama"]["pricing_model"] is None
    assert Decimal(rows["openai"]["total_cost"]) == Decimal("0.000055")
    assert Decimal(report.as_dict()["known_cost"]) == Decimal("0.000055")
    assert report.as_dict()["complete"] is False
    assert "N/A" in report.render_ascii() and "KNOWN SUBTOTAL" in report.render_ascii()


@pytest.mark.parametrize(
    "kind,category",
    [
        ("connection", r"connect|unreachable"),
        ("timeout", r"timeout|timed.out"),
        ("missing_model", r"model"),
        ("http", r"http|api"),
        ("malformed", r"malformed|invalid"),
        ("empty", r"empty"),
        ("incomplete", r"incomplete"),
        ("length", r"length|token.limit"),
    ],
)
def test_safe_error_categories_are_distinguishable(
    local_config, article, wire, kind, category, caplog
):
    local_config.translations.max_attempts = 1
    raw = response()
    if kind == "connection":
        wire[1].side_effect = requests.ConnectionError(SECRET)
    elif kind == "timeout":
        wire[1].side_effect = requests.Timeout(SECRET)
    else:
        if kind == "missing_model":
            raw = response(error=f"model '{SECRET}' not found")
            raw.status_code = 404
        elif kind == "http":
            raw = response(error=SECRET)
            raw.status_code = 403
        elif kind == "malformed":
            raw._content = json.dumps({"done": True, "message": {"content": []}}).encode()
        elif kind == "empty":
            raw = response("")
        elif kind == "incomplete":
            raw = response(done=False)
        elif kind == "length":
            raw = response(done_reason="length")
        wire[1].side_effect = lambda _: raw
    with pytest.raises(Exception) as caught:
        ArticleTranslator(local_config, logging.getLogger("contract")).translate_to_language(
            article, local_config.translations.languages[0]
        )
    assert len(wire[0]) == 1
    diagnostic = str(caught.value) + " " + str(getattr(caught.value, "category", ""))
    assert re.search(category, diagnostic, re.I)
    for sensitive in SENSITIVE_FRAGMENTS:
        assert sensitive not in diagnostic + caplog.text
    wire[2].assert_not_called()


def test_constructor_is_network_free(local_config, wire):
    ArticleTranslator(local_config, logging.getLogger("contract"))
    assert not wire[0]
    wire[2].assert_not_called()


def test_local_initialization_failure_marks_all_selected_languages(local_config, article, wire):
    # A configuration can be modified after validation; bulk remains fail-open,
    # whereas the explicit single-language request above must raise.
    local_config.translations.model = None
    translator = ArticleTranslator(local_config, logging.getLogger("contract"))
    result = translator.translate_article(article)
    assert result is article
    assert translator.last_run_stats["failed_languages"] == ["en", "ar"]
    assert translator.last_run_stats["translated_languages"] == []
    assert not wire[0]
    wire[2].assert_not_called()


@pytest.mark.parametrize("done", [False, True])
def test_rejected_completion_retains_tokens_and_timing(local_config, article, wire, caplog, done):
    caplog.set_level(logging.DEBUG, logger="contract")
    local_config.translations.languages = local_config.translations.languages[:1]
    wire[1].side_effect = lambda _: response(
        done=done,
        done_reason="length" if done else "stop",
        prompt_eval_count=13,
        eval_count=5,
        total_duration=987654321,
    )
    translator = ArticleTranslator(local_config, logging.getLogger("contract"))
    with collect_run_usage(local_config.llm.usage_reporting, "openai") as report:
        result = translator.translate_article(article)
    assert not result.translations
    assert len(wire[0]) == 1
    [row] = report.as_dict()["models"]
    assert (row["provider"], row["model"]) == ("ollama", MODEL)
    assert (row["input_tokens"], row["output_tokens"]) == (13, 5)
    observations = json.dumps(translator.last_run_stats, default=str)
    observations += json.dumps([r.__dict__ for r in caplog.records], default=str)
    observations += json.dumps(report.as_dict(), default=str)
    assert "987654321" in observations
    assert re.search(r"nanosecond|_ns\b", observations, re.I)
    wire[2].assert_not_called()


def test_api_error_envelope_overrides_otherwise_valid_completion(local_config, article, wire):
    wire[1].side_effect = lambda _: response(error=SECRET)
    with pytest.raises(Exception) as caught:
        ArticleTranslator(local_config, logging.getLogger("contract")).translate_to_language(
            article, local_config.translations.languages[0]
        )
    assert len(wire[0]) == 1
    for sensitive in SENSITIVE_FRAGMENTS:
        assert sensitive not in str(caught.value)
    wire[2].assert_not_called()


def test_level_filter_can_leave_no_eligible_local_languages(local_config, article, wire):
    local_config.translations.languages = [
        x for x in local_config.translations.languages if x.code == "ru"
    ]
    assert (
        ArticleTranslator(local_config, logging.getLogger("contract")).translate_article(article)
        is article
    )
    assert not wire[0]
    wire[2].assert_not_called()


def test_glossary_rows_keep_published_identity_despite_model_text(local_config, article, wire):
    from scripts.translation_hints import publishable_translation_hints, visible_glossary_items

    article.translation_hints = [
        VocabularyItem(term="heute", english="today", default_glossary=False),
        VocabularyItem(term="ÖPNV", english="public transport", default_glossary=True),
        VocabularyItem(term="Straße", english="street", default_glossary=True),
        VocabularyItem(term="straße", english="duplicate", default_glossary=True),
    ]
    visible = visible_glossary_items(publishable_translation_hints(article))
    assert [(identity, item.term) for identity, item in visible] == [
        ("term-2", "ÖPNV"),
        ("term-3", "Straße"),
    ]
    wire[1].side_effect = [
        response(text)
        for text in [
            "Translated title",
            "Translated summary",
            "First paragraph",
            "Second paragraph",
            "Invented headword A",
            "Invented headword B",
        ]
    ]
    language = next(x for x in local_config.translations.languages if x.code == "ar")
    translated = ArticleTranslator(
        local_config, logging.getLogger("contract")
    ).translate_to_language(article, language)
    assert translated.title == "Translated title"
    assert translated.summary == "Translated summary"
    assert translated.content == "First paragraph\n\nSecond paragraph"
    assert [row.term for row in translated.vocabulary] == [item.term for _, item in visible]
    assert [row.translation for row in translated.vocabulary] == [
        "Invented headword A",
        "Invented headword B",
    ]
    assert all(row.explanation == "" for row in translated.vocabulary)
    assert len(wire[0]) == 6
    wire[2].assert_not_called()

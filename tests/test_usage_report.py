from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from scripts.models import UsageReportingConfig
from scripts.usage_report import (
    ModelUsageRecord,
    RunUsageReport,
    collect_run_usage,
    record_direct_model_usage,
)


def _usage_config() -> UsageReportingConfig:
    return UsageReportingConfig(
        pricing_as_of="2026-08-02",
        prices={
            "openai": {
                "gpt-text": {
                    "aliases": ["gpt-text-????-??-??"],
                    "input_per_million": "1.00",
                    "cached_input_per_million": "0.10",
                    "output_per_million": "2.00",
                },
                "gpt-4o-mini-tts": {
                    "aliases": ["gpt-4o-mini-tts-*"],
                    "modality": "audio",
                    "input_per_million": "0.60",
                    "output_per_million": "12.00",
                },
            }
        },
    )


def test_report_aggregates_snapshots_and_applies_cached_input_pricing():
    report = RunUsageReport(_usage_config(), "openai")

    report.merge_langchain_usage(
        {
            "gpt-text-2026-07-01": {
                "input_tokens": 1_000,
                "output_tokens": 400,
                "total_tokens": 1_400,
                "input_token_details": {"cache_read": 200},
            }
        }
    )
    report.merge_langchain_usage(
        {
            "gpt-text-2026-07-01": {
                "input_tokens": 100,
                "output_tokens": 100,
                "total_tokens": 200,
            }
        }
    )

    [row] = report.costed_rows()
    assert row.pricing_name == "gpt-text"
    assert row.usage.input_tokens == 1_100
    assert row.usage.cached_input_tokens == 200
    assert row.usage.output_tokens == 500
    assert row.input_cost == Decimal("0.00092")
    assert row.output_cost == Decimal("0.001")
    assert row.total_cost == Decimal("0.00192")


def test_report_preserves_explicit_zero_cache_rates():
    config = _usage_config()
    pricing = config.prices["openai"]["gpt-text"]
    pricing.cached_input_per_million = Decimal(0)
    pricing.cache_write_per_million = Decimal(0)
    report = RunUsageReport(config, "openai")

    report.record(
        ModelUsageRecord(
            provider="openai",
            model="gpt-text",
            modality="text",
            input_tokens=200,
            cached_input_tokens=100,
            cache_write_tokens=100,
        )
    )

    [row] = report.costed_rows()
    assert row.input_cost == Decimal(0)


def test_report_merges_langchain_and_direct_speech_usage_in_one_table():
    fake_model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="done",
                response_metadata={"model_name": "gpt-text"},
                usage_metadata={
                    "input_tokens": 1_000,
                    "output_tokens": 500,
                    "total_tokens": 1_500,
                },
            )
        ]
    )

    with collect_run_usage(_usage_config(), "openai") as report:
        fake_model.invoke("hello")
        record_direct_model_usage(
            ModelUsageRecord(
                provider="openai",
                model="gpt-4o-mini-tts",
                modality="audio",
                input_tokens=10,
                output_tokens=20,
                source="openai_speech",
            )
        )

    payload = report.as_dict()
    assert len(payload["models"]) == 2
    assert payload["complete"] is True
    assert payload["known_cost"] == "0.002246"

    rendered = report.render_ascii()
    assert "gpt-text" in rendered
    assert "gpt-4o-mini-tts" in rendered
    assert "text" in rendered
    assert "audio" in rendered
    assert "$0.002246" in rendered


def test_report_marks_missing_or_incomplete_costs_as_unknown():
    report = RunUsageReport(_usage_config(), "openai")
    report.record(
        ModelUsageRecord(
            provider="openai",
            model="unknown-model",
            modality="text",
            input_tokens=10,
            output_tokens=2,
        )
    )
    report.record(
        ModelUsageRecord(
            provider="openai",
            model="gpt-4o-mini-tts",
            modality="audio",
            usage_complete=False,
            source="openai_speech",
        )
    )

    payload = report.as_dict()
    assert payload["complete"] is False
    assert all(row["total_cost"] is None for row in payload["models"])
    assert "KNOWN SUBTOTAL" in report.render_ascii()
    assert "N/A" in report.render_ascii()


def test_report_degrades_invalid_token_breakdown_to_incomplete_note():
    report = RunUsageReport(_usage_config(), "openai")

    report.record(
        ModelUsageRecord(
            provider="openai",
            model="gpt-text",
            modality="text",
            input_tokens=10,
            cached_input_tokens=11,
        )
    )

    payload = report.as_dict()
    [usage] = payload["models"]
    assert usage["usage_complete"] is False
    assert usage["total_cost"] is None
    assert any("Malformed langchain usage record" in note for note in payload["notes"])


def test_collect_run_usage_does_not_raise_on_malformed_langchain_metadata(monkeypatch):
    @contextmanager
    def malformed_callback():
        yield SimpleNamespace(
            usage_metadata={
                "gpt-text": {
                    "input_tokens": "not-an-integer",
                    "output_tokens": 2,
                }
            }
        )

    monkeypatch.setattr("scripts.usage_report.get_usage_metadata_callback", malformed_callback)

    with collect_run_usage(_usage_config(), "openai") as report:
        pass

    payload = report.as_dict()
    [usage] = payload["models"]
    assert usage["usage_complete"] is False
    assert any("malformed LangChain usage metadata" in note for note in payload["notes"])


def test_report_marks_non_mapping_langchain_metadata_incomplete_without_raising():
    report = RunUsageReport(_usage_config(), "openai")

    report.merge_langchain_usage(["unexpected", "shape"])

    payload = report.as_dict()
    assert payload["complete"] is False
    assert payload["models"] == []
    assert "malformed usage metadata" in report.render_ascii()


def test_ambiguous_pricing_is_reported_as_unknown_instead_of_breaking_the_job():
    config = _usage_config()
    config.prices["openai"]["duplicate"] = config.prices["openai"]["gpt-text"].model_copy(
        update={"aliases": ["gpt-text-*"]}
    )
    report = RunUsageReport(config, "openai")
    report.record(
        ModelUsageRecord(
            provider="openai",
            model="gpt-text-2026-07-01",
            modality="text",
            input_tokens=10,
            output_tokens=2,
        )
    )

    rendered = report.render_ascii()

    assert "N/A" in rendered
    assert "pricing aliases matched multiple models" in rendered

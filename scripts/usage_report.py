"""Run-scoped model token usage aggregation and estimated-cost reporting."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from decimal import Decimal
from fnmatch import fnmatchcase
from threading import Lock
from typing import Any, Literal

from langchain_core.callbacks import get_usage_metadata_callback

from scripts.models import ModelPricingConfig, UsageReportingConfig

MILLION = Decimal(1_000_000)


@dataclass
class ModelUsageRecord:
    """Normalized token usage for one provider model and modality."""

    provider: str
    model: str
    modality: Literal["text", "audio"]
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    usage_complete: bool = True
    source: Literal["langchain", "openai_speech", "elevenlabs_speech"] = "langchain"

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: ModelUsageRecord) -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.output_tokens += other.output_tokens
        self.usage_complete = self.usage_complete and other.usage_complete


@dataclass(frozen=True)
class CostedUsage:
    """One usage record with its resolved price and estimated cost."""

    usage: ModelUsageRecord
    pricing_name: str | None
    input_cost: Decimal | None
    output_cost: Decimal | None

    @property
    def total_cost(self) -> Decimal | None:
        if self.input_cost is None or self.output_cost is None:
            return None
        return self.input_cost + self.output_cost


_active_report: ContextVar[Any] = ContextVar(
    "briefberlin_run_usage_report",
    default=None,
)


class RunUsageReport:
    """Merge LangChain and direct-provider usage into one run report."""

    def __init__(self, config: UsageReportingConfig, default_provider: str):
        self.config = config
        self.default_provider = default_provider.strip().lower()
        self._records: dict[tuple[str, str, str], ModelUsageRecord] = {}
        self._notes: set[str] = set()
        self._collection_complete = True
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def merge_langchain_usage(self, usage_by_model: Any) -> None:
        """Normalize LangChain's provider-agnostic UsageMetadata mapping."""
        if not isinstance(usage_by_model, Mapping):
            self.mark_incomplete(
                "LangChain returned malformed usage metadata; usage may be incomplete."
            )
            return
        for model, raw_usage in usage_by_model.items():
            try:
                if not isinstance(raw_usage, Mapping):
                    raise TypeError("usage metadata must be an object")
                input_details = _mapping(raw_usage.get("input_token_details"))
                record = ModelUsageRecord(
                    provider=self.default_provider,
                    model=str(model),
                    modality="text",
                    input_tokens=_non_negative_int(raw_usage.get("input_tokens")),
                    cached_input_tokens=_non_negative_int(input_details.get("cache_read")),
                    cache_write_tokens=_non_negative_int(input_details.get("cache_creation")),
                    output_tokens=_non_negative_int(raw_usage.get("output_tokens")),
                    source="langchain",
                )
            except (TypeError, ValueError) as exc:
                self._record_incomplete(
                    provider=self.default_provider,
                    model=str(model),
                    modality="text",
                    source="langchain",
                    note=f"{model}: malformed LangChain usage metadata ({exc}).",
                )
                continue
            self.record(record)

    def record(self, record: ModelUsageRecord) -> None:
        """Add a normalized usage record to this run."""
        if not self.enabled:
            return
        try:
            _validate_record(record)
            provider = record.provider.strip().lower()
            model = record.model.strip()
        except (AttributeError, TypeError, ValueError) as exc:
            self._record_incomplete(
                provider=record.provider,
                model=record.model,
                modality=record.modality,
                source=record.source,
                note=f"Malformed {record.source} usage record could not be normalized ({exc}).",
            )
            return
        normalized = ModelUsageRecord(
            provider=provider,
            model=model,
            modality=record.modality,
            input_tokens=record.input_tokens,
            cached_input_tokens=record.cached_input_tokens,
            cache_write_tokens=record.cache_write_tokens,
            output_tokens=record.output_tokens,
            usage_complete=record.usage_complete,
            source=record.source,
        )
        self._merge_record(normalized)

    def _record_incomplete(
        self,
        *,
        provider: Any,
        model: Any,
        modality: Literal["text", "audio"],
        source: Literal["langchain", "openai_speech", "elevenlabs_speech"],
        note: str,
    ) -> None:
        normalized = ModelUsageRecord(
            provider=str(provider).strip().lower() or self.default_provider or "unknown",
            model=str(model).strip() or "unknown-model",
            modality=modality,
            usage_complete=False,
            source=source,
        )
        self._merge_record(normalized)
        self.mark_incomplete(note)

    def _merge_record(self, record: ModelUsageRecord) -> None:
        key = (record.provider, record.model, record.modality)
        with self._lock:
            current = self._records.get(key)
            if current is None:
                self._records[key] = record
            else:
                current.add(record)

    def add_note(self, note: str) -> None:
        if note:
            with self._lock:
                self._notes.add(note)

    def mark_incomplete(self, note: str) -> None:
        """Mark collection incomplete without interrupting the underlying model call."""
        with self._lock:
            self._collection_complete = False
            if note:
                self._notes.add(note)

    def costed_rows(self) -> list[CostedUsage]:
        rows = [self._cost_record(record) for record in self._records.values()]
        return sorted(
            rows,
            key=lambda row: (
                row.total_cost is None,
                -(row.total_cost or Decimal(0)),
                row.usage.provider,
                row.usage.model,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        rows = self.costed_rows()
        known_cost = sum(
            (row.total_cost for row in rows if row.total_cost is not None),
            Decimal(0),
        )
        complete = self._collection_complete and all(row.total_cost is not None for row in rows)
        return {
            "currency": self.config.currency,
            "pricing_as_of": (
                self.config.pricing_as_of.isoformat() if self.config.pricing_as_of else None
            ),
            "complete": complete,
            "known_cost": str(known_cost),
            "models": [
                {
                    "provider": row.usage.provider,
                    "model": row.usage.model,
                    "modality": row.usage.modality,
                    "input_tokens": row.usage.input_tokens,
                    "cached_input_tokens": row.usage.cached_input_tokens,
                    "cache_write_tokens": row.usage.cache_write_tokens,
                    "output_tokens": row.usage.output_tokens,
                    "total_tokens": row.usage.total_tokens,
                    "usage_complete": row.usage.usage_complete,
                    "pricing_model": row.pricing_name,
                    "input_cost": _decimal_string(row.input_cost),
                    "output_cost": _decimal_string(row.output_cost),
                    "total_cost": _decimal_string(row.total_cost),
                }
                for row in rows
            ],
            "notes": sorted(self._notes),
        }

    def render_ascii(self) -> str:
        """Render a dependency-free ASCII table suitable for CLI output."""
        if not self.enabled:
            return ""
        rows = self.costed_rows()
        title = "AI usage and estimated cost"
        if not rows:
            empty_report_notes = "\n".join(
                f"Note: {note}" for note in sorted(self._notes)
            )
            suffix = f"\n\n{empty_report_notes}" if empty_report_notes else ""
            return f"{title}\n\nNo model usage was recorded.{suffix}"

        headers = [
            "Provider",
            "Model",
            "Modality",
            "Input",
            "Cache read",
            "Cache write",
            "Output",
            "Total",
            "Input USD",
            "Output USD",
            "Total USD",
        ]
        table_rows: list[list[str]] = []
        known_input_cost = Decimal(0)
        known_output_cost = Decimal(0)
        all_costs_known = True

        for row in rows:
            usage = row.usage
            if row.input_cost is None or row.output_cost is None:
                all_costs_known = False
            else:
                known_input_cost += row.input_cost
                known_output_cost += row.output_cost
            table_rows.append(
                [
                    usage.provider,
                    usage.model,
                    usage.modality,
                    _tokens(usage.input_tokens),
                    _tokens(usage.cached_input_tokens) if usage.modality == "text" else "-",
                    _tokens(usage.cache_write_tokens) if usage.modality == "text" else "-",
                    _tokens(usage.output_tokens),
                    _tokens(usage.total_tokens),
                    _money(row.input_cost),
                    _money(row.output_cost),
                    _money(row.total_cost),
                ]
            )

        totals = [
            "TOTAL" if all_costs_known else "KNOWN SUBTOTAL",
            "",
            "",
            _tokens(sum(row.usage.input_tokens for row in rows)),
            _tokens(sum(row.usage.cached_input_tokens for row in rows)),
            _tokens(sum(row.usage.cache_write_tokens for row in rows)),
            _tokens(sum(row.usage.output_tokens for row in rows)),
            _tokens(sum(row.usage.total_tokens for row in rows)),
            _money(known_input_cost),
            _money(known_output_cost),
            _money(known_input_cost + known_output_cost),
        ]
        table = _ascii_table(headers, table_rows, totals)

        notes = list(sorted(self._notes))
        if not all_costs_known:
            notes.append("Rows marked N/A are excluded from the known subtotal.")
        if self.config.pricing_as_of:
            notes.append(f"Pricing configured as of {self.config.pricing_as_of.isoformat()}.")
        notes.append("Provider billing is authoritative; displayed costs are estimates.")
        rendered_notes = "\n".join(f"Note: {note}" for note in dict.fromkeys(notes))
        return f"{title}\n\n{table}\n\n{rendered_notes}"

    def _cost_record(self, usage: ModelUsageRecord) -> CostedUsage:
        resolved = self._resolve_price(usage.provider, usage.model, usage.modality)
        if resolved is None:
            self.add_note(
                f"{usage.provider}/{usage.model}: no unambiguous {usage.modality} price was configured."
            )
            return CostedUsage(usage, None, None, None)
        if not usage.usage_complete:
            return CostedUsage(usage, resolved[0], None, None)

        pricing_name, pricing = resolved
        cached = min(usage.cached_input_tokens, usage.input_tokens)
        cache_write = min(usage.cache_write_tokens, max(usage.input_tokens - cached, 0))
        regular = max(usage.input_tokens - cached - cache_write, 0)
        cached_rate = pricing.cached_input_per_million
        if cached_rate is None:
            cached_rate = pricing.input_per_million
        if cached and pricing.cached_input_per_million is None:
            self.add_note(
                f"{usage.model}: cached input used the standard input rate because no cache rate was configured."
            )
        cache_write_rate = pricing.cache_write_per_million
        if cache_write_rate is None:
            cache_write_rate = pricing.input_per_million
        if cache_write and pricing.cache_write_per_million is None:
            self.add_note(
                f"{usage.model}: cache creation used the standard input rate because no cache-write rate was configured."
            )
        input_cost = (
            Decimal(regular) * pricing.input_per_million
            + Decimal(cached) * cached_rate
            + Decimal(cache_write) * cache_write_rate
        ) / MILLION
        output_cost = Decimal(usage.output_tokens) * pricing.output_per_million / MILLION
        return CostedUsage(usage, pricing_name, input_cost, output_cost)

    def _resolve_price(
        self,
        provider: str,
        model: str,
        modality: Literal["text", "audio"],
    ) -> tuple[str, ModelPricingConfig] | None:
        provider_prices = self.config.prices.get(provider, {})
        exact = provider_prices.get(model)
        if exact is not None and exact.modality == modality:
            return model, exact

        matches = [
            (canonical, pricing)
            for canonical, pricing in provider_prices.items()
            if pricing.modality == modality
            if any(fnmatchcase(model, pattern) for pattern in pricing.aliases)
        ]
        if len(matches) > 1:
            names = ", ".join(sorted(name for name, _pricing in matches))
            self.add_note(f"{provider}/{model}: pricing aliases matched multiple models ({names}).")
            return None
        return matches[0] if matches else None


@contextmanager
def collect_run_usage(
    config: UsageReportingConfig,
    provider: str,
) -> Iterator[RunUsageReport]:
    """Collect LangChain and direct-provider usage for one execution context."""
    report = RunUsageReport(config, provider)
    if not config.enabled:
        yield report
        return

    context_token: Token[RunUsageReport | None] = _active_report.set(report)
    try:
        with get_usage_metadata_callback() as callback:
            try:
                yield report
            finally:
                try:
                    report.merge_langchain_usage(callback.usage_metadata)
                except Exception as exc:
                    report.mark_incomplete(
                        f"LangChain usage collection failed ({exc}); usage may be incomplete."
                    )
    finally:
        _active_report.reset(context_token)


def record_direct_model_usage(record: ModelUsageRecord) -> None:
    """Record usage from a non-LangChain provider call in the active run."""
    report = _active_report.get()
    if report is not None:
        report.record(record)


def add_usage_report_note(note: str) -> None:
    report = _active_report.get()
    if report is not None:
        report.add_note(note)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _non_negative_int(value: Any) -> int:
    if value is None:
        return 0
    result = int(value)
    if result < 0:
        raise ValueError(f"Token usage must be non-negative, got {result}")
    return result


def _validate_record(record: ModelUsageRecord) -> None:
    if not record.provider.strip() or not record.model.strip():
        raise ValueError("Usage records require non-empty provider and model names")
    for value in (
        record.input_tokens,
        record.cached_input_tokens,
        record.cache_write_tokens,
        record.output_tokens,
    ):
        if value < 0:
            raise ValueError("Token usage must be non-negative")
    if record.cached_input_tokens + record.cache_write_tokens > record.input_tokens:
        raise ValueError("Cached and cache-write tokens cannot exceed input tokens")


def _decimal_string(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _money(value: Decimal | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:.6f}"


def _tokens(value: int) -> str:
    return f"{value:,}"


def _ascii_table(headers: list[str], rows: list[list[str]], totals: list[str]) -> str:
    all_rows = [headers, *rows, totals]
    widths = [max(len(row[index]) for row in all_rows) for index in range(len(headers))]

    def separator() -> str:
        return "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    numeric_columns = set(range(3, len(headers)))

    def render(row: list[str]) -> str:
        cells = []
        for index, value in enumerate(row):
            aligned = (
                value.rjust(widths[index])
                if index in numeric_columns
                else value.ljust(widths[index])
            )
            cells.append(f" {aligned} ")
        return "|" + "|".join(cells) + "|"

    border = separator()
    lines = [border, render(headers), border]
    lines.extend(render(row) for row in rows)
    lines.extend([border, render(totals), border])
    return "\n".join(lines)

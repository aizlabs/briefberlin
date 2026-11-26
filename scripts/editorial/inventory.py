"""Read the editable source directory without touching host state."""

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .db import ROOT

SOURCE_REGISTRY = ROOT / "config/civic_sources.json"
DEFAULT_REGISTRY = (
    SOURCE_REGISTRY if SOURCE_REGISTRY.exists() else Path(__file__).with_name("civic_sources.json")
)
ADAPTERS = {"feed", "listing", "documents", "notice", "lookup"}
URL_FIELDS = {"monitor_url", "rss_url", "press_office_url", "example_url"}


def required_text(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"expected nonempty string for {key}")
    return value


def identifier(obj: dict[str, Any], key: str) -> str:
    value = required_text(obj, key)
    if not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", value):
        raise ValueError(f"invalid {key}: {value}")
    return value


def check_url(value: str) -> None:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").removesuffix(".")
    if (
        parsed.scheme not in {"http", "https"} or not host or parsed.username is not None
        or parsed.password is not None or "\\" in value or parsed.port == 0
        or any(ord(c) < 33 or c.isspace() or ord(c) == 127 for c in value)
    ):
        raise ValueError(f"invalid public URL: {value}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or not all(
            re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
            for label in host.split(".")
        ):
            raise ValueError(f"invalid public hostname: {host}") from None
    else:
        if not address.is_global:
            raise ValueError(f"expected public address: {host}")


def request_url(value: str) -> str:
    """Identify a validated HTTP request while keeping the supplied URL in source resources."""
    parsed = urlsplit(value)
    host = (parsed.hostname or "").removesuffix(".")
    authority = f"[{host}]" if ":" in host else host
    if parsed.port is not None and parsed.port != {"http": 80, "https": 443}[parsed.scheme]:
        authority += f":{parsed.port}"
    return urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))


@dataclass(frozen=True)
class Poll:
    key: str
    url: str
    adapter: str
    interval: int
    selector: str | None
    link_pattern: str | None


@dataclass(frozen=True)
class Source:
    id: str
    publisher: str
    scope: str
    active: bool
    poll: Poll
    resources: list[tuple[str, str, str]]
    metadata: str


def parse_source(raw: Any) -> Source:
    if not isinstance(raw, dict) or not isinstance(raw.get("poll"), dict):
        raise ValueError("expected source with poll configuration")
    source_id = identifier(raw, "id")
    options = raw["poll"]
    unexpected = options.keys() - {
        "endpoint_id", "adapter", "interval_minutes", "selector", "link_pattern", "note", "purpose"
    }
    if unexpected:
        raise ValueError(f"{source_id}: unknown poll settings: {sorted(unexpected)}")
    key = identifier(options, "endpoint_id")
    adapter = required_text(options, "adapter")
    interval = options.get("interval_minutes")
    if adapter not in ADAPTERS or type(interval) is not int or not 1 <= interval <= 525600:
        raise ValueError(f"{source_id}: invalid adapter or interval_minutes")
    active = raw.get("active")
    if type(active) is not bool:
        raise ValueError(f"{source_id}: active must be a boolean")
    selector = required_text(options, "selector") if "selector" in options else None
    if selector:
        import soupsieve

        try:
            soupsieve.compile(selector)
        except ValueError as exc:
            raise ValueError(f"{source_id}: invalid CSS selector") from exc
        except SyntaxError as exc:
            raise ValueError(f"{source_id}: invalid CSS selector") from exc
    pattern = required_text(options, "link_pattern") if "link_pattern" in options else None
    if pattern:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"{source_id}: invalid link_pattern") from exc
    primary = "rss_url" if adapter == "feed" else "monitor_url"
    url = required_text(raw, primary)
    lookup_purpose = options.get("purpose", "reference")
    if lookup_purpose not in ("contact", "subscription", "reference"):
        raise ValueError(f"{source_id}: invalid lookup purpose")
    roles = {
        "monitor_url": "reference", "rss_url": "reference",
        "press_office_url": "contact", "example_url": "example",
        primary: lookup_purpose if adapter == "lookup" else adapter,
    }
    resources = []
    unknown_urls = {field for field in raw if field.endswith("_url")} - URL_FIELDS
    if unknown_urls:
        raise ValueError(f"{source_id}: unclassified URL fields {sorted(unknown_urls)}")
    for field in sorted(URL_FIELDS.intersection(raw)):
        address = required_text(raw, field)
        check_url(address)
        resources.append((field, address, roles[field]))
    return Source(
        source_id, required_text(raw, "publisher"), required_text(raw, "scope"), active,
        Poll(key, request_url(url), adapter, interval, selector, pattern), resources,
        json.dumps(raw, ensure_ascii=False, sort_keys=True),
    )


def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_registry(path: Path) -> list[Source]:
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported registry schema")
    if not isinstance(data.get("sources"), list):
        raise ValueError("registry must contain a sources array")
    sources = [parse_source(raw) for raw in data["sources"]]
    if len({source.id for source in sources}) != len(sources):
        raise ValueError("duplicate source id")
    active: dict[str, Poll] = {}
    for source in sources:
        if source.active and source.poll.adapter != "lookup":
            shared = active.setdefault(source.poll.url, source.poll)
            if shared != source.poll:
                raise ValueError(f"{source.id}: conflicting settings or IDs for shared active URL")
    return sources

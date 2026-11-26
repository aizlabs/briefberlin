"""Bounded, sequential HTTP reads. Each collection tick shares one host budget."""

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import requests

from .inventory import check_url


class Gap(Exception):
    """A printable category, without downloaded text, URLs or request headers."""

    def __init__(self, category: str, retry_at: int = 0):
        super().__init__(category)
        self.retry_at = retry_at


@dataclass(frozen=True)
class Response:
    url: str
    body: bytes
    status: int = 200
    media: str = "text/html"
    etag: str = ""
    modified: str = ""


def retry_time(value: str, now: int) -> int:
    try:
        if value.isascii() and value.isdecimal() and len(value) <= 10:
            return now + int(value)
        dt = parsedate_to_datetime(value)
        return max(now, int((dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()))
    except (ValueError, TypeError, OverflowError, OSError):
        return 0


def host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


class Client:
    def __init__(self, *, per_host: int = 16, max_bytes: int = 4 * 1024 * 1024,
                 before_request: Callable[[str], None] | None = None):
        self.per_host = per_host
        self.max_bytes = max_bytes
        self.counts: Counter[str] = Counter()
        self.before_request = before_request

    def __call__(self, url: str, headers: dict[str, str]) -> Response:
        original_host = host(url)
        deadline = time.monotonic() + 25
        with requests.Session() as session:
            session.trust_env = False  # Public reads never consult .netrc or proxy credentials.
            session.headers["User-Agent"] = "BriefBerlin-Editorial/1.0"
            for _ in range(4):
                try:
                    check_url(url)
                except ValueError:
                    raise Gap("invalid public URL") from None
                if host(url) != original_host:
                    raise Gap("redirect outside source host")
                if self.before_request:
                    self.before_request(url)
                if self.counts[original_host] >= self.per_host:
                    raise Gap("tick host request limit")
                self.counts[original_host] += 1
                if time.monotonic() >= deadline:
                    raise Gap("request deadline")
                try:
                    with session.get(url, headers=headers, timeout=(4, 6), stream=True,
                                     allow_redirects=False) as response:
                        code = response.status_code
                        if code in (301, 302, 303, 307, 308):
                            location = response.headers.get("Location")
                            if not location:
                                raise Gap("redirect missing location")
                            url = urljoin(url, location)
                            continue
                        if code not in (200, 304):
                            retry = retry_time(response.headers.get("Retry-After", ""), int(time.time()))
                            raise Gap(f"HTTP {code}", retry)
                        body = bytearray()
                        for chunk in response.iter_content(16384):
                            if time.monotonic() >= deadline:
                                raise Gap("request deadline")
                            if len(body) + len(chunk) > self.max_bytes:
                                raise Gap("response size limit")
                            body.extend(chunk)
                        return Response(response.url, bytes(body), code,
                                        response.headers.get("Content-Type", "").lower(),
                                        response.headers.get("ETag", ""),
                                        response.headers.get("Last-Modified", ""))
                except requests.RequestException as exc:
                    raise Gap(type(exc).__name__) from None
        raise Gap("redirect limit")

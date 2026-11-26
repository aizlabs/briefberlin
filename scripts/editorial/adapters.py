"""Read public feeds and identify narrowly scoped publication links and evidence."""

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import feedparser
from bs4 import BeautifulSoup, NavigableString, Tag

from .http import Gap, Response, host
from .inventory import check_url, request_url
from .registry import Endpoint

DATE = re.compile(r"\b(?:20\d\d[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}\.\s?\d{1,2}\.\s?20\d\d)\b")
BERLIN_RELEASE = re.compile(r"/(?:pressemitteilung|polizeimeldung)\.\d+\.php$", re.I)
PUBLICATION_DATE = re.compile(r"(?:Pressemitteilung|Polizeimeldung|Veröffentlicht)\s+(?:vom|am)\s+"
                              r"(\d{1,2}\.\s?\d{1,2}\.\s?20\d\d)", re.I)
STAMP_LABEL = re.compile(r"(?:Stand|Aktualisiert(?: am)?|Zuletzt aktualisiert(?: am)?|"
                         r"Veröffentlicht(?: am)?|Last updated|Updated|Published)\s*:?\s*$", re.I)
NAVIGATION = re.compile(r"/(?:kontakt|contact|impressum|datenschutz|privacy|newsletter|"
                        r"abonnement|subscribe|sitemap)(?:[./-]|$)", re.I)
TRACKING = {"fbclid", "gclid"}
MAX_LINKS = 250


@dataclass(frozen=True)
class Item:
    url: str
    title: str
    evidence: str
    date: str = ""
    guid: str = ""
    alias: str = ""


@dataclass(frozen=True)
class Link:
    url: str
    title: str
    date: str = ""
    guid: str = ""


def clean(text: str) -> str:
    return " ".join(text.split())


def public_url(base: str, ref: str) -> str:
    try:
        if not ref.strip() or ref.lstrip().startswith("#"):
            return ""
        url = urljoin(base, ref)
        check_url(url)
        canonical = request_url(url)
        parts = urlsplit(canonical)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        remaining = [(k, v) for k, v in pairs if not k.lower().startswith("utm_") and k.lower() not in TRACKING]
        if remaining != pairs:
            return urlunsplit(parts._replace(query=urlencode(remaining)))
        return canonical
    except (ValueError, UnicodeError):
        return ""


def epoch(raw: str) -> int | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(raw)
        except (ValueError, TypeError, OverflowError):
            match = DATE.search(raw)
            if not match:
                return None
            date = match[0].replace(" ", "").replace("/", "-")
            try:
                dt = datetime.strptime(date, "%d.%m.%Y" if "." in date else "%Y-%m-%d")
            except ValueError:
                return None
    try:
        return int((dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo("Europe/Berlin"))).timestamp())
    except (ValueError, OverflowError, OSError):
        return None


def strip_markup(raw: str) -> str:
    return clean(BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)) if "<" in raw else clean(raw)


def feed(response: Response) -> tuple[list[Item], list[Link], set[str]]:
    parsed = feedparser.parse(response.body)
    if not parsed.version or (parsed.bozo and not parsed.entries):
        raise Gap("invalid or unsupported feed")
    items, links = [], []
    gaps: set[str] = set()
    if parsed.bozo:
        gaps.add("feed parser reported malformed input")
    for ordinal, entry in enumerate(parsed.entries, 1):
        url = public_url(response.url, entry.get("link", ""))
        title = strip_markup(entry.get("title", ""))
        if not url or not title:
            gaps.add(f"feed item {ordinal}: missing public address or title")
            continue
        date = entry.get("published", "")  # Atom updated alone can be a wrapper refresh.
        guid = entry.get("id", "")
        raw = next((c.value for c in entry.get("content", []) if c.get("value")), "")
        evidence = strip_markup(raw or entry.get("summary", ""))
        if len(evidence) >= 30 and evidence != title:
            items.append(Item(url, title, evidence, date, guid))
        elif host(url) == host(response.url):
            links.append(Link(url, title, date, guid))
        else:
            gaps.add(f"feed item {ordinal}: off-host item lacks evidence")
    return items, links, gaps


def soup(response: Response) -> BeautifulSoup:
    if response.media and not any(t in response.media for t in ("html", "text/plain", "xml")):
        raise Gap("unsupported HTML media type")
    doc = BeautifulSoup(response.body, "html.parser")
    for node in doc.select("script, style, nav, footer, header nav, form, aside, [hidden], [aria-hidden=true]"):
        node.decompose()
    return doc


def record_date(record: Tag) -> str:
    element = record.select_one("time[datetime]")
    if element:
        return str(element["datetime"])
    match = DATE.search(record.get_text(" ", strip=True))
    return match[0] if match else ""


def listing(endpoint: Endpoint, response: Response) -> list[Link]:
    doc = soup(response)
    if endpoint.selector:
        regions = doc.select(endpoint.selector)
    else:
        regions = [doc.select_one("main, [role=main], #content") or doc]
    links: dict[str, Link] = {}
    for region in regions:
        anchors = [region] if region.name == "a" else region.select("a[href]")
        for anchor in anchors:
            url = public_url(response.url, str(anchor.get("href", "")))
            if not url or url == public_url(response.url, response.url) or host(url) != host(response.url):
                continue
            path = urlsplit(url).path
            if NAVIGATION.search(path) or (endpoint.link_pattern and not re.search(endpoint.link_pattern, url)):
                continue
            title = clean(anchor.get_text(" ", strip=True) or str(anchor.get("title", "")))
            if not title:
                continue
            record = anchor.find_parent(["li", "article", "tr", "section"])
            date = record_date(record) if record and record.name != "section" else ""
            if not date:
                match = DATE.search(title) or DATE.search(path)
                date = match[0] if match else ""
            if endpoint.adapter == "documents":
                if not (path.lower().endswith(".pdf") or endpoint.link_pattern):
                    continue
            elif not (date or endpoint.link_pattern or BERLIN_RELEASE.search(path)):
                continue
            # A date in an index row, URL or title identifies a possible story.
            # It may be an event or deadline rather than its publication date.
            links.setdefault(url, Link(url, title))
            if len(links) > MAX_LINKS:
                raise Gap("listing link limit; narrow selector or link pattern")
    if not links:
        raise Gap("no matching publication links; check selector or link pattern")
    return list(links.values())


def extract(endpoint: Endpoint, response: Response, link: Link | None = None) -> Item:
    if response.body.startswith(b"%PDF-") or "application/pdf" in response.media:
        if not link or endpoint.adapter != "documents":
            raise Gap("unexpected PDF")
        try:
            result = subprocess.run(
                ["pdftotext", "-f", "1", "-l", "5", "-enc", "UTF-8", "-", "-"],
                input=response.body, capture_output=True, timeout=8, check=True,
            )
        except FileNotFoundError:
            raise Gap("PDF extraction requires pdftotext") from None
        except (subprocess.SubprocessError, OSError):
            raise Gap("unreadable PDF") from None
        evidence = clean(result.stdout.decode("utf8", "replace"))
        if len(evidence) < 30:
            raise Gap("PDF lacks extractable evidence")
        return Item(response.url, link.title, evidence, guid=link.guid, alias=link.url)

    doc = soup(response)
    notice = endpoint.adapter == "notice"
    selector = endpoint.selector if notice and endpoint.selector else "article, main, [role=main], #content"
    root = doc.select_one(selector) if notice else (doc.select_one("article") or doc.select_one(selector))
    if root is None:
        raise Gap("missing publication content region")
    date_node = (doc.select_one('head meta[property="article:published_time"], head meta[itemprop=datePublished]')
                 or root.select_one('meta[property="article:published_time"], [itemprop=datePublished], time[pubdate]'))
    date = (str(date_node.get("content") or date_node.get("datetime")
                or date_node.get_text(" ", strip=True)) if date_node else "")
    if not date:
        label = PUBLICATION_DATE.search(root.get_text(" ", strip=True)[:1000])
        date = label[1] if label else ""
    if not date and link and endpoint.adapter == "feed":
        date = link.date  # published in the feed entry, not the index row.
    canonical = doc.select_one('link[rel~="canonical"][href]')
    resolved = public_url(response.url, str(canonical["href"])) if canonical else ""
    url = response.url if not resolved or host(resolved) != host(response.url) else resolved
    if notice:
        url = endpoint.url
    for tag in root.select('.breadcrumb, .breadcrumbs, .social-share, .last-modified, '
                           '[itemprop=dateModified], [itemprop=datePublished], time[pubdate]'):
        tag.decompose()
    for stamp in root.select("time"):
        block = stamp.find_parent(["p", "li", "h1", "h2", "h3"])
        text = stamp.get_text(" ", strip=True)
        # A notice can use an unstructured div for prose, alongside other blocks.
        siblings = (stamp.previous_sibling, stamp.next_sibling)
        adjacent_prose = any(isinstance(node, NavigableString) and node.strip() for node in siblings)
        if not block and adjacent_prose:
            block = stamp.parent
        block_text = block.get_text(" ", strip=True) if block else ""
        prefix = block_text.removesuffix(text).strip() if text and block_text.endswith(text) else None
        if not block or prefix == "" or (prefix and STAMP_LABEL.fullmatch(prefix)):
            stamp.decompose()
        elif notice and stamp.get("datetime") and stamp["datetime"] != text:
            stamp.append(f" ({stamp['datetime']})")
    title_node = root.find("h1") or doc.find("h1") or doc.title
    title = clean(title_node.get_text(" ", strip=True)) if title_node else (link.title if link else "")
    for heading in root.select("h1"):
        heading.decompose()
    evidence = (clean(root.get_text(" ", strip=True)) if notice else
                clean(" ".join(p.get_text(" ", strip=True) for p in root.select("p"))))
    if len(evidence) < 30 or not title:
        raise Gap("publication lacks extractable evidence")
    return Item(public_url(response.url, url), title, evidence, date,
                link.guid if link else "", link.url if link else "")

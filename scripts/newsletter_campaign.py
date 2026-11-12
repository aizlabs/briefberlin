"""Daily Brevo newsletter campaign builder.

Builds one daily issue from the site's Atom feed (feed.xml), deduplicates the
A2/B1 story pairs, renders German HTML + plain-text, and hands the issue to
Brevo as a scheduled email campaign (list 3) - or sends it immediately to the
test list (list 4) in test mode. Runs from GitHub Actions
(.github/workflows/newsletter-daily.yml).

Safety properties (enforced here and covered by tests):

- Production stays disabled behind newsletter.enabled / NEWSLETTER_ENABLED.
- One audience per mode: list 3 for production, list 4 for test, never both,
  never any other list. No endpoint for creating, importing or deleting
  contacts is ever called; subscribers only arrive via the Brevo DOI form.
- Idempotent per day: campaign name BB-YYYY-MM-DD. Existing campaigns in a
  sending/sent/dead state stop the run; an incomplete draft is repaired in
  place, never duplicated. The content watermark advances only from campaigns
  observed as ``sent``.
- Content cutoff never exceeds the feed-fetch start time or the configured
  issue-day boundary; early preparation cannot consume future content.
- Production targets 07:00 Europe/Berlin; delayed runs schedule delivery
  one minute after preparation starts.
- Quota guard checks remaining free email credits and reserves additional
  headroom for double-opt-in and welcome mails; unknown balances fail closed.

API fields follow Brevo's official OpenAPI specs (developers.brevo.com,
Marketing Campaigns / Contact Management / Email API, base
https://api.brevo.com/v3): POST/GET/PUT/DELETE /emailCampaigns,
POST /emailCampaigns/{id}/sendNow, GET /contacts/lists/{id},
GET /smtp/statistics/aggregatedReport. Campaigns have no API field for a
plain-text part or for disabling open/click tracking - see
docs/newsletter-runbook.md for the resulting limitations.
"""

from __future__ import annotations

import argparse
import calendar
import html as html_module
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

from scripts.models import NewsletterConfig

logger = logging.getLogger("briefberlin.newsletter")

BERLIN = ZoneInfo("Europe/Berlin")

# Campaign status values from Brevo's official OpenAPI spec
# (developers.brevo.com, Marketing Campaigns API).
STATUS_DRAFT = "draft"
STATUS_SENT = "sent"
# Statuses that mean "this campaign owns the day; do not create another".
STATUS_ACTIVE = {"queued", "in_process", "in_review", "sent"}
# Cancelled/archived campaigns never re-send; do not silently recreate them.
STATUS_DEAD = {"cancelled", "archive"}

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_QUOTA = 3
EXIT_STALE = 4

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def format_german_date(moment: datetime) -> str:
    """Wochertag, DD.MM.YYYY for a Europe/Berlin datetime."""
    local = moment.astimezone(BERLIN)
    weekday = WEEKDAYS_DE[local.weekday()]
    return f"{weekday}, {local.day:02d}.{local.month:02d}.{local.year}"


def format_german_long_date(moment: datetime) -> str:
    local = moment.astimezone(BERLIN)
    return f"{local.day}. {MONTHS_DE[local.month - 1]} {local.year}"


def build_subject(articles: Sequence["NewsletterArticle"], issue_date: datetime) -> str:
    """German subject: 'BriefBerlin am Montag, 09.11.2026: <first headline>'."""
    base = f"BriefBerlin am {format_german_date(issue_date)}"
    if articles:
        headline = articles[0].title.strip()
        subject = f"{base}: {headline}"
    else:
        subject = base
    if len(subject) <= 78:
        return subject
    keep = subject[:78]
    cut = keep.rsplit(" ", 1)[0] if " " in keep else keep
    return cut.rstrip(" ,:;-") + "…"


# =============================================================================
# Config loading
# =============================================================================


def load_newsletter_config(environment: str = "local") -> NewsletterConfig:
    """Merge config/base.yaml -> config/<environment>.yaml -> environment."""
    import os

    config_dir = Path(__file__).parent.parent / "config"
    merged: Dict[str, Any] = {}

    for name in ("base.yaml", f"{environment}.yaml"):
        path = config_dir / name
        if path.exists():
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            section = data.get("newsletter", {})
            if isinstance(section, dict):
                merged.update(section)

    env_overrides = {
        "enabled": ("NEWSLETTER_ENABLED", "bool"),
        "api_key": ("BREVO_API_KEY", "str"),
        "feed_url": ("NEWSLETTER_FEED_URL", "str"),
        "site_base_url": ("NEWSLETTER_SITE_BASE_URL", "str"),
        "production_list_id": ("NEWSLETTER_PRODUCTION_LIST_ID", "int"),
        "test_list_id": ("NEWSLETTER_TEST_LIST_ID", "int"),
    }
    for key, (env_name, kind) in env_overrides.items():
        raw = os.getenv(env_name)
        if raw is None or raw == "":
            continue
        if kind == "bool":
            merged[key] = raw.strip().lower() in {"1", "true", "yes", "on"}
        elif kind == "int":
            merged[key] = int(raw)
        else:
            merged[key] = raw

    return NewsletterConfig(**merged)


# =============================================================================
# Feed and article model
# =============================================================================


@dataclass
class NewsletterArticle:
    """One newsletter story (already deduplicated across A2/B1)."""

    title: str
    link: str
    published: datetime
    teaser: str
    level: Optional[str] = None

    def safe_link(self, site_base_url: str) -> Optional[str]:
        """Only same-site article links are ever rendered."""
        base = site_base_url.rstrip("/") + "/"
        if not self.link.startswith(base):
            return None
        rest = self.link[len(base):]
        if not rest.startswith("articles/") or "://" in rest:
            return None
        return self.link


@dataclass
class FeedEntry:
    """Raw feed.xml entry before A2/B1 deduplication."""

    entry_id: str
    title: str
    link: str
    published: datetime
    text: str
    description: Optional[str] = None
    level: Optional[str] = None


def _parse_published(raw: Optional[str], struct: Optional[Any]) -> Optional[datetime]:
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    if struct:
        return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    return None


def strip_html_to_text(markup: str) -> str:
    soup = BeautifulSoup(markup or "", "html.parser")
    for tag in soup(["script", "style", "button"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def first_sentences(text: str, max_chars: int = 220) -> str:
    """Take one or two sentences as the teaser, hard-capped at max_chars."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    teaser = ""
    for sentence in sentences[:2]:
        if not sentence.strip():
            continue
        if teaser and len(teaser) + len(sentence) > max_chars:
            break
        teaser = f"{teaser} {sentence}".strip()
        if len(teaser) >= max_chars:
            break
    if len(teaser) > max_chars:
        teaser = teaser[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return teaser


def parse_feed(xml_text: str) -> List[FeedEntry]:
    parsed = feedparser.parse(xml_text)
    entries: List[FeedEntry] = []
    for entry in parsed.entries:
        published = _parse_published(
            getattr(entry, "published", None), getattr(entry, "published_parsed", None)
        )
        if published is None:
            logger.warning("Feed entry without usable date skipped: %s", getattr(entry, "id", "?"))
            continue
        content = ""
        if getattr(entry, "content", None):
            content = entry.content[0].get("value", "")
        elif getattr(entry, "summary", None):
            content = entry.summary
        entries.append(
            FeedEntry(
                entry_id=getattr(entry, "id", "") or getattr(entry, "link", ""),
                title=strip_html_to_text(getattr(entry, "title", "") or ""),
                link=getattr(entry, "link", "") or "",
                published=published,
                text=strip_html_to_text(content),
                description=None,
                level=None,
            )
        )
    return entries


def load_post_metadata(
    posts_dir: Path,
) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    """Map article permalink -> (level, description) from output/_posts front matter.

    The site permalink for a post file YYYY-MM-DD-<slug>.md is
    /articles/<slug>/ (see output/_config.yml ``permalink: /articles/:title/``).
    """
    mapping: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    if not posts_dir.exists():
        return mapping
    for post_path in posts_dir.glob("*.md"):
        match = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)\.md$", post_path.name)
        if not match:
            continue
        permalink = f"/articles/{match.group(1)}/"
        try:
            text = post_path.read_text(encoding="utf-8")
        except OSError:
            continue
        front_matter = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not front_matter:
            continue
        try:
            meta = yaml.safe_load(front_matter.group(1)) or {}
        except yaml.YAMLError:
            continue
        mapping[permalink] = (meta.get("level"), meta.get("description"))
    return mapping


def link_to_permalink(link: str, site_base_url: str) -> Optional[str]:
    """Normalize an absolute article URL to its /articles/<slug>/ path."""
    base_path = urlparse(site_base_url).path.rstrip("/")
    parsed = urlparse(link)
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    if base_path and path.startswith(base_path + "/"):
        path = path[len(base_path) :]
    if path.startswith("/articles/"):
        return path
    return None


def deduplicate_stories(
    entries: List[FeedEntry],
    metadata: Dict[str, Tuple[Optional[str], Optional[str]]],
    site_base_url: str,
) -> List[FeedEntry]:
    """Collapse A2/B1 pairs (and accidental double posts) to one entry per story.

    Grouping key is the exact ``description`` from the post front matter: both
    level variants of one story share it, different stories do not. The A2
    entry represents the story (simple German; the level switch lives on the
    article page). Entries without a resolvable permalink/description stay
    singletons.
    """
    groups: Dict[str, List[FeedEntry]] = {}
    singletons: List[FeedEntry] = []

    for entry in entries:
        permalink = link_to_permalink(entry.link, site_base_url)
        level, description = metadata.get(permalink, (None, None)) if permalink else (None, None)
        entry.level = level
        entry.description = description
        if description:
            groups.setdefault(description, []).append(entry)
        else:
            singletons.append(entry)

    representatives: List[FeedEntry] = []
    for group in groups.values():
        a2 = [item for item in group if item.level == "A2"]
        pool = a2 or group
        representatives.append(min(pool, key=lambda item: (item.published, item.link)))
    representatives.extend(singletons)
    representatives.sort(key=lambda item: (item.published, item.link))
    return representatives


# =============================================================================
# Issue rendering
# =============================================================================


@dataclass
class RenderedIssue:
    subject: str
    html: str
    text: str
    article_count: int
    window_start: datetime
    window_end: datetime


PUBLISHER_LINES = (
    "BriefBerlin LLC",
    "1201 North Orange Street, Suite 740",
    "Wilmington, DE 19801, United States",
)


def render_issue(
    articles: Sequence[NewsletterArticle],
    issue_date: datetime,
    window_start: datetime,
    window_end: datetime,
    site_base_url: str,
) -> RenderedIssue:
    safe_articles: List[Tuple[NewsletterArticle, str]] = []
    for article in articles:
        safe_link = article.safe_link(site_base_url)
        if safe_link is None:
            logger.warning("Skipping article with off-site link: %r", article.link)
            continue
        safe_articles.append((article, safe_link))

    base = site_base_url.rstrip("/")
    subject = build_subject([article for article, _ in safe_articles], issue_date)
    date_line = html_module.escape(format_german_long_date(issue_date))

    html_parts = [
        '<p style="font-size:22px;font-weight:bold;margin:0 0 4px 0;">BriefBerlin</p>',
        f'<p style="color:#666666;margin:0 0 20px 0;">{date_line}</p>',
    ]
    text_parts = [f"BriefBerlin – {format_german_long_date(issue_date)}", ""]

    for article, link in safe_articles:
        title = html_module.escape(article.title)
        teaser = html_module.escape(article.teaser)
        anchor = html_module.escape(link, quote=True)
        html_parts.append(
            f'<h2 style="font-size:19px;margin:22px 0 6px 0;">'
            f'<a href="{anchor}" style="color:#1a1a1a;text-decoration:none;">{title}</a></h2>'
            f"<p style=\"margin:0 0 6px 0;\">{teaser}</p>"
            f'<p style="margin:0 0 20px 0;">'
            f'<a href="{anchor}" style="color:#0b5394;">Weiterlesen auf BriefBerlin</a></p>'
        )
        text_parts.extend(
            [article.title, article.teaser, f"Weiterlesen: {link}", ""]
        )

    levels_note = (
        "Jede Nachricht gibt es in zwei Niveaus: A2 und B1. "
        "Auf der Artikelseite kannst du umschalten."
    )
    html_parts.append(
        '<p style="color:#666666;font-size:14px;border-top:1px solid #dddddd;'
        f'padding-top:14px;">{html_module.escape(levels_note)}</p>'
    )
    text_parts.extend([levels_note, ""])

    publisher_html = "<br>".join(html_module.escape(line) for line in PUBLISHER_LINES)
    footer_html = (
        f'<p style="color:#888888;font-size:12px;border-top:1px solid #dddddd;padding-top:14px;">'
        f"{publisher_html}<br>"
        f'<a href="{html_module.escape(base + "/", quote=True)}">briefberlin.de</a> · '
        f'<a href="{html_module.escape(base + "/contact/", quote=True)}">Kontakt</a> · '
        f'<a href="{html_module.escape(base + "/privacy/", quote=True)}">Datenschutz</a><br>'
        'Du möchtest den Newsletter abbestellen? <a href="{{ unsubscribe }}">'
        'Hier abmelden.</a></p>'
    )
    html_parts.append(footer_html)
    text_parts.extend(
        list(PUBLISHER_LINES)
        + [
            f"{base}/  ·  Kontakt: {base}/contact/  ·  Datenschutz: {base}/privacy/",
            "Newsletter abbestellen: {{ unsubscribe }}",
        ]
    )

    html = (
        '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
        f'<meta name="briefberlin-cutoff" content="{window_end.isoformat()}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>BriefBerlin</title></head>"
        '<body style="margin:0;padding:0;background:#f4f4f4;">'
        '<div style="max-width:600px;margin:0 auto;padding:24px;background:#ffffff;'
        'color:#1a1a1a;font-family:Georgia,serif;line-height:1.55;">'
        + "\n".join(html_parts)
        + "</div></body></html>"
    )

    return RenderedIssue(
        subject=subject,
        html=html,
        text="\n".join(text_parts),
        article_count=len(safe_articles),
        window_start=window_start,
        window_end=window_end,
    )


# =============================================================================
# Brevo client
# =============================================================================


class BrevoApiError(Exception):
    pass


class BrevoClient:
    """Thin wrapper over the verified Brevo endpoints the builder needs.

    Deliberately exposes no contact create/import/delete endpoint: the
    newsletter audience only ever grows through the Brevo double-opt-in form,
    and suppression/unsubscribe handling stays with Brevo.
    """

    def __init__(self, config: NewsletterConfig, session: Optional[requests.Session] = None):
        self.config = config
        self.session = session or requests.Session()
        self.calls: List[Tuple[str, str]] = []

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.config.api_base_url.rstrip('/')}{path}"
        headers = {"api-key": self.config.api_key or "", "content-type": "application/json"}
        self.calls.append((method, path))
        response = self.session.request(method, url, headers=headers, timeout=30, **kwargs)
        if response.status_code >= 400:
            # Never log a provider body: it may echo subscriber data or keys.
            # Fixed hints let operators diagnose activation/scope/routing errors
            # without exposing the underlying response in public Actions logs.
            hint = ""
            try:
                error = response.json()
            except ValueError:
                error = None
            if isinstance(error, dict):
                message = str(error.get("message", "")).lower()
                if "not allowed on this path" in message:
                    hint = " (provider rejected this endpoint method)"
                elif "account" in message and any(
                    word in message for word in ("activat", "validat", "suspend")
                ):
                    hint = " (check account activation or suspension in Brevo)"
                elif any(word in message for word in ("permission", "scope", "access")):
                    hint = " (check API key resource permissions in Brevo)"
                else:
                    for field in ("sender", "subject", "htmlContent", "listIds", "recipients", "tag", "type"):
                        if re.search(rf"\b{field.lower()}\b", message):
                            hint = f" (provider mentioned campaign field: {field})"
                            break
            raise BrevoApiError(f"{method} {path} -> HTTP {response.status_code}{hint}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def list_campaigns(self, limit: int = 100) -> List[Dict[str, Any]]:
        """All email campaigns, following pagination (spec max limit is 100)."""
        campaigns: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page = self._request(
                "GET", "/emailCampaigns",
                params={"limit": limit, "offset": offset, "excludeHtmlContent": "false"},
            )
            batch = page.get("campaigns", []) if isinstance(page, dict) else []
            campaigns.extend(batch)
            if len(batch) < limit:
                return campaigns
            offset += limit

    def create_campaign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self._request("POST", "/emailCampaigns", json=payload)
        return result if isinstance(result, dict) else {}

    def update_campaign(self, campaign_id: int, payload: Dict[str, Any]) -> Any:
        return self._request("PUT", f"/emailCampaigns/{campaign_id}", json=payload)

    def delete_campaign(self, campaign_id: int) -> Any:
        return self._request("DELETE", f"/emailCampaigns/{campaign_id}")

    def send_now(self, campaign_id: int) -> Any:
        return self._request("POST", f"/emailCampaigns/{campaign_id}/sendNow", json={})

    def get_list_stats(self, list_id: int) -> Dict[str, Any]:
        result = self._request("GET", f"/contacts/lists/{list_id}")
        return result if isinstance(result, dict) else {}

    def remaining_email_credits(self) -> Optional[int]:
        """Read remaining free-plan send credits; unknown plans fail closed.

        Brevo GET /account returns plan[].credits, creditsType and type.
        Do not confuse SMS credits or a paid plan's allocation with the daily
        free email balance. Live acceptance must verify the account's signal.
        """
        account = self._request("GET", "/account")
        if not isinstance(account, dict) or not isinstance(account.get("plan"), list):
            return None
        plans = [
            plan for plan in account["plan"]
            if isinstance(plan, dict) and plan.get("type") == "free"
            and plan.get("creditsType") == "sendLimit"
        ]
        if len(plans) != 1:
            return None
        credits = plans[0].get("credits")
        return credits if type(credits) is int and credits >= 0 else None

    def transactional_requests_24h(self) -> int:
        report = self._request("GET", "/smtp/statistics/aggregatedReport", params={"days": 1})
        if not isinstance(report, dict):
            return 0
        return int(report.get("requests") or 0)


# =============================================================================
# Planning and run flow
# =============================================================================


def issue_name_for(now: datetime, prefix: str) -> str:
    local_date = now.astimezone(BERLIN).date()
    return f"{prefix}-{local_date.isoformat()}"


def content_cutoff_for(now: datetime, cutoff_hour: int) -> datetime:
    """Deterministic window end: issue-day cutoff_hour Europe/Berlin."""
    local = now.astimezone(BERLIN)
    return local.replace(hour=cutoff_hour, minute=0, second=0, microsecond=0)


def scheduled_send_time_for(now: datetime, send_hour: int) -> datetime:
    local = now.astimezone(BERLIN)
    return local.replace(hour=send_hour, minute=0, second=0, microsecond=0)


def find_named_campaign(
    campaigns: List[Dict[str, Any]], name: str
) -> Optional[Dict[str, Any]]:
    for campaign in campaigns:
        if campaign.get("name") == name:
            return campaign
    return None


def find_last_sent_watermark(
    campaigns: List[Dict[str, Any]], prefix: str, production_list_id: int = 3
) -> Optional[datetime]:
    """Content cutoff of the newest campaign actually observed as sent.

    Scheduled-but-not-sent campaigns never advance the watermark: if they
    never complete, their articles re-enter the next issue instead of being
    lost. Brevo's campaign status does not expose per-recipient delivery, so
    ``sent`` is the strongest available completion signal; partial-delivery
    cases need the manual review path (runbook).
    """
    newest: Optional[Dict[str, Any]] = None
    for campaign in campaigns:
        name = campaign.get("name") or ""
        if not re.fullmatch(rf"{re.escape(prefix)}-\d{{4}}-\d{{2}}-\d{{2}}", name):
            continue
        if campaign.get("recipients", {}).get("lists") != [production_list_id]:
            continue
        if campaign.get("status") != STATUS_SENT:
            continue
        if newest is None or name > (newest.get("name") or ""):
            newest = campaign
    if newest is None:
        return None
    markers = BeautifulSoup(newest.get("htmlContent") or "", "html.parser").find_all(
        "meta", attrs={"name": "briefberlin-cutoff"}
    )
    if len(markers) > 1:
        raise ValueError("Latest sent newsletter has ambiguous cutoff metadata; review required")
    # Read old tag-based history for compatibility, but never create tags:
    # this account rejects the tag option on campaign creation.
    value = markers[0].get("content") if markers else newest.get("tag")
    try:
        watermark = datetime.fromisoformat(str(value or ""))
        if watermark.tzinfo is None:
            raise ValueError("Cutoff timezone is missing")
        return watermark
    except ValueError as error:
        raise ValueError(
            "Latest sent newsletter has missing or invalid cutoff metadata; review required"
        ) from error


def detect_stale_campaigns(
    campaigns: List[Dict[str, Any]], prefix: str, now: datetime
) -> List[Dict[str, Any]]:
    """Past-date campaigns still sitting in a pre-send state.

    A BB-<past day> campaign still queued/in_process long after its slot
    means Brevo never completed the send (or is stuck). Recovery needs a
    human decision, so the run reports it and exits non-zero instead of
    guessing. Articles are not lost: the watermark did not advance.
    """
    today_name = issue_name_for(now, prefix)
    stale: List[Dict[str, Any]] = []
    for campaign in campaigns:
        name = campaign.get("name") or ""
        if not name.startswith(f"{prefix}-") or name >= today_name:
            continue
        if campaign.get("status") in {"queued", "in_process", "in_review", "cancelling"}:
            stale.append(campaign)
    return stale


def resolve_target_list(config: NewsletterConfig, target: str, dry_run: bool) -> int:
    if target not in {"production", "test"}:
        raise ValueError(f"target must be 'production' or 'test', got {target!r}")
    if target == "production" and not dry_run and not config.enabled:
        raise PermissionError(
            "Production target refused: newsletter.enabled is false "
            "(set NEWSLETTER_ENABLED=true only after review and live acceptance)."
        )
    return config.production_list_id if target == "production" else config.test_list_id


def quota_check(
    subscribers: int, config: NewsletterConfig, remaining_credits: Optional[int]
) -> Optional[str]:
    if remaining_credits is None:
        return "Remaining email quota is unknown; refusing to schedule a campaign."
    if subscribers > config.daily_email_limit:
        return (
            f"List has {subscribers} subscribers, above the {config.daily_email_limit} "
            "emails/day plan limit; sending would only reach part of the list."
        )
    available = min(config.daily_email_limit, remaining_credits) - config.daily_reserve
    if subscribers > available:
        return (
            f"List has {subscribers} subscribers but only {available} mails are "
            f"unreserved ({remaining_credits} remaining credits, "
            f"{config.daily_email_limit} daily limit, {config.daily_reserve} "
            "reserved for double-opt-in and welcome mails)."
        )
    return None


def check_abuse(client: BrevoClient, config: NewsletterConfig) -> Tuple[Optional[int], bool]:
    """DOI/transactional volume in the last 24h against the alert threshold.

    Caveat (documented in the runbook): whether Brevo counts form-triggered
    double-opt-in mails inside /smtp/statistics/aggregatedReport must be
    confirmed during live acceptance; the check is a guard, not proof.
    """
    try:
        count = client.transactional_requests_24h()
    except BrevoApiError as error:
        logger.warning("Abuse-statistics endpoint failed: %s", error)
        return None, False
    logger.info("Transactional requests in provider's 24h window: %d", count)
    return count, count > config.abuse_threshold_24h


def build_campaign_payload(
    config: NewsletterConfig,
    issue_name: str,
    issue: RenderedIssue,
    list_id: int,
    cutoff: datetime,
    scheduled_at: Optional[datetime],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": issue_name,
        "type": "classic",
        "sender": {"name": config.sender_name, "email": config.sender_email},
        "subject": issue.subject,
        "htmlContent": issue.html,
        "recipients": {"listIds": [list_id]},
        "replyTo": config.sender_email,
    }
    if scheduled_at is not None:
        payload["scheduledAt"] = scheduled_at.isoformat()
    return payload


def run_issue_builder(
    config: NewsletterConfig,
    target: str,
    dry_run: bool,
    feed_xml: str,
    now: datetime,
    client: Optional[BrevoClient] = None,
    posts_dir: Optional[Path] = None,
) -> Tuple[int, Dict[str, Any]]:
    """One idempotent preparation run. Returns (exit_code, details)."""
    list_id = resolve_target_list(config, target, dry_run)
    prefix = config.campaign_name_prefix
    issue_name = issue_name_for(now, prefix)
    if target == "test" and not dry_run:
        stamp = now.astimezone(BERLIN).strftime("%Y%m%d-%H%M%S")
        issue_name = f"{prefix}-TEST-{stamp}"

    scheduled_at = scheduled_send_time_for(now, config.send_hour_berlin)
    # Never mark content after the start of the feed snapshot as processed.
    cutoff = min(now, content_cutoff_for(now, config.content_cutoff_hour_berlin))

    entries = parse_feed(feed_xml)
    if not entries:
        message = f"Feed had no usable entries; aborting without campaign ({config.feed_url})"
        logger.error(message)
        return EXIT_ERROR, {"reason": "malformed_or_empty_feed", "message": message}

    metadata = load_post_metadata(posts_dir or Path(config.posts_dir))
    representatives = deduplicate_stories(entries, metadata, config.site_base_url)

    abuse_count: Optional[int] = None
    abuse_detected = False
    subscribers: Optional[int] = None
    watermark: Optional[datetime] = None

    if not dry_run:
        assert client is not None
        campaigns = client.list_campaigns()

        existing = find_named_campaign(campaigns, issue_name)
        if existing is not None and existing.get("status") in STATUS_ACTIVE:
            abuse_count, abuse_detected = check_abuse(client, config)
            return EXIT_OK, {
                "reason": "already_scheduled_or_sent",
                "campaign": existing.get("name"),
                "status": existing.get("status"),
                "abuse_detected": abuse_detected,
                "abuse_count_24h": abuse_count,
            }
        if existing is not None and existing.get("status") in STATUS_DEAD:
            return EXIT_OK, {
                "reason": "cancelled_today",
                "message": (
                    f"Campaign {issue_name} is {existing.get('status')}; "
                    "not recreated automatically."
                ),
            }
        leftover_draft: Optional[Dict[str, Any]] = None
        if existing is not None and existing.get("status") == STATUS_DRAFT:
            # Draft from an interrupted earlier run (create without schedule,
            # or found after a timed-out create): repaired in place below,
            # never duplicated.
            leftover_draft = existing

        stale = detect_stale_campaigns(campaigns, prefix, now)
        if stale:
            names = ", ".join(
                f"{item.get('name')}({item.get('status')})" for item in stale
            )
            message = (
                "Stale pre-send campaigns from earlier days need a manual decision "
                f"(delete in Brevo so the articles re-send, or investigate): {names}"
            )
            logger.critical(message)
            return EXIT_STALE, {"reason": "stale_campaigns", "message": message}

        list_stats = client.get_list_stats(list_id)
        subscribers = int(list_stats.get("totalSubscribers") or 0)
        remaining_credits = client.remaining_email_credits()
        logger.info(
            "Quota snapshot: remaining_email_credits=%s subscribers=%d reserve=%d",
            remaining_credits, subscribers, config.daily_reserve,
        )
        quota_error = quota_check(subscribers, config, remaining_credits)
        if quota_error:
            logger.critical("Quota guard refused the send: %s", quota_error)
            return EXIT_QUOTA, {
                "reason": "quota",
                "message": quota_error,
                "subscribers": subscribers,
            }

        abuse_count, abuse_detected = check_abuse(client, config)
        if abuse_detected:
            logger.critical(
                "DOI/transactional volume in the last 24h is %d (threshold %d). "
                "Possible signup abuse - consider closing the form "
                "(newsletter.signup_open: false).",
                abuse_count,
                config.abuse_threshold_24h,
            )

        watermark = find_last_sent_watermark(campaigns, prefix, config.production_list_id)

    window_start = watermark or (cutoff - timedelta(days=config.first_run_lookback_days))
    selected: List[NewsletterArticle] = []
    for entry in representatives:
        if window_start < entry.published <= cutoff:
            teaser_source = entry.description if entry.description else entry.text
            selected.append(
                NewsletterArticle(
                    title=entry.title,
                    link=entry.link,
                    published=entry.published,
                    teaser=first_sentences(teaser_source),
                    level=entry.level,
                )
            )
    if len(selected) > config.max_articles_per_issue:
        logger.info(
            "Issue %s: keeping the %d newest stories out of %d eligible stories",
            issue_name,
            config.max_articles_per_issue,
            len(selected),
        )
        # Representatives are ordered oldest first. Keep the full issue cutoff
        # so omitted stories stay outside future issues once this one is sent.
        selected = selected[-config.max_articles_per_issue :]

    if not selected:
        return EXIT_OK, {
            "reason": "empty_issue",
            "message": "No new stories since the last issue; skipping (no email today).",
            "window_start": window_start.isoformat(),
            "window_end": cutoff.isoformat(),
            "abuse_detected": abuse_detected,
            "abuse_count_24h": abuse_count,
        }

    issue = render_issue(selected, now, window_start, cutoff, config.site_base_url)

    if dry_run:
        return EXIT_OK, {
            "reason": "dry_run",
            "issue": issue,
            "subscribers": subscribers,
            "list_id": list_id,
        }

    assert client is not None
    scheduled_at_payload = (
        max(scheduled_at, now + timedelta(minutes=1)) if target == "production" else None
    )
    payload = build_campaign_payload(
        config, issue_name, issue, list_id, cutoff, scheduled_at_payload
    )

    campaign_id: int
    if leftover_draft is not None:
        campaign_id = int(leftover_draft.get("id") or 0)
        client.update_campaign(campaign_id, payload)
        logger.info(
            "Repaired leftover draft campaign %s (%s) in place", issue_name, campaign_id
        )
    else:
        try:
            created = client.create_campaign(payload)
        except (requests.Timeout, requests.ConnectionError) as error:
            # The create may have succeeded server-side (timeout on the
            # response). Re-read by name instead of blindly creating a second
            # campaign.
            logger.warning("Campaign create failed (%s); re-checking by name", error)
            existing = find_named_campaign(client.list_campaigns(), issue_name)
            if existing is None:
                raise
            created = existing
        campaign_id = int(created.get("id") or 0)
        if target == "production" and created.get("status") == STATUS_DRAFT:
            client.update_campaign(campaign_id, payload)
            logger.info("Repaired draft campaign %s (%s)", issue_name, campaign_id)

    if target == "test":
        client.send_now(campaign_id)
        logger.info(
            "Test campaign %s (%s) sent now to list %s", issue_name, campaign_id, list_id
        )

    return EXIT_OK, {
        "reason": "created",
        "campaign": issue_name,
        "campaign_id": campaign_id,
        "scheduled_at": payload.get("scheduledAt"),
        "articles": issue.article_count,
        "subscribers": subscribers,
        "list_id": list_id,
        "abuse_detected": abuse_detected,
        "abuse_count_24h": abuse_count,
    }


# =============================================================================
# CLI
# =============================================================================


def write_outputs(
    details: Dict[str, Any],
    preview_dir: Optional[Path],
    summary_path: Optional[Path],
) -> None:
    issue = details.get("issue")
    if issue is not None and preview_dir is not None:
        preview_dir.mkdir(parents=True, exist_ok=True)
        (preview_dir / "issue.html").write_text(issue.html, encoding="utf-8")
        (preview_dir / "issue.txt").write_text(issue.text, encoding="utf-8")
        (preview_dir / "subject.txt").write_text(issue.subject + "\n", encoding="utf-8")

    if summary_path is None:
        return
    lines = ["### Newsletter run", ""]
    lines.append(f"- Result: `{details.get('reason')}`")
    for key in (
        "campaign",
        "campaign_id",
        "scheduled_at",
        "articles",
        "subscribers",
        "list_id",
    ):
        if key in details:
            lines.append(f"- {key}: {details[key]}")
    if "message" in details:
        lines.append(f"- {details['message']}")
    if "abuse_detected" in details:
        lines.append(
            f"- abuse alert: {details['abuse_detected']} "
            f"(24h requests: {details.get('abuse_count_24h')})"
        )
    if issue is not None:
        lines.append(
            f"- subject: {issue.subject}  \n- articles: {issue.article_count}  "
            f"- window: {issue.window_start.isoformat()} → {issue.window_end.isoformat()}"
        )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build and schedule the daily Brevo newsletter"
    )
    parser.add_argument("--target", choices=["production", "test"], default="production")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the issue and preview it; create no campaign",
    )
    parser.add_argument(
        "--feed-file",
        type=Path,
        help="Read feed.xml from a file instead of the live site",
    )
    parser.add_argument("--environment", default="local")
    parser.add_argument("--preview-dir", type=Path, default=Path(".newsletter-preview"))
    parser.add_argument("--summary-path", type=Path, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    config = load_newsletter_config(args.environment)

    # Capture BEFORE fetching: a slow request must not move the watermark
    # beyond the snapshot that the server may have produced.
    snapshot_started_at = datetime.now(BERLIN)
    if args.feed_file is not None:
        feed_xml = args.feed_file.read_text(encoding="utf-8")
    else:
        response = requests.get(config.feed_url, timeout=30)
        response.raise_for_status()
        feed_xml = response.text

    client: Optional[BrevoClient] = None
    if not args.dry_run:
        if not config.api_key:
            logger.error("BREVO_API_KEY is not configured; refusing to talk to Brevo")
            return EXIT_ERROR
        client = BrevoClient(config)

    try:
        code, details = run_issue_builder(
            config, args.target, args.dry_run, feed_xml, snapshot_started_at, client
        )
    except (PermissionError, ValueError) as error:
        logger.error("%s", error)
        return EXIT_ERROR
    except (requests.RequestException, BrevoApiError) as error:
        logger.error("Brevo/feed failure: %s", error)
        return EXIT_ERROR

    write_outputs(details, args.preview_dir, args.summary_path)
    logger.info("Run finished: %s", details.get("reason"))
    return code


if __name__ == "__main__":
    sys.exit(main())

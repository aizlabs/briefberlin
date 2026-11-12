"""Tests for the daily Brevo newsletter campaign builder.

All Brevo interaction goes through FakeBrevo - no network, no real key. The
fake records every call so isolation and no-contact-write guarantees are
asserted on the actual call log.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import Mock

import pytest
import requests
from pydantic import ValidationError

from scripts.models import NewsletterConfig
from scripts.newsletter_campaign import (
    BERLIN,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_QUOTA,
    EXIT_STALE,
    BrevoApiError,
    BrevoClient,
    build_subject,
    content_cutoff_for,
    deduplicate_stories,
    detect_stale_campaigns,
    find_last_sent_watermark,
    format_german_date,
    load_post_metadata,
    parse_feed,
    render_issue,
    run_issue_builder,
    scheduled_send_time_for,
)


def make_config(**overrides: Any) -> NewsletterConfig:
    defaults: Dict[str, Any] = {
        "enabled": True,
        "api_key": "test-key",
        "posts_dir": "/nonexistent-for-tests",
    }
    defaults.update(overrides)
    return NewsletterConfig(**defaults)


def atom_feed(entries: List[Dict[str, str]]) -> str:
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        "<title>BriefBerlin</title>",
    ]
    for entry in entries:
        parts.append("<entry>")
        parts.append(f"<title>{entry['title']}</title>")
        parts.append(f"<id>{entry['link']}</id>")
        parts.append(f'<link href="{entry["link"]}"/>')
        parts.append(f"<published>{entry['published']}</published>")
        content = entry.get("content", "Dies ist ein Test. Mehr Text folgt. Noch mehr.")
        parts.append(f'<content type="html">{content}</content>')
        parts.append("</entry>")
    parts.append("</feed>")
    return "\n".join(parts)


def make_entry(
    slug: str,
    published: str,
    title: Optional[str] = None,
    link_prefix: str = "https://briefberlin.de",
) -> Dict[str, str]:
    return {
        "title": title or f"Story {slug}",
        "link": f"{link_prefix}/articles/{slug}/",
        "published": published,
        "content": "Die Polizei war da. Es gab keine Verletzten. Der Grund ist unklar.",
    }


class FakeBrevo:
    """In-memory stand-in for BrevoClient with a full call log."""

    def __init__(
        self,
        campaigns: Optional[List[Dict[str, Any]]] = None,
        subscribers: int = 120,
        requests_24h: int = 5,
        create_timeouts: int = 0,
        fail_create: bool = False,
        remaining_credits: Optional[int] = 300,
    ) -> None:
        self.campaigns: List[Dict[str, Any]] = campaigns or []
        self.subscribers = subscribers
        self.requests_24h = requests_24h
        self.next_id = 1000
        self.calls: List[Tuple[str, str, Optional[Dict[str, Any]]]] = []
        self.create_timeouts = create_timeouts
        self.fail_create = fail_create
        self.remaining_credits = remaining_credits

    def _log(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.calls.append((method, path, payload))

    def list_campaigns(self, limit: int = 100) -> List[Dict[str, Any]]:
        self._log("GET", "/emailCampaigns")
        return list(self.campaigns)

    def create_campaign(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._log("POST", "/emailCampaigns", payload)
        import requests as requests_lib

        if self.fail_create:
            raise BrevoApiError("POST /emailCampaigns -> HTTP 500")
        if self.create_timeouts > 0:
            # Server accepted the create, but the client saw a timeout.
            self.create_timeouts -= 1
            campaign = {
                "id": self.next_id,
                "name": payload["name"],
                "status": "draft",
                "htmlContent": payload.get("htmlContent", ""),
            }
            self.next_id += 1
            self.campaigns.append(campaign)
            raise requests_lib.Timeout("simulated timeout after create")
        campaign = {
            "id": self.next_id,
            "name": payload["name"],
            "status": "queued" if payload.get("scheduledAt") else "draft",
            "htmlContent": payload.get("htmlContent", ""),
            "scheduledAt": payload.get("scheduledAt"),
        }
        self.next_id += 1
        self.campaigns.append(campaign)
        return campaign

    def update_campaign(self, campaign_id: int, payload: Dict[str, Any]) -> Any:
        self._log("PUT", f"/emailCampaigns/{campaign_id}", payload)
        for campaign in self.campaigns:
            if campaign["id"] == campaign_id:
                campaign.update(payload)
                campaign["status"] = (
                    "queued" if payload.get("scheduledAt") else campaign["status"]
                )
        return None

    def delete_campaign(self, campaign_id: int) -> Any:
        self._log("DELETE", f"/emailCampaigns/{campaign_id}")
        self.campaigns = [c for c in self.campaigns if c["id"] != campaign_id]
        return None

    def send_now(self, campaign_id: int) -> Any:
        self._log("POST", f"/emailCampaigns/{campaign_id}/sendNow")
        for campaign in self.campaigns:
            if campaign["id"] == campaign_id:
                campaign["status"] = "sent"
        return None

    def get_list_stats(self, list_id: int) -> Dict[str, Any]:
        self._log("GET", f"/contacts/lists/{list_id}")
        return {"id": list_id, "totalSubscribers": self.subscribers}

    def remaining_email_credits(self) -> Optional[int]:
        self._log("GET", "/account")
        return self.remaining_credits

    def transactional_requests_24h(self) -> int:
        self._log("GET", "/smtp/statistics/aggregatedReport")
        return self.requests_24h


def write_posts(
    directory: Path, posts: List[Dict[str, str]]
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for post in posts:
        front = (
            "---\n"
            f'title: "{post.get("title", "T")}"\n'
            f"date: {post['date']}\n"
            f"level: {post['level']}\n"
            'description: "{}"\n'.format(post["description"])
            + "---\n\nText\n"
        )
        (directory / post["filename"]).write_text(front, encoding="utf-8")


# =============================================================================
# DST / schedule / cutoff
# =============================================================================


def test_scheduled_time_handles_winter_and_summer_time():
    # Summer (CEST, UTC+2): 07:00 local
    summer = scheduled_send_time_for(datetime(2026, 7, 15, 5, 30, tzinfo=BERLIN), 7)
    assert summer.isoformat() == "2026-07-15T07:00:00+02:00"
    # Winter (CET, UTC+1): 07:00 local
    winter = scheduled_send_time_for(datetime(2026, 11, 15, 5, 30, tzinfo=BERLIN), 7)
    assert winter.isoformat() == "2026-11-15T07:00:00+01:00"
    # The morning CEST starts (2026-03-29): still 07:00 local, +02:00
    dst_start = scheduled_send_time_for(datetime(2026, 3, 29, 5, 30, tzinfo=BERLIN), 7)
    assert dst_start.isoformat() == "2026-03-29T07:00:00+02:00"
    # The morning CET returns (2026-10-25): 07:00 local, +01:00
    dst_end = scheduled_send_time_for(datetime(2026, 10, 25, 5, 30, tzinfo=BERLIN), 7)
    assert dst_end.isoformat() == "2026-10-25T07:00:00+01:00"


def test_content_cutoff_is_deterministic_regardless_of_run_time():
    early = content_cutoff_for(datetime(2026, 11, 8, 4, 45, tzinfo=BERLIN), 6)
    late = content_cutoff_for(datetime(2026, 11, 8, 6, 20, tzinfo=BERLIN), 6)
    assert early == late == datetime(2026, 11, 8, 6, 0, tzinfo=BERLIN)


def test_scheduled_send_time_utc_conversion_matches_berlin_7am():
    for now in (
        datetime(2026, 2, 1, 5, 30, tzinfo=BERLIN),
        datetime(2026, 8, 1, 5, 30, tzinfo=BERLIN),
    ):
        scheduled = scheduled_send_time_for(now, 7)
        assert scheduled.utcoffset() is not None
        assert scheduled.astimezone(BERLIN).hour == 7


# =============================================================================
# Feed, A2/B1 dedup, rendering
# =============================================================================


def test_deduplicate_collapses_a2_b1_pair_to_a2_link(tmp_path: Path):
    write_posts(
        tmp_path,
        [
            {
                "filename": "2026-11-07-161306-bad-a2.md",
                "date": "2026-11-07 16:13:06",
                "level": "A2",
                "description": "Stadtbad Schöneberg hat Probleme.",
            },
            {
                "filename": "2026-11-07-161452-bad-b1.md",
                "date": "2026-11-07 16:14:52",
                "level": "B1",
                "description": "Stadtbad Schöneberg hat Probleme.",
            },
        ],
    )
    metadata = load_post_metadata(tmp_path)
    entries = parse_feed(
        atom_feed(
            [
                make_entry("161306-bad-a2", "2026-11-07T16:13:06+01:00"),
                make_entry("161452-bad-b1", "2026-11-07T16:14:52+01:00"),
            ]
        )
    )
    result = deduplicate_stories(entries, metadata, "https://briefberlin.de")
    assert len(result) == 1
    assert result[0].level == "A2"
    assert result[0].link.endswith("/articles/161306-bad-a2/")


def test_deduplicate_collapses_double_published_same_level(tmp_path: Path):
    write_posts(
        tmp_path,
        [
            {
                "filename": "2026-09-16-142137-poller-a2.md",
                "date": "2026-09-16 14:21:37",
                "level": "A2",
                "description": "Streit um Poller in Berlin.",
            },
            {
                "filename": "2026-09-16-163518-poller-a2.md",
                "date": "2026-09-16 16:35:18",
                "level": "A2",
                "description": "Streit um Poller in Berlin.",
            },
        ],
    )
    metadata = load_post_metadata(tmp_path)
    entries = parse_feed(
        atom_feed(
            [
                make_entry("142137-poller-a2", "2026-09-16T14:21:37+02:00"),
                make_entry("163518-poller-a2", "2026-09-16T16:35:18+02:00"),
            ]
        )
    )
    result = deduplicate_stories(entries, metadata, "https://briefberlin.de")
    assert len(result) == 1
    assert result[0].link.endswith("/articles/142137-poller-a2/")


def test_deduplicate_keeps_different_stories_separate(tmp_path: Path):
    write_posts(
        tmp_path,
        [
            {
                "filename": "2026-11-07-1-a2.md",
                "date": "2026-11-07 10:00:00",
                "level": "A2",
                "description": "Erste Geschichte.",
            },
            {
                "filename": "2026-11-07-2-a2.md",
                "date": "2026-11-07 11:00:00",
                "level": "A2",
                "description": "Zweite Geschichte.",
            },
        ],
    )
    metadata = load_post_metadata(tmp_path)
    entries = parse_feed(
        atom_feed(
            [
                make_entry("1-a2", "2026-11-07T10:00:00+01:00"),
                make_entry("2-a2", "2026-11-07T11:00:00+01:00"),
            ]
        )
    )
    result = deduplicate_stories(entries, metadata, "https://briefberlin.de")
    assert len(result) == 2


def test_rendered_issue_escapes_content_and_filters_links():
    from scripts.newsletter_campaign import NewsletterArticle

    articles = [
        NewsletterArticle(
            title='Angriff <script>alert("x")</script> "Zitate"',
            link="https://briefberlin.de/articles/ok-a2/",
            published=datetime(2026, 11, 8, 9, 0, tzinfo=BERLIN),
            teaser="<b>Fett</b> & gefährlich <img src=x onerror=alert(1)>",
            level="A2",
        ),
        NewsletterArticle(
            title="Böser Link",
            link="https://evil.example.com/articles/steal/",
            published=datetime(2026, 11, 8, 9, 5, tzinfo=BERLIN),
            teaser="Soll nicht erscheinen.",
            level="A2",
        ),
    ]
    issue = render_issue(
        articles,
        datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN),
        datetime(2026, 11, 7, 6, 0, tzinfo=BERLIN),
        datetime(2026, 11, 8, 6, 0, tzinfo=BERLIN),
        "https://briefberlin.de",
    )
    assert issue.article_count == 1
    assert "<script>" not in issue.html
    assert "&lt;script&gt;" in issue.html
    assert "evil.example.com" not in issue.html
    assert "evil.example.com" not in issue.text
    assert "https://briefberlin.de/articles/ok-a2/" in issue.html
    assert "evil" not in issue.text
    assert 'href="{{ unsubscribe }}">Hier abmelden.</a>' in issue.html
    assert "Newsletter abbestellen: {{ unsubscribe }}" in issue.text


def test_subject_is_german_and_truncated():
    from scripts.newsletter_campaign import NewsletterArticle

    article = NewsletterArticle(
        title="Ein sehr langer Berliner Nachrichtentitel über alles",
        link="https://briefberlin.de/articles/x-a2/",
        published=datetime(2026, 11, 8, 9, 0, tzinfo=BERLIN),
        teaser="Teaser",
        level="A2",
    )
    subject = build_subject([article], datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN))
    assert subject.startswith("BriefBerlin am Sonntag, 08.11.2026:")
    assert len(subject) <= 79
    long = build_subject(
        [
            NewsletterArticle(
                title="Diese Überschrift ist wirklich außergewöhnlich lang und muss gekürzt werden",
                link="https://briefberlin.de/articles/x-a2/",
                published=datetime(2026, 11, 8, 9, 0, tzinfo=BERLIN),
                teaser="t",
            )
        ],
        datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN),
    )
    assert len(long) <= 79
    assert long.endswith("…")


def test_german_date_formatting():
    assert (
        format_german_date(datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN))
        == "Sonntag, 08.11.2026"
    )
    assert (
        format_german_date(datetime(2026, 3, 2, 5, 30, tzinfo=BERLIN))
        == "Montag, 02.03.2026"
    )


# =============================================================================
# Watermark and campaign-state recovery
# =============================================================================


def test_watermark_only_advances_from_sent_campaigns():
    campaigns = [
        {"name": "BB-2026-11-05", "status": "sent", "recipients": {"lists": [3]}, "tag": "2026-11-05T06:00:00+01:00"},
        {"name": "BB-2026-11-06", "status": "queued", "tag": "2026-11-06T06:00:00+01:00"},
        {"name": "BB-2026-11-04", "status": "sent", "recipients": {"lists": [3]}, "tag": "2026-11-04T06:00:00+01:00"},
    ]
    watermark = find_last_sent_watermark(campaigns, "BB")
    assert watermark == datetime(2026, 11, 5, 6, 0, tzinfo=BERLIN)


def test_watermark_none_without_sent_campaigns():
    assert find_last_sent_watermark(
        [{"name": "BB-2026-11-06", "status": "queued", "tag": "x"}], "BB"
    ) is None


def test_detect_stale_campaigns_flags_past_pre_send_states():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    campaigns = [
        {"name": "BB-2026-11-06", "status": "queued", "tag": "t"},
        {"name": "BB-2026-11-07", "status": "in_process", "tag": "t"},
        {"name": "BB-2026-11-05", "status": "sent", "recipients": {"lists": [3]}, "tag": "t"},
        {"name": "BB-2026-11-08", "status": "queued", "tag": "t"},
    ]
    stale = detect_stale_campaigns(campaigns, "BB", now)
    assert [c["name"] for c in stale] == ["BB-2026-11-06", "BB-2026-11-07"]


def test_run_skips_when_today_already_scheduled():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(
        campaigns=[{"name": "BB-2026-11-08", "status": "queued", "tag": "t", "id": 1}]
    )
    code, details = run_issue_builder(
        make_config(), "production", False, atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")]), now, client
    )
    assert code == EXIT_OK
    assert details["reason"] == "already_scheduled_or_sent"
    assert not any(method == "POST" and path == "/emailCampaigns" for method, path, _ in client.calls)


def test_run_repairs_leftover_draft_without_creating_a_second_campaign():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(
        campaigns=[{"name": "BB-2026-11-08", "status": "draft", "tag": "old", "id": 42}]
    )
    code, details = run_issue_builder(
        make_config(), "production", False, atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")]), now, client
    )
    assert code == EXIT_OK
    assert details["reason"] == "created"
    assert details["campaign_id"] == 42
    creates = [call for call in client.calls if call[0] == "POST" and call[1] == "/emailCampaigns"]
    updates = [call for call in client.calls if call[0] == "PUT" and call[1] == "/emailCampaigns/42"]
    assert creates == []
    assert len(updates) == 1
    assert len(client.campaigns) == 1


def test_run_recovers_from_timeout_after_create_without_duplicating():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(create_timeouts=1)
    code, details = run_issue_builder(
        make_config(), "production", False, atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")]), now, client
    )
    assert code == EXIT_OK
    assert details["reason"] == "created"
    creates = [call for call in client.calls if call[0] == "POST" and call[1] == "/emailCampaigns"]
    assert len(creates) == 1
    assert len([c for c in client.campaigns if c["name"] == "BB-2026-11-08"]) == 1
    assert any(call[0] == "PUT" for call in client.calls)


def test_run_reports_stale_campaigns_instead_of_guessing():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(
        campaigns=[{"name": "BB-2026-11-07", "status": "queued", "tag": "t", "id": 7}]
    )
    code, details = run_issue_builder(
        make_config(), "production", False, atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")]), now, client
    )
    assert code == EXIT_STALE
    assert details["reason"] == "stale_campaigns"
    assert not any(call[0] in {"POST", "PUT", "DELETE"} for call in client.calls)


def test_run_uses_sent_watermark_as_window_start():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(
        campaigns=[
            {"name": "BB-2026-11-07", "status": "sent", "recipients": {"lists": [3]}, "tag": "2026-11-07T06:00:00+01:00"}
        ]
    )
    feed = atom_feed(
        [
            make_entry("old-a2", "2026-11-07T04:00:00+01:00"),
            make_entry("new-a2", "2026-11-08T04:00:00+01:00"),
        ]
    )
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert code == EXIT_OK
    assert details["reason"] == "created"
    payload = next(call[2] for call in client.calls if call[0] == "POST")
    assert payload["type"] == "classic"
    html = payload["htmlContent"]
    assert "Story old-a2" not in html
    assert "Story new-a2" in html
    assert details["articles"] == 1


def test_missed_day_articles_are_recovered_after_failed_campaign():
    # Yesterday's campaign never sent (suspended -> cancelled); the watermark
    # stays at the last SENT campaign, so yesterday's articles return today.
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(
        campaigns=[
            {"name": "BB-2026-11-06", "status": "sent", "recipients": {"lists": [3]}, "tag": "2026-11-06T06:00:00+01:00"},
            {"name": "BB-2026-11-07", "status": "cancelled", "tag": "2026-11-07T06:00:00+01:00"},
        ]
    )
    feed = atom_feed(
        [
            make_entry("yesterday-a2", "2026-11-07T10:00:00+01:00"),
            make_entry("today-a2", "2026-11-08T04:00:00+01:00"),
        ]
    )
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert details["reason"] == "created"
    assert details["articles"] == 2


# =============================================================================
# Empty / malformed feeds, timing, quota
# =============================================================================


def test_empty_window_skips_issue_without_campaign():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(
        campaigns=[
            {"name": "BB-2026-11-07", "status": "sent", "recipients": {"lists": [3]}, "tag": "2026-11-07T06:00:00+01:00"}
        ]
    )
    feed = atom_feed([make_entry("old-a2", "2026-11-05T10:00:00+01:00")])
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert code == EXIT_OK
    assert details["reason"] == "empty_issue"
    assert not any(call[0] == "POST" and call[1] == "/emailCampaigns" for call in client.calls)


def test_malformed_feed_aborts_without_campaign():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo()
    code, details = run_issue_builder(make_config(), "production", False, "not-xml-at-all", now, client)
    assert code == EXIT_ERROR
    assert details["reason"] == "malformed_or_empty_feed"


@pytest.mark.parametrize("hour,minute,expected_hour,expected_minute", [
    (6, 40, 7, 0),
    (7, 0, 7, 1),
    (13, 40, 13, 41),
])
def test_production_schedules_even_when_trigger_is_late(hour, minute, expected_hour, expected_minute):
    now = datetime(2026, 11, 8, hour, minute, tzinfo=BERLIN)
    client = FakeBrevo()
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert code == EXIT_OK
    assert details["reason"] == "created"
    assert datetime.fromisoformat(details["scheduled_at"]) == now.replace(
        hour=expected_hour, minute=expected_minute
    )
    client.campaigns[0]["status"] = "queued"
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert details["reason"] == "already_scheduled_or_sent"
    assert len(client.campaigns) == 1


def test_quota_guard_refuses_over_reserve():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(subscribers=250)  # 250 > 300 - 60
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert code == EXIT_QUOTA
    assert details["reason"] == "quota"
    assert not any(call[0] == "POST" and call[1] == "/emailCampaigns" for call in client.calls)


def test_quota_guard_refuses_above_plan_limit():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(subscribers=350)
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert code == EXIT_QUOTA


def test_api_failure_on_create_fails_the_run_cleanly():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(fail_create=True)
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    with pytest.raises(BrevoApiError):
        run_issue_builder(make_config(), "production", False, feed, now, client)
    assert len([c for c in client.campaigns if c["name"].startswith("BB-")]) == 0


# =============================================================================
# Target isolation and gates
# =============================================================================


def test_production_target_requires_enable_gate():
    config = make_config(enabled=False)
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    with pytest.raises(PermissionError):
        run_issue_builder(
            config, "production", False, atom_feed([]), now, FakeBrevo()
        )


def test_production_dry_run_allowed_without_gate():
    config = make_config(enabled=False)
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    code, details = run_issue_builder(config, "production", True, feed, now, None)
    assert code == EXIT_OK
    assert details["reason"] == "dry_run"
    assert details["list_id"] == 3


def test_test_mode_targets_only_test_list_and_sends_now():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo()
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    code, details = run_issue_builder(make_config(), "test", False, feed, now, client)
    assert code == EXIT_OK
    payload = next(call[2] for call in client.calls if call[0] == "POST" and call[1] == "/emailCampaigns")
    assert payload["recipients"]["listIds"] == [4]
    assert details["campaign"].startswith("BB-TEST-")
    assert "scheduledAt" not in payload
    assert any(call[1].endswith("/sendNow") for call in client.calls)


def test_production_payload_uses_production_list_and_schedule():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo()
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    payload = next(call[2] for call in client.calls if call[0] == "POST" and call[1] == "/emailCampaigns")
    assert code == EXIT_OK
    assert payload["recipients"]["listIds"] == [3]
    assert payload["scheduledAt"] == "2026-11-08T07:00:00+01:00"
    assert 'name="briefberlin-cutoff" content="2026-11-08T05:30:00+01:00"' in payload["htmlContent"]
    assert "tag" not in payload
    assert payload["sender"] == {"name": "BriefBerlin", "email": "newsletter@briefberlin.de"}


def test_builder_never_writes_contacts():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo()
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    run_issue_builder(make_config(), "production", False, feed, now, client)
    forbidden = {
        call for call in client.calls if call[0] in {"POST", "PUT", "DELETE"} and "/contacts" in call[1]
    }
    assert forbidden == set()


def test_config_rejects_equal_list_ids():
    with pytest.raises(ValidationError):
        NewsletterConfig(production_list_id=3, test_list_id=3)


def test_abuse_threshold_flags_high_doi_volume():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(requests_24h=30)
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert code == EXIT_OK
    assert details["abuse_detected"] is True
    assert details["abuse_count_24h"] == 30


def test_abuse_below_threshold_stays_quiet():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo(requests_24h=10)
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert details["abuse_detected"] is False


def test_first_issue_includes_stories_from_two_day_lookback():
    now = datetime(2026, 11, 11, 6, 20, tzinfo=BERLIN)
    client = FakeBrevo()
    feed = atom_feed(
        [
            make_entry("at-start", "2026-11-09T06:00:00+01:00"),
            make_entry("within-window", "2026-11-09T06:01:00+01:00"),
        ]
    )

    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)

    assert code == EXIT_OK
    assert details["articles"] == 1
    payload = next(call[2] for call in client.calls if call[0] == "POST")
    assert "Story within-window" in payload["htmlContent"]


def test_window_excludes_entries_after_deterministic_cutoff():
    # Entry published 06:10 (after the 06:00 cutoff) waits for the next issue
    # even though the (delayed) run happens at 06:20.
    now = datetime(2026, 11, 8, 6, 20, tzinfo=BERLIN)
    client = FakeBrevo()
    feed = atom_feed(
        [
            make_entry("in-a2", "2026-11-08T05:00:00+01:00"),
            make_entry("late-a2", "2026-11-08T06:10:00+01:00"),
        ]
    )
    code, details = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert code == EXIT_OK
    assert details["reason"] == "created"
    assert details["articles"] == 1


@pytest.mark.parametrize('name,lists', [
    ('BB-TEST-20261109-120000', [4]),
    ('BB-2026-11-09', [4]),
    ('BB-2026-11-09-special', [3]),
])
def test_nonproduction_campaign_cannot_advance_production_window(name, lists):
    production = {'name': 'BB-2026-11-08', 'status': 'sent',
                  'recipients': {'lists': [3]}, 'tag': '2026-11-08T05:00:00+01:00'}
    other = {'name': name, 'status': 'sent', 'recipients': {'lists': lists},
             'tag': '2026-11-09T06:00:00+01:00'}
    assert find_last_sent_watermark([production, other], 'BB') == datetime.fromisoformat(production['tag'])


@pytest.mark.parametrize('month,offset', [(1, '+01:00'), (7, '+02:00')])
def test_pre_cutoff_preparation_recovers_later_publications_next_day(month, offset):
    now = datetime(2026, month, 8, 4, 30, tzinfo=BERLIN)
    client = FakeBrevo()
    before = make_entry('before', f'2026-{month:02d}-08T04:00:00{offset}')
    after = make_entry('after', f'2026-{month:02d}-08T05:45:00{offset}')
    code, details = run_issue_builder(make_config(), 'production', False,
                                    atom_feed([before, after]), now, client)
    assert code == EXIT_OK
    payload = next(c[2] for c in client.calls if c[0] == 'POST')
    assert f'content="{now.isoformat()}"' in payload['htmlContent']
    assert 'tag' not in payload
    assert 'Story after' not in payload['htmlContent']
    client.campaigns[0].update(status='sent', recipients={'lists': [3]})
    client.calls.clear()
    code, details = run_issue_builder(make_config(), 'production', False,
                                    atom_feed([before, after]), now.replace(day=9), client)
    assert code == EXIT_OK
    payload = next(c[2] for c in client.calls if c[0] == 'POST')
    assert 'Story after' in payload['htmlContent']
    assert 'Story before' not in payload['htmlContent']


def test_issue_keeps_newest_stories_and_drops_excess_after_send():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    entries = [make_entry("older", "2026-11-08T03:00:00+01:00")]
    entries += [make_entry(f"story-{i}", "2026-11-08T04:00:00+01:00") for i in range(10)]
    client = FakeBrevo()
    config = make_config()

    code, details = run_issue_builder(config, "production", False, atom_feed(entries), now, client)

    assert (code, details["reason"], details["articles"]) == (EXIT_OK, "created", 10)
    payload = next(call[2] for call in client.calls if call[0] == "POST")
    assert "Story older" not in payload["htmlContent"]

    client.campaigns[0].update(status="sent", recipients={"lists": [3]})
    code, details = run_issue_builder(
        config, "production", False, atom_feed(entries), now.replace(day=9), client
    )

    assert (code, details["reason"]) == (EXIT_OK, "empty_issue")


@pytest.mark.parametrize('remaining', [None, 0, 200, 299])
def test_quota_guard_uses_consumed_credits_and_fails_closed(remaining):
    client = FakeBrevo(subscribers=240, remaining_credits=remaining)
    code, details = run_issue_builder(make_config(), 'production', False,
        atom_feed([make_entry('one', '2026-11-08T04:00:00+01:00')]),
        datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN), client)
    assert (code, details['reason']) == (EXIT_QUOTA, 'quota')
    assert not any(c[0] in {'POST', 'PUT', 'DELETE'} for c in client.calls)


@pytest.mark.parametrize('account,expected', [
    ({'plan': [{'type': 'free', 'creditsType': 'sendLimit', 'credits': 237},
               {'type': 'sms', 'creditsType': 'sendLimit', 'credits': 999}]}, 237),
    ({'plan': [{'type': 'paid', 'creditsType': 'sendLimit', 'credits': 1000}]}, None),
    ({'plan': [{'type': 'free', 'creditsType': 'sendLimit', 'credits': True}]}, None),
    ({'plan': [{'type': 'free', 'creditsType': 'sendLimit', 'credits': -1}]}, None),
    ({'plan': [{'type': 'free', 'creditsType': 'sendLimit', 'credits': '300'}]}, None),
    ({'plan': []}, None), ({}, None),
])
def test_remaining_quota_parses_only_unambiguous_free_email_balance(monkeypatch, account, expected):
    from scripts.newsletter_campaign import BrevoClient
    client = BrevoClient(make_config())
    calls = []
    def request(method, path):
        calls.append((method, path))
        return account
    monkeypatch.setattr(client, '_request', request)
    assert client.remaining_email_credits() == expected
    assert calls == [('GET', '/account')]


def test_workflow_module_command_runs_without_editable_install():
    import os
    import subprocess
    import sys
    import sysconfig
    root = Path(__file__).resolve().parents[1]
    workflow = (root / '.github/workflows/newsletter-daily.yml').read_text()
    assert 'python -m scripts.newsletter_campaign "${ARGS[@]}"' in workflow
    # -S skips editable-install .pth files, matching the dependency-only runner.
    env = dict(os.environ, PYTHONPATH=sysconfig.get_paths()['purelib'])
    result = subprocess.run([sys.executable, '-S', '-m', 'scripts.newsletter_campaign', '--help'],
                            cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert '--dry-run' in result.stdout


@pytest.mark.parametrize(
    ("message", "hint"),
    [
        ("POST Method is not allowed on this path", "provider rejected this endpoint method"),
        ("Your account is not activated", "check account activation or suspension in Brevo"),
        ("Missing scope", "check API key resource permissions in Brevo"),
        ("type is missing", "provider mentioned campaign field: type"),
        ("htmlContent is invalid", "provider mentioned campaign field: htmlContent"),
        ("Unknown failure", ""),
    ],
)
def test_api_errors_expose_only_fixed_diagnostic_hints(message, hint):
    response = requests.Response()
    response.status_code = 405
    response._content = json.dumps({
        "message": message + " private@example.com xkeysib-private-test-value",
        "details": {"api-key": "another-private-value"},
    }).encode()
    session = Mock(spec=requests.Session)
    session.request.return_value = response
    client = BrevoClient(make_config(), session=session)

    with pytest.raises(BrevoApiError) as caught:
        client.create_campaign({"name": "test"})

    error = str(caught.value)
    assert error.startswith("POST /emailCampaigns -> HTTP 405")
    assert hint in error
    assert "private" not in error
    assert "xkeysib" not in error
    assert "details" not in error


def test_api_errors_do_not_dump_non_json_provider_responses():
    response = requests.Response()
    response.status_code = 502
    response._content = b"<html>private@example.com xkeysib-private-test-value</html>"
    session = Mock(spec=requests.Session)
    session.request.return_value = response
    client = BrevoClient(make_config(), session=session)

    with pytest.raises(BrevoApiError, match=r"^GET /account -> HTTP 502$"):
        client.remaining_email_credits()


def test_watermark_round_trip_uses_html_metadata_without_tags():
    now = datetime(2026, 11, 8, 5, 30, tzinfo=BERLIN)
    client = FakeBrevo()
    feed = atom_feed([make_entry("a-a2", "2026-11-08T05:00:00+01:00")])
    code, _ = run_issue_builder(make_config(), "production", False, feed, now, client)
    assert code == EXIT_OK
    campaign = client.campaigns[0]
    campaign.update(status="sent", recipients={"lists": [3]})
    assert find_last_sent_watermark([campaign], "BB") == now
    assert "tag" not in campaign


@pytest.mark.parametrize("html", [
    "",
    '<meta name="briefberlin-cutoff" content="invalid">',
    '<meta name="briefberlin-cutoff" content="2026-11-08T06:00:00">',
    '<meta name="briefberlin-cutoff" content="2026-11-08T06:00:00+01:00">' * 2,
])
def test_sent_campaign_with_unreadable_cutoff_refuses_replay(html):
    campaign = {"name": "BB-2026-11-08", "status": "sent",
                "recipients": {"lists": [3]}, "htmlContent": html}
    with pytest.raises(ValueError, match="review required"):
        find_last_sent_watermark([campaign], "BB")


def test_campaign_listing_requests_watermark_html():
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"campaigns": []}'
    session = Mock(spec=requests.Session)
    session.request.return_value = response
    assert BrevoClient(make_config(), session=session).list_campaigns() == []
    assert session.request.call_args.kwargs["params"]["excludeHtmlContent"] == "false"

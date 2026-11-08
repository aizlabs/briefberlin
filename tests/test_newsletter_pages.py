import re
from pathlib import Path
from urllib.parse import urlparse

import yaml
from bs4 import BeautifulSoup

SITE_ROOT = Path("output")

NEWSLETTER_PAGES = {
    "/newsletter/": "newsletter.md",
    "/newsletter/danke/": "newsletter-danke.md",
    "/newsletter/bestaetigt/": "newsletter-bestaetigt.md",
    "/newsletter/abgemeldet/": "newsletter-abgemeldet.md",
}


def test_newsletter_pages_exist_with_expected_permalinks():
    for permalink, filename in NEWSLETTER_PAGES.items():
        page = (SITE_ROOT / "_pages" / filename).read_text(encoding="utf-8")
        assert f"permalink: {permalink}" in page
        assert "layout: single" in page


def test_result_pages_are_excluded_from_sitemap():
    # The signup page is a real landing page; the three result pages only
    # make sense right after a form action and stay out of the sitemap.
    for permalink, filename in NEWSLETTER_PAGES.items():
        page = (SITE_ROOT / "_pages" / filename).read_text(encoding="utf-8")
        if permalink != "/newsletter/":
            assert "sitemap: false" in page, permalink


def test_signup_page_embeds_brevo_form_with_closure_gate():
    page = (SITE_ROOT / "_pages" / "newsletter.md").read_text(encoding="utf-8")
    config = yaml.safe_load((SITE_ROOT / "_config.yml").read_text(encoding="utf-8"))

    assert "{% include brevo-signup-form.html %}" in page
    # One commit flips newsletter.signup_open to false and the page shows a
    # closure notice instead of the form (abuse kill switch).
    assert "site.newsletter.signup_open == false" in page
    assert config["newsletter"]["signup_open"] is True
    assert "Datenschutzerkl" in page


def test_brevo_form_include_has_live_accessible_embed_without_secrets():
    include = (SITE_ROOT / "_includes" / "brevo-signup-form.html").read_text(
        encoding="utf-8"
    )

    iframe = BeautifulSoup(include, "html.parser").find("iframe")
    assert iframe is not None
    url = urlparse(iframe["src"])
    assert url.scheme == "https"
    assert url.hostname == "374fe9d0.sibforms.com"
    assert url.path.startswith("/v2/serve/")
    assert iframe.get("title") == "BriefBerlin Newsletter bestellen"
    assert int(iframe["height"]) >= 650
    assert_not_secret(include)


def test_result_pages_use_simple_german_and_offer_re_signup():
    danke = (SITE_ROOT / "_pages" / "newsletter-danke.md").read_text(encoding="utf-8")
    bestaetigt = (SITE_ROOT / "_pages" / "newsletter-bestaetigt.md").read_text(
        encoding="utf-8"
    )
    abgemeldet = (SITE_ROOT / "_pages" / "newsletter-abgemeldet.md").read_text(
        encoding="utf-8"
    )

    # Thank-you: check inbox and spam folder.
    assert "Spam-Ordner" in danke
    assert "newsletter@briefberlin.de" in danke
    # Confirmed: next scheduled issue, empty days skipped, no "tomorrow" promise.
    assert "um 7 Uhr" in bestaetigt
    assert "keine" in bestaetigt
    assert not re.search(r"[Mm]orgen [kK]omm", bestaetigt.replace("am nächsten Morgen", ""))
    # Unsubscribed: confirms leaving, offers voluntary signup again.
    assert "abgemeldet" in abgemeldet
    assert "'/newsletter/' | relative_url" in abgemeldet


def test_newsletter_is_linked_from_navigation_and_sidebar():
    navigation = yaml.safe_load(
        (SITE_ROOT / "_data" / "navigation.yml").read_text(encoding="utf-8")
    )

    assert "/newsletter/" in {item["url"] for item in navigation["main"]}
    levels_children = navigation["levels"][0]["children"]
    assert "/newsletter/" in {item["url"] for item in levels_children}


def test_privacy_policy_discloses_brevo_and_turnstile_processing():
    privacy = (SITE_ROOT / "_pages" / "privacy.md").read_text(encoding="utf-8")

    assert "Brevo" in privacy
    assert "Turnstile" in privacy
    # Timestamps and IPs are processed too: the policy must not claim the
    # email address is the only data point.
    assert "IP-Adresse" in privacy
    assert "Einwilligungsnachweise" in privacy
    # State tracking configuration without claiming no technical logs exist.
    assert "technische Verbindungsdaten" in privacy
    assert "Messung" in privacy


def assert_not_secret(content: str) -> None:
    # Brevo API keys and Cloudflare Turnstile secrets must never appear in
    # files served with the website.
    assert "xkeysib-" not in content
    assert not re.search(r"0x4AAA[A-Za-z0-9_\-]{20,}", content)

from pathlib import Path

import yaml

SITE_ROOT = Path("output")


def test_publisher_identity_is_configured_without_fake_phone_number():
    config = yaml.safe_load((SITE_ROOT / "_config.yml").read_text(encoding="utf-8"))

    publisher = config["publisher"]
    assert publisher["legal_name"] == "BriefBerlin LLC"
    assert publisher["organization_type"] == "NewsMediaOrganization"
    assert publisher["founding_date"] == "2026-06"
    assert publisher["email"] == "info@briefberlin.de"
    assert publisher["address"]["locality"] == "Wilmington"
    assert "telephone" not in publisher


def test_homepage_emits_publisher_organization_schema():
    homepage = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    custom_head = (SITE_ROOT / "_includes/head/custom.html").read_text(encoding="utf-8")

    assert "organization_schema: true" in homepage
    assert '"@id": {{ site.url | append: "/#publisher" | jsonify }}' in custom_head
    assert '"legalName": {{ site.publisher.legal_name | jsonify }}' in custom_head
    assert '"contactPoint"' in custom_head
    assert '"telephone"' not in custom_head


def test_public_pages_disclose_ownership_funding_and_contact_routes():
    about = (SITE_ROOT / "_pages/about.md").read_text(encoding="utf-8")
    contact = (SITE_ROOT / "_pages/contact.md").read_text(encoding="utf-8")

    assert "owned and operated by **BriefBerlin LLC**" in about
    assert "independently owned and privately funded" in about
    assert "registered mailing address" in about
    assert "info@briefberlin.de" in contact
    assert "does not currently offer telephone support" in contact


def test_publisher_pages_are_linked_from_navigation_and_footer():
    navigation = yaml.safe_load(
        (SITE_ROOT / "_data/navigation.yml").read_text(encoding="utf-8")
    )
    footer = (SITE_ROOT / "_includes/footer.html").read_text(encoding="utf-8")

    main_urls = {item["url"] for item in navigation["main"]}
    assert {"/about/", "/editorial-standards/", "/contact/"}.issubset(main_urls)
    assert "'/about/' | relative_url" in footer
    assert "'/editorial-standards/' | relative_url" in footer
    assert "'/corrections/' | relative_url" in footer
    assert "'/editorial-process/' | relative_url" in footer
    assert "'/contact/' | relative_url" in footer


def test_editorial_policies_describe_human_review_and_automation_truthfully():
    standards = (SITE_ROOT / "_pages/editorial-standards.md").read_text(encoding="utf-8")
    process = (SITE_ROOT / "_pages/editorial-process.md").read_text(encoding="utf-8")

    assert "Every article must have a named human author" in standards
    assert "not currently included in public article metadata" in standards
    assert "author-led, technology-assisted editorial process" in process
    assert "do not decide what BriefBerlin covers or publish content independently" in process


def test_corrections_policy_matches_article_correction_markup():
    policy = (SITE_ROOT / "_pages/corrections.md").read_text(encoding="utf-8")
    layout = (SITE_ROOT / "_layouts/post.html").read_text(encoding="utf-8")

    assert "visible correction note" in policy
    assert "original publication date is preserved" in policy
    assert "page.correction.note" in layout
    assert "page.last_modified_at" in layout
    assert 'class="article-correction"' in layout


def test_clara_becker_profile_and_byline_are_connected():
    authors = yaml.safe_load((SITE_ROOT / "_data/authors.yml").read_text(encoding="utf-8"))
    author_page = (SITE_ROOT / "_pages/clara-becker.md").read_text(encoding="utf-8")
    layout = (SITE_ROOT / "_layouts/post.html").read_text(encoding="utf-8")
    site_config = yaml.safe_load((SITE_ROOT / "_config.yml").read_text(encoding="utf-8"))

    clara = authors["clara-becker"]
    assert clara["name"] == "Clara Becker"
    assert clara["role"] == "Writer and Language Educator"
    assert clara["email"] == "clara@briefberlin.de"
    assert clara["same_as"] == []
    assert "University of Leipzig" in author_page
    assert site_config["defaults"][0]["values"]["author"] == "clara-becker"
    assert "site.data.authors[page.author]" in layout
    assert "article_author.url" in layout


def test_author_pages_use_reusable_layout_and_directory():
    author_page = (SITE_ROOT / "_pages/clara-becker.md").read_text(encoding="utf-8")
    author_layout = (SITE_ROOT / "_layouts/author.html").read_text(encoding="utf-8")
    directory = (SITE_ROOT / "_pages/authors.md").read_text(encoding="utf-8")
    navigation = yaml.safe_load(
        (SITE_ROOT / "_data/navigation.yml").read_text(encoding="utf-8")
    )

    assert "layout: author" in author_page
    assert "author_key: clara-becker" in author_page
    assert "site.data.authors[page.author_key]" in author_layout
    assert 'where: "author", page.author_key' in author_layout
    assert "site.data.authors" in directory
    assert {item["title"] for item in navigation["main"]} >= {"Authors"}


def test_author_and_news_article_schema_use_stable_entity_ids():
    custom_head = (SITE_ROOT / "_includes/head/custom.html").read_text(encoding="utf-8")

    assert '"@type": "Person"' in custom_head
    assert '"@type": "NewsArticle"' in custom_head
    assert 'article_author_url | append: "#person"' in custom_head
    assert 'site.url | append: "/#publisher"' in custom_head
    assert '"@type": "ImageObject"' in custom_head
    assert '"sameAs"' not in custom_head


def test_welcome_article_matches_author_led_editorial_policy():
    welcome = (
        SITE_ROOT / "_posts/2025-11-01-willkommen-bei-briefberlin.md"
    ).read_text(encoding="utf-8")

    assert "Unsere Autorin Clara Becker" in welcome
    assert "Clara prüft, bearbeitet und genehmigt jeden Artikel" in welcome
    assert "intelligentes System" not in welcome

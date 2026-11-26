"""Offline cases for execution on the installed host."""

import json
from contextlib import closing

import pytest

from scripts.editorial import adapters
from scripts.editorial.collection import collect, set_paused
from scripts.editorial.db import connect
from scripts.editorial.http import Gap, Response, retry_time
from scripts.editorial.registry import sync_registry
from scripts.editorial.smoke import compare_passes

NOW = 1700000000
ORIGIN = "https://example.org"
STORY = ORIGIN + "/release"


def registry(path, *entries):
    sources = []
    for name, adapter, route, endpoint in entries:
        row = {"id": name, "publisher": name, "scope": "Europe", "active": True,
               "monitor_url": ORIGIN + route,
               "poll": {"endpoint_id": endpoint, "adapter": adapter, "interval_minutes": 1}}
        if adapter == "feed":
            row["rss_url"] = row["monitor_url"]
        sources.append(row)
    path.write_text(json.dumps({"schema_version": 1, "sources": sources}))
    return path


@pytest.fixture
def conn(tmp_path):
    with closing(connect(tmp_path / "host.db")) as db:
        yield db


def response(url, text, **kw):
    return Response(url, text.encode(), **kw)


def rss(text="The city has approved extra funding for housing.", guid="g", title="Council",
        url=STORY, date="Tue, 14 Nov 2023 21:59:00 GMT"):
    return f"""<rss version="2.0"><channel><title>Example</title><item><title>{title}</title>
        <link>{url}</link><guid isPermaLink="false">{guid}</guid><pubDate>{date}</pubDate>
        <description>{text}</description></item></channel></rss>"""


def test_cross_feed_attribution_aliases_and_age(conn, tmp_path):
    sync_registry(conn, registry(tmp_path / "r", ("a", "feed", "/a", "a"),
                                 ("b", "feed", "/b", "b"), ("c", "feed", "/b", "b")))
    def fetch(url, headers):
        assert not conn.in_transaction
        return response(url, rss(title=url, guid=url, url=STORY + "?utm_source=news"))
    initial = collect(conn, now=NOW, fetch=fetch)
    assert sum(x["new_revisions"] for x in initial["endpoints"]) == 1
    assert conn.execute("SELECT count(*) FROM source_sightings").fetchone()[0] == 3
    row, = conn.execute("SELECT * FROM editorial_inputs")
    assert row["url"] == STORY and row["eligible"] == 0 and row["published_at"] < NOW
    original = row["revision_id"]
    collect(conn, now=NOW+61, fetch=lambda url, h: response(url, rss(
        date="Wed, 15 Nov 2023 21:59:00 GMT", guid=url, url=STORY + "-moved")))
    assert tuple(conn.execute("SELECT revision_id,url FROM editorial_inputs").fetchone()) == (
        original, STORY + "-moved")
    assert conn.execute("SELECT count(*) FROM report_revisions").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM report_urls").fetchone()[0] == 2
    collect(conn, now=NOW+122, fetch=lambda url, h: response(url, rss(
        text="The city has doubled the funding allocation for housing.", guid=url)))
    assert conn.execute("SELECT count(*) FROM reports").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM report_revisions").fetchone()[0] == 2


def test_dates_baseline_lookback_and_atom(conn, tmp_path):
    sync_registry(conn, registry(tmp_path / "r", ("a", "feed", "/a", "a")))
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><title>Items</title><entry>
        <id>one</id><title>Decision</title><link href="https://example.org/a/1"/>
        <published>2023-11-14T21:59:00Z</published><updated>2023-11-14T22:00:00Z</updated>
        <content>Approved decision with sufficient factual content.</content></entry></feed>"""
    collect(conn, now=NOW, lookback_hours=1, fetch=lambda u, h: response(u, atom))
    assert conn.execute("SELECT eligible FROM editorial_inputs").fetchone()[0] == 1
    old = rss(url=STORY + "/old", date="Tue, 14 Nov 2017 21:59:00 GMT")
    collect(conn, now=NOW+61, fetch=lambda u, h: response(u, old))
    assert conn.execute("SELECT eligible FROM editorial_inputs WHERE url=?", (STORY + "/old",)).fetchone()[0] == 0
    with pytest.raises(ValueError):
        collect(conn, lookback_hours=49)


def test_children_survive_rotation_and_304_and_use_real_evidence(conn, tmp_path):
    sync_registry(conn, registry(tmp_path / "r", ("a", "listing", "/news", "a")))
    page = """<main><nav><a href="/private">Contact 14.11.2023</a></nav>
        <ul><li><time datetime="2023-11-14">Today</time><a href="/one">One</a></li>
        <li><time datetime="2023-11-14">Today</time><a href="/two">Two</a></li></ul>
        <a href="/about">About</a></main>"""
    seen = []
    def fetch(url, headers):
        seen.append(url)
        if url.endswith("/news"):
            if headers:
                return Response(url, b"", 304)
            return response(url, page, etag="123")
        if url.endswith("/one") and seen.count(url) == 1:
            raise Gap("HTTP 503")
        return response(url, "<article><h1>Published release</h1><p>Original published body "
                             "from a separate child request.</p></article>")
    first = collect(conn, now=NOW, fetch=fetch, children=2)["endpoints"][0]
    assert first["pending"] == 1 and first["new_revisions"] == 1 and first["errors"] == ["HTTP 503"]
    # Index now rotates out the failed child. A successful read still retains it for delivery.
    def rotated(u, h):
        if u.endswith("/news"):
            return response(u, page.replace('href="/one"', 'href="/three"'))
        return fetch(u, h)
    collect(conn, now=NOW+301, fetch=rotated, children=4)
    assert seen.count(ORIGIN + "/one") == 2 and ORIGIN + "/about" not in seen
    assert ORIGIN + "/private" not in seen
    assert {r[0] for r in conn.execute("SELECT evidence FROM editorial_inputs")} == {
        "Original published body from a separate child request."}
    assert not any(r[0] for r in conn.execute("SELECT eligible FROM editorial_inputs"))


def test_conditional_index_retries_pending_child(conn, tmp_path):
    sync_registry(conn, registry(tmp_path / "r", ("a", "listing", "/news", "a")))
    def initial(u, h):
        if u.endswith("/news"):
            return response(u, '<main><a href="/a/2023/11/14/item">Story</a></main>', etag="tag")
        raise Gap("temporary child failure")
    collect(conn, now=NOW, fetch=initial)
    def again(u, h):
        if u.endswith("/news"):
            assert h == {"If-None-Match": "tag"}
            return Response(u, b"", 304)
        return response(u, "<article><h1>Story</h1><p>First successful extraction from "
                           "a previously unavailable report.</p></article>")
    row, = collect(conn, now=NOW+301, fetch=again)["endpoints"]
    assert row["new_revisions"] == 1 and row["unchanged"] and not row["errors"]


def test_notice_normalization_and_pause_race(conn, tmp_path):
    sync_registry(conn, registry(tmp_path / "r", ("a", "notice", "/fixed", "a")))
    def page(body, footer):
        return f"<main><h1>Status</h1><p>{body}</p><footer>{footer}</footer></main>"
    text = "The station is closed while repairs take place."
    for offset, body in ((0, text), (61, text), (122, "The station reopened after repairs this morning.")):
        collect(conn, now=NOW+offset, fetch=lambda u, h: response(u, page(body, str(offset))))
    assert [r[0] for r in conn.execute("SELECT eligible FROM editorial_inputs ORDER BY revision_id")] == [0, 1]
    assert [r[0] for r in conn.execute("SELECT revision_id FROM notice_changes")] == [2]
    def interrupted(url, headers):
        set_paused(conn, True)
        set_paused(conn, False)
        return response(url, page("This in-flight result must be discarded.", ""))
    result = collect(conn, now=NOW+183, fetch=interrupted)
    assert result["endpoints"][0]["errors"] == ["stale snapshot"]
    assert conn.execute("SELECT count(*) FROM editorial_inputs").fetchone()[0] == 2
    set_paused(conn, True)
    assert collect(conn, now=NOW+244, fetch=interrupted) == {"paused": True, "endpoints": []}


def test_pdf_index_missing_converter_is_actionable(conn, tmp_path, monkeypatch):
    sync_registry(conn, registry(tmp_path / "r", ("a", "documents", "/docs", "a")))
    def fetch(url, headers):
        if url.endswith("/docs"):
            return response(url, '<main><a href="/report.pdf">Report A</a><a href="/contact">Office</a></main>')
        return response(url, "%PDF-fixture", media="application/pdf")
    def missing(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(adapters.subprocess, "run", missing)
    one, = collect(conn, now=NOW, fetch=fetch)["endpoints"]
    assert one["errors"] == ["PDF extraction requires pdftotext"] and one["pending"] == 1
    class Extracted:
        stdout = b"The submitted public document describes the housing programme."
    monkeypatch.setattr(adapters.subprocess, "run", lambda *a, **kw: Extracted())
    two, = collect(conn, now=NOW+301, fetch=fetch)["endpoints"]
    assert two["sightings"] == 1 and not two["pending"] and not two["errors"]


def test_retry_after_date_and_delta():
    assert retry_time("60", NOW) == NOW+60
    assert retry_time("Tue, 14 Nov 2023 22:14:20 GMT", NOW) == NOW+60
    assert retry_time("unavailable", NOW) == 0


def test_mixed_feed_item_gaps_and_conditional_read(conn, tmp_path):
    sync_registry(conn, registry(tmp_path / "r", ("a", "feed", "/news", "a")))
    broken = ("<item><title>Short</title><link>https://other.org/short</link></item>"
              "<item><title>Missing link</title></item>")
    feed = rss().replace("</channel>", broken + "</channel>")
    first, = collect(conn, now=NOW, fetch=lambda u, h: response(u, feed, etag="v1"))["endpoints"]
    assert first["new_revisions"] == 1
    assert first["errors"] == ["feed item 2: off-host item lacks evidence",
                               "feed item 3: missing public address or title"]
    second, = collect(conn, now=NOW+61, fetch=lambda u, h: Response(u, b"", 304))["endpoints"]
    assert second["errors"] == first["errors"]
    assert sorted(r[0] for r in conn.execute("SELECT category FROM collection_gaps")) == first["errors"]


@pytest.mark.parametrize("parent_outcome", ["unavailable", "empty"])
def test_child_can_finish_while_index_is_unusable(conn, tmp_path, parent_outcome):
    sync_registry(conn, registry(tmp_path / "r", ("a", "listing", "/news", "a")))
    def initial(url, headers):
        if url.endswith("/news"):
            return response(url, '<main><a href="/2023/11/14/story">Release</a></main>', etag="one")
        raise Gap("unavailable child")
    collect(conn, now=NOW, fetch=initial)
    def subsequent(url, headers):
        if url.endswith("/news"):
            if parent_outcome == "unavailable":
                raise Gap("unavailable index")
            return response(url, "<main>No recent releases.</main>", etag="two")
        return response(url, "<article><h1>Release</h1><p>Evidence from the recovered child page.</p></article>")
    row, = collect(conn, now=NOW+301, fetch=subsequent)["endpoints"]
    assert row["new_revisions"] == 1 and row["pending"] == 0 and len(row["errors"]) == 1
    state = conn.execute("SELECT * FROM poll_state").fetchone()
    assert state["last_success"] == NOW and state["failures"] == 1
    assert json.loads(state["cursor"])["etag"] == "one"
    assert not next(iter(json.loads(state["cursor"])["children"].values()))["pending"]


@pytest.mark.parametrize(("label", "expected_date"), [
    ("", None),
    ("<p>Pressemitteilung vom 14.11.2017</p>", adapters.epoch("14.11.2017")),
])
def test_listing_and_event_times_cannot_refresh_undated_or_old_material(conn, tmp_path, label, expected_date):
    sync_registry(conn, registry(tmp_path / "r", ("a", "listing", "/news", "a")))
    def fetch(url, headers):
        if url.endswith("/news"):
            return response(url, '<main><ul><li><time datetime="2023-11-14">Today</time>'
                                 '<a href="/archive">Event</a></li></ul></main>')
        return response(url, '<article><h1>Event</h1><time datetime="2023-11-14">Deadline</time>' +
                        label + '<p>Registration for this programme closes on Tuesday.</p></article>')
    collect(conn, now=NOW, lookback_hours=48, fetch=fetch)
    assert tuple(conn.execute("SELECT published_at,eligible FROM editorial_inputs").fetchone()) == (
        expected_date, 0)


def test_notice_headline_and_inline_time_create_revisions(conn, tmp_path):
    sync_registry(conn, registry(tmp_path / "r", ("a", "notice", "/notice", "a")))
    for step, (heading, hour) in enumerate([("Closed", "09:00"), ("Closed", "09:00"),
                                             ("Limited access", "09:00"), ("Limited access", "14:00")]):
        page = (f"<main><h1>{heading}</h1><time>{step}</time><p>Stand: <time>{step}</time></p>"
                f"<p>The entrance is closed until <time>{hour}</time> while staff inspect it.</p></main>")
        collect(conn, now=NOW+61*step, fetch=lambda u, h: response(u, page))
    assert [r[0] for r in conn.execute("SELECT seen_count FROM source_sightings ORDER BY revision_id")] == [2, 1, 1]
    assert "14:00" in conn.execute("SELECT evidence FROM editorial_inputs ORDER BY revision_id DESC").fetchone()[0]


def test_stale_poll_cooldown_applies_to_an_already_running_poll(conn, tmp_path):
    sync_registry(conn, registry(tmp_path / "r", ("a", "feed", "/a", "a"), ("b", "feed", "/b", "b")))
    with closing(connect(tmp_path / "host.db")) as other:
        def throttle(url, headers):
            # Invalidate just this in-flight poll, as a competing tick would.
            conn.execute("UPDATE poll_state SET state_version=state_version+1 WHERE endpoint_id='b'")
            raise Gap("HTTP 429", NOW + 500)

        def overlapping(url, headers):
            assert url == ORIGIN + "/a"  # Its subsequent child fetch must honor the new cooldown.
            lost, = collect(other, now=NOW, endpoint_ids=["b"], fetch=throttle)["endpoints"]
            assert lost["errors"] == ["stale snapshot"]
            return response(url, rss(text="thin"))

        row, = collect(conn, now=NOW, endpoint_ids=["a"], fetch=overlapping)["endpoints"]
        assert row["pending"] == 1 and row["errors"] == ["host Retry-After"]
        assert other.execute("SELECT until_epoch FROM host_cooldowns").fetchone()[0] == NOW+500
        denied, = collect(other, now=NOW+100, endpoint_ids=["b"], fetch=overlapping)["endpoints"]
        assert denied["errors"] == ["host Retry-After"]


def test_smoke_requires_existing_identity_hash_and_another_sighting():
    original = {(1, 1, "hash"): 1}
    assert compare_passes(original, original)["repeated_revisions"] == 0
    assert compare_passes(original, {(1, 1, "changed"): 2})["repeated_revisions"] == 0
    assert compare_passes(original, {**original, (2, 2, "new"): 2})["repeated_revisions"] == 0
    result = compare_passes(original, {(1, 1, "hash"): 2, (1, 2, "edit"): 1, (2, 3, "new"): 1})
    assert result == {"repeated_revisions": 1, "new_reports": 1,
                      "new_revisions_on_existing_reports": 1, "all_original_revisions_retained": True}

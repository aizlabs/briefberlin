"""Registry and SQLite integration tests for the installed editorial host."""

import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.editorial import db
from scripts.editorial.__main__ import coverage, main
from scripts.editorial.inventory import DEFAULT_REGISTRY
from scripts.editorial.registry import StaleEndpoint, due_endpoints, sync_registry, update_poll_state


@pytest.fixture
def conn(tmp_path):
    with closing(db.connect(tmp_path / "private" / "state.db")) as connection:
        yield connection


def issuer(name="unit", url="https://example.org/releases"):
    return {"id": name, "publisher": name, "active": True, "scope": "Berlin",
            "monitor_url": url, "poll": {"endpoint_id": "bulletin", "adapter": "listing",
                                        "interval_minutes": 15}}


def reload(conn, path: Path, *sources):
    registry = path / "registry.json"
    registry.write_text(json.dumps({"schema_version": 1, "sources": sources}), encoding="utf-8")
    sync_registry(conn, registry)


def due(conn, now=1000):
    return due_endpoints(conn, now=now, limit=500)


def mark(conn, endpoint):
    with db.transaction(conn):
        update_poll_state(conn, endpoint, next_due=1001, success_at=100, cursor={"etag": "tag"},
                          baseline_complete=True)


def test_original_inventory(conn):
    sync_registry(conn)
    metadata = [json.loads(row[0]) for row in conn.execute("SELECT metadata FROM sources")]
    assert Counter(s["inventory"] for s in metadata) == {"november-audit": 151, "approved-addition": 8}
    assert {s["id"] for s in metadata if s["inventory"] == "approved-addition"} == {
        "infratest-dimap-berlin", "bizim-kiez", "immowelt-research", "rave-the-planet",
        "berliner-mieterverein", "gew-berlin", "dgb-berlin-brandenburg", "csd-berlin",
    }
    urls = sorted(tuple(r) for r in conn.execute("SELECT source_id,field,url FROM source_resources"))
    assert len(urls) == 228
    # Sorted (original source ID, field, unmodified URL) from the November audit and additions.
    assert hashlib.sha256(json.dumps(urls, ensure_ascii=False).encode()).hexdigest() == (
        "c9ac4325cdf8999bf5063293ab9e51bd1ee68fef4d925883359927d97825ec53"
    )
    info = coverage(conn)
    assert info["sources"] == 159
    assert set(info["active_poll_endpoints"]) == {"feed", "listing", "documents", "notice"}
    assert {"contact", "subscription", "reference", "example"} == {
        resource["purpose"] for resource in info["lookup_resources"]
    }
    assert len({endpoint.url for endpoint in due(conn)}) == len(due(conn))
    assert all(endpoint.adapter != "lookup" for endpoint in due(conn))
    assert len([r for r in info["endpoints"] if r["endpoint_id"] == "polizei-berlin-updates"]) == 3
    assert all(s["scope"] and isinstance(s["active"], bool) for s in metadata)
    assert "Brandenburg" in next(s["scope"] for s in metadata if s["id"] == "s-bahn-berlin")


def test_reload_pause_removal_and_return(conn, tmp_path):
    source = issuer()
    reload(conn, tmp_path, source)
    initial, = due(conn)
    mark(conn, initial)
    source["publisher"] = "Renamed"
    reload(conn, tmp_path, source)
    saved, = due(conn, 1001)
    assert saved.endpoint_id == initial.endpoint_id and saved.cursor == {"etag": "tag"}
    reload(conn, tmp_path, source)
    assert due(conn, 1001) == [saved]
    source["active"] = False
    reload(conn, tmp_path, source)
    assert not due(conn, 2000)
    reload(conn, tmp_path)
    assert conn.execute("SELECT present FROM sources").fetchone()[0] == 0
    assert conn.execute("SELECT cursor FROM poll_state").fetchone()[0] == '{"etag": "tag"}'
    source["active"] = True
    reload(conn, tmp_path, source)
    resumed, = due(conn, 2000)
    assert resumed.baseline_complete and resumed.cursor == saved.cursor
    with pytest.raises(StaleEndpoint):
        mark(conn, saved)


def test_move_and_reconfigure_rebaseline_without_losing_history(conn, tmp_path):
    source = issuer()
    reload(conn, tmp_path, source)
    original, = due(conn)
    mark(conn, original)
    source["monitor_url"] += "/new"
    reload(conn, tmp_path, source)
    moved, = due(conn)
    assert (moved.endpoint_id, moved.generation) == (original.endpoint_id, original.generation + 1)
    assert not moved.baseline_complete and moved.cursor == {}
    assert conn.execute("SELECT last_success FROM poll_state WHERE generation=1").fetchone()[0] == 100
    source["poll"]["selector"] = ".news"
    reload(conn, tmp_path, source)
    reconfigured, = due(conn)
    assert reconfigured.generation == moved.generation + 1
    with pytest.raises(StaleEndpoint):
        mark(conn, moved)


def test_shared_move_keeps_other_cursor(conn, tmp_path):
    a, b = issuer("alpha"), issuer("bravo")
    reload(conn, tmp_path, a, b)
    first, = due(conn)
    mark(conn, first)
    a["monitor_url"] += "/other"
    reload(conn, tmp_path, a, b)
    current = {endpoint.url: endpoint for endpoint in due(conn, 1001)}
    retained = current[b["monitor_url"]]
    split = current[a["monitor_url"]]
    assert (retained.endpoint_id, retained.generation) == (first.endpoint_id, first.generation)
    assert retained.cursor == {"etag": "tag"} and split.cursor == {}
    assert split.endpoint_id != retained.endpoint_id
    b["active"] = False
    reload(conn, tmp_path, a, b)
    assert due(conn, 1001) == [split]
    a["monitor_url"] += "/another"
    reload(conn, tmp_path, b, a)
    moved, = due(conn)
    assert (moved.endpoint_id, moved.generation) == (split.endpoint_id, split.generation + 1)


@pytest.mark.parametrize("reattach_paused", [False, True])
def test_rejoining_an_abandoned_address_rebaselines(conn, tmp_path, reattach_paused):
    a, b = issuer("alpha"), issuer("bravo")
    reload(conn, tmp_path, a, b)
    shared, = due(conn)
    mark(conn, shared)
    other_url = a["monitor_url"] + "/other"
    a["monitor_url"] = other_url
    reload(conn, tmp_path, a, b)
    other, = due(conn)
    mark(conn, other)
    a["monitor_url"] = b["monitor_url"]
    reload(conn, tmp_path, a, b)
    a["monitor_url"] = other_url
    if reattach_paused:
        a["active"] = False
        reload(conn, tmp_path, b, a)
        assert [row.url for row in due(conn, 1001)] == [shared.url]
    a["active"] = True
    reload(conn, tmp_path, b, a)
    restored, = due(conn)
    assert (restored.endpoint_id, restored.generation) == (other.endpoint_id, other.generation + 1)
    assert restored.cursor == {} and not restored.baseline_complete
    historical = conn.execute(
        "SELECT cursor, baseline_complete FROM poll_state WHERE endpoint_id=? AND generation=?",
        (other.endpoint_id, other.generation),
    ).fetchone()
    assert json.loads(historical["cursor"]) == {"etag": "tag"} and historical["baseline_complete"]
    still_shared = next(row for row in due(conn, 1001) if row.url == shared.url)
    assert still_shared.generation == shared.generation and still_shared.baseline_complete
    with pytest.raises(StaleEndpoint):
        mark(conn, other)


def test_paused_issuers_cannot_replace_the_last_active_config(conn, tmp_path):
    a, b = issuer("alpha"), issuer("bravo")
    a["active"] = False
    a["poll"].update(selector=".other", interval_minutes=30)
    reload(conn, tmp_path, a, b)
    initial, = due(conn)
    mark(conn, initial)
    b["active"] = False
    for members in ((a, b), (b, a)):
        reload(conn, tmp_path, *members)
        config = conn.execute("SELECT generation,selector,interval_minutes,active FROM endpoints")
        assert tuple(config.fetchone()) == (initial.generation, None, 15, 0)
        assert not due(conn, 1001)
    b["active"] = True
    reload(conn, tmp_path, a, b)
    resumed, = due(conn, 1001)
    assert resumed.generation == initial.generation and resumed.cursor == {"etag": "tag"}
    b["active"], a["active"] = False, True
    reload(conn, tmp_path, b, a)
    changed, = due(conn)
    assert changed.generation == initial.generation + 1 and not changed.baseline_complete


@pytest.mark.parametrize("scheme,port", [("http", 80), ("https", 443)])
def test_request_identity_coalesces_aliases_but_retains_source_urls(conn, tmp_path, scheme, port):
    url = f"{scheme}://example.org/news?q=a"
    a = issuer("alpha", f"{scheme}://EXAMPLE.ORG:{port}/news?q=a#one")
    b = issuer("bravo", url + "#two")
    distinct = issuer("charlie", f"{scheme}://example.org:8888/news?q=a#three")
    reload(conn, tmp_path, a, b, distinct)
    assert len(due(conn)) == 2
    shared = next(row for row in due(conn) if row.url == url)
    mark(conn, shared)
    raw_urls = dict(conn.execute("SELECT source_id,url FROM source_resources WHERE current=1"))
    assert raw_urls == {source["id"]: source["monitor_url"] for source in (a, b, distinct)}
    a["monitor_url"] = url + "#updated"
    reload(conn, tmp_path, distinct, b, a)
    retained = next(row for row in due(conn, 1001) if row.url == url)
    assert retained.endpoint_id == shared.endpoint_id and retained.generation == shared.generation
    assert retained.cursor == {"etag": "tag"}
    b["poll"]["endpoint_id"] = "separate"
    with pytest.raises(ValueError, match="shared active URL"):
        reload(conn, tmp_path, a, b, distinct)


def test_legacy_raw_poll_url_preserves_generation_on_reload(conn, tmp_path):
    raw = "https://EXAMPLE.ORG:443/feed#archived"
    a = issuer("alpha", raw)
    reload(conn, tmp_path, a)
    original, = due(conn)
    mark(conn, original)
    with db.transaction(conn):
        conn.execute("UPDATE endpoints SET url=?", (raw,))
        conn.execute("UPDATE poll_state SET url=?", (raw,))
    a["monitor_url"] = "https://example.org/feed#current"
    reload(conn, tmp_path, a)
    saved, = due(conn, 1001)
    assert saved.endpoint_id == original.endpoint_id and saved.generation == original.generation
    assert saved.url == "https://example.org/feed" and saved.cursor == {"etag": "tag"}


@pytest.mark.parametrize("change", ["duplicate", "lookup-url", "invalid-interval", "shared", "future",
                                    "invalid-id", "invalid-port", "selector", "regex"])
def test_invalid_reload_preserves_state(conn, tmp_path, change):
    a = issuer("alpha")
    reload(conn, tmp_path, a)
    saved = due(conn)
    b = deepcopy(a)
    b["id"] = "bravo"
    if change == "duplicate":
        b["id"] = a["id"]
    elif change == "lookup-url":
        b["example_url"] = "file:///etc/hosts"
    elif change == "invalid-interval":
        b["poll"]["interval_minutes"] = True
    elif change == "shared":
        b["poll"]["interval_minutes"] = 30
    elif change == "future":
        b["poll"]["unknown_setting"] = True
    elif change == "invalid-id":
        b["id"] = " "
    elif change == "invalid-port":
        b["monitor_url"] = "https://example.org:99999/releases"
    elif change == "selector":
        b["poll"]["selector"] = "["
    elif change == "regex":
        b["poll"]["link_pattern"] = "["
    with pytest.raises(ValueError):
        reload(conn, tmp_path, a, b)
    assert due(conn) == saved
    assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1


def test_concurrent_poll_and_failed_batch(conn, tmp_path):
    reload(conn, tmp_path, issuer())
    snapshot, = due(conn)
    with pytest.raises(RuntimeError):
        update_poll_state(conn, snapshot, next_due=2000, failure="429")
    with db.transaction(conn):
        update_poll_state(conn, snapshot, next_due=2000, failure="429")
    assert not due(conn, 1999)
    retry, = due(conn, 2000)
    assert retry.failures == 1 and not retry.baseline_complete and retry.cursor == {}
    with pytest.raises(StaleEndpoint), db.transaction(conn):
        conn.execute("INSERT INTO settings VALUES('temporary-observation','data')")
        update_poll_state(conn, snapshot, next_due=2100, success_at=2000)
    assert not conn.execute("SELECT * FROM settings").fetchall()
    mark(conn, retry)
    assert due(conn, 2000)[0].failures == 0


def test_migrations_reopen_rollback_and_reject_future(tmp_path, monkeypatch):
    path = tmp_path / "migration.db"
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.execute("INSERT INTO settings VALUES('host','kept')")
    with monkeypatch.context() as m:
        m.setattr(db, "MIGRATIONS", db.MIGRATIONS + [("CREATE TABLE extension(x)", "invalid SQL")])
        with pytest.raises(sqlite3.OperationalError):
            db.connect(path)
    with closing(db.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='extension'").fetchall()
    monkeypatch.setattr(db, "MIGRATIONS", db.MIGRATIONS + [("CREATE TABLE extension(x)",)])
    with closing(db.connect(path)) as upgraded:
        assert upgraded.execute("PRAGMA user_version").fetchone()[0] == version + 1
        assert upgraded.execute("SELECT value FROM settings WHERE key='host'").fetchone()[0] == "kept"
        upgraded.execute(f"PRAGMA user_version={version + 2}")
    with pytest.raises(ValueError, match="newer"):
        db.connect(path)


def test_cli_and_output_boundary(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="public output"):
        db.connect(tmp_path / "output" / "state.db")
    args = ["--db", str(tmp_path / "host.db")]
    assert main([*args, "init"]) == 0
    assert main([*args, "registry-sync", "--registry", str(DEFAULT_REGISTRY)]) == 0
    capsys.readouterr()
    assert main([*args, "coverage"]) == 0
    assert json.loads(capsys.readouterr().out)["sources"] == 159


@pytest.mark.parametrize("from_output", [True, False])
def test_installed_cli_rejects_database_inside_jekyll(tmp_path, monkeypatch, capsys, from_output):
    monkeypatch.setattr(db, "ROOT", tmp_path / "site-packages")
    public = tmp_path / "checkout" / "output"
    public.mkdir(parents=True)
    (public / "_config.yml").write_text("title: BriefBerlin\n", encoding="utf-8")
    monkeypatch.chdir(public if from_output else tmp_path)
    subpath = Path("assets/private/state.db")
    with pytest.raises(SystemExit) as error:
        main(["--db", str(subpath if from_output else public / subpath), "init"])
    assert error.value.code == 1 and "public output" in capsys.readouterr().err
    assert not (public / "assets").exists()


def test_output_symlink_cannot_expose_host_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output, host = tmp_path / "checkout" / "output", tmp_path / "host"
    output.mkdir(parents=True)
    host.mkdir()
    (output / "_config.yml").touch()
    (output / "linked").symlink_to(host, target_is_directory=True)
    with pytest.raises(ValueError, match="public output"):
        db.connect(output / "linked" / "state.db")
    assert not (host / "state.db").exists()

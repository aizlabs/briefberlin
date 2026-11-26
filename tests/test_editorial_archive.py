import json
from contextlib import closing
from pathlib import Path

import pytest

from scripts.editorial import archive, dispatch
from scripts.editorial.__main__ import main
from scripts.editorial.archive import (
    LEGACY,
    ORIGIN,
    record_publication,
    resolve_archive,
    setting,
    sync_archive,
)
from scripts.editorial.db import connect

NOW = 1_800_000_000


def post(root, slug, *, shared="", nested=False, translations=False, level="A2"):
    directory = root / ("history/_posts" if nested else "_posts")
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["---", "title: Example " + slug, "date: 2026-07-04 09:00:00", f"level: {level}"]
    if shared:
        lines.append("story: " + shared)
    if translations:
        lines.extend(["translations:", f"  de: /articles/{slug}/", f"  en: /articles/{slug}/en/"])
    (directory / f"2026-07-04-{slug}.md").write_text("\n".join([*lines, "---", "Text"]))


def sitemap(path, *slugs):
    path.write_text("<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>" +
                    "".join(f"<url><loc>{ORIGIN}/articles/{s}/</loc></url>" for s in slugs) + "</urlset>")


def test_shared_id_legacy_groups_translations_clock(tmp_path):
    root, fixture, groups = (tmp_path / x for x in ("output", "map.xml", "groups.json"))
    post(root, "first", shared="stable", translations=True)
    post(root, "other", nested=True)
    post(root, "legacy-a")
    post(root, "legacy-b", nested=True)
    sitemap(fixture, "first", "first/en", "other", "legacy-a", "legacy-b")
    groups.write_text(json.dumps({"old1": ["/articles/first/", "/articles/other/"],
                                 "old2": ["/articles/legacy-a/", "/articles/legacy-b/"]}))
    kwargs = dict(output=root, fixture=fixture, legacy=groups, now=NOW)
    with closing(connect(tmp_path / "db")) as conn:
        result = sync_archive(conn, **kwargs, known_live_story="stable", known_live_epoch=NOW - 90)
        assert result["ready"] and result["new_ledger_entries"] == 2
        assert dict(conn.execute("SELECT id,status FROM stories")) == {"stable": "live", "old2": "live"}
        assert conn.execute("SELECT COUNT(*) FROM editions").fetchone()[0] == 5
        assert conn.execute("SELECT story_id FROM editions WHERE path='/articles/other/'").fetchone()[0] == "stable"
        assert setting(conn, "fallback_epoch") == str(NOW - 90)
        assert conn.execute("SELECT verified_at FROM live_publications WHERE story_id='stable'").fetchone()[0] == NOW - 90
        post(root, "third", shared="stable")
        post(root, "local-draft", shared="draft")
        sitemap(fixture, "first", "first/en", "other", "legacy-a", "legacy-b", "third")
        result = sync_archive(conn, **kwargs)
        assert result["ready"] and result["new_ledger_entries"] == 0
        assert setting(conn, "fallback_epoch") == str(NOW - 90)
        assert any(i["issue"] == "not-in-sitemap" for i in result["issues"])
        post(root, "manual", shared="manual-event")
        sitemap(fixture, "first", "first/en", "other", "legacy-a", "legacy-b", "third", "manual")
        assert not sync_archive(conn, **kwargs)["ready"]
        assert setting(conn, "fallback_epoch") == str(NOW - 90)
        post(root, "manual-b", shared="manual-event", level="B1")
        sitemap(fixture, "first", "first/en", "other", "legacy-a", "legacy-b", "third", "manual", "manual-b")
        assert sync_archive(conn, **kwargs)["new_ledger_entries"] == 1
        assert setting(conn, "fallback_epoch") == str(NOW)
        assert not record_publication(conn, story_id="manual-event", publication_key="commit-123",
                                      origin="manual", verified_at=NOW + 60)
        with pytest.raises(ValueError, match="another story"):
            record_publication(conn, story_id="stable", publication_key="commit-123",
                               origin="manual", verified_at=NOW + 60)
        assert setting(conn, "fallback_epoch") == str(NOW)


def test_unmatched_live_claim_or_missing_sitemap_fails_closed(tmp_path):
    root, fixture = tmp_path / "output", tmp_path / "map"
    post(root, "known", shared="one")
    sitemap(fixture, "known", "unknown")
    with closing(connect(tmp_path / "db")) as conn:
        kwargs = dict(output=root, fixture=fixture, now=NOW)
        assert not sync_archive(conn, **kwargs, bootstrap_epoch=NOW)["ready"]
        assert setting(conn, "archive_bootstrapped") is None
        post(root, "known-b", shared="one", level="B1")
        sitemap(fixture, "known", "known-b")
        with pytest.raises(ValueError, match="epoch"):
            sync_archive(conn, **kwargs)
        assert sync_archive(conn, **kwargs, bootstrap_epoch=NOW)["ready"]
        fixture.write_text("<broken>")
        with pytest.raises(ValueError, match="XML"):
            sync_archive(conn, **kwargs)
        assert setting(conn, "archive_ready") == "0"
        assert setting(conn, "fallback_epoch") == str(NOW)


def test_public_audit_fixture_preserves_entire_archive_and_known_collision(tmp_path):
    groups = json.loads(LEGACY.read_text())
    all_paths = {path for paths in groups.values() for path in paths}
    assert len(all_paths) == 729
    fixture = tmp_path / "sitemap.xml"
    sitemap(fixture, *(path.removeprefix("/articles/").strip("/") for path in all_paths))
    root = Path(__file__).resolve().parents[1] / "output"
    with closing(connect(tmp_path / "db")) as conn:
        result = sync_archive(conn, output=root, fixture=fixture, bootstrap_epoch=NOW, now=NOW)
        assert result["ready"]
        assert any(i["issue"] == "collision" for i in result["issues"])
        assert conn.execute("SELECT count(*) FROM editions").fetchone()[0] == len(all_paths) - 1
        assert conn.execute("SELECT count(*) FROM editions WHERE lang!='de'").fetchone()[0] == 455


def test_fresh_bootstrap_requires_all_levels_and_exact_audited_collision(tmp_path):
    root, fixture, groups = (tmp_path / x for x in ("posts", "map.xml", "groups.json"))
    post(root, "new", shared="new-item")
    sitemap(fixture, "new")
    db = tmp_path / "db"
    args = ["--db", str(db), "archive-sync", "--output", str(root), "--sitemap-fixture", str(fixture),
            "--bootstrap-epoch", str(NOW - 20 * 365 * 86400)]
    assert main(args) == 1
    with closing(connect(db)) as conn:
        assert setting(conn, "archive_bootstrapped") is None
        assert conn.execute("SELECT count(*) FROM live_publications").fetchone()[0] == 0
        post(root, "new-b", shared="new-item", level="B1")
        post(root, "collision")
        post(root, "collision", nested=True)
        groups.write_text(json.dumps({"known-group": ["/articles/collision/"]}))
        sitemap(fixture, "new", "new-b", "collision")
        assert not sync_archive(conn, output=root, fixture=fixture, legacy=groups,
                                bootstrap_epoch=NOW, now=NOW)["ready"]


def test_manual_alias_hold_keeps_verified_clock_and_editor_can_link(tmp_path):
    root, fixture, groups = (tmp_path / x for x in ("posts", "map.xml", "groups.json"))
    post(root, "historical", shared="old")
    groups.write_text(json.dumps({"audited": ["/articles/historical/"]}))
    sitemap(fixture, "historical")
    with closing(connect(tmp_path / "db")) as conn:
        kwargs = dict(output=root, fixture=fixture, legacy=groups)
        sync_archive(conn, **kwargs, bootstrap_epoch=NOW-1, now=NOW-1)
        conn.execute("""INSERT INTO stories(id,title,first_seen,updated_at,model_score)
                        VALUES('candidate','Spandau housing',?,?,8)""", (NOW-10, NOW-9))
        post(root, "spandau", shared="manual-id")
        post(root, "spandau-housing", shared="manual-id", level="B1")
        sitemap(fixture, "historical", "spandau", "spandau-housing")
        result = sync_archive(conn, **kwargs, now=NOW)
        assert not result["ready"] and result["issues"][-1]["candidate_id"] == "candidate"
        assert setting(conn, "fallback_epoch") == str(NOW)
        assert conn.execute("SELECT verified_at FROM live_publications WHERE story_id='manual-id'").fetchone()[0] == NOW
        resolve_archive(conn, live_id="manual-id", candidate_id="candidate", outcome="same", actor="human")
        assert sync_archive(conn, **kwargs, now=NOW+10)["ready"]
        assert conn.execute("SELECT status FROM stories WHERE id='candidate'").fetchone()[0] == "covered"
        assert not record_publication(conn, story_id="candidate", publication_key="later-proof",
                                      verified_at=NOW+10, origin="manual")
        assert conn.execute("SELECT story_id FROM publication_keys WHERE publication_key='later-proof'").fetchone()[0] == "manual-id"
        assert setting(conn, "fallback_epoch") == str(NOW)


def test_collision_at_july_path_with_different_claimants_blocks(tmp_path):
    from scripts.editorial.archive import COLLISION_SLUG

    root, fixture = tmp_path / "posts", tmp_path / "map.xml"
    post(root, COLLISION_SLUG)
    post(root, COLLISION_SLUG, nested=True)
    post(root, "verified-a", shared="pair")
    post(root, "verified-b", shared="pair", level="B1")
    sitemap(fixture, COLLISION_SLUG, "verified-a", "verified-b")
    with closing(connect(tmp_path / "db")) as conn:
        result = sync_archive(conn, output=root, fixture=fixture, now=NOW, bootstrap_epoch=NOW)
        assert not result["ready"]
        assert {"path": f"/articles/{COLLISION_SLUG}/", "issue": "collision"} in result["issues"]


def test_sync_started_before_control_change_cannot_enable_dispatch(tmp_path, monkeypatch):
    root, fixture, db = tmp_path / "posts", tmp_path / "map.xml", tmp_path / "db"
    post(root, "pair-a", shared="pair")
    post(root, "pair-b", shared="pair", level="B1")
    sitemap(fixture, "pair-a", "pair-b")
    with closing(connect(db)) as conn, closing(connect(db)) as operator:
        options = dict(output=root, fixture=fixture, now=NOW)
        sync_archive(conn, **options, bootstrap_epoch=NOW-100)
        dispatch.configure(operator, paused=True, now=NOW)
        read_paths = archive.live_paths

        def resume_while_reading(path):
            dispatch.configure(operator, paused=False, now=NOW)
            return read_paths(path)

        with monkeypatch.context() as context:
            context.setattr(archive, "live_paths", resume_while_reading)
            assert sync_archive(conn, **options)["ready"]
        assert dispatch.tick(conn, now=NOW)["reason"] == "reconcile-after-control-change"
        assert sync_archive(conn, **options)["ready"]
        assert dispatch.tick(conn, now=NOW)["state"] == "idle"

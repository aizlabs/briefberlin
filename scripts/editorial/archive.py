"""Join local edition claims to the live sitemap and the researched legacy groups."""

import json
import re
import sqlite3
import time
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .db import ROOT, transaction
from .http import Client, Gap
from .matching import words

ORIGIN = "https://briefberlin.de"
SITEMAP = ORIGIN + "/sitemap.xml"
LEGACY = Path(__file__).with_name("archive_editions_v1.json")
ARTICLE_PATH = re.compile(r"/articles/[\w-]+/(?:[a-z]{2}(?:-[a-zA-Z]+)?/)?")
COLLISION_SLUG = "090000-neues-viertel-an-der-spree-geplant-a2"
COLLISION_PATH = f"/articles/{COLLISION_SLUG}/"
COLLISION_FILES = {
    f"_posts/2026-07-{day:02d}-{COLLISION_SLUG}.md":
    int(datetime(2026, 7, day, 9, tzinfo=timezone.utc).timestamp())
    for day in (4, 6)
}
STORY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}")


def setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str | int) -> None:
    conn.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))


def record_publication_tx(conn: sqlite3.Connection, *, story_id: str, publication_key: str,
                          verified_at: int | None, origin: str) -> bool:
    """Record one established live story within the caller's write transaction."""
    if not conn.in_transaction:
        raise ValueError("verified publication requires a write transaction")
    if origin not in {"archive-bootstrap", "manual", "automatic", "archive-observed"}:
        raise ValueError("unknown publication origin")
    if (not publication_key or (verified_at is None and origin != "archive-bootstrap")
            or (verified_at is not None and (type(verified_at) is not int or verified_at <= 0))):
        raise ValueError("invalid verified publication identity or time")
    alias = conn.execute("SELECT live_id FROM archive_comparisons WHERE candidate_id=? AND outcome='same'",
                         (story_id,)).fetchone()
    if alias:
        story_id = alias[0]
    owner = conn.execute("SELECT story_id FROM publication_keys WHERE publication_key=?",
                         (publication_key,)).fetchone()
    if owner and owner[0] != story_id:
        raise ValueError("publication key already belongs to another story")
    exists = conn.execute("SELECT 1 FROM live_publications WHERE story_id=?", (story_id,)).fetchone()
    if exists:
        conn.execute("INSERT OR IGNORE INTO publication_keys VALUES(?,?)", (publication_key, story_id))
        return False
    conn.execute("INSERT INTO live_publications(story_id,publication_key,verified_at,origin) "
                 "VALUES(?,?,?,?)", (story_id, publication_key, verified_at, origin))
    conn.execute("INSERT INTO publication_keys VALUES(?,?)", (publication_key, story_id))
    conn.execute("DELETE FROM evidence_holds WHERE story_id=?", (story_id,))
    conn.execute("UPDATE stories SET status='live' WHERE id=?", (story_id,))
    if origin != "archive-bootstrap" and verified_at is not None:
        set_setting(conn, "fallback_epoch", max(verified_at, int(setting(conn, "fallback_epoch") or 0)))
    return True


def record_publication(conn: sqlite3.Connection, *, story_id: str, publication_key: str,
                       verified_at: int, origin: str) -> bool:
    with transaction(conn):
        return record_publication_tx(conn, story_id=story_id, publication_key=publication_key,
                                     verified_at=verified_at, origin=origin)


def article_path(raw: str) -> str | None:
    if not isinstance(raw, str):
        return None
    if raw.startswith("/") and not raw.startswith("//"):
        raw = ORIGIN + raw
    parsed = urlsplit(raw)
    if (parsed.scheme == "https" and parsed.netloc == "briefberlin.de" and not parsed.query
            and not parsed.fragment and ARTICLE_PATH.fullmatch(parsed.path)):
        return parsed.path
    return None


def live_paths(fixture: Path | None) -> set[str]:
    if fixture:
        data = fixture.read_bytes()
    else:
        try:
            data = Client()(SITEMAP, {}).body
        except Gap as exc:
            raise ValueError(f"archive sitemap unavailable: {exc}") from None
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("invalid sitemap XML") from exc
    if root.tag.split("}")[-1] != "urlset":
        raise ValueError("expected an edition sitemap urlset")
    paths = {path for loc in root.findall("./{*}url/{*}loc") if loc.text
             and loc.text.strip().startswith(ORIGIN + "/")
             and (path := article_path(loc.text.strip()))}
    if not paths:
        raise ValueError("sitemap contains no live BriefBerlin editions")
    return paths


def metadata(post: Path) -> dict:
    with post.open(encoding="utf-8") as stream:
        if stream.readline().strip() != "---":
            raise ValueError("missing front matter")
        lines = []
        for line in stream:
            if line.strip() == "---":
                obj = yaml.safe_load("".join(lines))
                if isinstance(obj, dict):
                    return obj
                break
            lines.append(line)
    raise ValueError("incomplete front matter")


@dataclass
class Edition:
    path: str
    title: str
    level: str
    lang: str
    base: str
    explicit_id: str | None
    topics: list[str]
    summary: str
    published: int
    file: str


def claims(output: Path, issues: list[dict]) -> dict[str, list[Edition]]:
    found: dict[str, list[Edition]] = defaultdict(list)
    for post in sorted(output.glob("**/_posts/*.md")):
        if any(part.startswith((".", "_site")) for part in post.relative_to(output).parts):
            continue
        try:
            meta = metadata(post)
            # Jekyll collapses punctuation in :title (including old double hyphens).
            slug = re.sub(r"[^\w]+", "-", re.sub(r"^\d{4}-\d\d-\d\d-", "", post.stem).lower()).strip("-")
            path = article_path(meta.get("permalink", f"/articles/{slug}/"))
            links = meta.get("translations") or {}
            title, level = meta.get("title"), meta.get("level", "unspecified")
            shared = meta.get("story") or meta.get("story_id")
            if (not path or not isinstance(links, dict) or not isinstance(title, str)
                    or level not in {"A2", "B1", "unspecified"} or (shared is not None and
                    (not isinstance(shared, str) or not STORY_ID.fullmatch(shared)))):
                raise ValueError("invalid edition identity")
            when = meta.get("date")
            if isinstance(when, date) and not isinstance(when, datetime):
                when = datetime.combine(when, datetime.min.time())
            if not isinstance(when, datetime):
                when = datetime.fromisoformat(re.sub(r"\s+([+-]\d\d)", r"\1", str(when)))
            epoch = int((when if when.tzinfo else when.replace(tzinfo=timezone.utc)).timestamp())
            topics = meta.get("topics") or []
            if not isinstance(topics, list):
                topics = []
            base = Edition(path, title, level, "de", path, shared, [str(t) for t in topics],
                           str(meta.get("summary") or meta.get("description") or ""), epoch, post.relative_to(output).as_posix())
            found[path].append(base)
            for lang, url in links.items():
                expected = path if lang == "de" else f"{path}{lang}/"
                if article_path(url) != expected:
                    issues.append({"path": str(post.relative_to(output)), "issue": "translation-path-mismatch"})
                elif lang != "de":
                    found[expected].append(Edition(expected, title, level, lang, path, shared,
                                                    base.topics, base.summary, epoch, base.file))
        except (ValueError, TypeError, yaml.YAMLError) as exc:
            issues.append({"path": str(post.relative_to(output)), "issue": "invalid-front-matter",
                           "detail": type(exc).__name__})
    return found


def audited_collision(path: str, editions: list[Edition]) -> bool:
    return (path == COLLISION_PATH and len(editions) == 2
            and {ed.file: ed.published for ed in editions} == COLLISION_FILES
            and all(ed.title == "Neues Viertel an der Spree geplant" and ed.level == "A2"
                    and ed.explicit_id is None and ed.lang == "de" for ed in editions))


def archive_comparisons(conn: sqlite3.Connection) -> list[dict]:
    pairs = [dict(r) for r in conn.execute("""SELECT a.live_id,l.title AS live_title,
        a.candidate_id,c.title AS candidate_title,c.summary AS candidate_summary FROM archive_comparisons a
        JOIN stories l ON l.id=a.live_id JOIN stories c ON c.id=a.candidate_id
        WHERE a.outcome IS NULL ORDER BY a.live_id,a.candidate_id""")]
    for pair in pairs:
        pair["live_urls"] = [ORIGIN + row[0] for row in conn.execute(
            "SELECT path FROM editions WHERE story_id=? AND lang='de' ORDER BY path", (pair["live_id"],))]
        pair["candidate_sources"] = [dict(row) for row in conn.execute(
            "SELECT fact,attribution,url FROM story_evidence WHERE story_id=? "
            "ORDER BY recorded_at DESC,revision_id DESC LIMIT 4", (pair["candidate_id"],))]
    return pairs


def resolve_archive(conn: sqlite3.Connection, *, live_id: str, candidate_id: str, outcome: str,
                    actor: str, now: int | None = None) -> dict:
    if outcome not in {"same", "distinct"} or not actor.strip():
        raise ValueError("archive resolution requires an editor and same or distinct")
    with transaction(conn):
        row = conn.execute("SELECT outcome FROM archive_comparisons WHERE live_id=? AND candidate_id=?",
                           (live_id, candidate_id)).fetchone()
        if row is None or (row[0] is not None and row[0] != outcome):
            raise ValueError("unknown or already resolved archive comparison")
        if row[0] is None:
            if outcome == "same":
                if conn.execute("SELECT 1 FROM live_publications WHERE story_id=?", (candidate_id,)).fetchone():
                    raise ValueError("candidate already has a verified publication")
                conn.execute("UPDATE stories SET status='covered' WHERE id=?", (candidate_id,))
                conn.execute("DELETE FROM evidence_holds WHERE story_id=?", (candidate_id,))
            conn.execute("UPDATE archive_comparisons SET outcome=?,actor=?,resolved_at=? "
                         "WHERE live_id=? AND candidate_id=?", (outcome, actor, int(time.time()) if now is None
                                                               else now, live_id, candidate_id))
    return {"live_id": live_id, "candidate_id": candidate_id, "outcome": outcome}


def compare_manual_story(conn: sqlite3.Connection, live_id: str, items: list[Edition]) -> None:
    # A translation or simplified title can differ from the intake wording. Include the
    # original source text and edition topics when screening for a possible duplicate.
    titles = words(" ".join(e.title for e in items if e.lang == "de"))
    live_words = titles | words(" ".join(e.summary + " " + " ".join(e.topics) for e in items))
    for row in conn.execute("""SELECT s.id,s.title,s.summary,s.entities,s.place,
        group_concat(r.title || ' ' || r.evidence,' ') AS sources FROM stories s
        LEFT JOIN story_evidence e ON e.story_id=s.id LEFT JOIN report_revisions r ON r.id=e.revision_id
        WHERE s.status NOT IN ('live','covered','declined','skipped','expired') AND s.id<>?
        GROUP BY s.id""", (live_id,)):
        context = words(" ".join(str(value or "") for value in tuple(row)[1:]))
        identifiers = words(" ".join(row[k] or "" for k in ("title", "entities", "place")))
        if titles & identifiers or len(live_words & context) >= 2:
            conn.execute("INSERT OR IGNORE INTO archive_comparisons(live_id,candidate_id) VALUES(?,?)",
                         (live_id, row["id"]))


def sync_archive(conn: sqlite3.Connection, *, output: Path = ROOT / "output", fixture: Path | None = None,
                 bootstrap_epoch: int | None = None, known_live_story: str | None = None,
                 known_live_epoch: int | None = None, now: int | None = None, legacy: Path = LEGACY) -> dict:
    """Network and file reads precede reconciliation. A failed refresh inhibits dispatch."""
    now = int(time.time()) if now is None else now
    token = uuid.uuid4().hex
    with transaction(conn):
        control_generation = setting(conn, "dispatch_control_generation")
        set_setting(conn, "archive_sync_token", token)
        set_setting(conn, "archive_ready", 0)
    live = live_paths(fixture)
    issues: list[dict] = []
    local = claims(output, issues)
    mapping = json.loads(legacy.read_text(encoding="utf-8"))
    group_for = {path: group for group, paths in mapping.items() for path in paths}
    explicit: dict[str, set[str]] = defaultdict(set)
    for path in live & local.keys():
        for ed in local[path]:
            if ed.explicit_id and path in group_for:
                explicit[group_for[path]].add(ed.explicit_id)

    groups: dict[str, list[Edition]] = defaultdict(list)
    blocking = False
    for path in sorted(live | local.keys()):
        editions = local.get(path, [])
        if path not in live:
            issues.append({"path": path, "issue": "not-in-sitemap"})
            continue
        if len(editions) != 1:
            issue = "collision" if editions else "unmatched-live-path"
            issues.append({"path": path, "issue": issue})
            # An audited historical collision remains excluded. Unexpected live German
            # identities block dispatch until the repository and site agree.
            if (issue == "collision" and not audited_collision(path, editions)) or (not editions and path.count("/") == 3):
                blocking = True
            continue
        ed = editions[0]
        if ed.base not in live or len(local[ed.base]) != 1:
            issues.append({"path": path, "issue": "ambiguous-or-unverified-base"})
            continue
        group = group_for.get(ed.base)
        ids = explicit[group] if group else set()
        if len(ids) > 1:
            issues.append({"path": path, "issue": "conflicting-shared-ids"})
            blocking = True
            continue
        story_id = ed.explicit_id or next(iter(ids), None) or group
        if not story_id:
            issues.append({"path": path, "issue": "unmapped-live-story"})
            blocking = True
            continue
        groups[story_id].append(ed)
    if not groups:
        raise ValueError("no unambiguous live story matches the local archive")
    with transaction(conn):
        if setting(conn, "archive_sync_token") != token:
            raise ValueError("another archive refresh superseded this snapshot")
        first = setting(conn, "archive_bootstrapped") is None
        seed = bootstrap_epoch
        if first:
            if known_live_story is not None or known_live_epoch is not None:
                if bootstrap_epoch is not None or known_live_story not in groups:
                    raise ValueError("identify exactly one verified live archive story for the initial clock")
                seed = known_live_epoch
            if type(seed) is not int or not 0 < seed <= now:
                raise ValueError("initial archive sync requires an explicit bootstrap epoch or established live epoch")
        if first and blocking:
            return {"ready": False, "bootstrapped": False, "issues": issues}
        created = 0
        for story_id, items in groups.items():
            base = next((e for e in items if e.lang == "de"), None)
            if not base:
                continue
            existing = conn.execute("SELECT status FROM stories WHERE id=?", (story_id,)).fetchone()
            german = {e.path for e in items if e.lang == "de"}
            audit_group = group_for.get(base.path)
            audited_paths = {p for p in mapping.get(audit_group, []) if p.count("/") == 3}
            if audited_collision(COLLISION_PATH, local.get(COLLISION_PATH, [])):
                audited_paths.discard(COLLISION_PATH)
            expected = {path for path, local_items in local.items() if any(
                e.lang == "de" and e.explicit_id == story_id for e in local_items)}
            historical = bool(audit_group and german == audited_paths and expected <= audited_paths)
            if not historical and (not existing or existing[0] != "live"):
                levels = {e.level for e in items if e.lang == "de"}
                if expected - live or not {"A2", "B1"} <= levels:
                    issues.append({"story_id": story_id, "issue": "incomplete-live-editions"})
                    blocking = True
                    continue
            conflicts = [e.path for e in items if conn.execute(
                "SELECT 1 FROM editions WHERE path=? AND story_id!=?", (e.path, story_id)).fetchone()]
            if conflicts:
                raise ValueError("live edition already assigned to another story: " + conflicts[0])
            if existing and existing[0] in {"generating", "deploying"}:
                issues.append({"story_id": story_id, "issue": "awaiting-publication-verifier"})
                blocking = True
                continue
            if not existing:
                conn.execute("""INSERT INTO stories(id,title,summary,entities,first_seen,updated_at,status)
                    VALUES(?,?,?,?,?,?,'live')""",
                             (story_id, base.title, base.summary, json.dumps(base.topics), base.published, now))
            conn.executemany("""INSERT INTO editions VALUES(?,?,?,?,?) ON CONFLICT(path)
                DO UPDATE SET lang=excluded.lang,level=excluded.level,title=excluded.title
                WHERE editions.lang<>excluded.lang OR editions.level<>excluded.level
                   OR editions.title<>excluded.title""", [(e.path, story_id, e.lang, e.level, e.title)
                                                          for e in items])
            bootstrap = first or historical
            verified_at = known_live_epoch if first and story_id == known_live_story else None
            added = record_publication_tx(conn, story_id=story_id, publication_key=f"archive:{story_id}",
                                          verified_at=verified_at if bootstrap else now,
                                          origin="archive-bootstrap" if bootstrap else "archive-observed")
            created += added
            if added and not historical and not existing:
                compare_manual_story(conn, story_id, items)
        for pair in archive_comparisons(conn):
            issues.append({"issue": "possible-manual-duplicate", **pair})
            blocking = True
        if first and not blocking:
            set_setting(conn, "fallback_epoch", max(int(setting(conn, "fallback_epoch") or 0),
                                                    int(seed or 0)))
            set_setting(conn, "fallback_seed_origin", "verified:" + known_live_story
                        if known_live_story else "explicit-bootstrap")
            set_setting(conn, "archive_bootstrapped", now)
        set_setting(conn, "archive_ready", int(not blocking))
        set_setting(conn, "archive_checked_at", now)
        if not blocking and control_generation == setting(conn, "dispatch_control_generation"):
            set_setting(conn, "dispatch_requires_archive", 0)
    return {"ready": not blocking, "bootstrapped": not first or not blocking, "new_ledger_entries": created,
            "matched_stories": len(groups), "issues": issues}

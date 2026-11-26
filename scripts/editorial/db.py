"""Host SQLite state. All timestamps are integer UTC Unix seconds."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Append a tuple of individual statements for each release. DDL and user_version
# commit together; executescript() would implicitly commit the transaction.
MIGRATIONS = [
    (
        """CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
        """CREATE TABLE sources (
            id TEXT PRIMARY KEY, publisher TEXT NOT NULL, scope TEXT NOT NULL,
            active INTEGER NOT NULL CHECK(active IN (0,1)),
            present INTEGER NOT NULL CHECK(present IN (0,1)), metadata TEXT NOT NULL
        )""",
        """CREATE TABLE endpoints (
            id TEXT PRIMARY KEY, registry_key TEXT NOT NULL, url TEXT NOT NULL,
            generation INTEGER NOT NULL DEFAULT 1, adapter TEXT NOT NULL,
            interval_minutes INTEGER NOT NULL, selector TEXT, link_pattern TEXT,
            active INTEGER NOT NULL CHECK(active IN (0,1))
        )""",
        """CREATE INDEX endpoints_family ON endpoints(registry_key, url)""",
        """CREATE TABLE poll_state (
            endpoint_id TEXT NOT NULL REFERENCES endpoints(id), generation INTEGER NOT NULL,
            url TEXT NOT NULL, state_version INTEGER NOT NULL DEFAULT 0,
            next_due INTEGER NOT NULL DEFAULT 0, last_success INTEGER,
            cursor TEXT NOT NULL DEFAULT '{}', failures INTEGER NOT NULL DEFAULT 0,
            last_failure TEXT, baseline_complete INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(endpoint_id,generation)
        )""",
        """CREATE INDEX poll_due ON poll_state(next_due)""",
        """CREATE TABLE source_endpoints (
            source_id TEXT NOT NULL REFERENCES sources(id),
            endpoint_id TEXT NOT NULL REFERENCES endpoints(id), generation INTEGER NOT NULL,
            current INTEGER NOT NULL CHECK(current IN (0,1)),
            PRIMARY KEY(source_id,endpoint_id,generation),
            FOREIGN KEY(endpoint_id,generation) REFERENCES poll_state(endpoint_id,generation)
        )""",
        """CREATE UNIQUE INDEX source_current_endpoint
            ON source_endpoints(source_id) WHERE current=1""",
        """CREATE TABLE source_resources (
            source_id TEXT NOT NULL REFERENCES sources(id), field TEXT NOT NULL,
            url TEXT NOT NULL, purpose TEXT NOT NULL,
            current INTEGER NOT NULL CHECK(current IN (0,1)),
            PRIMARY KEY(source_id,field,url)
        )""",
    ),
    (
        """ALTER TABLE endpoints ADD COLUMN rebaseline_on_activation INTEGER NOT NULL
            DEFAULT 0 CHECK(rebaseline_on_activation IN (0,1))""",
    ),
    (
        """CREATE TABLE reports (
            id INTEGER PRIMARY KEY, url TEXT NOT NULL UNIQUE,
            first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL
        )""",
        """CREATE TABLE report_urls (
            url TEXT PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES reports(id)
        )""",
        """CREATE TABLE report_guids (
            endpoint_id TEXT NOT NULL, generation INTEGER NOT NULL, guid TEXT NOT NULL,
            report_id INTEGER NOT NULL REFERENCES reports(id),
            PRIMARY KEY(endpoint_id,generation,guid),
            FOREIGN KEY(endpoint_id,generation) REFERENCES poll_state(endpoint_id,generation)
        )""",
        """CREATE TABLE report_revisions (
            id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES reports(id),
            content_hash TEXT NOT NULL, title TEXT NOT NULL, evidence TEXT NOT NULL,
            publisher TEXT NOT NULL, published_at INTEGER, source_date TEXT,
            observed_at INTEGER NOT NULL, eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
            UNIQUE(report_id,content_hash)
        )""",
        """CREATE TABLE source_sightings (
            revision_id INTEGER NOT NULL REFERENCES report_revisions(id),
            source_id TEXT NOT NULL REFERENCES sources(id), endpoint_id TEXT NOT NULL,
            generation INTEGER NOT NULL, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
            seen_count INTEGER NOT NULL, PRIMARY KEY(revision_id,source_id,endpoint_id,generation),
            FOREIGN KEY(source_id,endpoint_id,generation)
                REFERENCES source_endpoints(source_id,endpoint_id,generation)
        )""",
        """CREATE TABLE collection_gaps (
            endpoint_id TEXT NOT NULL, generation INTEGER NOT NULL,
            observed_at INTEGER NOT NULL, category TEXT NOT NULL,
            PRIMARY KEY(endpoint_id,generation,category),
            FOREIGN KEY(endpoint_id,generation) REFERENCES poll_state(endpoint_id,generation)
        )""",
        """CREATE TABLE host_cooldowns (host TEXT PRIMARY KEY, until_epoch INTEGER NOT NULL)""",
        """CREATE VIEW editorial_inputs AS
            SELECT v.id AS revision_id,r.id AS report_id,v.title,r.url,v.publisher,
                   v.published_at,v.observed_at,v.evidence,v.eligible
            FROM report_revisions v JOIN reports r ON r.id=v.report_id""",
    ),
]


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """Commit a short write unit, rolling back on stale claims and other errors."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def migrate(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            raise ValueError(f"database schema {version} is newer than this installation")
        for number, statements in enumerate(MIGRATIONS[version:], version + 1):
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {number}")


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open and migrate a host DB; the caller closes the returned connection."""
    if path is None:
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        path = os.environ.get("BRIEFBERLIN_EDITORIAL_DB") or state / "briefberlin/editorial.sqlite3"
    requested = Path(path).expanduser()
    target = requested.resolve()
    public_roots = {(root / "output").resolve() for root in (ROOT, Path.cwd())}
    for candidate in {Path(os.path.abspath(requested)), target}:
        if any(candidate.is_relative_to(root) for root in public_roots) or any(
            (ancestor / "_config.yml").is_file()
            and (ancestor.name == "output" or (ancestor / "_posts").is_dir())
            for ancestor in candidate.parents
        ):
            raise ValueError("editorial database must be outside public output")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(target, timeout=5, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        migrate(conn)
        return conn
    except BaseException:
        conn.close()
        raise

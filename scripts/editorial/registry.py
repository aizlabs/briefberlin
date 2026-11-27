"""Reconcile configured issuers and persistent endpoint identities."""

import json
import sqlite3
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import transaction
from .inventory import DEFAULT_REGISTRY, Source, read_registry, request_url


def active_owners(conn: sqlite3.Connection) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute("""
        SELECT se.endpoint_id, s.id FROM sources s
        JOIN source_endpoints se ON se.source_id=s.id AND se.current=1
        WHERE s.present=1 AND s.active=1
    """):
        owners[row[0]].add(row[1])
    return owners


def _assign_endpoints(
    conn: sqlite3.Connection, groups: dict[tuple[str, str], list[Source]]
) -> dict[tuple[str, str], str]:
    """Reserve unchanged addresses first; split a shared cursor when issuers diverge."""
    existing = list(conn.execute("SELECT id, registry_key, url FROM endpoints ORDER BY id"))
    by_address = {(row["registry_key"], request_url(row["url"])): row["id"] for row in existing}
    assigned = {key: by_address[key] for key in groups if key in by_address}
    reserved = set(assigned.values())
    historic_ids = {row["id"] for row in existing}
    previous: dict[str, set[str]] = defaultdict(set)
    for row in conn.execute("SELECT source_id, endpoint_id FROM source_endpoints WHERE current=1"):
        previous[row["endpoint_id"]].add(row["source_id"])
    for key, members in sorted(groups.items()):
        if key in assigned:
            continue
        family, _ = key
        member_ids = {source.id for source in members}
        # A single issuer (or the whole group) moved. Keep its public ID and
        # create a new generation below. Other issuers retain their old cursor.
        moves = [
            row["id"] for row in existing
            if row["registry_key"] == family and row["id"] not in reserved
            and previous[row["id"]] and previous[row["id"]].issubset(member_ids)
        ]
        endpoint_id = moves[0] if moves else family
        if not moves and (endpoint_id in historic_ids or endpoint_id in reserved):
            endpoint_id = f"{family}@{uuid.uuid4().hex}"
        assigned[key] = endpoint_id
        reserved.add(endpoint_id)
    return assigned


def _store_endpoint(
    conn: sqlite3.Connection, endpoint_id: str, members: list[Source]
) -> int:
    existing = conn.execute("SELECT * FROM endpoints WHERE id=?", (endpoint_id,)).fetchone()
    enabled = [member for member in members if member.active]
    if not enabled and existing is not None:
        # All endpoints start this reload paused. Only an active issuer can replace
        # this endpoint's last effective configuration and advance its generation.
        return int(existing["generation"])
    poll = (enabled[0] if enabled else min(members, key=lambda member: member.id)).poll
    if any(member.poll != poll for member in enabled):
        raise ValueError(f"incompatible active settings for {poll.key}")
    active = bool(enabled) and poll.adapter != "lookup"
    content_config = (poll.url, poll.adapter, poll.selector, poll.link_pattern)
    generation = 1
    if existing is not None:
        old_config = (request_url(existing["url"]), existing["adapter"], existing["selector"],
                      existing["link_pattern"])
        generation = existing["generation"] + int(
            bool(existing["rebaseline_on_activation"]) or old_config != content_config
        )
        if existing["interval_minutes"] != poll.interval:
            conn.execute("""
                UPDATE poll_state SET state_version=state_version+1,
                    next_due=CASE WHEN failures=0 AND last_success IS NOT NULL
                        THEN last_success + ? ELSE next_due END
                WHERE endpoint_id=? AND generation=?
            """, (poll.interval * 60, endpoint_id, generation))
    conn.execute("""
        INSERT INTO endpoints(id,registry_key,url,generation,adapter,interval_minutes,
                              selector,link_pattern,active) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET url=excluded.url,generation=excluded.generation,
            adapter=excluded.adapter,interval_minutes=excluded.interval_minutes,
            selector=excluded.selector,link_pattern=excluded.link_pattern,active=excluded.active,
            rebaseline_on_activation=0
    """, (endpoint_id, poll.key, poll.url, generation, poll.adapter, poll.interval,
          poll.selector, poll.link_pattern, active))
    conn.execute("""
        INSERT INTO poll_state(endpoint_id,generation,url) VALUES(?,?,?)
        ON CONFLICT(endpoint_id,generation) DO NOTHING
    """, (endpoint_id, generation, poll.url))
    return generation


def _store_source(
    conn: sqlite3.Connection, source: Source, endpoint_id: str, generation: int
) -> None:
    conn.execute("""
        INSERT INTO sources(id,publisher,scope,active,present,metadata) VALUES(?,?,?,?,1,?)
        ON CONFLICT(id) DO UPDATE SET publisher=excluded.publisher,scope=excluded.scope,
            active=excluded.active,present=1,metadata=excluded.metadata
    """, (source.id, source.publisher, source.scope, source.active, source.metadata))
    conn.execute("UPDATE source_endpoints SET current=0 WHERE source_id=? AND current=1", (source.id,))
    conn.execute("""
        INSERT INTO source_endpoints(source_id,endpoint_id,generation,current) VALUES(?,?,?,1)
        ON CONFLICT(source_id,endpoint_id,generation) DO UPDATE SET current=1
    """, (source.id, endpoint_id, generation))
    conn.execute("UPDATE source_resources SET current=0 WHERE source_id=? AND current=1", (source.id,))
    conn.executemany("""
        INSERT INTO source_resources(source_id,field,url,purpose,current) VALUES(?,?,?,?,1)
        ON CONFLICT(source_id,field,url) DO UPDATE SET purpose=excluded.purpose,current=1
    """, [(source.id, field, url, purpose) for field, url, purpose in source.resources])


def sync_registry(conn: sqlite3.Connection, path: Path = DEFAULT_REGISTRY) -> None:
    sources = read_registry(Path(path))
    groups: dict[tuple[str, str], list[Source]] = defaultdict(list)
    for source in sources:
        groups[source.poll.key, source.poll.url].append(source)
    with transaction(conn):
        before = active_owners(conn)
        # Paused or removed issuers retain their current link. A cursor with no
        # remaining owner was abandoned by a move or merge. Even if it is then
        # attached to a paused group, its next activation needs a fresh baseline.
        conn.execute("""
            UPDATE endpoints SET rebaseline_on_activation=1 WHERE rebaseline_on_activation=0
            AND NOT EXISTS (SELECT 1 FROM source_endpoints se
                            WHERE se.endpoint_id=endpoints.id AND se.current=1)
        """)
        assigned = _assign_endpoints(conn, groups)
        conn.execute("UPDATE sources SET present=0 WHERE present=1")
        conn.execute("UPDATE endpoints SET active=0 WHERE active=1")
        for key, members in groups.items():
            endpoint_id = assigned[key]
            generation = _store_endpoint(conn, endpoint_id, members)
            for member in members:
                _store_source(conn, member, endpoint_id, generation)
        after = active_owners(conn)
        for endpoint_id in before.keys() | after.keys():
            if before.get(endpoint_id) != after.get(endpoint_id):
                conn.execute("""
                    UPDATE poll_state SET state_version=state_version+1 WHERE endpoint_id=?
                    AND generation=(SELECT generation FROM endpoints WHERE id=?)
                """, (endpoint_id, endpoint_id))


@dataclass(frozen=True)
class Endpoint:
    endpoint_id: str
    generation: int
    state_version: int
    url: str
    adapter: str
    interval_minutes: int
    selector: str | None
    link_pattern: str | None
    cursor: dict[str, Any]
    baseline_complete: bool
    failures: int


def due_endpoints(
    conn: sqlite3.Connection, *, now: int | None = None, limit: int = 100
) -> list[Endpoint]:
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    rows = conn.execute("""
        SELECT e.id AS endpoint_id,e.generation,p.state_version,e.url,e.adapter,e.interval_minutes,
               e.selector,e.link_pattern,p.cursor,p.baseline_complete,p.failures
        FROM endpoints e JOIN poll_state p ON p.endpoint_id=e.id AND p.generation=e.generation
        WHERE e.active=1 AND p.next_due<=? ORDER BY p.next_due,e.id LIMIT ?
    """, (int(time.time()) if now is None else now, limit))
    return [
        Endpoint(**{**dict(row), "cursor": json.loads(row["cursor"]),
                    "baseline_complete": bool(row["baseline_complete"])})
        for row in rows
    ]


class StaleEndpointError(RuntimeError):
    """The caller must discard this batch; another poll or config reload won."""


def update_poll_state(
    conn: sqlite3.Connection, endpoint: Endpoint, *, next_due: int,
    success_at: int | None = None, cursor: dict[str, Any] | None = None,
    failure: str | None = None, baseline_complete: bool | None = None,
    child_progress: dict | None = None,
) -> None:
    """Update after inserting observations in the same short transaction."""
    if not conn.in_transaction:
        raise RuntimeError("poll state and observations require an explicit transaction")
    if (failure is None) == (success_at is None):
        raise ValueError("provide one of success_at or failure")
    if failure is not None and (cursor is not None or baseline_complete is not None):
        raise ValueError("failed polls must retain cursor and baseline")
    if child_progress is not None:
        if failure is None:
            raise ValueError("child-only progress requires a failed parent")
        cursor = {**endpoint.cursor, "children": child_progress}
    changed = conn.execute("""
        UPDATE poll_state SET state_version=state_version+1,next_due=?,
            last_success=coalesce(?,last_success),cursor=coalesce(?,cursor),
            baseline_complete=coalesce(?,baseline_complete),
            failures=CASE WHEN ? IS NULL THEN 0 ELSE failures+1 END,last_failure=?
        WHERE endpoint_id=? AND generation=? AND state_version=? AND EXISTS(
            SELECT 1 FROM endpoints e WHERE e.id=poll_state.endpoint_id
            AND e.generation=poll_state.generation AND e.active=1)
    """, (next_due, success_at, json.dumps(cursor) if cursor is not None else None,
          baseline_complete, failure, failure, endpoint.endpoint_id, endpoint.generation,
          endpoint.state_version)).rowcount
    if changed != 1:
        raise StaleEndpointError(endpoint.endpoint_id)

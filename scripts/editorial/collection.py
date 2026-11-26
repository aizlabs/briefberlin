"""Collect due public material and atomically acknowledge each endpoint snapshot."""

import hashlib
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field

from . import adapters
from .adapters import Item, Link
from .db import transaction
from .http import Client, Gap, Response, host
from .registry import Endpoint, StaleEndpoint, due_endpoints, update_poll_state

Fetcher = Callable[[str, dict[str, str]], Response]
DAY = 86400


def paused(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM settings WHERE key='collection_paused'").fetchone()
    return bool(row and row[0] == "1")


def set_paused(conn: sqlite3.Connection, value: bool) -> None:
    with transaction(conn):
        if paused(conn) != value:
            conn.execute("INSERT INTO settings VALUES('collection_paused',?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(int(value)),))
            # Discard any batch fetched across a pause/resume boundary.
            conn.execute("UPDATE poll_state SET state_version=state_version+1")


@dataclass
class Batch:
    cursor: dict
    observations: list[tuple[Item, bool, int, int]] = field(default_factory=list)
    gaps: set[str] = field(default_factory=set)
    retry_at: int = 0
    unchanged: bool = False
    parent_failure: str | None = None


def retrieve(ep: Endpoint, fetch: Fetcher, now: int, lookback: int, children: int) -> Batch:
    cursor = dict(ep.cursor)
    batch = Batch(cursor)
    cutoff = cursor.setdefault("baseline_at", now)
    first_floor = cursor.setdefault("baseline_floor", cutoff - lookback * 3600 if lookback else cutoff + 1)
    headers = {header: cursor[key] for header, key in
               (("If-None-Match", "etag"), ("If-Modified-Since", "modified")) if cursor.get(key)}
    prior = cursor.get("children", {})
    queue = {url: dict(task) for url, task in prior.items()}
    try:
        response = fetch(ep.url, headers)
        if response.status == 304:
            if not ep.baseline_complete:
                raise Gap("304 without baseline")
            batch.unchanged = True
        else:
            items: list[Item] = []
            links: list[Link] = []
            item_gaps: set[str] = set()
            if ep.adapter == "feed":
                items, links, item_gaps = adapters.feed(response)
            elif ep.adapter in {"listing", "documents"}:
                links = adapters.listing(ep, response)
            elif ep.adapter == "notice":
                items = [adapters.extract(ep, response)]
            else:
                raise Gap("unsupported adapter")
            for item in items:
                batch.observations.append((item, ep.baseline_complete, first_floor, cutoff))
            if len(links) > adapters.MAX_LINKS:
                item_gaps.add("feed child link limit")
            queue = {url: task for url, task in queue.items() if task["pending"]}
            for link in links[:adapters.MAX_LINKS]:
                task = dict(prior.get(link.url) or {
                    "pending": True, "after_baseline": ep.baseline_complete,
                    "last_attempt": 0, "retry_at": 0,
                })
                task["link"] = asdict(link)
                queue[link.url] = task
            cursor.update(etag=response.etag, modified=response.modified, item_gaps=sorted(item_gaps))
    except Gap as exc:
        batch.parent_failure = str(exc)
        batch.gaps.add(str(exc))
        batch.retry_at = exc.retry_at
    batch.gaps.update(cursor.get("item_gaps", []))
    scheduled = sorted(
        (task for task in queue.values() if task["retry_at"] <= now
         and (task["pending"] or not batch.parent_failure)),
        key=lambda task: (task["last_attempt"], not task["pending"]),
    )
    for task in scheduled[:children]:
        link = Link(**task["link"])
        task["last_attempt"] = now
        try:
            child = fetch(link.url, {})
            if child.status != 200:
                raise Gap("unexpected child status")
            item = adapters.extract(ep, child, link)
        except Gap as exc:
            task.update(pending=True, retry_at=max(now + 300, exc.retry_at), error=str(exc))
            batch.retry_at = max(batch.retry_at, exc.retry_at)
        else:
            batch.observations.append((item, task["after_baseline"], first_floor, cutoff))
            task.update(pending=False, retry_at=0, after_baseline=True)
            task.pop("error", None)
    batch.gaps.update(t["error"] for t in queue.values() if t.get("error"))
    cursor["children"] = queue
    return batch


def save_item(conn: sqlite3.Connection, ep: Endpoint, item: Item, sources: list,
              now: int, after_baseline: bool, floor: int, baseline_at: int) -> tuple[int, int]:
    urls = list(dict.fromkeys(url for url in (item.url, item.alias) if url))
    if not urls:
        raise ValueError("observation requires a public address")
    identity = conn.execute("SELECT report_id FROM report_urls WHERE url=?", (item.url,)).fetchone()
    if not identity and item.alias:
        identity = conn.execute("SELECT report_id FROM report_urls WHERE url=?", (item.alias,)).fetchone()
    if not identity and item.guid:
        identity = conn.execute("SELECT report_id FROM report_guids WHERE endpoint_id=? "
                                "AND generation=? AND guid=?",
                                (ep.endpoint_id, ep.generation, item.guid)).fetchone()
    if identity:
        report_id = identity[0]
        conn.execute("UPDATE reports SET url=CASE WHEN last_seen<=? THEN ? ELSE url END, "
                     "last_seen=max(last_seen,?) WHERE id=?", (now, item.url, now, report_id))
    else:
        report_id = conn.execute("INSERT INTO reports(url,first_seen,last_seen) VALUES(?,?,?)",
                                 (item.url, now, now)).lastrowid
    conn.executemany("INSERT OR IGNORE INTO report_urls VALUES(?,?)", [(url, report_id) for url in urls])
    if item.guid:
        conn.execute("INSERT OR IGNORE INTO report_guids VALUES(?,?,?,?)",
                     (ep.endpoint_id, ep.generation, item.guid, report_id))
    content = f"{item.title}\0{item.evidence}" if ep.adapter == "notice" else item.evidence
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    date = adapters.epoch(item.date)
    ceiling = now if after_baseline else baseline_at
    eligible = bool(date is not None and max(now - 2 * DAY, floor) <= date <= ceiling)
    if ep.adapter == "notice" and after_baseline and identity:
        eligible = True
    inserted = conn.execute("""
        INSERT INTO report_revisions(report_id,content_hash,title,evidence,publisher,published_at,
                                     source_date,observed_at,eligible) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(report_id,content_hash) DO NOTHING
    """, (report_id, content_hash, item.title[:1000], item.evidence[:12000], sources[0]["publisher"],
          date, item.date or None, now, eligible)).rowcount
    revision_id = conn.execute("SELECT id FROM report_revisions WHERE report_id=? AND content_hash=?",
                               (report_id, content_hash)).fetchone()[0]
    conn.executemany("""
        INSERT INTO source_sightings VALUES(?,?,?,?,?,?,1)
        ON CONFLICT(revision_id,source_id,endpoint_id,generation) DO UPDATE SET
            last_seen=max(last_seen,excluded.last_seen),seen_count=seen_count+1
    """, [(revision_id, row["id"], ep.endpoint_id, ep.generation, now, now) for row in sources])
    return inserted, len(sources)


def poll(conn: sqlite3.Connection, ep: Endpoint, fetch: Fetcher, now: int,
         lookback: int, children: int) -> dict:
    sources = list(conn.execute("""
        SELECT s.id,s.publisher FROM source_endpoints se JOIN sources s ON s.id=se.source_id
        WHERE se.endpoint_id=? AND se.generation=? AND se.current=1 AND s.active=1 AND s.present=1
        ORDER BY s.id
    """, (ep.endpoint_id, ep.generation)))
    result = {"endpoint": ep.endpoint_id, "sources": [s["id"] for s in sources], "adapter": ep.adapter,
              "new_revisions": 0, "sightings": 0, "errors": [], "pending": 0, "unchanged": False}
    batch = retrieve(ep, fetch, now, lookback, children)
    with transaction(conn):
        if paused(conn):
            raise StaleEndpoint(ep.endpoint_id)
        pending = [t for t in batch.cursor.get("children", {}).values() if t["pending"]]
        next_due = (now + min(DAY, 60 * 2 ** min(ep.failures, 10)) if batch.parent_failure
                    else now + ep.interval_minutes * 60)
        if pending:
            next_due = min(next_due, max(now + 60, min(t["retry_at"] for t in pending)))
        next_due = max(next_due, batch.retry_at)
        if batch.parent_failure:
            update_poll_state(conn, ep, next_due=next_due, failure=batch.parent_failure,
                              child_progress=batch.cursor["children"] if ep.cursor.get("children") else None)
        else:
            update_poll_state(conn, ep, next_due=next_due, success_at=now,
                              cursor=batch.cursor, baseline_complete=True)
        conn.execute("DELETE FROM collection_gaps WHERE endpoint_id=? AND generation=?",
                     (ep.endpoint_id, ep.generation))
        conn.executemany("INSERT INTO collection_gaps VALUES(?,?,?,?)", [
            (ep.endpoint_id, ep.generation, now, reason) for reason in batch.gaps
        ])
        for item, after_baseline, floor, baseline_at in batch.observations:
            revisions, sightings = save_item(conn, ep, item, sources, now, after_baseline, floor, baseline_at)
            result["new_revisions"] += revisions
            result["sightings"] += sightings
        result.update(errors=sorted(batch.gaps), pending=len(pending), unchanged=batch.unchanged)
    return result


def collect(conn: sqlite3.Connection, *, now: int | None = None, limit: int = 20,
            lookback_hours: int = 0, children: int = 4, fetch: Fetcher | None = None,
            endpoint_ids: Iterable[str] | None = None) -> dict:
    if not 0 <= lookback_hours <= 48 or not 1 <= children <= 16 or not 1 <= limit <= 500:
        raise ValueError("lookback_hours must be 0..48, children 1..16, limit 1..500")
    tick_now = int(time.time()) if now is None else now
    selected = set(endpoint_ids) if endpoint_ids is not None else None

    def check_cooldown(address: str) -> None:
        row = conn.execute("SELECT until_epoch FROM host_cooldowns WHERE host=?", (host(address),)).fetchone()
        current = int(time.time()) if now is None else now
        if row and row[0] > current:
            raise Gap("host Retry-After", row[0])

    client = Client(before_request=check_cooldown)

    def guarded_fetch(url: str, headers: dict[str, str]) -> Response:
        if fetch:
            check_cooldown(url)
        try:
            return (fetch or client)(url, headers)
        except Gap as exc:
            if exc.retry_at:
                # The server's instruction outlives a stale endpoint snapshot.
                with transaction(conn):
                    conn.execute("INSERT INTO host_cooldowns VALUES(?,?) ON CONFLICT(host) "
                                 "DO UPDATE SET until_epoch=max(until_epoch,excluded.until_epoch)",
                                 (host(url), exc.retry_at))
            raise

    rows = []
    for ep in due_endpoints(conn, now=tick_now, limit=500 if selected is not None else limit):
        if paused(conn) or len(rows) >= limit:
            break
        if selected is not None and ep.endpoint_id not in selected:
            continue
        try:
            rows.append(poll(conn, ep, guarded_fetch, tick_now, lookback_hours, children))
        except StaleEndpoint:
            rows.append({"endpoint": ep.endpoint_id, "adapter": ep.adapter, "errors": ["stale snapshot"]})
    return {"paused": paused(conn), "endpoints": rows}

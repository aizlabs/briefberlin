"""Disposable public collection check. Output is aggregate and contains no story text."""

import json
import logging
import os
import sys
import time
import warnings
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from .collection import collect
from .db import connect, transaction
from .registry import sync_registry

SAMPLES = {
    "presse-und-informationsamt-des-landes-berlin-updates",
    "bizim-kiez-updates",
    "polizei-berlin-updates",
    "council-of-the-european-union-updates",
    "landesamt-fur-gesundheit-und-soziales-berlin-updates",
    "s-bahn-berlin-updates",
}


def counts(conn) -> dict:
    return {name: conn.execute(query).fetchone()[0] for name, query in {
        "reports": "SELECT count(*) FROM reports",
        "revisions": "SELECT count(*) FROM editorial_inputs",
        "source_links": "SELECT count(*) FROM source_sightings",
        "sightings": "SELECT coalesce(sum(seen_count),0) FROM source_sightings",
    }.items()}


def snapshot(conn) -> tuple:
    return tuple(tuple(map(tuple, conn.execute(query))) for query in (
        "SELECT revision_id,url,published_at,observed_at FROM editorial_inputs ORDER BY revision_id",
        "SELECT id,report_id,content_hash FROM report_revisions ORDER BY id",
        "SELECT * FROM source_sightings ORDER BY revision_id,source_id,endpoint_id,generation",
        "SELECT endpoint_id,generation,cursor FROM poll_state ORDER BY endpoint_id,generation",
    ))


def revision_sightings(conn) -> dict:
    return {(r["report_id"], r["id"], r["content_hash"]): r["sightings"] for r in conn.execute("""
        SELECT v.report_id,v.id,v.content_hash,sum(s.seen_count) AS sightings
        FROM report_revisions v JOIN source_sightings s ON s.revision_id=v.id GROUP BY v.id
    """)}


def compare_passes(first: dict, second: dict) -> dict:
    original_reports = {key[0] for key in first}
    new = second.keys() - first.keys()
    return {
        "repeated_revisions": sum(second[key] > first[key] for key in first.keys() & second.keys()),
        "new_reports": len({key[0] for key in new} - original_reports),
        "new_revisions_on_existing_reports": sum(key[0] in original_reports for key in new),
        "all_original_revisions_retained": first.keys() <= second.keys(),
    }


def run(state: Path, summary: dict) -> bool:
    now = int(time.time())
    with closing(connect(state)) as conn:
        sync_registry(conn)
        summary["registry_sources"] = conn.execute("SELECT count(*) FROM sources WHERE present=1").fetchone()[0]
        first = collect(conn, endpoint_ids=SAMPLES, now=now, children=2)
        summary["first"] = counts(conn)
        identity = snapshot(conn)
        first_sightings = revision_sightings(conn)
    with closing(connect(state)) as conn:
        summary["reopened"] = counts(conn)
        restored = snapshot(conn) == identity
        # Run the regular due selection a second time without waiting for hour/day cadences.
        # Preserve server Retry-After deadlines and failed endpoint backoff.
        with transaction(conn):
            # Force full feed/notice bodies so a 304 alone cannot pass verification.
            conn.execute("""
                UPDATE poll_state SET next_due=0,
                    cursor=CASE WHEN endpoint_id IN (SELECT id FROM endpoints WHERE adapter IN ('feed','notice'))
                                THEN json_remove(cursor,'$.etag','$.modified') ELSE cursor END
                WHERE last_success IS NOT NULL AND failures=0
            """)
        second = collect(conn, endpoint_ids=SAMPLES, now=int(time.time()), children=2)
        summary["repeat"] = counts(conn)
        comparison = compare_passes(first_sightings, revision_sightings(conn))
    for name, result in (("initial_attempts", first), ("repeat_attempts", second)):
        summary[name] = [{k: v for k, v in row.items() if k != "sources"} for row in result["endpoints"]]
    families = {row["adapter"] for row in first["endpoints"]}
    summary.update(persisted_identity=restored, **comparison)
    return bool(summary["first"]["reports"] and restored and comparison["repeated_revisions"]
                and comparison["all_original_revisions_retained"]
                and families == {"feed", "listing", "notice", "documents"})


def main() -> int:
    summary: dict = {}
    directory = TemporaryDirectory(prefix="briefberlin-collection-")
    path = Path(directory.name)
    ok = False
    try:
        logging.disable(logging.CRITICAL)
        for key in ("TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
            os.environ[key] = str(path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ok = run(path / "state.sqlite3", summary)
    except Exception as exc:
        summary["failure_category"] = type(exc).__name__
    finally:
        try:
            directory.cleanup()
        except OSError as exc:
            summary["cleanup_failure"] = type(exc).__name__
        summary["disposed"] = not path.exists()
        print(json.dumps(summary, sort_keys=True))
    return 0 if ok and summary["disposed"] else 1


if __name__ == "__main__":
    sys.exit(main())

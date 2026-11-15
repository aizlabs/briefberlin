#!/usr/bin/env python3
"""Builds the full failure report for a failed `bb generate` from the pipeline log.

Usage: bb_report.py <log> <exit code> <posts written>
Prints the report. Nothing is summarised away: every warning, error, quality score and
issue in the log is listed in order, plus the traceback and the run's cost.
"""
import json
import re
import sys

log_path, rc, n_posts = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(log_path, encoding="utf-8", errors="replace").read().splitlines()

events, plain, traceback, cost = [], [], [], None
in_tb = False
for raw in lines:
    try:
        rec = json.loads(raw)
        msg, level = str(rec.get("message", "")), str(rec.get("level", ""))
    except (ValueError, AttributeError):
        msg, level = raw, ""
        if raw.startswith("Traceback"):
            in_tb = True
        if in_tb:
            traceback.append(raw)
            continue
        if raw.startswith("| TOTAL"):
            cells = [c.strip() for c in raw.strip("|").split("|")]
            cost = cells[-1] if cells else None
            continue
        if raw.startswith(("Manual pipeline failed", "Error", "error:")) or "rror" in raw[:40]:
            plain.append(raw)
        continue
    if level in ("WARNING", "ERROR", "CRITICAL") or re.search(
        r"Quality check attempt|Regenerat|issues|Passed on|Failed after|Quality gate|Adapting to|Generating .* article|complete:",
        msg,
        re.IGNORECASE,
    ):
        events.append(("⚠️ " if level in ("WARNING", "ERROR", "CRITICAL") else "• ") + msg)

why = []
for e in events:
    if "Quality gate failed" in e:
        why.append(e.lstrip("⚠️• ").strip())
why += plain
if not why and traceback:
    why.append(traceback[-1])
if not why:
    why.append(f"The pipeline exited with code {rc} and wrote {n_posts} of the 2 expected posts.")

out = [f"❌ Generate FAILED (exit code {rc}, {n_posts}/2 posts written). Nothing was published.",
       "Your source text is kept: tap Retry to run it again, or Cancel to delete it.", "",
       "WHY:"] + [f"  {w}" for w in why] + ["", "RUN LOG (steps, scores, issues, warnings):"]
out += [f"  {e}" for e in events] or ["  (no pipeline steps were logged)"]
if traceback:
    out += ["", "TRACEBACK (last lines):"] + [f"  {t}" for t in traceback[-15:]]
if cost:
    out += ["", f"Cost of this run: {cost}"]
out += ["", f"Full log: {log_path}"]
print("\n".join(out))

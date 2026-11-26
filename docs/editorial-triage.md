# Archive and triage on the installed host

Run from the checked-out repository, with the state path configured as described in [the collection guide](editorial-collection.md). Use the installed command or `uv run python -m scripts.editorial`. Host-only verification:

```sh
uv run pytest tests/test_editorial_archive.py tests/test_editorial_triage.py
briefberlin-editorial archive-sync --output output --bootstrap-epoch "$(date +%s)"
briefberlin-editorial triage-claim --owner "tick-$HOSTNAME-$$" --lease-seconds 600
briefberlin-editorial triage-decide --token "$TOKEN" --model "$MODEL_VERSION" < "$PRIVATE_DECISION_FILE"
briefberlin-editorial triage-status
briefberlin-editorial triage-resolve --owner "$EDITOR_ID" --revision "$REVISION" --compare "$STORY_ID"
briefberlin-editorial triage-rate --actor "$EDITOR_ID" --story "$STORY_ID" --rating 8 --note "Confirmed" --action-id "$ACTION_ID"
```

Initialize the archive before the first discovery poll. Use the explicit bootstrap epoch only when the last verified live time is unknown. With independent evidence use `--known-live-story ID --known-live-epoch UTC_SECONDS` in place of `--bootstrap-epoch`. Later `archive-sync --output output` invocations leave the seed untouched. The post's front-matter date, commit time and sitemap lastmod describe different events from a verified publication. For tests only, supply `--sitemap-fixture PATH` and a separate disposable DB with global `--db PATH`.

The archive returns JSON. Inspect `issues` and require `ready=true` before dispatch. The live sitemap must match at least one local German edition. The importer scans nested posts, reads the shared `story` field and translation URLs, and groups older paths using the versioned November public-edition audit. A legacy standalone issue may have an unspecified reading level. Two July files claim the same public URL. The importer excludes that edition, reports its collision and uses their other unambiguous editions. Unknown live German identities inhibit dispatch. On HTTP/XML or reconciliation failure the CLI exits unsuccessfully and `settings.archive_ready` stays 0. Local claims missing from the live sitemap are reported and withheld.

## Scheduler and publisher interface

In each dispatch tick reconcile active publisher attempts and refresh the archive from a current checkout and the live site. Require both a successful fresh check and `archive_ready=1`. Read `editorial_queue` inside the dispatch transaction. Select pending stories with sufficient evidence, an unexpired `expires_at`, a current deadline, no `needs_review` and the eligible tier. `score` is the editor override when present, otherwise the model score. Bands are 0 (9–10), 1 (7–8), 2 (4–6), 3 (skip). A rate action records feedback separately from approval. Scheduler/review operations retain their own reservation, approval and slot state. For material changes recheck the reserved `evidence_version` and invalidate stale approvals before dispatch. `first_seen` is the original queue age. `updated_at` records the last assessment update. Immutable `model_decisions` retain per-event rationale, impact, timing, source references and model version.

`story_evidence` rows with a positive version belong to the corresponding content version. Select rows with `evidence_version <= reserved_version` for generation. Null versions are additional observations, including corrections and duplicates for frozen publications. In-flight workers must recheck `needs_review` before an irreversible step. For a live story correction, surface the flagged source to the editor. A separate event receives its own ID and `parent_id` with `relationship='follow-up'`.

After verifying expected live edition URLs and identity, call `archive.record_publication(conn, story_id=..., publication_key=..., verified_at=..., origin="manual" or "automatic")`. It opens a short write transaction. Use `record_publication_tx` inside an existing write transaction to update a manifest atomically. A first success records one story and moves the global `settings.fallback_epoch` forward. Repeat checks, translations and later redeploys return false without moving it. Reusing another story's publication key raises an error. An archive bootstrap may have null verified time. A newly observed out-of-band publication uses the observation time. Active generating/deploying stories wait for the publication verifier.

## Held-out historical replay

Keep each event, its related editions and wire copies in a single partition. Withhold these events from the model's rubric examples. During evaluation use just the contemporaneous source excerpt and date; compare outcomes afterward. Use a disposable host database.

| Case | Evaluation |
|---|---|
| 21 November 2026. All lifts at a Berlin library failed and a popular reading salon closed. Two reports repeat the operator; a later notice announces reopening. | Recognise the closure as a distinctive local access consequence. Attach the repeated claim and retain its origin. Treat reopening as a linked follow-up. Use no preset numerical gold label. |
| 25 November 2026. Spandau's music school announces an Advent concert. | Evaluate modest district interest and the event date without importing the score for the unrelated Spandau student housing event. [District announcement](https://www.berlin.de/ba-spandau/aktuelles/pressemitteilungen/2026/pressemitteilung.1743538.php) |
| Synthetic federal rule. A change to household benefits names Berlin eligibility, effective date and local application procedure. Compare a version with only a Berlin press-office address. | Score the explicit Berlin effects on their evidence. Hold or skip unsupported local application. |
| Synthetic replay of a quoted wire interview published by two newsrooms, followed by a dated Berlin agency document contradicting a live fact. | Retain the wire origin on both sightings. Route the material correction to the editor without starting a second publication. |

For a newly observed out-of-band learner story, the archive waits until both A2 and B1 are present and every locally claimed German edition is in the sitemap. A partial live pair yields `incomplete-live-editions` and keeps dispatch inhibited. Historical standalone archive articles retain their actual available editions.


## Recovering a manual publication or insufficient evidence

When a newly verified manual story shares terms with an unpublished candidate, the archive records the live outcome and clock immediately. Dispatch is inhibited until the editor evaluates the possible matches. Run `triage-status` to see each pair under `archive_comparisons`. Inspect the two stories and their sources, then record the decision and refresh the live archive.

```sh
briefberlin-editorial archive-resolve --live "$LIVE_ID" --candidate "$CANDIDATE_ID" --outcome same --actor "$EDITOR_ID"
briefberlin-editorial archive-sync --output output
```

Use `distinct` when the events differ. With `same`, the candidate retains its evidence history and becomes `covered`. Later publication receipts for either identity point to the same verified story. Rechecking a different publication key reserves that key for the verified story without advancing the clock. Every unreviewed pair continues to block dispatch. A failed or non-ready archive sync exits with status 1.

An ambiguous revision appears under `held_cases`. Use `triage-resolve --revision` to retry it after an editor identifies the event. An identified story with insufficient facts appears under `evidence_holds`, with its stable ID, current revision and unresolved question. A later material observation updates that revision and keeps the hold. After the editor evaluates the evidence, run `triage-resolve --owner "$EDITOR_ID" --story "$STORY_ID"`. Submit one `same` or `correction` event for that ID with the new token. Each completed reassessment preserves the original queue age and records the editor and decision. A story still lacking evidence remains held.

An exact syndicated copy returns a `syndicated` claim receipt. All events retain their existing scores and content versions. The new revision and its sightings retain the republishing outlets, with the quote, attribution and explicit wire origin from the earlier decision. For ordinary reports freshness starts at source publication. A changed fixed notice starts at its observation time only after the collector has previously observed different content at the same endpoint and generation. The model may shorten the default 48-hour eligibility window. For a later service end, supply an exact `timing_quote` containing the calendar date and year. The host checks the Berlin date and limits extensions to 90 days from the evidence.

# BriefBerlin editorial discovery implementation plan

Draft for implementation, 26 November 2026. Repository baseline inspected at `origin/main` commit `57c705f`. The [shared source registry](../config/civic_sources.json) contains the 151 November audit entries and eight approved additions from polling, tenant organisations, unions, housing research and event organisers. The registry will evolve independently.

## Delivery and ownership

| Stage | Owner and deliverable | Completion condition |
| --- | --- | --- |
| Build in this repository | Implement discovery, matching, scoring, scheduling decisions, editorial commands, publication integration, migrations, install/update procedures, automated test cases and an operator handover brief. | The change is ready for the owner to review and merge. All business rules and reusable code live in the repository. |
| Permitted local check | Exercise the actual collector and SQLite persistence path against public sources in an isolated temporary directory. | Report aggregate results and adapter gaps, close the database, and remove all local smoke-test state. |
| Merge | The owner merges the reviewed changes to main. | A specific main commit can be supplied to the OpenClaw operator. |
| Finish on the installed OpenClaw machine | Install that commit, resolve paths and capabilities against the installed version, create durable production state, run the test suite, verify skills and operator interactions, exercise deployment recovery, and enable the schedule. | The operator records the installed commit, actual commands, observed results, remaining issues and operating mode. |

The source registry, scoring policy, migrations, test fixtures made for the repository, and handover brief are deliverables. Downloaded reports, test decisions, cursors and the local smoke database are disposable. The existing research workbook is an input to implementation. Start the host database from the registry and the current published archive.

## Editorial contract

BriefBerlin covers changes that matter to people in Berlin, in a form accessible to German learners. This includes housing, everyday costs, transport, schools, health, public decisions, neighbourhood life, culture and distinctive local reporting. A German or international announcement qualifies when the evidence establishes a meaningful Berlin consequence. A Berlin address in a press-office footer establishes little about the event.

| Whole-number score | Decision on a new, current, sufficiently evidenced story |
| --- | --- |
| 9–10 | Tier 0. Dispatch for publication immediately, subject to the normal article quality checks. |
| 7–8 | Tier 1. Queue for the next available 12-hour slot. Publish the highest eligible score. |
| 4–6 | Tier 2. If the slot is open and no Tier 0 or Tier 1 is eligible, ask the editor about one candidate. Publication requires an affirmative decision for that story. |
| 0–3 | Skip. Retain the decision on the host to recognise repeat reports and support calibration. |

Use one global fallback clock. It measures elapsed time since the last successfully live BriefBerlin **story**, including manual publication. The two language levels and their translations count once. Feed arrivals, duplicate sightings, ratings, previews, failed runs and unrelated site redeploys do not move the clock. A Tier 1 candidate arriving shortly before the slot opens can win it. There is no extra 12-hour wait before considering Tier 2.

The Spandau student housing restart is the confirmed early calibration example: **8, Tier 1**. Historical publication is positive evidence of editorial taste. At replay time, judge what a reader and an editor could have known when each source appeared. Present-day age and the fact that we later covered an event would otherwise distort the evaluation.

## Proposed software boundaries

Use OpenClaw for scheduled invocations, LLM judgment, and the editor conversation. Keep durable state and irreversible transitions behind a small Python command interface that all skills share. A skill can be invoked again after a lost reply, so a repeated invocation must be safe.

| Component | Responsibility |
| --- | --- |
| Source registry and collector | Load the current public-source configuration, pick due endpoints, discover new or revised reports, and persist observations. |
| Editorial triage skill | Read the candidate evidence and a shortlist of existing stories. Decide whether it describes the same event, a material follow-up, or a new event. Score eligible stories with the versioned rubric. |
| Queue dispatcher | Apply tier bands and clock rules in SQLite. Reserve at most one fallback for an open slot, dispatch Tier 0 promptly, and create deduplicated review requests for Tier 2. |
| Editor skill | Show the source, Berlin consequence, score and reason. Accept a rating, publish decision, hold or decline for a specific story. OpenClaw owns the editor-facing interaction on the installed host. |
| Story publisher | Run the existing generation and publication steps for one manifest and story ID. Verify the live edition URLs. Reconcile partial success before retrying. |

Proposed repository locations are `config/civic_sources.json` for the directory, `config/editorial_policy.yaml` for intervals and thresholds, a Python package under `scripts/` for the shared operations, and `openclaw/skills/` for skill entry points and their prompt references. Keep the existing manual input configuration in `config/sources.yaml` compatible. Provide one idempotent installer/update path for the shipped skills and a versioned database migration command. Final names can follow existing repository conventions.

### 1. Import and update the source registry

Import the shared JSON inventory. Preserve its source IDs and assign durable endpoint IDs so a rename or URL change preserves history. Enrich the seed records with jurisdiction, topics, active status and adapter settings as needed. Each endpoint carries its URL, purpose, adapter, cadence and verification status. Several institutions can share an endpoint. Fetch it once while keeping each attribution. A source can have a working RSS feed, a press-office contact and a separate document archive.

Record the difference between an RSS/Atom feed, an HTML listing, a document index, an operational notice, and a contact or subscription page. For a listing, discovery means following links to individual publications. For a changing service notice at a fixed address, compare the substantive notice after stripping navigation. Keep contacts and lookup-only resources in the directory with clear purposes. Each active discovery endpoint must have a retrieval method or appear in the handover as an explicit coverage gap. Do not manufacture a news item from a changed footer or a subscription form.

An edited registry takes effect on the next configuration reload. Pausing a source stops polls and preserves its history. Adding a source establishes a baseline so its entire archive does not enter the breaking-news queue. A bounded initial freshness window or an explicit historical backfill can be requested separately. Backfilled material is comparison data by default.

### 2. Give reports and stories separate identities

Use one durable SQLite database on local disk on the OpenClaw host. Collectors may fetch in parallel. Use one logical story-matching worker initially and short transactions for reservations and writes. Network and LLM calls happen outside a database write transaction. Enable foreign keys per connection, version the schema, and use SQLite's supported online backup mechanism if the database is live.

| Persistent entity | Key facts and invariants |
| --- | --- |
| Endpoint and cursor | ID, configuration version, next due time, last success, conditional request headers or pagination cursor, recent failures. Advance past a batch only after the observations are durable. |
| Report and revision | Origin endpoint, external ID or canonical URL, publisher, source publication time, first/last seen time, meaningful content hash, extracted evidence. A changed report at a stable URL creates a revision. Multiple feeds can point to the same report. |
| Story | Stable internal ID, description of the event, place, people or organisations, event time, first seen, possible parent story. Store tier and workflow state separately. |
| Story evidence | Links a story to a report revision, attribution and the facts it supplies. A roundup can support several distinct events. |
| Decision and feedback | Model score, evidence version, reason, prompt/model version, editor rating, action and time. Preserve the original assessment when an editor overrides it. |
| Review request and work claim | Story ID, revision, request/slot identity, status, lease owner and expiry. Enforce one active fallback reservation and idempotent handling of responses. |
| Publication and editions | Story ID, manual or automatic origin, generation attempt, manifest, expected edition URLs, commit identity, deployment state, verified live time and any last failure. Repeated checks of the same publication yield one success. |

Store timestamps in UTC and render Berlin-local dates for editorial context. Preserve the publisher's stated timezone and date precision. Freshness uses the publication/update or event evidence. First discovery alone cannot establish that an old document is new.

### 3. Collect, deduplicate and merge

On each tick, fetch due endpoints with bounded per-host concurrency and timeouts. Honour conditional requests, rate limits and backoff. Parse only new or meaningfully revised material. Store short attributed evidence suitable for fact-checking, the public link, and the relevant dates. Keep discovery state outside Jekyll output. Preserve the existing private input boundaries for generation.

Use exact identifiers and hashes first. An unchanged repeat updates the sighting time and costs no LLM call. For semantic matching, retrieve likely candidates from both the pending queue and the published archive across every source category. Start with SQLite text search, named entities, place and event dates. Include long-running events when distinctive identifiers match. Introduce embeddings only if replay shows important misses. The matcher returns a candidate ID from the supplied shortlist or proposes a new story, with the concrete fact that supports its decision. An uncertain match stays in triage until resolved.

Apply the same relevance rubric and tier thresholds to all eight additions and the original inventory. Preserve the origin of each claim. A tenants' initiative announcing a protest and a district office responding to it can supply distinct facts to one pending story. Two newspapers carrying a single dpa dispatch add two sightings of the same reporting. Record the credited wire service and the original interview, document or witness when the attribution is explicit. Repetition alone adds no independent confirmation and does not raise the score.

| Existing state | Arrival that describes the same event |
| --- | --- |
| Pending Tier 0, 1 or 2 | Attach the evidence. Keep the original queue age. Re-score if a fact changes the editorial case. An unchanged duplicate cannot overturn an editor's decision. |
| Awaiting Tier 2 approval | Add the report. Keep one review request. If facts materially change what the editor would approve, supersede the old revision. |
| Generating or deploying | Attach the sighting to the same story. Freeze the evidence version used for the draft. Recheck any material correction before push. A simple repeat never launches another job. |
| Live | Record the source and sighting, then finish. A separate subsequent event, such as a closure being lifted, can become a linked follow-up with its own score. A correction to a published fact goes to editorial review. |
| Declined, skipped or expired | Preserve the previous disposition for a repeat. A substantive new development can re-enter triage with its relationship documented. |

Bootstrap the published-story ledger from the current archive before the first live poll. Use the post's shared story identifier where available. For legacy posts reconcile date, edition, headline and the live sitemap. The audit found nested historical posts and a shared public URL, so scanning only the top-level posts directory is insufficient. Keep ambiguous mappings explicit. Reconcile newly published manual or out-of-band posts before making a fallback decision.

### 4. Score candidates and learn from decisions

Give the model the source evidence and date, the event's publication history, a few relevant editorial examples and the current rubric. Treat fetched text as quoted data. Ask it to identify what happened, who in Berlin is affected, why it matters now, and the evidence for its strongest claim. Consider material changes in cost, access, rights, safety, local life and public decisions. A compelling neighbourhood story can qualify with a small geographic footprint. A national announcement needs a specific Berlin application. Distinguish proposals, adopted decisions and measures already in force.

Require structured output with an integer score from 0 to 10, short rationale, Berlin consequence, what changed, time sensitivity, evidence references and any unresolved factual issue. The application derives the tier mechanically from the score. Evidence sufficiency and expiry are separate eligibility fields, so an incomplete or stale high-scoring item cannot be dispatched automatically. Reject malformed output and retry once with the validation error before retaining it for triage.

The initial calibration set should pair archive positives with real announcements from the same sources that BriefBerlin would usually pass over. Include local human-interest stories, federal rules affecting Berlin households, updates to an old event, narrow district notices and stories about Brandenburg alone. Keep entire events and their editions together when separating development examples from held-out examples.

Provisional anchors include the first official Berlin election result at 10, Spandau student housing at 8, a single school's climbing area at 5, and a Brandenburg-only pay ruling at 2. Spandau is editor-confirmed. The other values remain proposed. When an editor rescores a candidate, store the score and publication decision separately. In particular, raising a Tier 2 score in response to a review request must not silently count as approving it. Offer a distinct “rate and publish” action when both are intended. Review disagreements periodically and release explicit prompt versions so performance can be compared and a change can be rolled back.

### 5. Run the 12-hour dispatcher

1. Reconcile live publications and any reservations whose outcome is uncertain. Process editor responses and fresh evidence. Treat unrelated deployments as housekeeping.
2. If a verified, eligible Tier 0 is available, dispatch it immediately. Concurrent Tier 0 stories can queue behind a busy publication worker in score/freshness order. A manual draft waiting for a human must leave that worker available.
3. Otherwise, when at least 12 elapsed hours have passed since the last live story, reserve the best current Tier 1. Break equal scores by upcoming reader deadline, then freshness, then a stable ID. Recheck the clock and candidate status immediately before committing to the fallback.
4. If the same slot is open with no eligible Tier 1, present one best Tier 2 for approval. If all candidates are stale or skipped, leave the slot open. A decline records the decision. Defer the next Tier 2 suggestion to the configured review cadence to avoid a stream of prompts.
5. A new Tier 0 can supersede a waiting fallback. If a manual publication or a Tier 0 closes the window, mark an outstanding fallback request superseded. An editor can still explicitly publish the item through the manual path. If a fallback push has already succeeded, reconcile it and give the Tier 0 the next available dispatch.

A story pushed at 08:57 and confirmed live at 09:00 starts the clock at 09:00. At 21:00 a Tier 1 first seen at 20:30 is eligible. A confirmed Tier 0 at 16:00 instead moves the fallback to 04:00 the next day. Use elapsed hours across Berlin daylight-saving transitions. Seed the initial clock from the latest established live story. When that time cannot be reconstructed, record an explicit bootstrap time and start a fresh window.

### 6. Integrate publishing and manual review

The present OpenClaw `briefberlin` skill accepts a pasted article, generates A2 and B1, and asks for approval after preview. Its `bb` helper uses one pending file and works out which posts to publish by inspecting a shared Git working tree. Its cleanup and staging operate across output paths. Running a second generation in that tree could mix or delete drafts.

Implement a story-scoped generation workspace, explicit file manifest and publication claim before allowing automatic dispatch. Give the approved automated path its own entry point. Keep the existing manual preview and approval semantics. Both paths write to the same story ledger and share the final push/deploy reconciliation. Before a manual publication that matches a pending automatic story, attach the manual draft to that story ID and suppress the competing dispatch. A manual draft can remain open while an unrelated Tier 0 proceeds.

Reuse `scripts/manual_pipeline.py`, its quality gate, and existing translation, illustration and audio procedures. Map the ledger ID to the A2/B1 story identifier across retries. A partial generation with a single edition remains an incomplete attempt. Use the real publication window for visible dates and News sitemap membership. Source publication dates belong in provenance. Preserve the current site's audio/podcast and optional-media failure policies.

Persist the intended edition URLs and commit identity before an external step can leave an ambiguous result. If push succeeds but the response is lost, inspect the remote commit and expected manifest before attempting another push. After deployment, verify the expected canonical pages and story identity. A later Pages deployment can contain the intended commit. Recheck outstanding publications after restart and close the global clock once per story. An expired worker lease alone is insufficient evidence that a push failed.

### 7. Expose editor actions through OpenClaw

Each review card should carry the immutable story ID and a review revision, headline, score, short rationale, Berlin impact and original source link. Support approve, decline, rate and hold. Record who acted through the configured editor identity on the host. A repeated callback returns the recorded outcome. A late response for a superseded request explains its current status and offers an explicit manual decision. Notification delivery does not count as editorial approval. The existing chat transport can be exercised by the operator on the installed host.

Expose status for last successful poll by source, recent fetch failures, pending stories by tier, oldest pending work, outstanding editor request, latest verified publication and next fallback time. A failure in one feed should leave the other sources progressing. Include separate controls to pause automatic publishing, pause collection, and resume with reconciliation.

## Implementation sequence and acceptance

| Increment | Deliverables | Acceptance evidence |
| --- | --- | --- |
| 1. Registry and database | Load the shared inventory, validate stable IDs and URLs, classify endpoint types, add migrations and a configurable state path. | All 159 seed entries accounted for, including lookup-only entries. Registry reload preserves IDs, retained reports and cursors. |
| 2. Collection | Implement RSS/Atom and the listing, document or service adapters needed by the actual endpoints. Add the local smoke entry point and fetch-status summary. | An actual report persists in temporary SQLite. A repeat fetch records the same item without producing a second candidate. Adapter failures are reported by source. |
| 3. Triage and archive | Build archive bootstrap, candidate retrieval, structured LLM matching and scoring, prompt fixtures and feedback persistence. | Host replay covers exact repeats, cross-agency duplicates, revisions, existing publications, a separate follow-up and editor overrides. Compare score bands with the confirmed examples. |
| 4. Scheduling and editor review | Implement dispatch transactions, global clock, freshness checks, expiring claims, review cards and responses. | Host tests exercise the 12-hour boundary, no eligible candidate, no response, decline, stale response, Tier 0 arrival during review and concurrent ticks. |
| 5. Publication integration | Isolate drafts, reuse generation, record manifests, integrate manual publishing and verify remote/live outcomes. | Host tests cover a waiting manual draft plus an unrelated Tier 0, partial A2/B1 output, crash after push, duplicate callbacks and an unrelated site redeployment. One story receives one live ledger entry. |
| 6. Handover and host activation | Ship skills, installer, host test commands, backup/recovery procedure and a release-specific handover. | Operator verifies scheduling, persistent storage, real OpenClaw skill discovery, model access, editor routing and a controlled publication. Record the activation time and first observed decisions. |

### Local verification and disposal

The future smoke command should create a new temporary directory and explicitly route the SQLite database, WAL/SHM files, caches, extracted text and logs into it. Run the real discovery entry point over representative active endpoints, including a verified RSS feed, an HTML listing and a source outside Berlin. Exercise each implemented adapter family. Reopen the same database to check that report IDs, source links, timestamps and cursors survived. Poll again to check duplicate behaviour. Describe endpoints that failed or were not exercised.

Run this check with generation, editor delivery, Git publication and production scheduling disabled. Close all connections and delete only the smoke directory, including on failure; report a cleanup failure if any files survive. Keep a text summary of counts, error categories and coverage in the handover. Transfer neither the local database nor discovered candidate contents to the host. The tests for the remaining behaviours ship with the repository for execution on the installed machine.

### Contents of the operator handover

The implementer should complete `docs/editorial-discovery-handover.md` against the delivered code and actual merged revision. Include exact install, migrate, import, status, start, stop, backup, restore and rollback commands. Identify the runtime user, state-directory setting, skill paths, model configuration, source registry version, and which credentials the existing publisher expects by name only. Record which checks ran locally and the verified disposal of smoke data.

On the host, install the merged revision and initialise fresh state. Import the live archive, inspect registry coverage, then run collection and editorial decisions in observation mode. Verify OpenClaw can discover and invoke the skills with its installed version. Use a test clock or fixtures for the 12-hour scenarios. Exercise editor approval and refusal in the configured conversation. Verify manual and automated publication, then enable live scheduling under the owner's launch decision. A pause or rollback must preserve sightings, editorial decisions and publication identities for reconciliation.

## Defaults that can be calibrated on the host

No unresolved editorial decision blocks implementation. Use configurable starting values of a five-minute dispatcher tick, 15-minute polls for high-frequency Berlin feeds, hourly polls for slower sources, and daily checks for genuinely low-frequency active listings. Stagger per host. During observation, measure actual publication frequency, duplicate rates, source errors, LLM cost and disagreements with the editor.

Choose candidate expiry from the story's deadline or service end time when known. As a provisional fallback, reconsider unscheduled candidates after 48 hours and retain one Tier 2 suggestion per 12-hour review interval unless the editor asks for another. Reconsideration requires a fresh factual reason to keep an item eligible. The hold duration, polling intervals, model choice and publication-latency target can be tuned without changing the agreed integer tier bands or 12-hour publication rule.

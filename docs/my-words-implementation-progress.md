# Meine Wörter implementation progress

This log records the sequential plan, implementation, and independent review for each phase of [the brief](my-words-implementation-brief.md).

## Phase 1 Storage and word identity

Plan:

1. Add `output/assets/js/my-words-store.js` with a small `BriefBerlin.words` browser API and a CommonJS factory for isolated tests.
2. Normalize identity separately from display content; validate all stored fields and same-origin article URLs, including deployment base paths.
3. Implement read/add/addMany/remove/undo with explicit results, read-before-write, one-write batches, first-save preservation, and notifications only after successful persistence.
4. Refresh subscribers on storage events and page restoration. Preserve corrupt/unsupported data and report access/quota failures.
5. Add dependency-free behavioral tests in `tests/js/my-words-store.test.cjs`, run with `node --test tests/js/*.test.cjs`.
6. Start an independent reviewer after implementation, resolve its findings, then proceed to Phase 2.

Implementation and independent review: completed; results below.

Phase 1 complete: independent reviewer fixed subscriber exception isolation, canonical timestamp validation, malformed batch handling, persisted-field allowlisting, sessionStorage event filtering, and encoded path validation. All 15 storage tests pass.

## Phase 2 Article save flow

Plan:

1. Refactor `glossary-popup.js` to track original glossary membership independently of `BriefBerlin.words` and reconcile all matching marked occurrences.
2. Preserve existing editorial rows; mark only dynamically added rows/sections for removal. Add a single bulk-save control and collection link beside the heading.
3. Wire popup save/remove, batch save, undo, refresh events, and inline error reporting; announce success only after persistence.
4. Add escaped public title/URL and collection URL attributes to `post.html`, and base-path metadata plus store-before-glossary loading in `head/custom.html`.
5. Replace obsolete static assertions in `test_site_layouts.py`; verify behavior in a browser fixture and submit the completed phase to an independent fixing reviewer.

Phase 2 complete: reviewer fixed malformed hint filtering, invalid locale/URL handling, inline undo focus, and original membership preservation. Verified 15 unit tests, 10 site-layout tests, 8 browser tests, and a successful Jekyll build. Browser fixtures explicitly serve UTF-8.

## Phase 3 Collection page and discoverability

Plan:

1. Add the German, noindex, sitemap-excluded `/meine-woerter/` page in `output/_pages/meine-woerter.html` using the existing single-page layout.
2. Add `my-words-page.js`: safe text rendering, German collation/newest sorting, counts, article links, removal with focus recovery, undo, and empty/error states. Retain last good content on read failures.
3. Add a plain navigation entry near Artikel/Niveaus, keeping its German label on translated editions. Load collection JS only on this page.
4. Add scoped CSS for responsive controls, list rows, text actions, popup/status controls, touch targets, and visible focus; preserve unrelated styling.
5. Test the collection against production markup in a local browser fixture, including mobile overflow, sorting, undo, keyboard focus, and failures, then obtain independent verification/fixes.

Phase 3 complete: reviewer fixed cross-tab row/link focus recovery, corrupt-storage handling during removal, and retry focus. Verified 15 unit, 10 layout, and 7 collection-page browser tests. Built page has noindex, is absent from sitemap, and retains German navigation on the English edition.

## Phase 4 CSV and Anki export

Plan:

1. Add pure serializers and a browser download function to `my-words-export.js`. CSV uses five German columns, BOM, CRLF, quoted fields, and formula-like text protection. Anki uses two tab-separated fields and documented separator/HTML/column headers.
2. Escape all Anki text and URLs before adding controlled HTML; quote TSV fields to preserve literal quotes and encode embedded tabs/newlines without extra records.
3. Add a native disclosure export menu and German import guidance to the page. The page supplies its sorted full collection; export rechecks storage and never mutates undo or timestamps.
4. Add Node serializer tests and browser download-content tests; verify synthetic exports with a real spreadsheet application and an isolated Anki collection.
5. Obtain a fresh independent review and fixes before integrated QA.

Phase 4 complete: 22 unit tests, 9 collection browser tests, and the real Anki 26.09.4 importer passed. Excel 16.115 opened the synthetic CSV with all five columns, multiline/quoted text and Unicode intact. Anki created two complete cards and no duplicates on re-import. Real import testing found that localized column headers can map the back field to tags in English Anki; optional column headers were therefore omitted, keeping only separator/HTML headers. The independent reviewer fixed URL cleanup when download DOM setup fails and focus recovery when data changes during export.

## Phase 5 Integrated verification and release readiness

Plan:

1. Extend `tests/test_site_layouts.py` to assert storage-before-glossary ordering, page-only scripts, escaped article metadata, German navigation, and noindex/sitemap/empty-state markup.
2. Add built-site browser checks against a temporary Jekyll destination, covering real generated articles, navigation to the collection, persistence, back navigation, export, keyboard interaction, translated navigation, and narrow layouts.
3. Document repeatable unit/browser/build/Anki test commands without adding production dependencies. Include desktop/mobile screenshots as review evidence outside the published site.
4. Run relevant Python tests, all JS behavior tests, Ruff, and Jekyll; inspect actual screenshots and fix any integration defects.
5. Start a final independent verification/fixing agent, rerun affected checks, and record final evidence. Then create an isolated feature branch and PR containing only this feature.


Phase 5 implementation evidence before final independent review:

- 22 JavaScript unit tests pass (`node --test tests/js/*.test.cjs`).
- 58 targeted Python tests pass (site layouts, publisher sources/translations, language profiles, newsletter pages, site trust).
- Repository-wide Ruff passes.
- Jekyll builds successfully using the installed Ruby 3.4 toolchain; build artifacts stay in `/private/tmp/briefberlin-my-words-site`.
- 20 browser tests pass, including three against real generated Jekyll pages; no page JavaScript errors in the integrated journey.
- Desktop and mobile screenshots inspected. Capture waits for `document.fonts.ready` to avoid transient blank font-rendering captures. Mobile export instructions shortened after visual inspection.
- Browser tests use isolated Chrome/Chromium profiles and local fixture servers. Repeatable commands are in `tests/js/README.md`.
- Real Excel 16.115 CSV read and Anki 26.09.4 import/reimport verified with synthetic vocabulary. Anki verification uses its official import engine in a disposable collection, not a personal profile or UI session.

Final independent review complete: fixed a reproduced mobile popup overflow when error, undo, or cross-tab messages expand the popup. Repositioning now runs after message changes and clamps to the visible viewport. Reviewer reran 22 unit tests, 58 targeted Python tests, 21 browser tests, Ruff, Jekyll, syntax/whitespace checks, and Anki import/reimport successfully.

## Pull request integration

The working checkout is on an older branch. Current `origin/main` contains newer reading-size controls and articles. The feature is being applied to an isolated `codex/my-words-browser-glossary` worktree based on current main; upstream controls/content are preserved. The collection's required generic noindex support is included, without the unrelated 404 page or its styles. Final-main integration verified independently. Two content conflicts were resolved by retaining both upstream reading-size loading/audio tests and the vocabulary additions. The CSS cache version was advanced to include the feature. A browser test now waits for restored article state after navigation and a new regression verifies reading-size preferences coexist with saved vocabulary.

Final branch validation: **22 JavaScript unit tests, 60 targeted Python tests, 22 browser tests**, repository-wide Ruff, Jekyll build, syntax and diff checks all pass. The final reviewer inspected desktop/mobile screenshots and found no further runtime integration issues. The PR contains no unrelated 404 page, generated article, source-input, audio, or reading-size implementation changes.

All five phases and the final-main integration review are complete. The only remaining operational step is opening the requested pull request.

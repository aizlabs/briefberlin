# Meine Wörter implementation brief

Status: implemented in five phases, each independently reviewed and fixed. See [implementation progress](my-words-implementation-progress.md) for verification and integration results.

## Purpose

Readers can save vocabulary while reading BriefBerlin, find it again across visits, and export it for study elsewhere. The feature is entirely browser-side and fits the existing article glossary. It introduces no accounts, backend, external integration, or article-generation work.

This brief is the implementation contract for a minimal release. The phases below are intended to become separate, sequential tasks with independently verifiable outcomes.

## Release scope

- Save individual vocabulary entries through the existing word popup.
- Saving adds the word to the article glossary if absent and makes its marked occurrences bold.
- Save the entire visible glossary with a single button.
- Persist one entry per matching word across articles and visits in the same browser.
- Preserve the exact term, translation, explanation, and first saved public article title/link.
- Provide a dedicated `/meine-woerter/` page with removal and undo.
- Sort alphabetically by default, with a newest-added alternative.
- Export the entire collection as CSV or Anki-compatible text.
- Use German interface text everywhere, including entry points on translated editions.

Excluded: accounts, backend, synchronization between devices, sentence extraction or links, new definitions, AI calls, grammar enrichment, audio, quizzes, review scheduling, search, filters, partial exports, import/restore, bulk deletion, `.apkg` generation, and individual save controls on glossary rows.

Browser storage is not a backup. Clearing site data removes the collection; private browsing may discard it when the private session closes. Serving the site from another origin does not transfer the collection. Offline availability of the website is not part of this feature.

## Existing implementation

- `output/assets/js/glossary-popup.js` parses embedded `.article-glossary-data`, opens word popups, and changes glossary rows and `.article-term--default` styling.
- Its current selection is an in-memory `Set`, initialized from `defaultGlossary`, with no persistence.
- `scripts/publisher.py` already emits vocabulary IDs, terms, English translations, explanations, and `defaultGlossary` flags. Existing IDs are article-local and must not become cross-article word identities.
- `output/_layouts/post.html` has the public article title and URL available through Jekyll.
- `output/_includes/head/custom.html` loads the glossary script.
- Navigation is defined in `output/_data/navigation.yml`; the masthead can translate existing navigation labels.
- Existing static-site checks are in `tests/test_site_layouts.py`. Runtime state and export behavior need behavioral tests, beyond source-text assertions.

The implementation must preserve unrelated working-tree edits. In particular, the head include and shared stylesheet already have local changes when this brief is written.

## Product behavior

### Separate original glossary membership from saved state

The original article glossary is editorial content. The personal collection is explicit user choice. Never initialize the personal collection with all original glossary entries.

| State | Article presentation | Popup |
| --- | --- | --- |
| Original glossary word, not saved | Present in glossary and bold | Wort speichern |
| Additional vocabulary word, not saved | Existing clickable presentation | Wort speichern |
| Saved word available in this article | Present in glossary and bold | Gespeichert ✓ and Entfernen |
| Original glossary word removed from collection | Remains in glossary and bold | Wort speichern |
| Additional word removed from collection | Added row disappears; original styling returns | Wort speichern |

On every article load, derive presentation from original membership plus current saved keys. A saved key matching another article's available vocabulary is saved there too. Reconcile only existing vocabulary metadata and marked occurrences; do not scan arbitrary prose or infer new matches.

Use each article's own definition in its displayed glossary. The personal collection retains the first saved definition. This avoids rewriting editorial content when different articles explain the same term differently.

### Save one word

1. The reader opens the existing word popup.
2. The popup displays its existing term, translation, and explanation.
3. The reader chooses `Wort speichern`.
4. Persist the entry before reporting success.
5. Add a missing glossary row and bold all marked occurrences associated with the matching word.
6. Update the popup to `Gespeichert ✓`, with an `Entfernen` action.
7. Announce the outcome without moving focus, navigating, or opening a modal.

Saving an existing key is a no-op: it does not duplicate the entry, replace its definition/source, or make it newest again. If duplicate article-local metadata entries share a word key, update all matching marked occurrences and render only one added glossary row.

### Save the visible glossary

Place a compact control group beside or beneath the `Vokabeln` heading:

```text
Vokabeln
[ Alle Wörter speichern ]    Meine Wörter →
```

- Save entries currently represented in the displayed glossary, including personally added rows.
- Do not bulk-save the full hidden vocabulary hint payload.
- Deduplicate against existing saved keys and within the batch.
- Persist the batch in one write; do not report partial success.
- When every visible entry is saved, disable the button and show `Alle gespeichert ✓`.
- Recompute this state after saves, removals, undo, and changes from another tab.
- Removing an original glossary word re-enables the button. Removing a personally added word also removes its row, so it no longer belongs to the visible batch.
- Never add save buttons beside individual glossary rows.

If saving a word creates a glossary section, create its controls at the same time. Remove this dynamically created section when its final row disappears. Preserve original glossary headings and content.

If a legacy article lacks usable structured vocabulary metadata, preserve its existing content and do not offer a misleading bulk-save control. Do not parse arbitrary glossary prose into invented structured definitions.

### Removal and undo

Removal is available from the popup and from the collection page. Persist first, then reconcile every affected view. Preserve original glossary words; remove only personally added membership and styling.

Show `Wort entfernt. Rückgängig` in a small accessible status area near the relevant controls. Retain the latest removal for undo until the next successful collection mutation or navigation; sorting and exporting do not invalidate it. Undo restores the complete original entry, including its timestamp and article link. If another tab has already restored the key, do not overwrite that entry.

Keep keyboard focus usable after removing a row: move to the next removal control, the previous one, or the empty-state action as appropriate. The undo control must be keyboard reachable.

## Collection page and navigation

Create `/meine-woerter/` with `lang: de`, the title `Meine Wörter`, and a layout consistent with existing static pages. Keep it out of the sitemap and mark it noindex because its useful content is browser-specific.

Add a plain `Meine Wörter` link in the main navigation, preferably near `Artikel` and `Niveaus`, and another beside article glossaries. The navigation label stays German even when surrounding navigation is translated. Do not add a floating launcher or navigation count badge.

```text
Meine Wörter
12 gespeicherte Wörter

Deine Wörter werden nur in diesem Browser gespeichert.
Wenn du die Websitedaten löschst, wird auch diese Liste gelöscht.

Sortieren: [ Alphabetisch ▾ ]       [ Exportieren ▾ ]

die Genehmigung                                  Entfernen
permission
Eine offizielle Erlaubnis.
Artikel: Neue Regeln für …
```

- Use a simple vertical list and existing typography, spacing, and colors.
- Show the exact saved term, translation, explanation, and linked article title. Omit empty optional text fields without placeholder dashes.
- Use normal same-tab article navigation; no sentence fragments or new-tab behavior by default.
- Display correct singular/plural counts: `1 gespeichertes Wort`, `2 gespeicherte Wörter`.
- Default to `Alphabetisch`, using German-aware collation of the displayed term. Include articles such as `die` in sorting; do not introduce linguistic parsing.
- Offer `Zuletzt hinzugefügt`, sorting descending by original saved time with a deterministic alphabetical tie-breaker.
- Sorting does not mutate entries. Remember the choice only for the current page session in this release.
- Export the full collection in the displayed order; no checkboxes or selection state.
- On mobile, wrap controls and list content without horizontal scrolling.
- Use semantic controls, visible focus, adequate touch targets, and accessible names such as `Genehmigung aus ‚Meine Wörter‘ entfernen` (popup) and `Genehmigung entfernen` (on the Meine Wörter page).

Empty state:

> Noch keine Wörter gespeichert.
>
> Tippe in einem Artikel auf ein Wort und wähle „Wort speichern“. Du kannst auch alle Wörter einer Vokabelliste speichern.

Provide `Zu den Artikeln`. Hide sorting and export controls when empty. Provide a German `<noscript>` message explaining that this feature needs JavaScript; articles remain readable.

## Storage contract

Use `localStorage` with key `briefberlin.myWords.v1`. Store a JSON envelope with `schemaVersion: 1` and an array of entries. Keep the shared storage module independent of page DOM logic.

| Entry field | Contract |
| --- | --- |
| `key` | Stable serialization of language plus normalized term |
| `language` | Vocabulary language, initially `de` |
| `term` | Exact original display term |
| `translation` | Existing translation; mapped from current `english` metadata |
| `explanation` | Existing glossary explanation |
| `articleTitle` | First saved public article title |
| `articleUrl` | First saved public article URL |
| `savedAt` | ISO timestamp from the first successful save |

Identity normalization: Unicode NFC, trim surrounding whitespace, collapse repeated whitespace. Preserve capitalization and punctuation. Do not strip noun articles, stem terms, or merge inflections. `sie` and `Sie` remain distinct; `beantragen` and `beantragt` remain distinct. Identical normalized terms in the same language merge regardless of source article, definition, or CEFR level. Preserve exact display fields separately from the normalized key.

Expose operations equivalent to read, add, add-many, remove, and restore. Return explicit success/error results. Read the latest stored envelope immediately before mutation and perform a single write for each operation. Notify the active document after success and subscribe to the native `storage` event for other tabs. Re-read on page restoration where browser back/forward caching could otherwise leave stale presentation.

This is best-effort coordination across tabs, not transactional synchronization; truly simultaneous writes may race. Do not introduce a database, locking framework, or backend to solve this in the minimal release.

Validation and failure behavior:

- Validate envelope version, field types, timestamps, keys, and public article URLs before use.
- Treat a missing key as an empty collection.
- Treat malformed or unsupported stored data as an error, not an empty collection; preserve the original bytes and disable mutations that could overwrite them.
- Catch storage access and quota failures. Never show `Gespeichert` when the write failed.
- On failure, retain the last valid rendered state and allow a later retry.
- Render saved text with text nodes; never inject stored strings as raw HTML.
- Accept only appropriate same-origin public article URLs, including the configured base path. Do not export private source URLs, drafts, logs, or metrics.

Suggested failure copy:

- Save failure: `Das Wort konnte nicht gespeichert werden. Bitte versuche es erneut.`
- General write failure: `Die Änderung konnte nicht gespeichert werden. Bitte versuche es erneut.`
- Read failure: `Deine gespeicherten Wörter konnten nicht geladen werden. Deine Daten wurden nicht verändert.`

## Export contract

Generate files in the browser with `Blob` and downloadable object URLs; release URLs after use. No upload or server request is involved. Disable export for an empty or unreadable collection.

### CSV

Label: `CSV herunterladen`.

Filename: `briefberlin-meine-woerter-YYYY-MM-DD.csv`, using the reader's local date.

Columns, in order: `Wort`, `Übersetzung`, `Erklärung`, `Artikeltitel`, `Artikel-URL`.

Use UTF-8 with a BOM for common spreadsheet compatibility, comma separators, and consistent row endings. Quote and escape fields correctly, including embedded quotes, separators, and line breaks. Protect spreadsheet consumers from formula-like text, including leading control/whitespace variants, without changing stored values. Document that this export is for external use, not a restore format.

### Anki text

Label: `Für Anki herunterladen`.

Filename: `briefberlin-meine-woerter-YYYY-MM-DD-anki.txt`.

Use UTF-8 tab-separated text with Anki import headers declaring the separator and HTML handling. Target a basic two-field note: term on the front, translation plus explanation plus linked article title on the back. Escape all text before adding controlled HTML for line breaks and the source link. Prevent embedded tabs/newlines in glossary content from creating extra records or columns.

Include short German import guidance near the export controls, identifying the front/back field mapping. Do not force a localized note-type name that may not exist in the reader's Anki installation. Check current import behavior during implementation and validate an actual import before release, including repeated imports of the same file. Export itself never removes words or resets their timestamps.

No `.apkg`, media, review history, account connection, or automatic synchronization in this release.

## Implementation phases

### Phase 1 Storage and word identity

Deliver `output/assets/js/my-words-store.js`, versioned data validation, deduplication, mutations, error results, and change notifications. Use a small site-scoped namespace and plain JavaScript consistent with the existing frontend; no new frontend framework or production bundler.

Add executable unit tests for identity, repeated saves, batch deduplication, timestamp preservation, remove/restore, malformed storage, unsupported schema versions, blocked access, and quota failures. Choose the smallest available JavaScript test harness; keep fixtures under `tests/` and document its execution command.

Exit criterion: persistence behavior is verified independently of the UI, including that failed writes do not produce successful state changes.

### Phase 2 Article save flow

Depends on Phase 1. Refactor `output/assets/js/glossary-popup.js` around original membership and saved keys. Add explicit escaped public title/URL metadata in `output/_layouts/post.html`. Load the storage module before the glossary script in `output/_includes/head/custom.html`.

Deliver popup saving/removal, state restoration, bulk glossary saving, dynamic-section cleanup, undo, and reconciliation after storage events/page restoration. Preserve the existing publisher JSON format; generation changes should not be necessary.

Exit criterion: an additional word can be saved, survive reload, become bold and appear in the glossary, then be removed/undone correctly. Original glossary entries remain intact throughout.

### Phase 3 Collection page and discoverability

Depends on Phases 1 and 2. Add `output/_pages/meine-woerter.html` and `output/assets/js/my-words-page.js`. Update `output/_data/navigation.yml` and add scoped styles to `output/assets/css/custom.css`. Load the collection script only where required.

Deliver the list, counts, both sorting modes, article links, removal/undo, empty/error/no-JavaScript states, and navigation. Preserve German feature labels on translated editions without changing the rest of their existing navigation.

Exit criterion: the collection is usable on desktop and mobile, with keyboard access and correct navigation back to an article.

### Phase 4 CSV and Anki export

Depends on Phases 1 and 3. Add `output/assets/js/my-words-export.js` with pure serialization functions plus the download behavior, and connect it to the collection page export controls.

Test umlauts, non-Latin translations, quotes, commas, tabs, newlines, HTML-like strings, empty optional values, formula-like text, and deterministic ordering. Verify a CSV in a spreadsheet application and the Anki file in Anki, recording the application/version used for the latter.

Exit criterion: both downloads include every saved entry exactly once in the displayed order, preserve usable glossary content and article links, and import correctly in their intended applications.

### Phase 5 Integrated verification and release readiness

Depends on all previous phases. Extend `tests/test_site_layouts.py` for page metadata, script ordering, navigation, and the static page contract. Add browser behavior coverage for the complete user journeys. Run relevant existing site/publisher tests and a Jekyll build; run repository-required checks appropriate to changed code.

Inspect desktop and narrow mobile rendering, keyboard focus, popup positioning, storage failure messages, translated-edition navigation, and back/forward behavior. Confirm that no private input or generated internal artifacts enter the saved collection or exports.

Exit criterion: all acceptance scenarios below pass, evidence and test commands are recorded, and there are no unrelated file changes in the feature diff.

## Acceptance scenarios

1. A fresh browser shows an empty collection even when an article has a default glossary.
2. Saving one additional word adds one row and bolds matching marked occurrences; reload preserves both.
3. Re-saving the same word from the same or another article does not duplicate it or change its first saved definition, link, or timestamp.
4. Saving all stores exactly the visible glossary entries; hidden click-only hints remain unsaved.
5. The save-all button accurately distinguishes partial and complete saved state.
6. Removing an original glossary word leaves the article glossary and bolding unchanged.
7. Removing a personally added word restores the original article presentation; undo restores its full saved record.
8. The collection page sorts correctly in both modes and links to the first saved public article.
9. CSV and Anki exports include all entries exactly once and do not modify the collection.
10. Changes made in one tab appear in another after the storage event; back navigation does not show stale saved state.
11. Blocked/full storage never causes a false success indication. Malformed stored data is not silently overwritten.
12. The feature remains understandable with a keyboard and on a narrow mobile viewport, without horizontal scrolling or intrusive overlays.
13. Feature labels are German on every edition. The saved translation and explanation remain the original glossary content.
14. JavaScript-disabled readers can still read articles and see an explanation on the collection page.

## Completion and follow-up

The minimal release is complete when a reader can save a word, close and reopen the site, find it once in Meine Wörter, revisit its article, export it, and remove or restore it. Personal vocabulary remains entirely in browser storage.

Break the phases into implementation tasks using their dependencies and exit criteria. Any request for sentence context, restore/import, `.apkg`, review exercises, or synchronization should be tracked separately rather than expanding these tasks.

## References

- [MDN localStorage documentation](https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage)
- [Anki text import documentation](https://docs.ankiweb.net/manual/importing/text-files)

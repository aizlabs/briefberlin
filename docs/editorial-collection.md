# Collect public editorial inputs

Use the installed `briefberlin-editorial` command or `python -m scripts.editorial` from the checkout. All commands below use the host state selected by `BRIEFBERLIN_EDITORIAL_DB`. The optional global `--db PATH` overrides it. The fallback is `$XDG_STATE_HOME/briefberlin/editorial.sqlite3` or `~/.local/state/briefberlin/editorial.sqlite3`.

```sh
briefberlin-editorial init
briefberlin-editorial registry-sync
briefberlin-editorial coverage
briefberlin-editorial collect --limit 20 --children 4
briefberlin-editorial collection-pause
briefberlin-editorial collection-resume
```

Sync the registry after editing its source entries. A collection tick fetches due endpoints and emits JSON with source IDs, adapter, new revisions, sightings, pending children, conditional-response status and error categories. A successful JSON result can contain individual source failures. `coverage` includes the current collection pause state, last poll outcomes and adapter gaps. A pause invalidates outstanding poll snapshots.

The first successful poll establishes a baseline. For a new endpoint, an explicit `collect --lookback-hours 12` admits dated evidence from the preceding 12 hours (maximum 48). Undated discoveries remain historical. A substantive change observed on a previously baselined fixed notice can qualify. Inspect `editorial_inputs` for revision-level facts and `source_sightings` for all issuer associations, including publishers that share an endpoint. A sighting can repeat without creating a revision.

Listing adapters follow same-host, dated publication links. Set a registry `selector` and an optional `link_pattern` to narrow ambiguous index pages. A document index follows PDF links and extracts text from the first five pages using Poppler's `pdftotext` on the host PATH. A fixed notice uses its configured content selector. Inaccessible pages, unsupported markup, missing extractors and exhausted request budgets appear in the JSON. Evidence is limited to 12,000 characters per revision. Source dates retain their original text alongside a UTC epoch when parseable. Date-only and timezone-free values use Europe/Berlin.

Each tick is sequential and permits 16 requests per host, counts redirects, and caps each decoded response at 4 MiB. The collector accepts at most three redirects within the source host (including its www alias). Each request has a four-second connect timeout, six-second read timeout and a 25-second deadline checked between chunks. The collector retains undelivered children after an index rotates, and retries them on later due polls. A 304 on an index still allows its children to be checked. More than 250 matching links in one index produces a coverage gap for the operator to narrow.

The collector dates HTML articles from publication metadata or an explicit publication label. A dated link, event time or deadline can identify a listing entry to fetch. These dates do not establish when an article appeared. A feed entry's own published date can date its linked article. Indexed PDFs currently have no publication date unless a future adapter can establish one. Feed titles can vary across issuers while sharing one evidence revision. A fixed notice includes its headline and inline dates and times in the evidence comparison. A moved feed GUID retains its report history and exposes the latest observed canonical address through `editorial_inputs.url`.

Mixed feeds report the position and reason for unreadable entries and retain the usable entries. Undelivered child URLs remain eligible for retry through a failed or empty index response. The endpoint records the index failure even if a child succeeds. The collector persists a server's Retry-After deadline by host as soon as it receives it. Overlapping ticks recheck this deadline before starting each request or redirect.

The local public-source smoke command is `python -B -m scripts.editorial.smoke`. It loads the registry, samples all four adapter families, closes and reopens its temporary SQLite database, polls again, and reports disposal. A passing repeat must add a sighting to an existing report ID, revision ID and content hash. The summary counts newly discovered reports and new revisions of existing reports separately. Sample source failures appear individually. This check exercises collection and persistence only. The host can run the offline cases with `uv run pytest tests/test_editorial_collection.py tests/test_editorial_registry.py`.

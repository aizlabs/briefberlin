# Newsletter Runbook (Brevo daily issue)

Daily German newsletter: signup via a Brevo double-opt-in form embedded on
`/newsletter/`, one issue per day at 07:00 Europe/Berlin, built from
`feed.xml` by `scripts/newsletter_campaign.py` in GitHub Actions.

**Status: daily sending enabled on November 8, 2026.** Production uses the
repository variable `NEWSLETTER_ENABLED=true` and the two active daily cron
slots. The first eligible issue is November 9 at 07:00 Europe/Berlin, provided
there are new stories and the quota/state guards pass. See the launch evidence
and the two incomplete provider checks below; these are not reported as passed.

## Resources (already set up in Brevo / Cloudflare)

| Resource | Value |
| --- | --- |
| Sender | BriefBerlin <newsletter@briefberlin.de> (verified, domain authenticated) |
| Production list | BriefBerlin Täglich, **list ID 3** |
| Test list | BriefBerlin Test, **list ID 4** |
| Forbidden list | Default list **2** (unrelated, never use) |
| Signup form | "BriefBerlin Newsletter", editor: https://app.brevo.com/contact/forms/subscription/edit/6aefa90739d234847dcd4e0a |
| DOI template | ID 4, subject "Bitte bestätige deine Anmeldung bei BriefBerlin" |
| Welcome template | ID 2, subject "Willkommen bei BriefBerlin!" |
| CAPTCHA | Cloudflare Turnstile (Managed), hosts briefberlin.de + sibforms.com |
| Inbound mail | Cloudflare Email Routing: newsletter@ and dmarc@ -> o.zozulya.ch@gmail.com |

## Launch checklist

1. **Form embedded**: the real Brevo iframe is installed in
   `output/_includes/brevo-signup-form.html` with an accessible title and a
   responsive width. Only the public URL is included.
2. **Brevo redirects saved and verified after reload**:
   - Thank-you: `https://briefberlin.de/newsletter/danke/`
   - After confirmation: `https://briefberlin.de/newsletter/bestaetigt/`
   - Default unsubscribe page: German copy/survey and redirect to
     `https://briefberlin.de/newsletter/abgemeldet/` after the survey.
   The default footer flow has an intermediate unsubscribe page/survey;
   do not promise a single-click footer unsubscribe until delivered-mail
   testing confirms the exact experience. Inbox and RFC 8058 acceptance results are recorded below.
3. **Secrets / variables** (GitHub repo settings):
   - Secret `BREVO_API_KEY` - Brevo v3 API key; IP allow-listing must be OFF
     (GitHub runner IPs change every run).
   - `NEWSLETTER_ENABLED=true` enables production; set it to `false` to stop
     future builder runs. Test-list dispatches do not require the gate.
4. **Deploy and verify** using the live acceptance evidence below.
5. **Production schedule**: 03:30 and 04:15 UTC prepare/retry the same 07:00
   Berlin issue. Campaign-name idempotency prevents the retry from duplicating
   an existing issue. GitHub may delay triggers; the builder skips late runs.

## Launch evidence — November 8, 2026

- The owner explicitly authorized completing checks and enabling daily sending.
  The existing Brevo tracking markup is an accepted product limitation; keep
  consent management enabled and unknown-consent tracking disabled.
- Current test sends both succeeded against the approved one-contact test list:
  https://github.com/aizlabs/briefberlin/actions/runs/42509344711 (campaign 9) and
  https://github.com/aizlabs/briefberlin/actions/runs/42509726493 (campaign 10).
  Campaign 9 arrived in Gmail with SPF, DKIM (`briefberlin.de`), DMARC pass,
  both List-Unsubscribe headers, German footer and usable HTML/text alternatives.
  These successful runs supersede the old tag-related failures below.
- API snapshots: before campaign 9, 292 email credits and 8 transactional
  requests; after that one-recipient campaign plus a new DOI/welcome pair,
  289 credits and 10 transactional requests. This verifies all three sends
  consume credits and form-triggered DOI/welcome traffic reaches the abuse
  statistic. Campaign 10 then sent successfully. Reserve: 60; audience: 1.
- Gmail's Unsubscribe control reported success. The delivered RFC 8058 HTTPS
  endpoint was also POSTed with `List-Unsubscribe=One-Click` and returned 200;
  Brevo recorded campaign 9's unsubscribe and Email campaigns Blocklisted.
  These two actions were close together, so their individual propagation
  latency is not established. A fresh form signup delivered a new DOI; after
  confirmation it redirected to `/newsletter/bestaetigt/`, delivered welcome,
  and restored Email campaigns Subscribed. The test contact is left subscribed.
  Inbox one-click has no website redirect; only the footer flow redirects.
- Both forwarding checks reached Cloudflare Email Routing and were recorded
  Forwarded for `newsletter@` and `dmarc@`, to the verified Gmail destination.
  Gmail retained the original Sent messages without a duplicate inbox copy;
  forwarding evidence is Cloudflare's delivery outcome, not a duplicate message.
- Contact campaign statistics showed zero named opens/clicks despite earlier
  message opens and confirmation/unsubscribe use. Pixel/rewrite markup remains
  present. This observation does not prove that every event is anonymous.
- **Incomplete CAPTCHA-specific check:** missing-token and invalid-token POSTs
  both returned HTTP 403 from the provider's browser-signature protection,
  before form validation. They caused no new DOI, but do not demonstrate the
  specific Turnstile validation error. The managed widget remains configured;
  the normal live signup path succeeds. Do not weaken protection to test it.
- **Incomplete consent export check:** the filtered Marketing event export
  completed in Brevo's notification center. The available sample contained
  campaign delivery/unsubscribe events, not the full form-submission journey.
  Transactional logs visibly contain `optin` and `final_confirmation` timestamps.
  CSV download automation failed, so neither the downloaded file nor a complete
  end-to-end DOI audit export is verified. Contact-row export alone is not proof.
  For follow-up, export form events plus transactional logs as described in:
  https://help.brevo.com/hc/en-us/articles/208733449
  Never put these private exports in the public repository or Actions artifacts.

## Earlier acceptance history — November 8, 2026

- PR #21 merged at `974f44b6e79d431735ae3000fb5f4d9cb676e67c`; website
  deployment passed: https://github.com/aizlabs/briefberlin/actions/runs/42440310719
- Test dry-run passed and produced a three-story HTML/text/subject preview:
  https://github.com/aizlabs/briefberlin/actions/runs/42440336490
- Restricted `BriefBerlin GitHub Actions Newsletter` key created after approval
  and saved as repository secret `BREVO_API_KEY`. It expires November 8, 2027
  or after 90 days unused. Scopes: email campaigns All; transactional email,
  contacts and account Read. Production gate remains absent; cron stays off.
- Signup reached `/newsletter/danke/`; list 3 was empty before confirmation.
  German DOI arrived, its link reached `/newsletter/bestaetigt/`, and the
  contact then appeared in list 3. German welcome arrived afterward. Both
  delivered messages had SPF, DKIM (`d=briefberlin.de`) and DMARC pass,
  List-Unsubscribe headers and usable text/plain alternatives. These checks
  do not establish campaign delivery behavior.
- Signup description shortened in Brevo to: “Neue Nachrichten aus Berlin.
  Jeden Morgen um 7 Uhr. Kostenlos und jederzeit abmeldbar.” Verified live.
- **Original no-markup requirement not met (subsequently accepted):** both delivered transactional messages contain `/tr/op/`
  pixels and `/tr/cl/` rewritten links despite consent management Yes and
  unknown-consent tracking No (rechecked in the UI). The delivered campaign
  also includes `/mk/op/` pixels and `/mk/cl/` rewritten links. Do not claim
  no tracking; the original no-tracking requirement is not met.
- **Campaign API refusal diagnosed and fixed:** the first two test-list attempts reached
  `POST /emailCampaigns -> HTTP 405`. No campaign send occurred. Read calls,
  quota and statistics checks preceding creation succeeded. Runs:
  https://github.com/aizlabs/briefberlin/actions/runs/42440935819 and
  https://github.com/aizlabs/briefberlin/actions/runs/42441209161 .
  Creating a UI-only draft `BB-TEST-UI-20261108` (ID 5, no recipients/send) did
  not resolve the API failure. A later diagnostic run returned HTTP 400:
  https://github.com/aizlabs/briefberlin/actions/runs/42441772149 .
  The approved encrypted diagnostic identified the actual refusal: this
  account cannot use the campaign `tag` option. The builder now omits `tag`
  and stores its cutoff in HTML metadata. A no-send API test created the
  campaign (HTTP 201) and verified the metadata survives retrieval:
  https://github.com/aizlabs/briefberlin/actions/runs/42442976102 .
  That diagnostic job intentionally failed at its pre-send guard, so no mail
  was sent. Legacy tag watermarks remain readable. Missing/invalid cutoff
  metadata in the latest sent production campaign now refuses a replay.
  Temporary diagnostic code and workflow routing have been removed. A real
  test send then succeeded (campaign 7, list 4 only) and arrived in Gmail:
  https://github.com/aizlabs/briefberlin/actions/runs/42443120036 .
  SPF, DKIM and DMARC passed; List-Unsubscribe and List-Unsubscribe-Post were
  present. Both MIME alternatives rendered the three-story issue. The first
  send exposed an English provider footer and no unsubscribe URL in the text
  part; the renderer now supplies an explicit German unsubscribe placeholder
  link so the provider-generated text can include the actual URL. The
  corrected send arrived with that German link in both HTML and text/plain,
  and without the English provider unsubscribe sentence:
  https://github.com/aizlabs/briefberlin/actions/runs/42443312933 .
  Its footer link opened the German native unsubscribe page; submitting it
  blocklisted campaign delivery, and the German survey redirected to
  `/newsletter/abgemeldet/`. Gmail displayed its own Unsubscribe control, but
  that separate inbox action has not been exercised. A fresh DOI after this
  campaign unsubscribe restored Subscribed status only after confirmation;
  the test address is left subscribed at the end of acceptance testing.
- **Welcome unsubscribe corrected:** native transactional `{{ unsubscribe }}`
  showed an English sender-unsubscribe page and left campaign status Subscribed.
  A separate German Brevo form `BriefBerlin Abmeldung` was created (editor ID
  `6aefe72939d234847dcd53c2`). Submitting it set campaign status Blocklisted
  and redirected to `/newsletter/abgemeldet/`. Its public URL is now saved in
  the welcome template footer. A fresh delivered welcome contained the new
  public unsubscribe URL in its plain-text part. This manual email-entry form
  is not a one-click promise; campaign/Gmail one-click testing remains pending.
- Resubmission after unsubscribe reached the thank-you page. Sender-level
  transactional suppression from the earlier native-unsubscribe test blocked
  fresh DOI mail. After restoring only the newsletter sender for this approved
  test address, a fresh DOI arrived. Campaign status stayed Blocklisted before
  that click and changed to Subscribed after it; a new welcome then arrived.
- Home usage showed 298/300 credits after the first DOI and welcome sends.
  Later quota, statistics, forwarding and campaign results are in the launch
  evidence above; CAPTCHA-specific rejection and full consent export remain incomplete.

## Operating the builder

```bash
# Preview today's issue (no Brevo traffic at all)
uv run briefberlin-newsletter --dry-run --feed-file output/_site/feed.xml

# Preview against the live feed
uv run briefberlin-newsletter --dry-run

# Send immediately to the TEST list (4) - requires BREVO_API_KEY
BREVO_API_KEY=... uv run briefberlin-newsletter --target test

# Production (list 3) requires NEWSLETTER_ENABLED=true. Targets 07:00 Berlin;
# delayed runs schedule delivery one minute after preparation starts.
BREVO_API_KEY=... NEWSLETTER_ENABLED=true uv run briefberlin-newsletter --target production
```

Exit codes: `0` ok/skip (empty issue, already scheduled, dry run),
`1` error (feed/API failure, gate refusal), `3` quota guard, `4` stale
campaign state (needs a human decision). Only `1`, `3`, `4` page the owner
via the Actions failure notification (`3`/`4` are re-thrown as failures in the
workflow; see workflow comments).

### Safety properties

- One campaign name per day (`BB-YYYY-MM-DD`); a second run the same day finds
  it and stops. Plus the workflow-level `concurrency: newsletter-daily`.
- An interrupted create (timeout after Brevo accepted it) is recovered by
  name-lookup + draft repair, never by creating a second campaign.
- The content watermark (stored in the HTML `briefberlin-cutoff` meta field)
  advances **only** from
  campaigns observed with status `sent`. Scheduled/queued/failed campaigns
  never advance it, so stories from missed days can be picked up while they
  are still in the feed.
- If there is no sent production campaign, the window starts two days before
  the current content cutoff. Subsequent issues start at the content cutoff
  recorded in the latest sent production campaign.
- Content boundary: the window ends at the earlier of 06:00 Europe/Berlin
  and the feed-fetch start time. Early preparation never consumes future
  content; stories appearing after that snapshot remain eligible tomorrow.
- Only strict `BB-YYYY-MM-DD` sent campaigns targeting production list 3
  can advance production history. Test campaigns never affect that window.
- If eligible stories exceed `max_articles_per_issue` (default 10), the issue
  includes the newest stories up to the limit. The saved cutoff still covers
  the full window, so omitted stories are dropped once the issue is sent.
- Quota: reads `GET /account` and requires one free email plan with
  `creditsType=sendLimit` and a nonnegative integer `credits` balance.
  Scheduling refuses unknown, ambiguous or unsupported plan responses and
  requires the audience to fit within `min(300, remaining credits) - 60`.
  SMS credits never count. This checks the current balance, not a reservation:
  later DOI/welcome traffic can still consume the reserve before 07:00.
- Test mode uses list 4 with campaign names `BB-TEST-<timestamp>`; production
  uses list 3. Config validation refuses equal list IDs. The builder calls no
  contact create/import/delete endpoint at all - audience growth and
  suppression (unsubscribe/blacklist) stay with Brevo.
- Abuse alert: >`abuse_threshold_24h` (25) transactional requests in 24h opens
  a GitHub issue with aggregate counts only (never subscriber data).

### Kill switch (signup abuse)

1. `newsletter.signup_open: false` in `output/_config.yml` (one commit) -
   `/newsletter/` shows a closure notice instead of the form.
2. Disable the form in Brevo (form editor) as well.
3. Investigate via Brevo's form logs; if a production send was already
   scheduled for 07:00, cancel/delete the `BB-<date>` campaign in Brevo.

## Live acceptance checks (see evidence and limitations above)

- [x] Both inbound aliases accepted and forwarded by Cloudflare to the verified
      Gmail destination; self-sent Gmail duplicates are not separately visible.
- [ ] Signup form rejects a missing/invalid Turnstile token (submit with the
      widget blocked; must NOT create a pending signup).
- [x] Signup does NOT enter list 3 before the DOI click (check list + form
      logs after form submit).
- [x] DOI email arrives in German from BriefBerlin, confirmation link works.
- [x] German welcome email (template 2) arrives after confirmation.
- [x] Footer unsubscribe, Gmail inbox action and RFC 8058 endpoint exercised;
      provider suppression verified. Footer survey redirects to `/newsletter/abgemeldet/`;
      inbox action has no redirect. Fresh DOI resubscription verified.
- [x] Test campaign (list 4): delivered mail shows DKIM pass with
      `d=briefberlin.de`, DMARC pass, `List-Unsubscribe` AND
      `List-Unsubscribe-Post` headers, visible unsubscribe link, publisher
      footer with `/contact/` and `/privacy/` links.
- [x] Inspect delivered campaign tracking markup and contact statistics;
      retain restrictive consent settings. Accepted limitation below.
- [x] Delivered campaign has a usable plain-text part and German unsubscribe URL.
- [ ] Full consent-event export: combine form-event and transactional logs;
      contact export alone does not contain the full DOI journey.
- [x] Quota balance: compare `GET /account` free email credits before and
      after real DOI, welcome and test sends; verify unknown balances prevent
      scheduling. Confirm remaining credits plus reserve cover the audience.
- [x] Abuse statistics: confirm whether form-triggered DOI mails are counted
      in `/smtp/statistics/aggregatedReport` (fire 2-3 test signups, compare).

## Material limitations and unresolved decisions

1. **Plain text part**: Brevo's campaign API has NO `textContent` field
   (verified against the official OpenAPI spec). We render a plain-text
   version for previews/artifacts; Brevo generates the delivered text part
   from HTML. A real delivered issue was verified readable, including its
   German unsubscribe URL.
2. **Open/click tracking**: account-level per-contact tracking consent is
   enabled, with "Track contacts whose consent is unknown" set to No.
   Both settings were saved and verified after reload. Live DOI/welcome tests
   and campaign tests still showed pixels and rewritten links. The owner chose
   to retain Brevo with this disclosed behavior and consider a custom flow later.
   Pixel presence alone does not establish identified open tracking. Brevo's
   July 21, 2026 transactional API clarification describes unknown/no-consent
   opens as aggregate-only when unknown-consent tracking is disabled:
   https://developers.brevo.com/changelog/2026/7/21
   This statement does not prove identical behavior for every campaign click.
   The signup form does
   not collect tracking consent. Verify DOI, welcome and campaign messages
   in real delivered mail before claiming there are no pixels or rewritten
   links. Existing contacts with explicit tracking consent are not covered
   by the unknown-consent default. See Brevo's per-contact consent docs:
   https://help.brevo.com/hc/en-us/articles/37113920427922
3. **Partial delivery**: Brevo's campaign status has no per-recipient
   delivery view via API. The watermark advances on `sent`; if a send was
   partially delivered the status still reads `sent`. Mitigation is manual:
   check the campaign report in Brevo before deciding.
4. **Unconfirmed signups / cleanup**: Brevo keeps native-form pending signups
   in form logs, not ordinary contacts. The original design's "delete
   unconfirmed contacts > 7 days" was NOT implemented - a blind
   contact-deletion job is out of scope without a precise, reviewed scope.
   Actual retention/export behavior is documented in the privacy policy;
   verify during acceptance and decide if anything more is needed.
5. **DMARC rua**: the zone currently keeps the pre-existing DMARC record
   (`rua=mailto:dmarc_rua@onsecureserver.net`). `dmarc@briefberlin.de`
   routing exists, but the rua target was intentionally NOT changed (never
   add a second DMARC record). Decide: keep the external aggregate receiver
   or switch rua to `dmarc@briefberlin.de` in one edit.
6. **Quota accounting**: the free plan counts DOI + welcome mails against
   300/day. The builder now reads the free email balance from `GET /account`
   (`plan[].credits`, `creditsType=sendLimit`, `type=free`) and fails closed
   if the response is unknown or unsupported. Before enabling production,
   the balance decrease was verified after real DOI, welcome and test sends
   (292 to 289 for three deliveries).
   The 60-email reserve is additional headroom, not an atomic provider quota
   reservation; signups after scheduling can still consume it.
   Reference: https://developers.brevo.com/reference/get-account
7. **Suspended/late campaigns**: if a past day's campaign sits in a pre-send
   state, the builder refuses (exit 4) rather than guessing. Manual recovery:
   investigate in Brevo; deleting the stuck campaign makes its articles
   re-send with the next issue (watermark never advanced).

## Site pieces

- Pages: `/newsletter/`, `/newsletter/danke/`, `/newsletter/bestaetigt/`,
  `/newsletter/abgemeldet/` (German, simple language; result pages are
  `sitemap: false`).
- Closure gate: `newsletter.signup_open` in `output/_config.yml`.
- Privacy policy discloses Brevo + Turnstile processing and observed tracking
  markup in DOI, welcome and campaign messages.
- Tests: `tests/test_newsletter_pages.py` (site),
  `tests/test_newsletter_campaign.py` (builder).

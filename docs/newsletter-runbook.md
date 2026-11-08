# Newsletter Runbook (Brevo daily issue)

Daily German newsletter: signup via a Brevo double-opt-in form embedded on
`/newsletter/`, one issue per day at 07:00 Europe/Berlin, built from
`feed.xml` by `scripts/newsletter_campaign.py` in GitHub Actions.

**Status: implementation complete, NOT launched.** The production schedule is
disabled and the production gate is off until this PR is reviewed and the live
acceptance checks below pass.

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
   testing confirms the exact experience. Inbox RFC 8058 testing is pending.
3. **Secrets / variables** (GitHub repo settings):
   - Secret `BREVO_API_KEY` - Brevo v3 API key; IP allow-listing must be OFF
     (GitHub runner IPs change every run).
   - Keep `NEWSLETTER_ENABLED` absent or `false` during acceptance testing.
     Test-list dispatches do not require the production gate.
4. **Deploy the website and run the live acceptance checks** below. Keep the
   production gate off and the schedule commented out until all checks pass.
5. **Enable production after acceptance**: set `NEWSLETTER_ENABLED=true` and
   uncomment the `schedule:` block in `.github/workflows/newsletter-daily.yml`
   (03:30 and 04:15 UTC; see the workflow comments for the DST reasoning).

## Acceptance evidence — November 8, 2026

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
- **Tracking failed:** both delivered transactional messages contain `/tr/op/`
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
  Exact API balance deltas, CAPTCHA rejection, forwarding, consent export,
  abuse-statistics coverage and campaign headers/tracking remain unverified.

## Operating the builder

```bash
# Preview today's issue (no Brevo traffic at all)
uv run briefberlin-newsletter --dry-run --feed-file output/_site/feed.xml

# Preview against the live feed
uv run briefberlin-newsletter --dry-run

# Send immediately to the TEST list (4) - requires BREVO_API_KEY
BREVO_API_KEY=... uv run briefberlin-newsletter --target test

# Production (list 3) - additionally requires NEWSLETTER_ENABLED=true and
# >= 30 min lead before 07:00 Berlin
BREVO_API_KEY=... NEWSLETTER_ENABLED=true uv run briefberlin-newsletter --target production
```

Exit codes: `0` ok/skip (empty issue, already scheduled, too late, dry run),
`1` error (feed/API failure, gate refusal), `3` quota guard, `4` stale
campaign state or article-limit overflow (needs a human decision). Only `1`, `3`, `4` page the owner
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
  never advance it, so missed days re-send their articles automatically.
- Content boundary: the window ends at the earlier of 06:00 Europe/Berlin
  and the feed-fetch start time. Early preparation never consumes future
  content; stories appearing after that snapshot remain eligible tomorrow.
- Only strict `BB-YYYY-MM-DD` sent campaigns targeting production list 3
  can advance production history. Test campaigns never affect that window.
- If pending stories exceed `max_articles_per_issue`, exit 4 before any
  campaign mutation. Raise the cap after review to send the complete backlog;
  no truncation or watermark advance occurs, even for shared timestamps.
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

## Live acceptance checks (partial results recorded below)

- [ ] `newsletter@briefberlin.de` and `dmarc@briefberlin.de` deliver to the
      configured Gmail inbox (send mail from an external account).
- [ ] Signup form rejects a missing/invalid Turnstile token (submit with the
      widget blocked; must NOT create a pending signup).
- [x] Signup does NOT enter list 3 before the DOI click (check list + form
      logs after form submit).
- [x] DOI email arrives in German from BriefBerlin, confirmation link works.
- [x] German welcome email (template 2) arrives after confirmation.
- [ ] Unsubscribe works from the emailed link and from Gmail's one-click
      button; `/newsletter/abgemeldet/` shows afterwards; resubscription
      starts a fresh DOI.
- [ ] Test campaign (list 4): delivered mail shows DKIM pass with
      `d=briefberlin.de`, DMARC pass, `List-Unsubscribe` AND
      `List-Unsubscribe-Post` headers, visible unsubscribe link, publisher
      footer with `/contact/` and `/privacy/` links.
- [ ] Verify the delivered campaign's tracking behavior (click/open). See
      limitations below - verify the account-level consent settings in mail.
- [ ] Verify the delivered campaign has a usable plain-text part (see
      limitations below).
- [ ] Consent-event export works (Brevo contact export includes DOI events).
- [ ] Quota balance: compare `GET /account` free email credits before and
      after real DOI, welcome and test sends; verify unknown balances prevent
      scheduling. Confirm remaining credits plus reserve cover the audience.
- [ ] Abuse statistics: confirm whether form-triggered DOI mails are counted
      in `/smtp/statistics/aggregatedReport` (fire 2-3 test signups, compare).

## Material limitations and unresolved decisions

1. **Plain text part**: Brevo's campaign API has NO `textContent` field
   (verified against the official OpenAPI spec). We render a plain-text
   version for previews/artifacts, but the delivered mail's text part is
   whatever Brevo generates from the HTML. Verify in acceptance.
2. **Open/click tracking**: account-level per-contact tracking consent is
   enabled, with "Track contacts whose consent is unknown" set to No.
   Both settings were saved and verified after reload. Live DOI/welcome tests
   still showed pixels and rewritten links; this is an unresolved launch blocker.
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
   verify that this balance decreases after real DOI, welcome and test sends.
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
- Privacy policy updated for Brevo + Turnstile processing (draft, pending
  review).
- Tests: `tests/test_newsletter_pages.py` (site),
  `tests/test_newsletter_campaign.py` (builder).

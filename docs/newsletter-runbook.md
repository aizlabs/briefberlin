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
- The content watermark (stored in the campaign `tag`) advances **only** from
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

## Live acceptance checks (all PENDING - do not mark passed without evidence)

- [ ] `newsletter@briefberlin.de` and `dmarc@briefberlin.de` deliver to the
      configured Gmail inbox (send mail from an external account).
- [ ] Signup form rejects a missing/invalid Turnstile token (submit with the
      widget blocked; must NOT create a pending signup).
- [ ] Signup does NOT enter list 3 before the DOI click (check list + form
      logs after form submit).
- [ ] DOI email arrives in German from BriefBerlin, confirmation link works.
- [ ] German welcome email (template 2) arrives after confirmation.
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
   Both settings were saved and verified after reload. The signup form does
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

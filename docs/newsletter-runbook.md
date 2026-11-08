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

1. **Embed the form**: replace the placeholder in
   `output/_includes/brevo-signup-form.html` with the real HTML embed from the
   Brevo form builder (Share -> Embed). Nothing else changes.
2. **Configure Brevo redirects** (form editor, "Confirmation"/success URLs) to:
   - Thank-you: `https://briefberlin.de/newsletter/danke/`
   - After confirmation: `https://briefberlin.de/newsletter/bestaetigt/`
   - Unsubscribe page redirect: `https://briefberlin.de/newsletter/abgemeldet/`
   (Brevo's own unsubscribe page stays in between; the redirect lands on our
   page.) Verify the exact redirect fields available in the form editor.
3. **Secrets / variables** (GitHub repo settings):
   - Secret `BREVO_API_KEY` - Brevo v3 API key; IP allow-listing must be OFF
     (GitHub runner IPs change every run).
   - Variable `NEWSLETTER_ENABLED=true` - production gate for the builder.
4. **Enable the schedule**: uncomment the `schedule:` block in
   `.github/workflows/newsletter-daily.yml` (03:30 and 04:15 UTC; see the
   workflow comments for the DST reasoning).
5. **Run the live acceptance checks** below; keep the workflow disabled until
   they pass.

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
campaign state (needs a human decision). Only `1`, `3`, `4` page the owner
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
- Deterministic cutoff: the issue window always ends at 06:00 Europe/Berlin
  on the issue day, no matter when the run actually fires.
- Quota: refuses production sends when list size exceeds
  `daily_email_limit - daily_reserve` (300 - 60 by default), keeping headroom
  for DOI/welcome mails inside the Brevo free plan's 300/day cap.
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
      limitations below - Brevo campaigns cannot disable tracking via API.
- [ ] Verify the delivered campaign has a usable plain-text part (see
      limitations below).
- [ ] Consent-event export works (Brevo contact export includes DOI events).
- [ ] Abuse statistics: confirm whether form-triggered DOI mails are counted
      in `/smtp/statistics/aggregatedReport` (fire 2-3 test signups, compare).

## Material limitations and unresolved decisions

1. **Plain text part**: Brevo's campaign API has NO `textContent` field
   (verified against the official OpenAPI spec). We render a plain-text
   version for previews/artifacts, but the delivered mail's text part is
   whatever Brevo generates from the HTML. Verify in acceptance.
2. **Open/click tracking**: Brevo email campaigns track opens/clicks and the
   campaign API exposes no switch to turn that off (only UTM customization
   and account-level IP anonymization, which is not "off"). We send no UTM
   parameters and add no own tracking, but provider tracking is expected.
   This is a deviation from the original design goal "no tracking" and needs
   an explicit go/no-go before launch.
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
   300/day; there is no verified API to query the exact remaining quota, so
   the builder reserves a fixed headroom (`daily_reserve: 60`) instead.
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

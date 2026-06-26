# Spai Monetization Roadmap

**Status:** Design only, no code changes yet  
**Last updated:** March 18, 2026

## Purpose

This document defines a realistic monetization strategy for Spai based on the current repository state:

- Static Jekyll site hosted from `output/`
- Automated article generation and GitHub Pages deployment
- Existing Telegram channel publishing workflow
- No user accounts, subscriptions, checkout, or consent-management implementation yet

The goal is to add monetization in a way that is technically simple, policy-compliant, and consistent with the educational positioning of the product.

## Current-State Constraints

### What already exists

- The site has a natural web ad insertion point in [`output/_includes/head/custom.html`](../output/_includes/head/custom.html).
- The deployment pipeline already supports Telegram channel publishing through [`scripts/publish_telegram_channel.py`](../scripts/publish_telegram_channel.py) and [`.github/workflows/deploy-pages.yml`](../.github/workflows/deploy-pages.yml).
- The public site is configured for `https://spaili.com` in [`output/_config.yml`](../output/_config.yml).
- The privacy page exists and has been updated to reflect the current no-ads / no-analytics state in [`output/_pages/privacy.md`](../output/_pages/privacy.md).

### What is missing

- No cookie consent or CMP implementation
- No US-state privacy signal handling such as GPC-based opt-out flows
- No analytics baseline for pageviews, retention, or source attribution
- No advertiser-facing disclosure or ad placement rules
- No published production support email or formal takedown contact outside GitHub Issues
- No content policy layer to reduce sensitive-news inventory before ad review
- Public-facing site copy still exposes implementation details that are not part of the reader value proposition

## Feasibility Matrix

### 1. Google AdSense on the website

**Feasibility:** High  
**Fit with current architecture:** Strong  
**Why:** Spai is a static content site with individual article pages, policy pages, and a custom head include where ad scripts can be inserted without backend work.

**Requirements before launch:**

- Publish a real support contact for readers, rights holders, and ad review
- Finalize privacy/disclosure wording
- Remove public-facing "AI-generated", "automatically generated", or similar implementation framing unless a specific legal or policy obligation requires it
- Add privacy controls for both:
  - EEA/UK/Switzerland opt-in consent flows
  - California and similar US-state opt-out flows, including GPC handling where applicable
- Keep the site navigation, article templates, and policy pages stable during review
- Reduce dependence on conflict-heavy or policy-restricted inventory for the first review cycle

**Assessment:** This should be the primary monetization path for the site itself.

### 2. Telegram monetization

**Feasibility:** Medium  
**Fit with current architecture:** Strong for distribution, moderate for direct revenue  
**Why:** The repo already publishes articles to Telegram. Telegram can therefore be used immediately as a traffic and audience-retention channel.

**Important constraints:**

- Telegram Ads are useful for promoting a Telegram channel or bot, not for sending users directly to the website.
- Telegram channel revenue sharing depends on channel scale; it is not an immediate monetization lever for a small audience.

**Assessment:** Telegram is worth pursuing, but mainly as an audience-growth loop first and a revenue line second.

### 3. Facebook / Meta monetization

**Feasibility:** Medium for content distribution, low for direct website monetization  
**Fit with current architecture:** Weak for site ads, moderate for repurposed social content  
**Why:** Meta's creator monetization programs are built around Facebook-native posts, videos, reels, and creator surfaces. They are not a drop-in monetization layer for a Jekyll site.

**Assessment:** Meta should be treated as a republishing and acquisition channel, not as the main ad stack for the existing web product.

### 4. Outbrain / Teads-style native recommendation widgets

**Feasibility:** Medium later, low now  
**Fit with current architecture:** Technically possible, strategically mixed  
**Why:** Outbrain supports publisher integrations on article pages and requires privacy notices, consent handling where required, US opt-out signal handling, ad labeling, and `ads.txt`.

**Constraints:**

- These widgets change the editorial feel of the site more than standard display ads.
- They work better once there is enough traffic depth and pageview volume to justify a recommendation unit.
- Brand-safety and quality rules are strict; hard-news conflict coverage can create friction.

**Assessment:** Possible as a second-stage experiment after AdSense, but not the best first monetization move for Spai.

### 5. Taboola

**Feasibility:** Medium later, low now  
**Fit with current architecture:** Similar to Outbrain  
**Why:** Taboola is built for publisher monetization and recirculation, but it applies network-wide publisher policies and content restrictions.

**Constraints:**

- Better suited once Spai has enough traffic and enough evergreen inventory to support recirculation widgets.
- Adds "recommended content" UX that may not fit a focused language-learning brand unless placed carefully.

**Assessment:** Viable later, but only after the site has stronger scale and a clear UX decision around recommendation widgets.

### 6. Ezoic

**Feasibility:** Medium  
**Fit with current architecture:** Reasonable, but operationally heavier than AdSense  
**Why:** Ezoic is designed for web monetization and is more accessible to growing publishers than premium managed networks, but its official setup expects `ads.txt`, Google Ad Manager application, and Ezoic-managed ad integration.

**Constraints:**

- More operational complexity than starting with direct AdSense
- Better as an optimization layer once baseline traffic and ad performance already exist

**Assessment:** Worth considering after AdSense if Spai wants more aggressive yield optimization without waiting for premium-network scale.

### 7. Mediavine / premium managed networks

**Feasibility:** Low now, potentially high later  
**Fit with current architecture:** Good later if traffic and quality thresholds are met  
**Why:** Mediavine explicitly reviews for original content, clean traffic, reader experience, and good standing with Google AdSense/AdExchange, and its current requirements target more established publishers.

**Constraints:**

- Current thresholding makes this a growth-stage option, not an initial monetization option
- Spai needs stronger recurring traffic and a more mature audience base first

**Assessment:** This is a later-stage target if the site grows beyond basic AdSense economics.

## Privacy and Consent Matrix

Spai should not treat all regions as having the same ad-tech rules.

### EEA / UK / Switzerland

**Recommended handling:**

- explicit opt-in consent before loading personalized ad tech where required
- CMP compatible with Google and the IAB framework
- privacy notice covering cookies, advertising, measurement, and vendors

### California

**Recommended handling:**

- clear privacy notice
- "Do Not Sell or Share My Personal Information" path if the stack triggers that obligation
- honor Global Privacy Control (GPC) signals where applicable

Important nuance: California is not simply "EU consent for the US". In many cases the core pattern is opt-out and signal honoring rather than blanket opt-in.

### Other US state privacy regimes

Spai should assume expansion pressure beyond California. Colorado and Connecticut are already enforcing opt-out rights in coordination with California regulators, and ad partners increasingly expect a standardized US privacy signal path.

**Practical recommendation:**

- choose a CMP / privacy layer that can support both:
  - EU-style consent signaling
  - US-state opt-out signaling through GPP or equivalent mechanisms

### Rest of world

For other countries and territories, Spai should not guess. The safe operating model is:

- maintain a flexible consent/privacy layer
- geolocate compliance mode at the framework level
- update the policy page before activating any new ad partner or analytics tool

## Recommended Monetization Strategy

### Primary revenue line

Use **Google AdSense** on article pages and archive pages after policy-readiness work is complete.

### Secondary revenue line

Use **Telegram** to:

- distribute every newly published article
- capture repeat readers who prefer messaging apps
- create a channel large enough to qualify for meaningful Telegram ad revenue later

### Tertiary experiment

Use **Facebook / Meta** only if Spai commits to repackaging articles into native short-form formats:

- text summaries
- carousel-style vocab posts
- short explainer reels

This is a separate content workflow and should not block site monetization.

## Ranked Vendor Shortlist

This shortlist mixes:

- **official thresholds** where a platform publishes them
- **operating thresholds** that are recommended for Spai based on fit, effort, and likely yield

If a threshold below is not explicitly published by the vendor, it should be treated as an implementation heuristic, not a contractual requirement.

### 1. Google AdSense

**Rank:** Best first platform  
**Why it ranks first:** simplest fit for the current static site, lowest integration overhead, best first approval target

**Official threshold:**

- No public minimum traffic threshold found in the official AdSense policy/help material reviewed

**Recommended Spai start threshold (inference):**

- `10,000-20,000 monthly sessions`
- `75-100 indexed articles`
- at least `60-90 days` of stable publishing and clean policy pages

**Recommended move-on threshold:**

- Reassess once Spai reaches `50,000+ monthly sessions` or AdSense revenue plateaus for `2-3 months`

**Decision rule:**

- Start here first unless the site is still too early to pass review confidently

### 2. Journey by Mediavine

**Rank:** Best early-growth alternative after or alongside AdSense testing  
**Why it ranks second:** explicit entry product for smaller publishers, cleaner growth path than jumping straight to premium managed ad sales

**Official threshold:**

- Journey starts at `1,000 monthly sessions`

**Recommended Spai start threshold (inference):**

- `10,000+ monthly sessions` and evidence that the audience is recurring, not just one-off news spikes

**Recommended move-on threshold:**

- Reevaluate at `50,000 monthly sessions` for Mediavine main program eligibility

**Decision rule:**

- Consider Journey only if Spai wants a more guided growth stack and is willing to adopt a managed monetization setup earlier

### 3. Ezoic

**Rank:** Best mid-stage optimization platform  
**Why it ranks third:** stronger monetization tooling than raw AdSense, but materially more operational complexity

**Official threshold:**

- Ezoic generally requires `250,000+ monthly active users`
- lower-traffic sites may be eligible through the `Incubator Program`

**Recommended Spai start threshold (inference):**

- `100,000+ monthly sessions` if AdSense is underperforming and Spai is ready for heavier ad-tech operations

**Recommended move-on threshold:**

- Reevaluate when Spai can qualify for a higher-end managed network or when Ezoic complexity outweighs revenue lift

**Decision rule:**

- Use Ezoic only if AdSense is no longer enough and Spai is ready to manage a more demanding monetization stack

### 4. Mediavine main program

**Rank:** Best premium target later  
**Why it ranks fourth:** high-quality publisher positioning and potentially stronger long-term economics, but not a near-term entry point

**Official threshold:**

- Current Mediavine requirements page says the site should generate `at least $5,000 annual ad revenue`
- Legacy and still-referenced Mediavine guidance often uses `50,000 monthly sessions` as the practical traffic gate for ad management review

**Interpretation:**

- Treat `annual ad revenue` as the current formal program qualifier
- Treat `50,000 monthly sessions` as the practical operating threshold Spai should still use for planning

**Recommended Spai start threshold (inference):**

- `50,000-70,000 monthly sessions`
- stable mostly-organic traffic
- clear evergreen archive, not just volatile headline traffic

**Recommended move-on threshold:**

- This is more of a destination than a stepping stone; reassess only if Spai grows large enough to negotiate more bespoke arrangements

**Decision rule:**

- Treat this as a medium-term goal, not a launch platform

### 5. Outbrain

**Rank:** Best native-recommendation experiment later  
**Why it ranks fifth:** officially open to publishers of any scale, but strategically better once Spai has enough content depth and traffic to justify recommendation widgets

**Official threshold:**

- Outbrain states it works with publishers of `any scale`

**Recommended Spai start threshold (inference):**

- `100,000+ monthly pageviews`
- strong archive depth
- willingness to add clearly labeled recommendation units

**Recommended move-on threshold:**

- Only if recommendation widgets prove they add meaningful revenue without harming trust or retention

**Decision rule:**

- Test only after the core display-ad path is already working

### 6. Taboola

**Rank:** Similar to Outbrain, slightly lower fit for current state  
**Why it ranks sixth:** useful for recirculation and native recommendation monetization, but not the cleanest first monetization layer for an education-focused brand

**Official threshold:**

- No public minimum traffic threshold found in the Taboola publisher help material reviewed

**Recommended Spai start threshold (inference):**

- `100,000-200,000 monthly pageviews`
- strong internal content inventory
- deliberate UX decision to use recommendation widgets

**Recommended move-on threshold:**

- Continue only if the widget meaningfully lifts revenue or recirculation without damaging brand quality

**Decision rule:**

- Keep Taboola behind AdSense/Ezoic/Mediavine in the queue

### 7. Telegram monetization

**Rank:** Best distribution-led monetization lane, not best immediate ad platform  
**Why it ranks separately:** it is already integrated in the repo, but revenue depends on channel size rather than site traffic directly

**Official threshold:**

- Telegram Ads display in public channels with `1,000+ subscribers`
- Telegram channel owners can receive `50%` of ad revenue in eligible contexts

**Recommended Spai start threshold (inference):**

- Start audience building immediately
- expect meaningful monetization only after the channel is materially larger than the bare minimum

**Decision rule:**

- Use from day one for traffic and retention, but do not put it ahead of web monetization for near-term revenue planning

## Traffic Ladder for Spai

This is the practical progression I recommend.

### Stage A: 0 to 10,000 monthly sessions

Focus:

- keep ads off or minimal
- improve content quality, indexing, and archive depth
- build Telegram and search presence

Primary goal:

- become review-ready, not revenue-maximal

### Stage B: 10,000 to 50,000 monthly sessions

Primary vendor:

- Google AdSense

Secondary option:

- Journey by Mediavine if a managed early-stage stack is attractive

Do not prioritize yet:

- Outbrain
- Taboola
- premium managed networks

### Stage C: 50,000 to 100,000 monthly sessions

Primary options:

- keep AdSense if RPM and UX remain acceptable
- evaluate Mediavine main program

Secondary option:

- test whether Journey or another managed setup is outperforming direct AdSense

### Stage D: 100,000 to 250,000 monthly sessions

Primary options:

- Mediavine if qualified and accepted
- Ezoic if AdSense is underperforming and Spai wants stronger optimization

Experimental options:

- Outbrain
- Taboola

### Stage E: 250,000+ monthly users / large-scale publishing

Primary options:

- premium managed monetization
- negotiated direct demand or higher-tier managed partners

Experimental options:

- recommendation widgets only if they still fit the brand and UX

## Consistency Check Against the Current Product

### Consistent

- AdSense matches the static-site deployment model.
- Telegram matches the existing publishing automation.
- The site already has privacy/about/contact pages, which are usually expected for ad review.

### Inconsistent or risky

- Public pages still contain placeholder email addresses, which weakens trust and review readiness.
- The content mix includes hard-news and conflict topics; this can reduce advertiser demand and increases policy-review sensitivity.
- There is no consent layer yet, which blocks a compliant ad launch for EEA/UK/Swiss traffic.
- There is no measurement baseline yet, so ad RPM and channel performance would be hard to evaluate.

## Implementation Roadmap

## Phase 0: Documentation and policy readiness

**Goal:** Remove obvious review blockers before any monetization code is added.

Tasks:

- Update architecture and setup docs so they match the current repo state
- Define one canonical monetization plan in this document
- Replace placeholder production contact information in public site pages
- Finalize privacy-policy language for analytics, advertising, and consent
- Audit public-facing copy and remove unnecessary references to AI generation or automation where those references do not serve users, compliance, or editorial trust
- Add a short advertising disclosure policy for future sponsored placements

Exit criteria:

- Docs no longer contradict current site config or pipeline behavior
- Public-facing policy pages are credible enough for ad review
- Public site messaging emphasizes educational value, source quality, and reader usefulness rather than implementation mechanics

## Phase 1: AdSense readiness

**Goal:** Prepare the site for a first AdSense application without changing the business model.

Tasks:

- Audit article templates for clean layout and clear separation between content and future ad slots
- Define which pages may carry ads:
  - article pages
  - homepage
  - paginated archive pages
- Keep non-monetized pages clean:
  - privacy
  - contact
  - about
- Add analytics and search-console instrumentation plan
- Add a lightweight content-quality review pass for topics likely to be restricted or low-yield

Suggested launch guardrails:

- Minimum content base: 75-100 solid indexed articles
- Stable navigation and policy pages
- Real contact method and takedown path
- No placeholder branding or broken links
- No unnecessary "AI-generated" framing in reader-facing brand or editorial copy

Exit criteria:

- Ready to submit for AdSense review
- Ready to measure RPM, CTR, and page-level revenue after approval

## Phase 2: Consent and ad-slot implementation

**Goal:** Introduce the minimum site changes required to run ads safely.

Tasks:

- Add a privacy/compliance layer that covers both:
  - EEA/UK/Switzerland consent requirements
  - California and similar US-state opt-out requirements
- Honor GPC or equivalent browser-level privacy signals where applicable
- Gate ad loading behind configuration so local preview and dry runs stay clean
- Add a small number of ad slots only after approval:
  - one above or below article content
  - one in archive/list views
- Define performance and UX constraints:
  - no layout shift from ad placeholders
  - no ad insertion inside vocabulary lists
  - no aggressive density on short A2 articles

Exit criteria:

- Ads can be enabled or disabled through configuration
- Consent behavior is documented and testable
- Ad placement does not damage readability

## Phase 3: Telegram audience monetization

**Goal:** Turn the existing Telegram publisher into a repeat-traffic channel.

Tasks:

- Add Telegram CTAs to the site and article footers
- Define a channel content mix:
  - full article notifications
  - short vocab recaps
  - weekly top stories
- Track:
  - subscribers
  - click-through to site
  - return traffic share
- Evaluate paid Telegram promotion only as channel growth spend, not as direct site monetization

Exit criteria:

- Telegram is generating measurable recurring traffic
- Channel metrics justify continuing or pausing growth spend

## Phase 4: Meta distribution experiments

**Goal:** Test whether social-native versions of the content can earn or drive acquisition.

Tasks:

- Create a repurposing format for Facebook-native posts and short video scripts
- Publish a limited weekly cadence
- Measure referral traffic and creator-earnings signals separately from web ads
- Stop quickly if effort is high and distribution is weak

Exit criteria:

- Clear evidence that Meta is worth staffing as a separate content lane

## Prioritized Recommendation

1. Prepare the site for **AdSense** first.
2. Use **Telegram** as the first audience-growth multiplier because the automation already exists.
3. Consider **Ezoic** only after AdSense if Spai wants stronger optimization without waiting for premium-network scale.
4. Treat **Outbrain/Taboola** as later-stage experiments for recirculation/native recommendations, not as the first monetization layer.
5. Treat **Meta/Facebook** as an optional distribution experiment, not a core monetization dependency.

## Risks and Mitigations

### AdSense review rejection

Mitigation:

- tighten public trust pages
- avoid placeholder contact info
- keep educational value explicit
- reduce sensitive-news concentration during initial review

### Low revenue from hard-news inventory

Mitigation:

- diversify with culture, science, travel, lifestyle, and evergreen learner content
- build archive traffic, not only same-day news traffic

### Consent complexity

Mitigation:

- keep the first implementation minimal
- choose a privacy layer that supports both Google-style consent and US-state opt-out signaling
- avoid vendor lock-in to a tool that only solves Europe

### Telegram channel does not scale

Mitigation:

- use Telegram primarily as retention and distribution
- do not assume channel ad revenue in near-term financial forecasts

### Meta republishing consumes too much effort

Mitigation:

- run it as a time-boxed experiment with explicit stop criteria

## Suggested Success Metrics

### Site monetization

- AdSense approval
- RPM by page type
- Revenue per 1,000 sessions
- Bounce rate change after ads
- Average session duration after ads

### Telegram

- Channel subscribers
- Click-through rate to `spaili.com`
- Share of return visitors from Telegram

### Meta

- Referral traffic to site
- Follower growth
- Time spent per published asset
- Revenue or bonus eligibility signals if native monetization is enabled

## Official Sources Checked

- Google AdSense program policies: [support.google.com/adsense/answer/48182](https://support.google.com/adsense/answer/48182)
- Google AdSense beginner policy guidance: [support.google.com/adsense/answer/23921](https://support.google.com/adsense/answer/23921)
- Google guidance on user consent for ads-related processing: [support.google.com/google-ads/answer/14009343](https://support.google.com/google-ads/answer/14009343)
- Telegram Ads getting started: [ads.telegram.org/getting-started](https://ads.telegram.org/getting-started)
- Telegram channel and bot ad revenue types: [core.telegram.org/type/BroadcastRevenueBalances](https://core.telegram.org/type/BroadcastRevenueBalances)
- Meta newsroom on Facebook Content Monetization: [about.fb.com/news/2024/10/monetize-content-facebooks-new-streamlined-program/amp/](https://about.fb.com/news/2024/10/monetize-content-facebooks-new-streamlined-program/amp/)
- Meta Audience Network overview: [facebook.com/business/marketing/audience-network](https://www.facebook.com/business/marketing/audience-network)
- California Privacy Protection Agency on opt-out rights and GPC enforcement: [cppa.ca.gov/announcements/2025/20250909.html](https://cppa.ca.gov/announcements/2025/20250909.html)
- Mediavine requirements: [mediavine.com/mediavine-requirements/](https://www.mediavine.com/mediavine-requirements/)
- Mediavine program path and Journey entry point: [help.mediavine.com/programs-and-the-publisher-path-to-growth](https://help.mediavine.com/programs-and-the-publisher-path-to-growth)
- Outbrain publisher guidelines: [outbrain.com/publishers/guidelines/](https://www.outbrain.com/publishers/guidelines/)
- Outbrain minimum traffic requirement: [outbrain.com/help/publishers/outbrains-minimum-traffic-requirement/](https://www.outbrain.com/help/publishers/outbrains-minimum-traffic-requirement/)
- Taboola publisher policy: [pubhelp.taboola.com/hc/en-us/articles/360033751274-Taboola-Publisher-Policy](https://pubhelp.taboola.com/hc/en-us/articles/360033751274-Taboola-Publisher-Policy)
- Ezoic publisher compliance and monetization requirements: [support.ezoic.com/kb/article/ezoic-site-requirements-for-monetization](https://support.ezoic.com/kb/article/ezoic-site-requirements-for-monetization)

## Notes on Interpretation

- The Meta conclusion is partly an inference from Meta's public product positioning: current official materials describe creator monetization and app inventory, not a simple website ad product for a static content site like Spai.
- The Google recommendation assumes Spai keeps the content educational, clearly attributed, and policy-compliant; approval is not guaranteed.
- The California recommendation is deliberately different from the EEA model: for California, the key issue is often opt-out rights and signal honoring rather than universal opt-in consent.

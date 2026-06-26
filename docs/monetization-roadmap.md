# BriefBerlin Monetization Roadmap

BriefBerlin should launch without ads or trackers unless the privacy policy and consent flow are updated first.

## Current Recommendation

For the first deploy, prioritize:

- stable public articles;
- clean German learner experience;
- accurate privacy and contact pages;
- basic search indexing;
- lightweight traffic measurement only if it is configured legally.

Do not enable AdSense, affiliate links, recommendation widgets, or third-party pixels before the site has enough content and the policy pages match the implementation.

## Candidate Paths

### Stage 1: No Ads

Use this while validating content quality and publishing cadence.

Requirements:

- privacy page states no ads or analytics if that remains true;
- no third-party scripts beyond the Jekyll/GitHub Pages build requirements;
- public posts have no private source attribution.

### Stage 2: Privacy-Respecting Analytics

Consider a lightweight analytics provider only after deciding the target jurisdiction and consent requirements.

Requirements:

- update `output/_pages/privacy.md`;
- document the provider and data retention;
- avoid collecting private source data.

### Stage 3: Display Ads

Consider AdSense or another network only after the site has meaningful recurring traffic and enough reviewed content.

Requirements:

- update privacy/cookie language before enabling scripts;
- verify learner content complies with ad policies;
- review layout impact on mobile reading.

### Stage 4: Products or Sponsorships

Potential future options:

- downloadable reading packs;
- newsletter sponsorships;
- paid audio bundles;
- partnerships with German teachers or language schools.

These should be evaluated only after BriefBerlin has a consistent content archive and clear audience signals.

## Deployment Guardrail

The public site config should use the production domain, currently planned as:

```yaml
url: "https://briefberlin.de"
```

If a different domain is chosen, update `output/_config.yml`, media-domain examples, and policy copy before launch.

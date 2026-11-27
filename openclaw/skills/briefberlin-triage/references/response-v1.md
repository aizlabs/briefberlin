# Model response, berlin-v1

Return one JSON object. For an unresolved report return `{"uncertain":"Name the missing fact or ambiguous match."}`. Otherwise supply 1–8 complete events. All keys in this illustrative event are required. Copy the revision ID, public URL, exact quote and attribution from the claim. The example uses synthetic evidence.

```json
{
  "events": [{
    "relationship": "new", "candidate_id": null,
    "title": "District expands evening permit appointments",
    "change": "The district opened an evening appointment slot for parking permits.",
    "place": "Berlin", "entities": ["District office"], "event_date": "2026-03-10",
    "score": 7, "rationale": "Working residents can attend after their shift.",
    "berlin_consequence": "Residents can apply for a local parking permit after work.",
    "time_sensitivity": "Bookings open today.",
    "sufficient": true, "unresolved": "", "material": true,
    "deadline": null, "expires_at": null,
    "evidence": {
      "revision_id": 42, "url": "https://example.org/permit",
      "quote": "Evening bookings open today", "attribution": "District office", "wire_origin": null,
      "fact": "The district office opened evening bookings today."
    }
  }]
}
```

Use only supplied candidate IDs for `same`, `follow-up` and `correction`. A `new` event requires a null candidate. Name the matching or distinguishing fact in `change`. `material` means a consequential change relative to the supplied candidate. A simple repeat has `material=false`. Enter the source's recognised publisher or explicitly credited origin (e.g. “dpa”) in attribution. Preserve additional fact provenance in the fact or rationale. A true integer score and boolean flags are required. If a factual issue prevents dispatch, use `sufficient=false` and explain it in `unresolved`. If you cannot assign the event identity safely, use the whole-report uncertainty form.

Use ISO YYYY-MM-DD or null for event date, and integer UTC Unix seconds or null for deadline and expiry. For an evidenced service or opportunity ending after 48 hours, include an exact `timing_quote` from the evidence containing the Berlin end date and year (ISO or German long or numeric date). The maximum extension is 90 days from the evidence. Otherwise leave the fields null. Enter an explicitly credited wire service in evidence.wire_origin, or null when absent. Expiry must be on or before the deadline. Null expiry applies a 48-hour interval from source publication (or observed material notice change), capped by a supplied deadline. The application computes the tier.

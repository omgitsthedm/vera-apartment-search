# Interpret VERA scoring

VERA ranks evidence; it does not certify a listing, landlord, building, or legal outcome. Executable scoring behavior lives in `scripts/score_listings.py`, `scripts/enrich_listings.py`, `config/listing_confidence.py`, and the owner-approved search configuration. This document defines the stable interpretation contract without duplicating changeable personal criteria.

## Evidence groups

The overall score combines these groups:

- Search fit
- Independent-landlord evidence
- Building and landlord safety evidence
- Rent-stability evidence
- Listing completeness and scam-resistance evidence

Each listing must expose component scores and plain-language reasons. Missing or synthetic risk data must reduce confidence or require manual review; it must never become favorable evidence by default.

## Recommendations

- `pursue`: the listing passes current hard filters and the highest current scoring threshold without a severe red flag
- `pursue cautiously`: the listing clears the configured cautious threshold but retains material caveats
- `manual review`: evidence is incomplete, conflicting, or too weak for an automated recommendation
- `skip`: the listing fails a hard filter, falls below the configured threshold, or carries a major red flag

Thresholds, price ceilings, target neighborhoods, unit preferences, and forensic deductions are executable configuration. Do not copy their values into public documentation or change them without David's approval.

## Invariants

- A listing without a public-record match must not produce a clean building score
- No missing field may inflate a grade or recommendation
- Probabilistic AI-photo output remains evidence, not proof, and does not change the score
- Protected-class signals never enter scoring
- Public output carries explanations and source links but no private contact, note, preference, or watchlist field

Run `python3 tests/test_scoring.py`, `python3 tests/test_public_lens.py`, and `python3 tests/test_neighborhood_gate.py` after a scoring, enrichment, hard-filter, or geography change.

# Scoring Rules

This bot starts with a 100-point scoring framework and stays conservative with claims.

## Score Buckets

### Search Fit: 35 points

- Neighborhood fit: 12
- Price fit: 10
- Unit type fit: 5
- Freshness: 8

### Independent Landlord Fit: 20 points

- By-owner language: 8
- Owner-scale signals: 6
- Non-corporate contact pattern: 6

### Building And Landlord Safety: 20 points

- HPD signal quality: 8
- DOB or similar building-risk signal: 4
- Ownership clarity: 4
- No bad-actor pattern: 4

### Rent-Stability Upside: 10 points

- Public reference hit: 6
- Building age and size clues: 4

### Listing Quality And Scam Resistance: 15 points

- Data completeness: 5
- Address plausibility: 3
- Credible photos: 3
- Contact consistency: 2
- Duplicate sanity: 2

## Recommendation Thresholds

- `pursue`: 80 and above, with hard filters passed and no severe red flag
- `pursue cautiously`: 60 to 79, or strong fit with meaningful caveats
- `skip`: below 60, failed hard filter, or major red flag

## Hard Filters

A listing only counts as qualified if it is:

- in a target neighborhood
- studio or 1 bedroom
- at or under `$2500`
- not clearly a room share
- not clearly sublet-only if the listing reads temporary or unstable

## Positive Signals

- direct-owner language
- no-fee language
- complete or verifiable address
- small-building cues
- consistent owner identity across listing and record checks
- decent photo set
- honest-looking description without luxury padding

## Negative Signals

- management-company branding
- luxury leasing-office language
- suspiciously vague address
- weak or inconsistent contact details
- repeated spammy duplicates
- bad-actor watchlist hit
- severe HPD or DOB pattern

## Important Rule

The bot should score evidence, not confidence theater. If data is thin, the score should reflect that thinness.

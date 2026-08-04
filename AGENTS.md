# VERA engine agent rules

- Canonical engine: `/Users/davidmarsh/Code/Personal/vera-apartment-search`, GitHub `omgitsthedm/vera-apartment-search`, branch `main`.
- Canonical dashboard: `/Users/davidmarsh/Code/Personal/nyc-apartment-search-dashboard`, GitHub `omgitsthedm/vera-dashboard`.
- Ownership: VERA is an internal Little Fight NYC company product, not a client. Public canonical URL: `https://littlefightnyc.com/vera`. Operational business identity: `hello@littlefightnyc.com`.
- These Personal checkout paths are intentionally preserved until a separately authorized coordinated move updates every LaunchAgent and dashboard reference; do not casually relocate them.
- LaunchAgents run this checkout and may refresh and deploy the dashboard automatically.
- Never run pipeline, schedule-installation, publishing, or deployment scripts without clear production authorization.
- Never read, stage, expose, or copy `.env*`, raw/private listing data, personal notes, contact details, preferences, or production logs.
- Do not change search criteria or scoring weights without David's approval.
- This system discovers and ranks listings only; it must not contact landlords or submit applications.

Use `SOURCE_OF_TRUTH.md` for routing and `README.md` only when operational detail is needed. Preserve unrelated work and distinguish source changes from scheduled generated output.

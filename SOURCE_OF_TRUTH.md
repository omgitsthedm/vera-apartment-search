# VERA engine source of truth

Verified 2026-08-03.

- Product owner: Little Fight NYC; VERA is an internal company product, not a client.
- Operational identity: `hello@littlefightnyc.com`
- Public canonical URL: `https://littlefightnyc.com/vera`
- Local: `/Users/davidmarsh/Code/Personal/vera-apartment-search`
- GitHub: `https://github.com/omgitsthedm/vera-apartment-search`, branch `main`
- Dashboard: `/Users/davidmarsh/Code/Personal/nyc-apartment-search-dashboard`
- Dashboard GitHub: `https://github.com/omgitsthedm/vera-dashboard`, branch `main`
- Netlify: `vera-pipeline`, site ID `fcd6f741-d479-44f4-8ee1-51da2b321227`
- Baseline production deploy: `6a6c3be8e180a87e5f0f26ae`
- Method: local LaunchAgents run this engine; its publisher syncs sanitized public output into the dashboard checkout and performs a CLI production upload.

The active LaunchAgents reference this Code checkout. Agency operations classifies VERA as an internal property and intentionally routes these external supporting checkouts. The old Projects and Desktop/OpenClaw paths are not deployment sources. Do not move this checkout, alter schedules, run the pipeline, or publish as housekeeping. A future move to `/Users/davidmarsh/Code/LiFi NYC/Internal/VERA/` must update all LaunchAgent and dashboard paths in one authorized maintenance window. Private/raw data and credentials must remain local and unexposed.

## Cloud publish — added 2026-08-04, supersedes the Netlify method above

The "Method" line above describes the Mac-only path. It is still true of the
Mac, but it is no longer how the app is fed.

- **The nightly GitHub Actions sweep publishes its own feed** to the orphan
  `feed` branch of this repo, served by
  `https://raw.githubusercontent.com/omgitsthedm/vera-apartment-search/feed/{public,archive,meta}.json`
  with `access-control-allow-origin: *`. It uses only the automatic
  `GITHUB_TOKEN`.
- **Do NOT create a Netlify personal access token for VERA.** Settled
  determination, recorded in the Little Fight NYC handoff. A PAT made during
  setup was deleted once a code audit proved it unnecessary. Any doc telling
  you to add `NETLIFY_AUTH_TOKEN` / `NETLIFY_SITE_ID` is superseded.
- The app reads three origins — the site's own copy, the Netlify mirror, and
  the cloud feed — and adopts the **freshest**, not the first to answer.
- `scripts/public_lens.py` is the single implementation of the privacy
  boundary. The dashboard repo imports it; do not fork a second copy.
  `audit_public_payload()` refuses to publish a payload carrying personal
  fields.
- Cross-run engine memory lives in the **Actions cache**, not a branch —
  that data has never been through the public lens and this repo is public.

## Cost constraint — VERA spends nothing

David, 2026-08-04: "I don't want to spend a dime on VERA." Everything above
is free and must stay free.

- Actions is unmetered **because this repo is PUBLIC**. If it is ever made
  private, Actions becomes metered (~450 min/month against a 2,000-minute
  tier). Flag that before any such change.
- The Hugging Face classifier downloads once and runs on the runner's own
  CPU. There is no inference API bill.
- `vera-pipeline` on Netlify is the only paid surface VERA still touches,
  and as of 2026-08-04 it is redundant: its payload measured byte-identical
  to the site's own `/vera/data/public.json`, and both were hours staler
  than the cloud feed. Turning off the Mac's deploy to it needs David's
  explicit word, because a recorded determination says to keep it.

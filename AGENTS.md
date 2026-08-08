# VERA engine agent rules

- Canonical engine: `/Users/davidmarsh/Code/Personal/vera-apartment-search`, GitHub `omgitsthedm/vera-apartment-search`, branch `main`.
- Canonical public application: `/Users/davidmarsh/Code/LiFi NYC/Little Fight NYC Business/Website/littlefightnyc-website/app/public/vera`, GitHub `omgitsthedm/littlefightnyc-website`.
- Ownership: VERA is David's internal Little Fight NYC product and public demo, not a client. Canonical URL: `https://littlefightnyc.com/vera/`. Operational business identity: `hello@littlefightnyc.com`.
- This engine checkout remains separate so raw/private hunt data never enters the public website repository or Netlify property. Do not casually relocate it; active LaunchAgents use this path.
- The scheduled GitHub Actions cloud sweep publishes only sanitized `public.json`, `archive.json`, and `meta.json` to the orphan `feed` branch. Little Fight exposes them through first-party `/vera/data/*` rewrites.
- The former `nyc-apartment-search-dashboard` checkout and `vera-pipeline` Netlify project are historical. Never sync, publish, or deploy them.
- Never run pipeline, schedule-installation, or cloud-publishing workflows without clear production authorization.
- Never read, stage, expose, or copy `.env*`, raw/private listing data, personal notes, contact details, preferences, or production logs.
- Do not change search criteria or scoring weights without David's approval.
- This system discovers and ranks listings only; it must not contact landlords or submit applications.

Use `SOURCE_OF_TRUTH.md` for routing and `README.md` only when operational detail is needed. Preserve unrelated work and distinguish source changes from scheduled generated output.

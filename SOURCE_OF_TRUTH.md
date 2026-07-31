# VERA engine source of truth

Verified 2026-07-31.

- Local: `/Users/davidmarsh/Code/Personal/vera-apartment-search`
- GitHub: `https://github.com/omgitsthedm/vera-apartment-search`, branch `main`
- Dashboard: `/Users/davidmarsh/Code/Personal/nyc-apartment-search-dashboard`
- Dashboard GitHub: `https://github.com/omgitsthedm/vera-dashboard`, branch `main`
- Netlify: `vera-pipeline`, site ID `fcd6f741-d479-44f4-8ee1-51da2b321227`
- Baseline production deploy: `6a6c3be8e180a87e5f0f26ae`
- Method: local LaunchAgents run this engine; its publisher syncs sanitized public output into the dashboard checkout and performs a CLI production upload.

The active LaunchAgents reference this Code checkout. The old Projects and Desktop/OpenClaw paths are not deployment sources. Do not move this checkout, alter schedules, run the pipeline, or publish as housekeeping. Private/raw data and credentials must remain local and unexposed.

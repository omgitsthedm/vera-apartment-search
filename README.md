# Apartment Search

Local-first NYC apartment-search intelligence system for daily rental discovery, verification, scoring, and reporting.

## Purpose

This project runs as a visible local bot from:

`/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search`

Bot name: `VERA`
Meaning: `Verified Evaluation for Rental Analysis`

VERA is designed to help identify realistic studio and 1-bedroom apartment listings in target NYC neighborhoods while reducing duplicate junk, suspicious listings, and risky buildings.

It does not:

- message landlords
- submit applications
- publish anything
- create outreach

It only discovers, normalizes, verifies, ranks, and reports.

## Folder Map

- `README.md`: operating manual
- `configs/`: user preferences, scoring notes, source registry, schedules, health procedure, and machine-readable catalog files
- `scripts/`: local pipeline scripts and shell runners
- `raw/`: timestamped source snapshots by source
- `normalized/`: normalized listing datasets
- `deduped/`: duplicate-clustered datasets and cluster exports
- `enriched/`: listings with public-record and landlord-signal enrichment
- `scored/`: final scored datasets
- `reports/daily/`: daily reports
- `reports/weekly/`: weekly reports
- `reports/shortlist/`: shortlist reports
- `logs/`: timestamped script logs
- `cache/`: discovery seeds, reference data, and lightweight state files
- `screenshots/`: optional manual review captures
- `watchlists/`: building, owner, and bad-actor watchlists
- `schemas/`: listing schema docs
- `prompts/`: local LLM prompt references
- `exports/`: CSV exports for manual review

## User Search Criteria

Current first-pass criteria live at:

`/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/configs/user_preferences.json`

Highlights:

- Neighborhoods:
  - East Village
  - Alphabet City
  - Greenwich Village
  - Lower East Side
  - Stuytown
  - West Village
  - Tribeca
  - SoHo
  - Chelsea
  - Williamsburg
  - Greenpoint
  - East Williamsburg
- Unit types:
  - studio
  - 1 bedroom
- Max rent:
  - `$2500`
- Preference:
  - likely independent landlords

## Source List

Human-readable source notes:

- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/configs/source_registry.md`

Machine-readable source catalog used by the scripts:

- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/configs/source_catalog.json`

Current operating mode:

- **Craigslist**: LIVE — public HTML capture with browser-like requests, cached detail fetches, conservative rate limits
- **StreetEasy**: LIVE — embedded JSON extraction from search result pages, no detail page fetch needed (low volume at sub-$2,500 price points — honest market reality)
- **RentHop**: LIVE — search page crawl + detail page JSON-LD extraction, NYC-focused
- **Apartments.com**: NOT FEASIBLE — returns HTTP 403 on all requests (anti-bot)
- **Zillow/HotPads/Trulia**: NOT FEASIBLE — Zillow Group anti-bot protection blocks all requests
- **Facebook Marketplace**: NOT FEASIBLE — login-gated, cannot be automated locally

## Local Model Usage

The LLM is the analyst layer, not the source of truth.

Recommended routing:

- `qwen3:8b`: extraction, classification, and utility work
- `qwen3:14b`: synthesis and report-writing
- `llama3.1:8b`: fallback

Current health check expects those models to be available through local Ollama.

Important external path:

- Ollama stores models outside this folder at `~/.ollama/models`

## Script List

- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/discover_listings.py`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/normalize_listings.py`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/dedupe_listings.py`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/refresh_public_records.py`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/enrich_listings.py`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/score_listings.py`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/health_check.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/run_hourly.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/run_weekly.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/publish_dashboard.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/run_hourly_autonomous.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/run_weekly_autonomous.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/run_daily.sh` (legacy, kept for manual use)
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/run_daily_autonomous.sh` (legacy, kept for manual use)
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/install_launch_agents.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/remove_launch_agents.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/launch_agents_status.sh`

## Run Order

Standard daily order:

1. `./scripts/health_check.sh`
2. `python3 ./scripts/discover_listings.py`
3. `python3 ./scripts/normalize_listings.py`
4. `python3 ./scripts/dedupe_listings.py`
5. `python3 ./scripts/refresh_public_records.py`
6. `python3 ./scripts/enrich_listings.py`
7. `python3 ./scripts/score_listings.py --scope daily`

Weekly run:

1. `./scripts/health_check.sh`
2. `./scripts/run_weekly.sh`

## Schedule Overview

Reference schedule lives at:

- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/configs/schedules.md`

Current cadence:

- **Hourly**: full pipeline (discover → normalize → dedupe → enrich → score → publish dashboard)
- **Weekly**: market summary and red-flag review (Sunday 7:00 PM)

Current autonomous setup files:

- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/configs/launchd/com.vera.apartment-search.hourly.plist`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/configs/launchd/com.vera.apartment-search.weekly.plist`

Helper commands:

- Install local schedules: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/install_launch_agents.sh`
- Remove local schedules: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/remove_launch_agents.sh`
- Inspect local schedules: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/launch_agents_status.sh`

Autonomous behavior:

- Hourly autonomous cycle runs the full VERA pipeline and then refreshes and deploys the public dashboard.
- Weekly autonomous cycle runs the weekly VERA report and then refreshes and deploys the public dashboard.

## Output File Locations

- Latest raw snapshots: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/raw/`
- Normalized datasets: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/normalized/`
- Deduped datasets and cluster exports: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/deduped/`
- Enriched datasets: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/enriched/`
- Scored datasets: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scored/`
- Daily reports: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/reports/daily/`
- Weekly reports: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/reports/weekly/`
- Shortlist reports: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/reports/shortlist/`
- CSV exports: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/exports/`
- Logs: `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/logs/`

## Scoring Explanation

The starting system is a 100-point model:

- Search fit: `35`
- Independent landlord fit: `20`
- Building and landlord safety: `20`
- Rent-stability upside: `10`
- Listing quality and scam resistance: `15`

Labels:

- `pursue`
- `pursue cautiously`
- `skip`

Detailed weighting notes live at:

- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/configs/scoring_rules.md`

## Known Limitations

- Discovery is live for Craigslist, StreetEasy, and RentHop. StreetEasy has low volume at the sub-$2,500 price point (market reality).
- Apartments.com, Zillow, HotPads, and Trulia are blocked by anti-bot protections (HTTP 403). Facebook Marketplace requires login. None are feasible for honest automated scraping.
- Public-record enrichment overlays live official NYC Open Data risk counts when the address resolves cleanly, but owner and tax-record verification still need additional sources such as ACRIS or PLUTO.
- The bot estimates signals such as independent landlord likelihood and rent-stabilization likelihood. It does not claim legal certainty.
- Duplicate matching includes cross-source deduplication with relaxed thresholds for listings from different sources, but image-hash matching is not yet implemented.

## Manual Review Notes

- Treat `pursue` as a shortlist signal, not a final truth verdict.
- Review vague-address listings manually even when they score reasonably.
- Review every `rent_stabilized_signal` as an estimate unless backed by a real public reference hit.
- Keep bad-actor watchlists updated in `watchlists/`.
- Replace sample fixtures with live source adapters only after each source is documented and tested.

# CLAUDE.md — VERA (Apartment Search Agent)
> Local OpenClaw agent | Machine: this Mac (NOT the remote Dakota machine)
> Owner: David — personal use, not a LiFi NYC or AHA project

## What VERA Is
VERA is a personal apartment hunting robot running on OpenClaw (local). She scrapes, normalizes, deduplicates, scores, and enriches NYC apartment listings, then outputs ranked reports.

## What VERA Is NOT
- NOT part of Little Fight NYC (no client work, no website building)
- NOT part of After Hours Agenda (no products, no e-commerce)
- NOT Dakota (Dakota is the LiFi sales agent on the REMOTE machine at 192.168.0.110)
- NOT customer-facing in any way

## Pipeline
Raw sources → normalized → deduped → scored → enriched → reports/exports

## Key Folders
- `configs/` — source catalog, scoring weights
- `raw/` — raw scraped data
- `normalized/` → `deduped/` → `scored/` → `enriched/` — pipeline stages
- `reports/` — final ranked output
- `exports/` — CSV/JSON exports
- `logs/` — pipeline run logs
- `watchlists/` — saved search criteria

## Rules
- This is personal data. Never share listings, scores, or preferences outside this folder.
- Don't modify scoring weights without David's approval.
- Don't confuse this with any LiFi NYC or AHA project.

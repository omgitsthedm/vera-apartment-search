# Schedules

Current cadence for VERA.

## Autonomous Mode

VERA runs on local launchd templates:

- **Hourly autonomous run**: every 60 minutes (StartInterval = 3600)
- **Weekly autonomous run**: Sunday 7:00 PM local time

Local files:

- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/configs/launchd/com.vera.apartment-search.hourly.plist`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/configs/launchd/com.vera.apartment-search.weekly.plist`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/install_launch_agents.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/remove_launch_agents.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/launch_agents_status.sh`

Autonomous runners:

- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/run_hourly_autonomous.sh`
- `/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search/scripts/run_weekly_autonomous.sh`

These wrappers run the full VERA pipeline and then publish the dashboard snapshot to the live Netlify site.

## Hourly Run (Primary)

Full pipeline every hour:

1. Health check
2. Discovery (Craigslist + StreetEasy + RentHop)
3. Normalization
4. Deduplication (including cross-source matching)
5. Public records refresh (NYC Open Data)
6. Enrichment (landlord classification, risk scoring)
7. Scoring
8. Dashboard publish

Cache TTL and rate limiting prevent unnecessary hammering of sources on repeated runs.

## Weekly Run

- Market summary
- Duplicate cluster report
- Red-flag building review

Suggested local window:

- Sunday evening

## Important Rule

Do not hammer websites.

- Cache seen IDs and URLs (18h TTL for Craigslist, 12h for StreetEasy/RentHop)
- Revisit only new or changed listings when possible
- Conservative rate limiting (1200ms Craigslist, 2000ms StreetEasy/RentHop)

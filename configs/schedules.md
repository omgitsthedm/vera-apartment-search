# VERA schedules

Verified 2026-08-10 against the loaded `com.vera.apartment-search.*` agents. All four were loaded, idle at inspection time, and reported last exit code `0`.

## Local engine cadence

The loaded LaunchAgents run only the canonical engine checkout at
`/Users/davidmarsh/Code/Personal/vera-apartment-search`:

| Agent | Machine-local schedule | Entrypoint |
|---|---:|---|
| `com.vera.apartment-search.daily` | 08:00 daily | `scripts/run_daily_autonomous.sh` |
| `com.vera.apartment-search.watchdog` | 10:00 daily | `scripts/watchdog_stale_run.sh` |
| `com.vera.apartment-search.nightly` | 23:00 daily | `scripts/run_nightly_autonomous.sh` |
| `com.vera.apartment-search.weekly` | Sunday 19:00 | `scripts/run_weekly_autonomous.sh` |

Their only tracked templates live in `configs/launchd-v2/`. The stale
`configs/launchd/` templates that pointed at a retired Desktop/OpenClaw
checkout were deleted. No unattended schedule installer ships with the
engine; schedule replacement requires a separately authorized maintenance
window.

The daily and nightly runners execute the discovery-to-snapshot pipeline. The
nightly runner also performs local notification and enrichment follow-ons. The
weekly runner creates the market, duplicate, red-flag, and transit refreshes.
The watchdog reports a stale local snapshot.

None of these local jobs deploys a website or syncs a dashboard checkout.
Their run state records `publish_status: external` because public feed
publication belongs to the cloud workflow.

## Public feed cadence

`.github/workflows/sanctioned-cloud-sweep.yml` is scheduled on GitHub Actions at
05:30 UTC daily and also supports explicit manual dispatch. GitHub may queue a
scheduled job after its trigger time. Manual dispatch is a publication action
and requires current authorization. The workflow:

1. Runs the cloud-safe engine pipeline.
2. Passes the result through `scripts/public_lens.py` and its independent
   privacy audit.
3. Force-pushes only `public.json`, `archive.json`, and `meta.json` to the
   orphan `feed` branch.
4. Leaves the Little Fight NYC site to expose those files through its exact
   first-party `/vera/data/*` routes.

The sole public application is `https://littlefightnyc.com/vera/`. The
historical dashboard checkout and dedicated VERA Netlify project are not
schedule targets and must not be restored.

## Pipeline stages

The primary discovery-to-snapshot pipeline is:

1. Health check
2. Discovery
3. Normalization
4. Deduplication, including cross-source matching
5. NYC public-record refresh
6. Enrichment and risk scoring
7. Scoring
8. Snapshot composition

Cache TTLs and conservative rate limits prevent repeated jobs from hammering
source websites. Revisit only new or changed listings when possible.

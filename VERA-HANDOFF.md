---
contentType: Reference
title: Operate and recover VERA
verified: 2026-08-10
---

# Operate and recover VERA

VERA has one public home at [littlefightnyc.com/vera](https://littlefightnyc.com/vera/) and one separate engine for private processing. Use this document to route work, verify a release, recover either side, and avoid restoring the retired standalone dashboard.

## Objective and audience

This reference is for an AI agent or human operator taking over VERA across repositories. VERA is David's Little Fight NYC product and public software demo, not a client project. It discovers and ranks New York City apartment listings, explains its evidence, and never contacts landlords or submits applications.

The public Atlas scope is Manhattan, Brooklyn, Queens, and the Bronx, centered near downtown Manhattan. It excludes Staten Island, New Jersey, Nassau, and Suffolk from the browser product. Do not widen that product geography without David's approval.

VERA must add no dedicated hosting bill. Its public app shares Little Fight NYC's existing Netlify property, and its sanitized feed uses the public engine repository's GitHub Actions allowance.

## Canonical paths and repositories

| Surface | Canonical local path | GitHub and branch | Role |
| --- | --- | --- | --- |
| Public website | `/Users/davidmarsh/Code/LiFi NYC/Little Fight NYC Business/Website/littlefightnyc-website` | `omgitsthedm/littlefightnyc-website`, `main` | Browser app, legal pages, Progressive Web App shell, first-party data routes, tests, and Netlify release |
| Public VERA source | `/Users/davidmarsh/Code/LiFi NYC/Little Fight NYC Business/Website/littlefightnyc-website/app/public/vera` | Same website repository | Static VERA application mounted at `/vera/` |
| Engine | `/Users/davidmarsh/Code/Personal/vera-apartment-search` | `omgitsthedm/vera-apartment-search`, `main` | Discovery, enrichment, scoring, private runtime state, and sanitized feed publication |

The Little Fight fleet manifest routes public-product work to the first row and records the engine as an intentional supporting upstream. Do not move the engine as housekeeping because loaded LaunchAgents use its absolute path. Do not route work to a local historical-dashboard checkout.

## Architecture and privacy boundary

```text
public engine source and private runtime state
  -> scripts/public_lens.py and audit_public_payload()
  -> public.json, archive.json, and meta.json on the engine feed branch
  -> exact Little Fight Netlify rewrites under /vera/data/
  -> anonymous browser at littlefightnyc.com/vera/
```

The browser may read only these first-party endpoints:

- `https://littlefightnyc.com/vera/data/public.json`
- `https://littlefightnyc.com/vera/data/archive.json`
- `https://littlefightnyc.com/vera/data/meta.json`

Unfiltered source payloads, owner-only fields, contacts, notes, credentials, logs, local environment files, and private engine state must not enter the website repository, Netlify, the `feed` branch, or this handoff. `scripts/public_lens.py` is the single transformation boundary. `audit_public_payload()` must pass before publication.

The engine GitHub repository is public. The 2026-08-10 review confirmed that tracked `configs/user_preferences.json` contains search criteria and `configs/alerts.json` contains the published Little Fight operational identity plus alert thresholds. Neither file contains a credential field or secret pattern. Treat those settings as public source, not private runtime state.

## Release rails

### Public application

The website's GitHub `main` branch is connected to Netlify site `littlefightnyc`, ID `0907d8fe-7018-48db-a6be-1f906e4b2619`. A normal source push can build and publish production.

Use this rail:

1. Confirm the exact candidate commit, clean worktree, remote relationship, and Netlify site ID.
2. Run `npm run quality:release` from the website repository under Node 24.
3. Push only the authorized commit to `main`.
4. Wait for that exact revision to become the ready production deploy.
5. Run `EXPECTED_REVISION=commit_sha npm run quality:live`.
6. Verify `/release.json`, `/vera/`, and all three `/vera/data/*` responses.

Never run `netlify deploy --prod`, restore a dedicated VERA Netlify project, add VERA Netlify credentials, or point the browser at an upstream host.

### Sanitized feed

`.github/workflows/sanctioned-cloud-sweep.yml` runs the cloud-safe engine, applies the privacy lens, and force-pushes only the three public files to the orphan `feed` branch. It uses the automatic `GITHUB_TOKEN`. Local engine jobs write `publish_status: external`; they never sync or deploy a dashboard.

## Schedules

The following loaded LaunchAgents were verified on 2026-08-10. Times are machine-local:

| Label | Schedule | Entrypoint |
| --- | --- | --- |
| `com.vera.apartment-search.daily` | 08:00 daily | `scripts/run_daily_autonomous.sh` |
| `com.vera.apartment-search.watchdog` | 10:00 daily | `scripts/watchdog_stale_run.sh` |
| `com.vera.apartment-search.nightly` | 23:00 daily | `scripts/run_nightly_autonomous.sh` |
| `com.vera.apartment-search.weekly` | Sunday 19:00 | `scripts/run_weekly_autonomous.sh` |

All four were loaded, idle at inspection time, and reported last exit code `0`. Their tracked templates are the four files in `configs/launchd-v2/`. No unattended schedule installer ships with the engine. Replacing schedules or moving the engine requires a separately authorized maintenance window.

GitHub Actions schedules `sanctioned-cloud-sweep.yml` for 05:30 UTC daily. GitHub may queue the job after that trigger time. Manual dispatch is a production publication action and requires current authorization.

`public-feed-health.yml` is a separate read-only monitor scheduled for 07:00 UTC daily and available through manual dispatch. It performs one GET of the first-party `https://littlefightnyc.com/vera/data/meta.json` route and fails closed if the response is unavailable or invalid, `origin` is not `cloud`, `pool` is empty, or `generated_at` is older than 36 hours. The 90-minute offset follows the expected 05:30 UTC cloud-sweep slot; it allows for the normal sweep duration but does not make GitHub's scheduler punctual. It has read-only repository permission, no secrets, no notifications, and never runs discovery or publishes data.

## Validation commands

Run the engine's isolated checks without reading private runtime data:

```bash
python3 tests/test_scoring.py
python3 tests/test_mail_ingest.py
python3 tests/test_public_lens.py
python3 tests/test_source_honesty.py
python3 tests/test_neighborhood_gate.py
python3 tests/test_public_product_boundary.py
```

The public-product boundary check enforces one public app, no retired deploy entrypoints, no hourly runner, the exact active schedule templates, and this handoff's canonical markers.

The 2026-08-10 documentation closeout ran all six checks successfully. `./scripts/health_check.sh` also reported no failures in the isolated worktree.

For website changes, use the root quality lanes from the website repository:

```bash
npm run quality:fast
npm run quality:full
npm run quality:release
EXPECTED_REVISION=commit_sha npm run quality:live
```

Use the narrowest proportional lane. A production candidate requires `quality:release` before push and revision-bound `quality:live` after Netlify reports the exact deploy ready.

## Evidence snapshot

This snapshot was collected on 2026-08-10 and reconciled after the documentation closeout. Because this handoff is versioned inside the engine repository, it does not hard-code its own containing commit. Re-run the commands below before treating any revision, count, or workflow result as current.

| Evidence | Observed value |
| --- | --- |
| Website GitHub `main` | `8f43c9a7b80791ac067702cfb9ee51934dbc33ca` |
| Live `/release.json` revision | `8f43c9a7b80791ac067702cfb9ee51934dbc33ca`, production, clean source, built `2026-08-10T20:57:03.846Z` |
| Netlify production deploy | `6a7a3b011b38280008c5886a`, ready, Git-connected `main`, published `2026-08-10T20:57:16.023Z` |
| Engine `feed` branch | `a0d8509668000945fcc0e0fc3a9c42d7abef3422` |
| Historical dashboard `main` | `ec61413b2ed6fb6225b46c706ab0711f65fe8d85`, GitHub repository archived and private |
| Latest observed cloud sweep | [Run 31363590525](https://github.com/omgitsthedm/vera-apartment-search/actions/runs/31363590525), successful on engine revision `3604daab0f4e4f1dfbd434284756da4175668b70` |
| Live feed metadata | Generated `2026-08-10T07:13:05Z`; pool `279`; shortlist `22` |
| Live HTTP evidence | `/vera/`, `public.json`, `archive.json`, and `meta.json` returned HTTP `200` |
| Deleted standalone hosting | Netlify project `vera-pipeline` is deleted; its former hostname and data route returned HTTP `404` |

Refresh Git and live evidence with:

```bash
git ls-remote https://github.com/omgitsthedm/littlefightnyc-website.git HEAD refs/heads/main
git ls-remote https://github.com/omgitsthedm/vera-apartment-search.git HEAD refs/heads/main refs/heads/feed
curl -fsSL https://littlefightnyc.com/release.json
curl -fsSIL https://littlefightnyc.com/vera/
curl -fsSIL https://littlefightnyc.com/vera/data/public.json
curl -fsSIL https://littlefightnyc.com/vera/data/archive.json
curl -fsSIL https://littlefightnyc.com/vera/data/meta.json
```

## Retired surfaces

The `omgitsthedm/vera-dashboard` GitHub repository is archived and private. It is the retained historical recovery record, not a deploy target, feed source, or product source. The former local checkout moved intact to `/Users/davidmarsh/.Trash/VERA-production-closeout-20260810/Code/Personal/nyc-apartment-search-dashboard` on 2026-08-10. Do not route future work to its old path or restore the checkout unless David explicitly requests historical recovery.

The former `vera-pipeline` Netlify project is deleted. Its public routes returned `404` during this audit. Do not recreate the project, its credentials, its host, or its deployment path.

The engine no longer carries hourly runners, a local dashboard publisher, or a standalone health publisher. Git history preserves those implementations. Do not recreate them.

## Recovery and next actions

Recover the browser product from verified website Git history and release it through Git-connected Netlify. Treat rollback as a new Git release. Do not use a historical Netlify deploy or the retired dashboard checkout as source.

Recover the engine from `omgitsthedm/vera-apartment-search` `main`. Restore private runtime data only from an owner-approved private backup. Never reconstruct it from the public `feed` branch.

Restore schedules only from `configs/launchd-v2/` during an authorized maintenance window. Confirm every absolute engine path before loading a plist.

One external decision remains:

- **License**: the engine repository has no tracked license file. Describe it as public source, not open source or AGPL-licensed, until David selects and adds a license

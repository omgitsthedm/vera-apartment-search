---
contentType: Reference
title: Operate and recover VERA
verified: 2026-08-16
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
  -> validated Netlify edge cache with bounded stale-while-revalidate
  -> VERA service worker's last-valid publication cache
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
6. Verify `/release.json`, `/vera/`, and all three `/vera/data/*` responses. A
   conditional feed GET must still return `200` with a complete JSON body; a
   bodyless `304` is a release failure.

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

`public-feed-health.yml` is a separate read-only monitor scheduled for 07:00 UTC daily and available through manual dispatch. It performs one GET of the first-party `https://littlefightnyc.com/vera/data/meta.json` route and fails closed if the response is unavailable or invalid, `origin` is not `cloud`, `snapshot_source` is not `latest` (including `last_known_good` fallback), `pool` is empty, or `generated_at` is older than 36 hours. The 90-minute offset follows the expected 05:30 UTC cloud-sweep slot; it allows for the normal sweep duration but does not make GitHub's scheduler punctual. It has read-only repository permission, no secrets, no notifications, and never runs discovery or publishes data.

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

## 2026-08-14–16 restoration and publication-resilience record

VERA stayed reachable, but the public app did not meet its product contract. A slow feed could leave the interface waiting, a browser transition could reject, and Atlas could show coarse blocks or an empty map after a warm route remount. Some listings could also carry an incorrect borough label or coordinates that did not belong in the public map. This record covers the corrective release and the matching engine scope repair.

### What changed

The website repair includes:

- A `3.5s` soft loading status, a `45s` timeout for each attempt, and three
  bounded attempts separated by `750ms` and `2250ms`; a valid `Retry-After` is
  honored up to `10s`
- A fresh manual retry after those attempts, plus guarded resume handling for
  persisted page restores and a visible returning iOS/WebKit tab
- Generation ownership and cancellation so an older request cannot overwrite
  a newer successful boot
- A safe fallback when a browser View Transition times out
- Browser-side coordinate and borough defenses for Atlas, plus real streets and buildings instead of the old block-only treatment
- Refined loading, receipt, filter, and mobile layouts with native controls
- Atlas remount protection: the app mounts the map on the next animation frame after a route transition, which prevents a blank canvas after `Today` then `Atlas`
- Application and CSS query version `v61` and Progressive Web App shell cache
  `vera-shell-v14`; the map remains `v60`

The engine repair is `4ab12e8c845848854518f2b10f42a22952dc0c3e`, the merge of the four-borough public-scope change. `scripts/public_lens.py` is the canonical geography authority for the public payload. New York City Neighborhood Tabulation Area polygons resolve a valid coordinate pair before a source borough label. A listing outside Manhattan, Brooklyn, Queens, or the Bronx, with invalid or incomplete coordinates, or without an approved borough when it has no coordinates, cannot reach any public listing surface. The lens then writes the resolved borough back to the sanitized record, and `audit_public_payload()` rejects a mismatch.

The browser checks this contract again before rendering Atlas. This second check protects visitors from stale or malformed feed data. It does not replace the engine lens or permit the browser to access private data.

### Publication transport repair

The August 16 failure message was not caused by an absent feed. A repeat visit
could forward a browser validator through the Netlify edge to the upstream
publication, receive a bodyless `304`, and pass that non-OK response to the
application even when the JSON publication itself was healthy.

Website PRs [16](https://github.com/omgitsthedm/littlefightnyc-website/pull/16)
and [17](https://github.com/omgitsthedm/littlefightnyc-website/pull/17) repair the
complete path:

- The edge uses the normal downstream request path, validates a complete
  endpoint-specific JSON body, and never shares an error or malformed `200`.
- Browser HTTP caching is disabled with `Cache-Control: no-store`, upstream
  validators are removed, and a conditional first-party GET still returns a
  complete `200` representation.
- Netlify's private shared cache keeps a valid publication fresh for five
  minutes and may serve it stale for up to 36 hours while revalidating.
- The service worker validates public, archive, and metadata contracts before
  saving or serving them. It falls back to the last valid cached publication on
  a network failure, `304`, `429`, `5xx`, or malformed `200`; invalid legacy
  entries are pruned.
- Cache writes are tied to the fetch-event lifetime, and an older
  `generated_at` value cannot overwrite a newer cached publication.

The cached publication is an availability fallback, not proof of freshness.
The displayed `generated_at` timestamp remains authoritative, and the browser
labels a saved fallback as an offline copy.

### Release evidence

| Surface | Verified value | Dated status |
| --- | --- | --- |
| Engine `main` | `4ab12e8c845848854518f2b10f42a22952dc0c3e` | Merged four-borough scope enforcement |
| Engine `feed` | `966de3d0afae472c282b6987d9c024b6bd884f27` | Sanitized cloud feed after the scoped sweep |
| Cloud sweep | [Run 31859782209](https://github.com/omgitsthedm/vera-apartment-search/actions/runs/31859782209) | Succeeded |
| Feed metadata | Generated `2026-08-15T02:59:08+00:00`; pool `267`; shortlist `24` | Live first-party data matched the feed commit |
| Initial website recovery | `9dac6a76c876fbef50ad9584cd927068873c88c9` | Live through Git-connected Netlify |
| Initial Netlify deploy | `6a7fd1f274e9be00089d10c3` | Ready production deploy, published `2026-08-15T02:42:34.906Z` |
| Atlas remount correction | `8ec1106641005e646a276d5700293f61b2bc5e65` | Merged through [website PR 15](https://github.com/omgitsthedm/littlefightnyc-website/pull/15) |
| Corrective Netlify deploy | `6a7fda7c92046d000814a720` | Ready production deploy, published `2026-08-15T03:19:02.923Z` |
| Live release | `8ec1106641005e646a276d5700293f61b2bc5e65` | `/release.json` matched GitHub `main`; `quality:live` passed |
| Publication retry and worker repair | `974cba66bc27e9a5134ee6d4982f062c32c26d73` | Merged through website PR 16 |
| Final edge response contract | `a8bf1045b8d200f123347dea17eee35de6e8e7d1` | Merged through website PR 17; live `/release.json` matched |
| Final Netlify deploy | `6a827b370ade700008da5e90` | Ready production deploy, published `2026-08-17T03:09:22.056Z` |

The scoped live feed audit found no public-payload or geography problems. It contained `149` Manhattan, `71` Brooklyn, `32` Queens, and `15` Bronx listings. Of `267` listings, `206` had coordinates and `61` used the permitted no-coordinate borough path. These counts are a dated observation, not a product guarantee.

The final publication-resilience gate passed `312` unit tests and `248` browser
executions across desktop and mobile Chromium, Firefox, desktop WebKit, iPhone
WebKit, and iPad WebKit. Deterministic worker and edge suites cover `304`,
`429`, `503`, rejected requests, invalid `200` bodies, legacy-cache migration,
cache-write lifetime, out-of-order publications, slow success, automatic
recovery, bounded retries, and manual retry. A production fresh boot and reload
both rendered the current publication without the failure message or console
errors. Treat later browser, feed, edge, or worker changes as a reason to rerun
the gate, not as proof that the same result still holds.

### Revalidate a public release

Run the website commands from the canonical website repository under Node 24:

```bash
npm run quality:release
EXPECTED_REVISION=commit_sha npm run quality:live
curl -fsSL https://littlefightnyc.com/release.json
curl -fsSIL https://littlefightnyc.com/vera/
curl -fsSL https://littlefightnyc.com/vera/data/public.json >/dev/null
curl -fsSL https://littlefightnyc.com/vera/data/archive.json >/dev/null
curl -fsSL https://littlefightnyc.com/vera/data/meta.json >/dev/null
curl -fsSL -H 'If-None-Match: "vera-revalidation-check"' \
  https://littlefightnyc.com/vera/data/public.json >/dev/null
```

Replace `commit_sha` with the exact merged website revision. Confirm that `/release.json` reports that revision and that Netlify marks the corresponding Git-connected production deploy ready. Then test a fresh Atlas load and the route sequence `Atlas` to `Today` to `Atlas` on the relevant browser profiles. Do not perform a manual Netlify production deploy.

To validate the engine boundary without opening private runtime data, run:

```bash
python3 tests/test_scoring.py
python3 tests/test_mail_ingest.py
python3 tests/test_public_lens.py
python3 tests/test_source_honesty.py
python3 tests/test_neighborhood_gate.py
python3 tests/test_public_product_boundary.py
```

Refresh the release chain before a recovery action:

```bash
git ls-remote https://github.com/omgitsthedm/littlefightnyc-website.git \
  HEAD refs/heads/main
git ls-remote https://github.com/omgitsthedm/vera-apartment-search.git \
  HEAD refs/heads/main refs/heads/feed
curl -fsSL https://littlefightnyc.com/release.json
```

### Recovery, rollback, and follow-up

Recover or roll back the public application by creating a reviewed Git commit from a known website revision, merging it to website `main`, and verifying the new Git-connected Netlify deployment. Do not republish a historical Netlify deploy, recreate `vera-pipeline`, or restore the dashboard.

Recover the engine from engine `main`. Restore private runtime state only from an owner-approved private backup. Never use the public `feed` branch as a private-state backup. Restore LaunchAgents only from `configs/launchd-v2/` during an authorized maintenance window after checking every absolute path.

The separate shared website dependency item is complete. Website `main` revision `1a74dce054d56653430ac8d2742e0a08cc6fe6d8` updates `@netlify/blobs` from `10.7.11` to `10.7.13` without changing VERA application files, clears the production dependency audit, and is live as Netlify production deploy `6a80385d91786e0008821986`. The isolated Node 24 release gate passed 312 Dakota tests, 239 multi-engine browser tests, the build and substantive audits, followed by revision-bound `quality:live`. Five unrelated dirty Little Fight entries were excluded and remain preserved in the canonical checkout.

The next action is routine observation only: let the scheduled feed publication
run and rerun the same first-party feed, conditional-response, and geography
checks if its listing counts or scope change. Keep the browser at
`littlefightnyc.com/vera/` and keep the engine privacy boundary unchanged.

## Earlier VERA 2.0 public release record

The public VERA 2.0 release is live through the existing website rail. This is
a browser-product record, not an engine or feed-schema release.

| Field | Verified release value |
| --- | --- |
| Release ID | `vera-2.0-2026-08-13` |
| Public feature commit | `5320c757ab89ac44c90658d207ac6ccb3f8cec7f` |
| Final public revision | `0a4d1d4a31ea3c2ac1f512afa653bb305dbc9183` |
| Netlify production deploy | `6a7d752e5c61310008bc3a9f`, ready and tied to the final revision |
| Public verification | `quality:release` PASS with 173/173 browser executions; revision-bound `quality:live` PASS; live VERA harness 160/160 |
| Release decision | `In Observation`; no known P0/P1 product blocker, with dated operational and manual-device follow-up retained in the dossier |
| Durable dossier | Website repository `.lifi/evidence/releases/vera-2.0-2026-08-13/` |

The release did not change engine code, private runtime data, ranking, feed
schema, feed publication, or LaunchAgent schedules. The dossier may record
public release facts and redacted evidence only. It must not absorb raw listing
data, contacts, credentials, private paths beyond routing references, or engine
runtime artifacts.

## Evidence snapshot

This snapshot was refreshed on 2026-08-16 after the publication-resilience
release. Because this handoff is versioned inside the engine repository, it
does not hard-code its own containing commit. Re-run the commands below before
treating any revision, count, or workflow result as current.

| Evidence | Observed value |
| --- | --- |
| Website GitHub `main` | `a8bf1045b8d200f123347dea17eee35de6e8e7d1` |
| Live `/release.json` revision | `a8bf1045b8d200f123347dea17eee35de6e8e7d1`, production `main`, built `2026-08-17T03:09:08.852Z` |
| Netlify production deploy | `6a827b370ade700008da5e90`, ready, Git-connected `main`, published `2026-08-17T03:09:22.056Z` |
| Engine `main` | `2b0a5ec9426a27b6c4aa04d4fb6396232140ec55` |
| Engine `feed` branch | `5e60d39ac89d89f05b55ed95b05b6694af34b1cb` |
| Historical dashboard `main` | `ec61413b2ed6fb6225b46c706ab0711f65fe8d85`, GitHub repository archived and private |
| Latest observed cloud sweep | [Run 31930101946](https://github.com/omgitsthedm/vera-apartment-search/actions/runs/31930101946), successful on engine revision `2b0a5ec9426a27b6c4aa04d4fb6396232140ec55` |
| Live feed metadata | Generated `2026-08-16T06:16:56+00:00`; pool `264`; shortlist `25`; Manhattan `142`, Brooklyn `76`, Queens `32`, Bronx `14`, out of scope `0` |
| Live HTTP evidence | `/vera/` and all three data endpoints returned `200`; conditional data GETs also returned complete `200` JSON; browser cache `no-store`; Netlify private cache hit |
| Deleted standalone hosting | Netlify project `vera-pipeline` is deleted; its former hostname and data route returned HTTP `404` |

Refresh Git and live evidence with:

```bash
git ls-remote https://github.com/omgitsthedm/littlefightnyc-website.git HEAD refs/heads/main
git ls-remote https://github.com/omgitsthedm/vera-apartment-search.git HEAD refs/heads/main refs/heads/feed
curl -fsSL https://littlefightnyc.com/release.json
curl -fsSIL https://littlefightnyc.com/vera/
curl -fsSL https://littlefightnyc.com/vera/data/public.json >/dev/null
curl -fsSL https://littlefightnyc.com/vera/data/archive.json >/dev/null
curl -fsSL https://littlefightnyc.com/vera/data/meta.json >/dev/null
curl -fsSL -H 'If-None-Match: "vera-revalidation-check"' \
  https://littlefightnyc.com/vera/data/public.json >/dev/null
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

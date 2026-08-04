# VERA Platform — Version History

The canonical changelog for the whole platform: engine (this repo),
dashboard (`nyc-apartment-search-dashboard`), and the littlefightnyc.com
mount. Every change wave gets an entry here; the current version lives in
`VERSION` and is stamped into every published snapshot (`app.version`).

Component prefixes: **engine** · **dashboard** · **site** (littlefightnyc.com) · **ops** (scheduling/infra).

---

## 1.2.0 — 2026-08-04 · "The Verification Layer Tells the Truth"

The campaign that rebuilt VERA around a public product, then spent the
last stretch finding out why its core output was empty. Both causes were
in the plumbing, not the market.

### engine
- **Empty drop, cause 1: no retry on city outages.** A sweep's building
  lookups all returned HTTP 503, so no listing earned a BBL, risk scores
  fell back to the synthetic 50/45 defaults, `has_synthetic_risk_scores()`
  flagged every survivor and the scorer correctly refused to recommend
  anything. An earlier sweep the same day matched 17 buildings; the only
  difference was upstream weather. `read_json_url` now retries 5xx and
  timeouts with backoff (1.5s/3s/6s) and still raises 4xx immediately.
- **Empty drop, cause 2: borough-as-neighborhood.** 189 of 248 listings
  carried a borough ("Brooklyn") in the neighborhood field, so the cheap
  filter rejected them as "outside target neighborhoods" and they never
  reached a city-record lookup at all. `config/nta_lookup.py` resolves
  those coordinates to the true NTA2020 neighborhood, and both filters now
  match compound city names ("Upper East Side-Lenox Hill-Roosevelt
  Island", "East Harlem (South)") that exact matching could never hit.
  **Verification coverage 18 → 51 listings per sweep.** Target list
  unchanged; out-of-area listings still fail.
- **Full-city geography.** `build_nta_polygons.py` derives all 197
  residential NTAs from DCP NTA2020 (simplified ~22m, 167KB), replacing a
  70-hood focus subset. Borough-only resolution 62 → 167.
- **records_health** published end-to-end so a dead verification layer is
  never mistaken for a quiet day.
- **Forensic tells now count** (approved weights): relist −10, contact
  reuse −15, description clone −25, photo clone −20, capped −45, each
  deduction named on the listing.
- **Photo forensics**: perceptual hashing catches re-uploaded stolen
  photos; provenance scanning reads C2PA/XMP/EXIF generator markers as
  fact. An ML classifier was deliberately declined — see
  `docs/proposals/ai-photo-detection.md`.
- **Real transit**: MTA GTFS static supplies 496 stations and scheduled
  ride times, so commute minutes are quoted rather than invented.
- **Cloud-daily proven**: the full pipeline discovered 233 listings on
  GitHub runners (94% of local yield). Craigslist's API serves datacenter
  IPs fine; only renthop/leasebreak refuse.
- **Source honesty**: nybits, nooklyn and Housing Connect answered 200
  with JavaScript shells and yielded zero while reading green. Disabled
  with an explicit status; per-source `record_count` now published.
- Email-alert ingestion and Reddit OAuth are wired and config-absent-safe,
  awaiting credentials.

### site
- Ground-up rebuild: the daily drop, Steward Grades cited to HPD/DOB/311,
  Receipts archive, printable field kit, corrections channel, fair-housing
  statement, move-in ledger.
- **A real map**: MapLibre GL over OpenFreeMap vector tiles, listings as
  living markers, the hand-drawn city kept as offline fallback.
- One spring-based motion language across every surface, reduced-motion
  respected throughout.
- 89 in-page acceptance checks.

### ops
- Sanctioned cloud sweep runs daily on GitHub Actions; cloud publish
  awaits repository secrets.

---

## 1.1.0 — 2026-07-23 · "The Reviewed Building"

### engine
- **openigloo source rebuilt** (lost with the `~/Projects` copy in June, existed in no surviving code). Server-rendered unit cards carry everything VERA needs, so discovery costs one request per borough with zero detail fetches. Verification yield: **52 records** across Manhattan/Brooklyn/Queens/Bronx with 100% field coverage (address, zip, beds/baths, photos), two spot-checked against their live detail pages.
- The rebuild captures openigloo's signature signal the old adapter never had: **tenant building-review scores** (25 of 52 rated), **rent-stabilized / good-cause / verified badges** (35 flagged), and **price-drop detection** from struck-through prices (11 found). These flow into the record body, amenities, and a rent-stabilization hint.
- Groundwork: the StreetEasy React Flight parser was generalized (`_next_flight_stream` / `_next_flight_chunks`) for reuse across Next.js sources.

---

## 1.0.3 — 2026-07-23 · "Right Borough"

### engine
- Neighborhood labels corrected from the map, not the ad: when GeoSearch confidently resolves a building somewhere other than the listing's claimed neighborhood, the resolved place wins ("East Village" was being stamped on a Rosedale, Queens house because source hints echo the search query). Original hint preserved in `neighborhood_raw`; correction noted on the record.

---

## 1.0.2 — 2026-07-23 · "Pictures or It Didn't Happen"

### engine
- Photos now actually reach the shortlist: `normalize_listings.py` parsed `image_urls` from raw records but never emitted them — the field existed in every downstream schema, permanently empty, in every era of the pipeline. One line; the 1.0.1 extraction work now flows end-to-end.

---

## 1.0.1 — 2026-07-23 · "Wide Net"

### engine
- craigslist expanded city-wide: all five boroughs queried (was Manhattan+Brooklyn), 50 results/query — 228 records in verification (MN 49 / BK 50 / QN 48 / BX 50 / SI 31). Fixed a silent scope bug: `user_preferences.json` borough filter was overriding catalog discovery scope; catalog now defines the net, prefs only trim text-query noise.
- Listing photos restored: full-size images extracted (thumbnail-free, deduped, capped at 6) — 87% coverage in verification; StreetEasy photos flow through the Flight parser; RentHop JSON-LD images confirmed wired.

---

## 1.0.0 — 2026-07-23 · "Resurrection"

The day VERA became a platform. Full audit → rebuild → public launch in one wave.

### ops
- Engine consolidated at `~/Code/Personal/vera-apartment-search` (off iCloud, TCC-safe), first-ever git remote (private GitHub).
- launchd schedule restored: nightly 23:00 / daily 08:00 / weekly Sun 19:00 ET, once-per-ET-date guards; stale-run watchdog (Mac notification + ntfy phone push at >30h).
- Netlify data feed renamed `vera-pipeline` (was `nyc-apartment-search-vera`); littlefightnyc.com proxies from it — feed = loading dock, never a destination.
- Root-caused and fixed the silent publish gate: archive-era `.env` exported a dead `VERA_ROOT`; runners and publish now re-assert the checkout path after env load.

### engine
- **Ownership layer (new)**: HPD registration contacts + PLUTO + portfolio estimation resolve real `owner_name`/`owner_type` (individual / LLC / HDFC) per building; co-op detection via PLUTO building classes; GeoSearch unit-strip retry for higher BBL match rates. "Private landlord" is now records-driven, not text-guessed.
- craigslist scraper rebuilt on the `sapi` JSON endpoint (old HTML search was a dead JS shell): 0 → 59 records, borough-scoped queries, scam-price de-obfuscation.
- StreetEasy scraper rebuilt for React Flight streaming markup: 0 → 4 records (thin market at the $2,500 cap is real, documented).
- Big-three sources restored to daily cadence (hourly cadence had orphaned them); dead HDC source honestly disabled; ollama made optional (deterministic mode).
- Deterministic/free mode: `OPENAI_API_KEY` unset by runners; enrichment runs rules-only. Platform cost: $0/month.
- ntfy nightly digest (`notify_digest.py`) + zero-dependency `vera` MCP server (shortlist/listing/changes/status) registered for Claude sessions.

### dashboard
- Complete rebuild as branded mission control (commit `4742fdf`): radar-sweep insignia, token system, IBM Plex self-hosted, nav rail (Overview · Shortlist · Map · Intel · How it works · Ops), dossier deep links (`#/listing/<uid>`), self-hosted Leaflet map, lens dials that re-rank client-side, truth-telling Ops preserved.
- Payload split: `hunt.json` (full, `?full=1`) / `public.json` (default — landlord contacts, personal notes, and watchlist editorial stripped) / `dashboard.json` (ops, lazy).

### site
- **littlefightnyc.com/vera launched** — the platform's canonical front door and the first live entry in the "personal builds as public examples" program. Static mount in `app/public/vera/`, data proxied live from vera-pipeline, `/VERA` normalized, sitewide CSP passed without exceptions.

### Known gaps at 1.0.0
- Listing photos not yet extracted by rebuilt scrapers (fix in flight).
- craigslist queries limited to Manhattan/Brooklyn (borough expansion in flight).
- openigloo source (14 records in June) not yet rebuilt; nybits/nooklyn/housing_connect yield zero.
- Portfolio estimates null for 1–2 family homes (no HPD registration requirement — expected).
- Shortlist rebuilding from scratch post-resurrection; June-scale depth (~25 visible) returns as nightly runs accumulate.

---

## Prehistory (0.x, unversioned)

- **0.3** · 2026-04-01 → 06-30 — `~/Projects` era: nightly/daily/weekly production, 12 sources, ~140 records/night, 59k-record June peak. Killed mid-flight by the Jun-30 home-folder sweep; schedulers disabled Jul-3; survived only in a Jul-16 archive.
- **0.2** · 2026-03-26/27 — VERA proper: git repo, 6-dataset public-records vetting, scoring engine, publish guards. Broken by macOS TCC on the iCloud Desktop 3 days later.
- **0.1** · 2026-03-17 — `apartment_hunter` prototype (OpenClaw era).

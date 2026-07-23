# VERA Platform — Version History

The canonical changelog for the whole platform: engine (this repo),
dashboard (`nyc-apartment-search-dashboard`), and the littlefightnyc.com
mount. Every change wave gets an entry here; the current version lives in
`VERSION` and is stamped into every published snapshot (`app.version`).

Component prefixes: **engine** · **dashboard** · **site** (littlefightnyc.com) · **ops** (scheduling/infra).

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

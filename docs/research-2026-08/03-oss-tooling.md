# NYC Apartment-Search Engine: Build-vs-Adopt Research (Aug 2026)

Research agent report, 2026-08-03.

## 1. Housing-data backbone: adopt wholesale

**nycdb** (github.com/nycdb/nycdb) alive, actively maintained — last push 2026-06-30 (PLUTO FAR/MIH columns, #407); June 2026 updates for DCP Housing DB + open-data schema drift. Python CLI (`pip install nycdb`, or Dockerfile + docker-compose) that downloads/cleans/loads ~65 datasets into Postgres. Load: `hpd_violations, hpd_complaints, hpd_registrations, hpd_litigations, hpd_charges, dob_violations, dob_complaints, dobjobs, acris, pluto_latest, pad, rentstab_v2 + rentstab_summary` (stabilized unit counts — THE join for stabilization detection), `marshal_evictions, executed_evictions, oca` (housing court), `oath_hearings, ecb_violations, dohmh_rodent_inspections, dos_active_corporations, speculation_watch_list, nycha_bbls`. Re-run `nycdb --download/--load` per dataset; upstream YAMLs track revisions. **The HDC/JustFix shared instance is no longer public** (PR #400, Apr 2026) — self-host or nothing. AGPLv3 code, CC BY-NC-SA data.

**JustFix Who-Owns-What** (github.com/JustFixNYC/who-owns-what, pushed 2026-07-22), on nycdb. `portfoliograph/` (graph.py, standardize.py, landlord_index.py) builds the LLC-linking graph: nodes = standardized HPD-registration contact names + business addresses; edges = name↔address co-occurrence with fuzzy matching; connected components = portfolios. Django `wow/` app exposes unauthenticated JSON endpoints: `address`, `address/aggregate`, `address/buildinginfo`, `address/indicatorhistory`, `address/export`, `address/latestdeed`, district alert feeds, `signature/*` (Signature-portfolio dashboard in same repo). **Steal `portfoliograph` + `sql/` rather than reimplementing landlord dedup.**

**ANHD DAP Portal** (portal.displacementalert.org; github.com/ANHD-NYC-CODE) = reference implementation for district-dashboard + property-lookup UX; WOW ships `address/dap-aggregate` for it. **Heatseek**: dormant (2023) — historical only.

## 2. Apartment-hunting GitHub repos

- **VikParuchuri/apartment-finder** (1,059★): archived, dead since 2019. Architecture (poll CL → filter price/transit → Slack) still canonical; copy the shape, don't run it.
- **moritzWa/ai-apartment-finder** (pushed 2026-07-23): the modern successor. Scrapes Craigslist (cheerio), FB Marketplace + StreetEasy (Apify actors) twice daily on GitHub Actions cron, dedupes into SQLite, LLM-scores 0–10 against a written rubric (fake 2BRs, "garden" basements, flex walls, scam prices), texts survivors via SendBlue/iMessage. `source_health` table detects layout changes (0 results twice in a row). No server. **Steal: rubric-as-prompt classifier, source-health canary, SQLite-as-only-state.**
- **osaidd/rental-inbox** (pushed 2026-07-30, PyPI `uvx rental-inbox`): parses your own StreetEasy/Zillow ALERT EMAILS via Gmail + scrapes CL, into a ranked mapped local dashboard with plugin folder. **Email ingestion = the single best ToS-safe way to get StreetEasy listings in 2026.**
- Craigslist: **irahorecka/pycraigslist** (pushed 2026-04) maintained; RSS long dead; low-frequency HTML scraping works.
- StreetEasy scrapers: Selenium-era ones broken; SE blocks since 2017. BoreMore/streeteasy-area-ids has useful area-ID mapping. RoboHouse deleted.
- FB Marketplace: **danyk20/facebook-marketplace-scraper** (pushed 2026-07-07) works headless at personal scale.

## 3. openigloo, apartmentaudit.nyc, RentReboot

**openigloo**: NO public API 2026; daily HPD-derived data + crowdsourced reviews (the one corpus you can't rebuild — and can't access). **apartmentaudit.nyc**: alive; per-address maintenance/litigation/eviction/bedbug grading straight from NYC Open Data — proof the data half is rebuildable. **RentReboot**: alive, press-covered; cross-references live StreetEasy listings against the rent-stabilized building list, emails matches; ships a Chrome extension overlaying stabilization odds on StreetEasy. **Steal both: listings×rentstab join, extension-overlay surface.**

## 4. AI-era tools (2025–2026)

Zillow: NL search → real-estate app inside ChatGPT (Oct 6, 2025) → **Zillow AI Mode** (Mar 25, 2026, cross-session memory + tour scheduling). Redfin (Feb 2026), Realtor.com (Mar 2026) ChatGPT apps. All MCP-under-the-hood but ChatGPT-exclusive. Open(ish): Apify-hosted Zillow/Redfin MCP (paid), sap156/zillow-mcp-server, ATTOM (Jan 2026) + Cotality (Mar 2026) enterprise MCP. **None knows NYC-specific truth (stabilization, HPD history, portfolios) — that's the edge.** **Realer Estate** (realerestate.org, the teens' portal, NYT/CBS Nov 2025) already fuses listings + public data for below-market/stabilized finds, drew investment: closest competitor and validation.

## 5. What power users recommend

HN 2025–26: theretowhere.com (commute/preference heatmaps, 321pts), streetleaky.com (Jul 2026 extension overlaying complaints on listings), realest.casa, howfar.nyc, Realer Estate. Reddit circuit: RentReboot for stabilized alerts, openigloo for vetting, StreetEasy saved-search emails as the de-facto feed, FB groups/Listings Project for no-fee. **Pattern: nobody scrapes StreetEasy; they overlay it (extensions) or ingest its emails.**

## 6. StreetEasy/Zillow access reality (2026)

Zillow consumer API dead since 2021; Bridge = MLS-only. Zillow runs Imperva WAF + fingerprinting; low-volume Playwright+stealth works, ToS prohibits. StreetEasy: no API, RSS 403s (verified), press-and-hold CAPTCHA. **Verified working: StreetEasy official market-data CSVs still free** (`cdn-charts.streeteasy.com/rentals/All/medianAskingRent_All.zip` → 200; the city itself pipelines these). Personal read-only viability: alert-email parsing + extension overlay + aggregate CSVs; direct crawling fragile/hostile.

## Verdict table

| Tool | Verdict |
|---|---|
| nycdb (Docker/pip) | ADOPT |
| who-owns-what portfoliograph + WOW API | ADOPT |
| RentReboot rentstab join; extension overlay | STEAL PATTERN |
| rental-inbox (email ingestion) | ADOPT/STEAL |
| moritzWa/ai-apartment-finder | STEAL PATTERN |
| pycraigslist; danyk20 FB scraper | ADOPT |
| apartmentaudit.nyc / DAP Portal / theretowhere | STEAL PATTERN |
| StreetEasy CDN market CSVs | ADOPT |
| VikParuchuri finder, Heatseek, old SE scrapers | IGNORE |
| openigloo API, Zillow Bridge, ChatGPT apps, Apify MCP | IGNORE |

## Stack recommendation (personal scale)

1. **Base**: Postgres + nycdb; load pluto_latest, pad, hpd_violations, hpd_complaints, hpd_registrations, hpd_litigations, dob_complaints, dob_violations, rentstab_v2, marshal_evictions, oca, dohmh_rodent_inspections, acris. Weekly cron refresh.
2. **Landlord layer**: vendor portfoliograph + sql/ locally; WOW hosted JSON for one-offs.
3. **Listings intake**: StreetEasy/Zillow saved-search alert emails → Gmail parser (rental-inbox base), pycraigslist poller, FB scraper — launchd cron into SQLite/Postgres.
4. **Join**: listing address → BBL via pad/GeoSearch → violations-per-unit, portfolio size, evictions, stabilization likelihood (rentstab_v2 units>0 + pre-1974 + 6+ units), bedbug/rodent history.
5. **Score + notify**: LLM rubric classifier → alert only ≥ threshold; source-health canary.
6. **Browse surface**: optional Chrome extension overlaying the dossier on StreetEasy.

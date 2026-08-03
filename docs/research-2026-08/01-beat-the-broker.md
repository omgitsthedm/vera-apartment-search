# How NYC Brokers Get Inventory First — and How to Beat Them (August 2026)

Research agent report, 2026-08-03. Claims carry source URLs; folklore marked.

## 1. The broker supply chain and the lag

**Verified:** The REBNY RLS is a broker-only exclusives-sharing system (rebuilt on CoStar infrastructure) that syndicates to ~200 consumer sites — brokers see RLS entries before portal syndication completes (rebny.com/rls, CitySignal, Bisnow). Crucially, StreetEasy refused the RLS feed, so agents enter listings there directly — RLS is not StreetEasy's source (TRD 2017). Back-office rental inventory lives in **OLR** (olr.com, legacy duopoly with RealPlus) and, on the landlord side, **Funnel (ex-Nestio)** — leasing CRM that syndicates availability from big owners' systems outward (Inman 2019, TRD 2018). **Correction to the premise:** UrbanDigs is a Manhattan/Brooklyn *sales* comps/analytics tool for agents, not a rental inventory pipe.

**Lag:** NYC rentals list only 30–60 days before availability (Brick Underground). One summer-2026 tracker (50,130 units, 20 platforms, June 1–Jul 14) found StreetEasy first-publishes 69.8% of listings; Zillow follows shared inventory in ~1 hour but originates ~4.6%; landlord portals post pre-dawn (TF Cornerstone ~2:39 AM) while aggregators cluster 1:30–2:30 PM; openigloo and Craigslist each surface ~7% of first looks (rentreboot.com/guide/nyc-rental-platform-data-report-summer-2026 — SEO/content site with stated methodology but unaudited; treat magnitudes, not decimals). Same site: pocket-listing → broker-blast → syndication sequence of 24–48 hours insider circulation, ~20% of rentals never publicly listed — **folklore-adjacent**: directionally consistent with broker quotes, the 20% figure unverified.

## 2. Post-FARE Act reality (one year in)

**Verified:** FARE (Local Law 119 of 2024) took effect June 11, 2025; Second Circuit rejected REBNY's appeal July 2026 (Crain's, TRD). Day one, ~1,355 listings vanished from StreetEasy in 24 hours; the no-fee button was retired (amNY). A year later: May 2026 citywide inventory 33,064, −10.7% YoY; June 2026 Manhattan inventory −16%, record median $5,295, non-doorman rents +18% YoY vs +4% doorman — fees baked into rent on the small-landlord segment (Brick Underground, StreetEasy blog). Enforcement real but small: 2,000+ DCWP complaints, 74 summonses (~100 violations), ~$27K penalties, ~$15K OATH-ordered refunds by mid-2026 (Queens Chronicle).

**Documented workarounds:** relabeled "management/administrative/technology fees" up to ~$4,200 (Milton Coste); steering tenants to "hire" the broker for off-market units — DCWP/OATH cases exist; a "shadow market" of unlisted units, predicted pre-passage (TRD Dec 2024). Self-listing is priced: StreetEasy FRBO costs $249/2 weeks, so small landlords lean on free channels — Craigslist, openigloo (free no-fee/owner filters), Facebook groups, Leasebreak, Listings Project. **Owner-paid/no-fee inventory now surfaces first on free channels and landlord sites, not StreetEasy.**

## 3. Pre-listing public-data signals (real vs. wishful)

All datasets real, on NYC Open Data (IDs verified via API this week). Most predict *building-level* events, not unit availability. The strongest unit-level predictor remains **inferred lease expiry** — a unit listed/rented ~12/24 months ago comes due on schedule (build from portal history; folklore-free but DIY). Ranked:

- **Strong:** HPD Registration Contacts (owner/agent names + addresses for direct outreach — the actionable payload); DOB alteration filings on small buildings (gut reno → re-rent at completion); new-building C of O (lease-up pipeline before marketing).
- **Medium:** ACRIS deed transfer to a new LLC on a 6–20 unit building (turnover coming, months-scale, monthly-updated data); marshal evictions (daily, unit-specific, low volume, ethically grim); vacate orders rescinded (rare).
- **Weak:** Housing litigation resolutions.

## 4. What the industry says

Compass's Jason Haber: apartment hunting is now "like it's 1999 … you have to know who to call" (NY Post). Post sources describe unlisted "shadow market" units preserving tenant-paid fees. Corcoran COO Gary Malin attributes non-doorman rent spikes to FARE cost-shifting. StreetEasy's economists counter that undersupply, not FARE, drives rent growth. Hell Gate found enforcement toothless at six months. The "rents jumped 15%" claim was early tabloid framing; measured data shows ~6–8% on re-listed formerly fee-bearing units.

## BEAT THE BROKER PLAYBOOK (effort → payoff)

1. **Low/high — 15-minute alert loop:** StreetEasy saved-search + openigloo + Craigslist past-12h + RentHop new. Most units findable within 24h of first post; speed beats access for ~75% of the market.
2. **Low/high — check landlord sites at 7 AM:** big-owner portals (TF Cornerstone, Glenwood, StuyTown, Douglaston…) post hours before aggregators, owner-paid by definition.
3. **Medium/high — portfolio direct-contact:** pick 20 buildings you want; pull owner/managing-agent phone from HPD Registration Contacts or WhoOwnsWhat.justfix.nyc; call about upcoming vacancies. This is the FARE-era shadow-inventory channel.
4. **Medium/medium — supers + neighborhood walk:** folklore-that-works per multiple guides; tip culture real but anecdotal.
5. **Medium/medium — dead-listing revival:** email agents on units marked rented 45–60 days ago; fall-throughs common (single-source claim).
6. **High/medium — data watchlist:** script the appendix datasets for target blocks (new C of O, Alt-filings completing, deed transfers). Weeks of lead time, building-level only.
7. **Know your rights:** listing broker demanding a fee or "steering" you into hiring them = DCWP complaint; refusing the fee is legally protected (NYC.gov FAQ).

## DATASETS appendix (NYC Open Data, IDs verified Aug 2026)

| Dataset | ID | Cadence |
|---|---|---|
| HPD Multiple Dwelling Registrations | tesw-yqqr | Annual cycle (due Sept 1), refreshed monthly |
| HPD Registration Contacts | feu5-w2e2 | Same |
| DOB Job Application Filings (BIS) | ic3t-wcy2 | Daily |
| DOB NOW: Build – Job Filings | w9ak-ipjd | Daily |
| DOB Permit Issuance | ipu4-2q9a | Daily |
| DOB Certificate of Occupancy | bs8b-p36w | Daily |
| ACRIS – Real Property Master (+Legals 8h5j-fqxa) | bnx9-e6tj | ~Monthly (laggy: 1–2 wks to record) |
| Evictions (DOI/Marshals, executed) | 6z8x-wfk4 | Daily |
| Order to Repair/Vacate Orders (HPD) | tb8q-a3ar | Daily |
| Housing Litigations (HPD) | 59kj-x8nc | Monthly |

Housing-court filings (holdovers pending) are NY State OCA data, not NYC Open Data — via Housing Data Coalition/nycdb mirrors.

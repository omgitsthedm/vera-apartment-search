# Where Small NYC Landlords Advertise Vacancies — August 2026

Research agent report, 2026-08-03.

**Market context.** One year post-FARE: 1,000+ listings vanished from StreetEasy day one, Manhattan new listings −35%, citywide inventory 33,064 May 2026 (−10.7% YoY). **The decisive stat (RentReboot summer-2026 study: 50,130 apartments, 20 platforms, Jun 1–Jul 14): 51.3% of apartments appeared on exactly ONE site — 77% for units under $2,500.** The small-landlord budget segment is structurally fragmented and must be monitored per-channel.

## Channel census (volume / owner-share / monitorability / scam risk)

- **Craigslist** — 645 Manhattan listings in the 6-wk study, larger outer-borough; median $2,600. High owner-direct ("carries what aggregators never see"). **2026 change: consolidated to `www.craigslist.org/search/area/newyork?cat=hhh`** (old `newyork.craigslist.org/search/*` 301s; `/search/abo` 404s — use `?cat=` codes). SSR HTML, pollable; RSS dead; IP rate-limits. Scam risk HIGH (16% of FTC-reported rental scams).
- **Facebook Marketplace + groups** (Gypsy Housing etc.) — large, high owner-direct in groups; **unmonitorable within ToS** (login walls, no API); ~50% of US rental-scam reports start on FB. Human spot-checks only.
- **Listings Project** — 370 NYC listings/week, Wednesdays, human-vetted, mostly sublets/furnished. SSR, no signup wall on /real-estate/new-york-city; weekly diff trivial. Scam risk low.
- **Leasebreak** — 403s bots; tenant lease-breaks not owners; headless required.
- **Reddit r/NYCapartments + borough subs** — steady daily by-owner posts; Reddit OAuth JSON free tier works for new-post polling. (2026 rule text unverified — check flair/price rules manually.)
- **Nextdoor** — low volume, high owner-share, login-walled. Skip.
- **Zillow FRBO** — small but real owner subset; PerimeterX anti-bot; commercial scraper APIs only.
- **Furnished Finder** — NYC 526 / Brooklyn 828 / Queens 147; ~100% owner-direct; mid-term/furnished niche; indexable pages.
- **SpareRoom/Roomi** — rooms mostly; whole-unit volume marginal.
- **Chinese channels** — dadi360 (Flushing "非中介无佣金" forum), **hrw360.com (5,434 listings, "房东直租无中介费" = landlord-direct no-fee)**, nychinaren, us168168; WeChat/RedNote closed. Forums are SSR/phpBB-style — pollable. Very high owner-direct share.
- **Russian** — rusrek.com («Р.Реклама»), continuous Brooklyn/SI incl. "от хозяина" (from owner); plain HTML.
- **Polish** — Bazarynka / polishclassifieds.com (Greenpoint/Ridgewood/Maspeth); plain HTML.
- **Spanish** — no dominant classifieds found; activity in FB groups (inherits unmonitorability).
- **Physical signs** — meaningful outer-borough; no digitization service exists in 2026.

## Local Law 86 of 2025 — what it actually is

**NOT a listings law.** LL86 = Rent Transparency Act, effective Jan 26, 2026: buildings with stabilized units must post a bilingual common-area notice (address, DHCR registration number, DHCR contact) so tenants can check status; HPD enforces. **Creates no public dataset.** The useful adjacent data remains DHCR's stabilized-building list + HPD registrations.

## New since Nov 2025

- **RentReboot** — free stabilized-unit StreetEasy alerts (Time Out, Apr 2025), now monitors 20+ platforms ~15-min and publishes coverage research. No API; its studies are the field map.
- **LeaseSwap NYC "Hidden Rentals"** iOS app — aggregates StreetEasy, RentHop, CL, Leasebreak, r/NYCapartments, NYBits with instant alerts.
- **openigloo's leasing-marketplace pivot** — now 15% of Manhattan inventory with **69% of its listings appearing nowhere else**; THE FARE-era small-landlord venue. No public API.
- **hrw360.com** — Chinese landlord-direct classifieds, possibly 2025–26 launch. No VC-backed owner-direct startup with an API surfaced — honest unknown.

## WHERE TO POINT THE PIPELINE (ranked)

1. **Craigslist** — new `?cat=` endpoints; poll 15-min; best owner-direct/$ ratio; heavy scam-filtering required.
2. **openigloo** — 69%-exclusive small-landlord inventory; scrape listing pages.
3. **r/NYCapartments + borough subs** — Reddit OAuth JSON polling; cheap and legal.
4. **Listings Project** — weekly SSR diff; near-zero scam noise.
5. **dadi360 + hrw360** — SSR forums, explicit landlord-direct sections.
6. **rusrek.com + Bazarynka** — plain-HTML classifieds, trivially pollable.
7. **Furnished Finder** — 100% owner, mid-term niche.
8. **Zillow FRBO** — only via commercial scraper API + proxies; budget accordingly.

(Facebook: highest volume but ToS-unmonitorable and ~50% of scam reports — human spot-checks. Posting rhythm: Mon–Wed; "weekends are dead.")

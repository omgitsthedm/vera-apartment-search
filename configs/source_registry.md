# Source Registry

This file is the human-readable inventory of source behavior, status, and duplicate risk.

## Source: Craigslist — LIVE
Access method: public HTML search + cached detail pages
Status: **LIVE** — primary discovery source
Rate limiting: 1200ms between requests
Cache TTL: 18 hours per listing
Known fragility: noisy results, vague addresses, inconsistent formatting
Notes about duplicates: high duplicate risk within source; high owner-direct upside

## Source: StreetEasy — LIVE
Access method: embedded JSON data from public search result pages
Status: **LIVE** — low volume at sub-$2,500 price point (honest market reality)
Rate limiting: 2000ms between requests
Cache TTL: 12 hours per listing
Known fragility: embedded data format could change; NYC-specific platform
Notes about duplicates: high overlap with Zillow-family inventory; photos served from zillowstatic.com
Note: Alphabet City does not have a separate StreetEasy slug; covered under East Village search

## Source: RentHop — LIVE
Access method: search page crawl + detail page JSON-LD extraction
Status: **LIVE** — good volume, full structured data on detail pages
Rate limiting: 2000ms between requests
Cache TTL: 12 hours per listing
Known fragility: HTML structure changes; some results return outside target neighborhoods
Notes about duplicates: moderate overlap with Craigslist; cross-source dedupe handles this

## Source: Apartments.com — NOT FEASIBLE
Status: **NOT FEASIBLE**
Reason: returns HTTP 403 on all requests, aggressive anti-bot protection
Last tested: 2026-03-17

## Source: Zillow — NOT FEASIBLE
Status: **NOT FEASIBLE**
Reason: Zillow Group anti-bot protection, HTTP 403 on all requests
Last tested: 2026-03-17

## Source: HotPads — NOT FEASIBLE
Status: **NOT FEASIBLE**
Reason: owned by Zillow Group, same anti-bot protection
Last tested: 2026-03-17

## Source: Trulia — NOT FEASIBLE
Status: **NOT FEASIBLE**
Reason: owned by Zillow Group, same anti-bot protection
Last tested: 2026-03-17

## Source: Facebook Marketplace — NOT FEASIBLE
Status: **NOT FEASIBLE**
Reason: login-gated, cannot be scraped without authentication
Last tested: 2026-03-17

## Verification Source: NYC Open Data — LIVE
Access method: Socrata API (5 datasets)
Status: **LIVE** — provides HPD complaints, violations, litigation, registrations, buildings
Rate limiting: low
Used for: building risk scoring, not listing discovery

## Verification Source: NYC HPD Online
Access method: public building search
Status: reference only
Used for: building-level risk context

## Verification Source: ACRIS
Access method: public property and document lookup
Status: reference only (not yet automated)
Used for: ownership clues

## Verification Source: NYC Property / Finance Lookup
Access method: public lookup surfaces
Status: reference only (not yet automated)
Used for: owner and tax-benefit clues

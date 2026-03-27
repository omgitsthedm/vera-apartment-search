# VERA Multi-Source Expansion Design

**Date**: 2026-03-17
**Status**: Approved

## Goal

Expand VERA from Craigslist-only to 3-4 honest live sources. Convert scheduling to hourly. Improve dedupe and scoring for multi-source operation.

## Source Strategy

| Source | Status Target | Approach |
|--------|--------------|----------|
| Craigslist | LIVE (keep as-is) | Existing adapter, no changes |
| StreetEasy | LIVE | New public HTML adapter, neighborhood-based search |
| Apartments.com | LIVE | New public HTML adapter, filtered search |
| RentHop | EXPERIMENTAL | Attempt HTML adapter, mark honestly |
| Zillow/HotPads/Trulia | NOT FEASIBLE | Aggressive anti-bot, Zillow Group |
| Facebook Marketplace | NOT FEASIBLE | Login-gated |

## Adapter Pattern

Each new adapter follows the Craigslist pattern:
1. Build search URLs per neighborhood
2. Fetch search result pages with browser-like headers
3. Extract listing URLs from results
4. Fetch detail pages (with caching)
5. Parse structured data from HTML
6. Store raw JSON snapshots

Conservative rate limiting (2000ms+ between requests). Cache TTL per source. Graceful failure per query.

## Scheduling Change

- Replace daily plist with hourly plist (StartInterval = 3600)
- New `run_hourly_autonomous.sh` wrapping the full pipeline + dashboard publish
- Keep weekly summary as separate job
- Cache discipline prevents hammering sources on hourly runs

## Dedupe Improvements

- Add cross-source URL domain matching (same listing ID across sites)
- Add source_url-based dedup for listings cross-posted across sites
- Existing union-find algorithm handles multi-source naturally

## Scoring Improvements

- Stronger broker/management penalties in landlord classification
- New penalty for vague/missing addresses
- New penalty for suspiciously incomplete listings
- Multi-source confirmation bonus (listing on 2+ sites = more trustworthy)

## Dashboard

- Preserve existing publish flow
- Add source breakdown metadata to scored output
- No structural changes to dashboard pipeline

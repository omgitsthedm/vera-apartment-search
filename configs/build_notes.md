# Build Notes

## Bot Identity

- Bot name: `VERA`
- Expansion: `Verified Evaluation for Rental Analysis`
- Role: local-first NYC apartment-search analyst
- Temperament: skeptical, literal, organized, conservative with claims

## Working Root

- `/Users/davidmarsh/Code/Personal/vera-apartment-search`

## Current Build Status

- Foundation: complete
- Local sample discovery stub: enabled
- Normalization, dedupe, enrichment, and scoring pipeline: working
- Live official public-record refresh: working for matched addresses through NYC Open Data
- Live source automation: not enabled yet
- Listing-site live adapters: not enabled yet

## Why The First Pass Uses Seeds

The first goal is a transparent, inspectable local pipeline that can be tested repeatedly without relying on brittle or login-heavy live scraping on day one.

The sample fixtures are visible under:

- `/Users/davidmarsh/Code/Personal/vera-apartment-search/cache/discovery_seeds/`

The sample public-record reference layer is visible under:

- `/Users/davidmarsh/Code/Personal/vera-apartment-search/cache/reference_data/`

## Intended Next Steps

1. Validate the visible local pipeline end to end.
2. Swap sample discovery inputs with approved live source adapters one source at a time.
3. Expand official verification beyond HPD into owner and tax-record sources such as ACRIS or PLUTO.
4. Tighten duplicate logic and owner classification once real listing volume arrives.

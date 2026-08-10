# VERA: verified NYC apartment hunting

VERA is a verification-first New York City apartment-search engine. It gathers listings from fragmented public sources, checks available claims against city records, explains uncertainty, and publishes a privacy-filtered public feed for [Little Fight NYC's VERA demo](https://littlefightnyc.com/vera/).

The Today view shows at most eight listings that clear the current published gates. Market and Browse expose the wider sanitized net so visitors can inspect what VERA rejected, what needs verification, and why.

## Public product and separate engine

The browser application lives in the Little Fight NYC website repository at `/app/public/vera/`. This public repository remains the separate processing engine because unfiltered source payloads, private runtime state, credentials, and owner-only fields must never enter the website repository or Netlify.

The browser reads only these first-party routes:

- `/vera/data/public.json`
- `/vera/data/archive.json`
- `/vera/data/meta.json`

GitHub Actions publishes the three sanitized files to this repository's orphan `feed` branch. `scripts/public_lens.py` removes private fields, and `audit_public_payload()` blocks a publication that fails the privacy contract.

## What VERA computes

- **Steward Grade**: building-level evidence from Housing Preservation and Development (HPD), Department of Buildings (DOB), 311, and related public records; missing evidence renders `?`, not a favorable grade
- **Listing-risk evidence**: relist history, contact reuse, description similarity, perceptual photo hashes, and a clearly labeled probabilistic AI-photo signal
- **Move-in cost context**: deposit, fee, and cash-to-keys estimates with source and legal caveats
- **Ownership evidence**: deed, registration, entity, and portfolio links where the available records support them
- **Transit context**: Metropolitan Transportation Authority (MTA) General Transit Feed Specification (GTFS) stations and timetable-derived ride minutes, with approximate walking time marked as approximate

VERA does not guarantee that a listing is legitimate, available, broker-free, privately owned, or suitable. It exposes evidence and uncertainty so a person can verify the listing before paying or applying.

## Safety contract

VERA has no public account system, advertising, or analytics. Browser hunt state stays in local storage. The engine never contacts landlords or submits applications.

Do not run the pipeline, change schedules, publish the cloud feed, alter search criteria, or change scoring weights without the authorization required by `AGENTS.md`.

## Run and verify the engine

Python 3.12 or newer runs the deterministic engine. Optional enrichment dependencies are installed only in the environment that uses them. Ollama is not required.

Run the six isolated checks before changing an operational boundary:

```bash
python3 tests/test_scoring.py
python3 tests/test_mail_ingest.py
python3 tests/test_public_lens.py
python3 tests/test_source_honesty.py
python3 tests/test_neighborhood_gate.py
python3 tests/test_public_product_boundary.py
```

Read `AGENTS.md` before work, `SOURCE_OF_TRUTH.md` for stable routing, `configs/snapshot_schema.md` for the feed contract, `configs/schedules.md` for cadence, and `VERA-HANDOFF.md` for cross-repository recovery.

## Credits

VERA uses New York City Open Data, NYC Planning GeoSearch, MTA GTFS data, JustFix Who Owns What, MapLibre GL, OpenFreeMap, and the `umm-maybe/AI-image-detector` model. Check each source's current terms before redistributing data or derivatives.

## License status

This repository is public, but it does not currently include a license file. Public visibility does not grant permission to copy, modify, or redistribute the code. Do not describe VERA as open source or AGPL-licensed until David selects and adds an explicit license.

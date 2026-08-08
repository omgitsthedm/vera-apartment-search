# VERA — verified NYC apartment hunting

**Every claim on the page survives the question "how do you know that?"**

VERA is an open, verification-first engine for finding privately-owned
NYC rentals — no brokers, no corporate landlords, no scams. It sweeps
the fragmented channels where small landlords actually post, joins every
listing against the city's own records, and publishes a curated daily
drop of at most eight listings that clear every gate — with an honest
public ledger of everything it passed on and why.

**Live:** https://littlefightnyc.com/vera/ · the field manual and daily
receipts are free at `/vera/manual/` and `/vera/archive/`.

## What it computes (all cited or ≈-marked)
- **Steward Grade** — does this owner fix things? A–E from HPD
  violations, heat/hot-water complaints, bedbug filings, housing-court
  history, DOB records. No data grades `?`, never an A.
- **Scam forensics** — relist detection (a fresh posting can't reset the
  true days-on-market), contact reuse across listings, template
  descriptions, perceptual-hash photo clones, and an AI-photo classifier
  read (Hugging Face, probabilistic on its face).
- **The money, by law** — deposit and application-fee caps, FARE-Act
  broker-fee rules, a cash-to-keys total on every listing.
- **Ownership chain-of-proof** — deed → HPD registration → DOS entity →
  portfolio, with links to walk it yourself.
- **Honest commutes** — MTA GTFS stations and timetable-quoted ride
  minutes. Nothing invented, everything ≈-marked.

## What it refuses
No accounts. No tracking. No urgency theater. No AI chat. No landlord
contact, ever. No protected-class signals anywhere in scoring —
see `/vera/corrections/` for the fair-housing statement and the
owner correction channel.

## Run it
Python 3.12+, stdlib + Pillow. `scripts/run_daily.sh` runs the pipeline;
GitHub Actions runs the cloud sweep daily (`.github/workflows/`). Feed
contract: `configs/snapshot_schema.md`. The public browser reads only Little
Fight's `/vera/data/{public,archive,meta}.json` routes. Agent rules:
`AGENTS.md`.

Built by [Little Fight NYC](https://littlefightnyc.com). AGPL-3.0 intent
for code; data derivations carry their sources' terms (MTA GTFS, NYC
Open Data, StreetEasy public CSVs).

## Credits

VERA stands on public data and open work:

- **NYC Open Data** — HPD violations, complaints and registrations, DOB
  records, 311, PLUTO, ACRIS.
- **NYC Department of City Planning** — NTA2020 neighbourhood boundaries,
  and the keyless [GeoSearch](https://geosearch.planninglabs.nyc/) geocoder.
- **MTA** — GTFS static schedules for stations and ride times.
- **[JustFix](https://whoownswhat.justfix.org/)** — the Who Owns What API,
  which links buildings into landlord portfolios.
- **AI-photo detection** — [`umm-maybe/AI-image-detector`](https://huggingface.co/umm-maybe/AI-image-detector),
  licensed CC BY 4.0.
- **[MapLibre GL](https://maplibre.org/)** (BSD-3) over
  **[OpenFreeMap](https://openfreemap.org/)** tiles, from OpenStreetMap data.

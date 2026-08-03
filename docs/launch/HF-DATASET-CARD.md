# HF dataset card draft — nyc-apartment-hunt-derivations
Pending David's account decision. Contents when published:
- `transit_stations.json` — 496 NYC subway parent stations w/ true line
  sets, derived from MTA GTFS static (refresh weekly, script included)
- `transit_routes.json` — per-route scheduled stop sequences (cumulative
  seconds) for timetable-quoted ride estimates
- `hoods.json` — NYC DCP NTA2020 neighborhood polygons, Manhattan+BK
  hunt zone, simplified to 22m (149KB, source dataset 9nt8-h7nd)
License: source terms (MTA developer terms; NYC Open Data). Card must
state derivation scripts + refresh cadence + the ≈ philosophy.

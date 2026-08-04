# Self-hosted basemap (Protomaps/pmtiles) — attempted, not shipped

**Date:** 2026-08-04 · **Status:** extraction proven, rendering NOT verified — deliberately not shipped

## Why it's worth doing

VERA's map currently depends on OpenFreeMap's tile servers at runtime.
OpenFreeMap is excellent, free, keyless and actively maintained — but it
is donation-funded, single-maintainer, and offers **no SLA**. If it goes
down, VERA's Atlas goes dark. For a product meant to be the default way
someone finds an apartment, that is the last third-party dependency in
the critical path.

## What was proven

- `go-pmtiles` v1.31.2 (prebuilt macOS arm64 binary; `go install` fails
  in this environment because proxy.golang.org is unreachable, and the
  binary itself needs `GODEBUG=netdns=cgo` — its default resolver takes a
  broken IPv6 path to Cloudflare).
- A five-borough extract from `build.protomaps.com/20260803.pmtiles`:
  **29MB at z0–14** (11MB at z0–13), 43 HTTP range requests, ~30 seconds.
- The archive's real vector layers: `boundaries, buildings, earth,
  landcover, landuse, places, pois, roads, water` (note: **no `natural`
  layer** — a plausible-looking guess that silently renders nothing).
- Vite's dev server **does** serve HTTP 206 range requests, so local
  testing is viable.

## Why it wasn't shipped

MapLibre fetched the pmtiles header (16KB, one request) and then never
requested a single tile — with both relative and root-relative
`pmtiles://` URLs. The canvas mounted, the pins drew, and the basemap
stayed black. Root cause not established.

Shipping that would have replaced a verified, good-looking map with a
black rectangle, and committed 29MB to the website repo's history
permanently to do it. The working map stays.

## To finish this later

1. Serve the archive and confirm MapLibre issues tile range requests —
   suspect the `pmtiles://` protocol registration timing relative to
   `new maplibregl.Map()`, or a TileJSON the protocol fails to synthesize.
2. Self-host glyphs too (the drafted style still pointed at
   OpenFreeMap's font endpoint, so it was never fully independent).
3. Decide hosting: 29MB in git history forever is a real cost. Cloudflare
   R2 with free egress is the better home; Netlify range support at that
   size is verified only up to a few MB.
4. Keep OpenFreeMap wired as the fallback either way.

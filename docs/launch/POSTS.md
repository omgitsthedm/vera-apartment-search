# Ready-to-paste launch posts — David presses submit
Both written for their cultures: useful first, humble, zero hype. Edit freely.

---

## r/NYCapartments

**Title:** I built a free tool that checks NYC listings against city records — steward grades for landlords, scam tells computed, no accounts, no ads

**Body:**

After getting tired of ghost listings and "days on market" counters that
reset every relist, I built VERA for my own hunt and it grew into
something worth sharing: littlefightnyc.com/vera

What it does, all from public records:
- **Steward Grade (A–E)** per listing — does this owner actually fix
  things? Computed from HPD violations, heat/hot-water complaints over
  three winters, bedbug filings, and housing-court history, with links
  to every record so you can check the work.
- **Scam tells, computed** — relists that reset the DOM counter (it
  keeps its own memory), the same contact across many listings,
  template descriptions, stolen photos (perceptual hash), and an
  AI-photo read (flagged as probabilistic, not proof).
- **The money, by law** — deposit/application caps, FARE Act rules, a
  real cash-to-keys total. If a listing's demand is illegal, it says so.
- **A daily drop, not infinite scroll** — at most 8 listings that clear
  every gate, plus a public archive of every drop and what happened to
  each (rented / price dropped / still sitting). Nothing edited after
  the fact.
- The **field manual** (all 16 scam tells + a 26-point viewing
  checklist) is free at /vera/manual/ even if you never use the app.

No accounts, no tracking, nothing sold. It never contacts landlords.
The engine is open source: github.com/omgitsthedm/vera-apartment-search
Fair-housing statement and a landlord correction channel are first-class
pages. Happy to answer anything — and if you find a record it's reading
wrong, tell me and it gets fixed.

---

## Show HN

**Title:** Show HN: VERA – NYC apartment search that verifies listings against city records

**Body:**

I built this for my own apartment hunt after the usual portals kept
showing me relisted ghosts and landlords with violation histories I only
learned about after touring.

VERA sweeps the fragmented channels where small NYC landlords actually
post (Craigslist API, openigloo, Listings Project, Reddit — 51% of
listings appear on exactly one platform), joins every listing to NYC
open data by address, and publishes a curated daily drop of at most
eight listings that clear every gate — with a public, append-only
archive of everything it showed and what happened to it.

Technical bits HN might enjoy:
- Zero-framework front end (~5k LOC vanilla JS, 91 in-page tests,
  CSP with no inline script), deterministic SVG "building portraits"
  seeded from each listing's uid, real NTA polygons for maps.
- The landlord "Steward Grade" is computed only from cited public
  records (HPD/DOB/311/housing court), each failure deep-linked; no
  data renders "?" — never a default A.
- Relist detection via an address-history store (a fresh posting can't
  reset true days-on-market), perceptual-hash photo-clone detection,
  and an HF image classifier for AI-generated photos (surfaced as
  probability, deliberately excluded from scoring).
- The whole pipeline also runs daily on GitHub Actions — turns out most
  sources serve datacenter IPs fine; the residential-IP half runs on a
  Mac at home. MTA GTFS static supplies stations and scheduled ride
  times so commute numbers are quoted, never invented.
- No accounts, no server-side user state (everything personal is
  localStorage), no scraping escalation, and it never contacts anyone.

Engine: github.com/omgitsthedm/vera-apartment-search
Live: littlefightnyc.com/vera — the field manual and receipts are
static pages if you just want the reference material.

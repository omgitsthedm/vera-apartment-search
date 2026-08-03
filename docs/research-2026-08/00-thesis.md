# THE NEW VERA — thesis, August 3, 2026

Synthesis of five research reports (01–05 in this directory) + nine months of VERA
operating history. This is the answer to: *"I want a privately owned rental in
August 2026 — how do I find it without being scammed, without violations, and
before the brokers?"*

## What we were missing (the honest audit)

1. **We watch portals; the game moved to fragmented free channels.** 51.3% of NYC
   listings appear on exactly ONE platform — **77% for units under $2,500**, which
   is precisely our hunt. Post-FARE, small landlords fled to free channels
   (StreetEasy FRBO costs $249/2wk). openigloo alone now carries 69%-exclusive
   small-landlord inventory. Our pipeline covers a fraction of the real owner-direct
   market. **Fragmentation is the moat: whoever aggregates the fragments owns the
   under-$3,000 owner-direct segment.**
2. **We have no pre-listing radar.** Brokers win on relationships; data can win on
   time. HPD Registration Contacts (feu5-w2e2) legally publishes every small
   building's owner/agent. DOB alteration filings completing, new C of O, ACRIS
   deed transfers to new small LLCs — each predicts turnover weeks before a listing
   exists. Nobody consumer-facing does this.
3. **We verify listings; we should verify COUNTERPARTIES.** The chain — ACRIS deed
   → HPD registration humans → DOS entity → Who-Owns-What portfolio — is buildable
   this week (nycdb + portfoliograph, both maintained, both AGPL/open). The NY LLC
   Transparency Act is a confirmed DEAD END (non-public DB, effectively
   foreign-LLCs-only after the 2025 veto + FinCEN scoping) — public-records
   chain-matching is the only path, and it's ours.
4. **We built a dashboard; the winning shape is a curation ritual.** Renters'
   complaints are not "too few listings" — they're stale data, spam, fee opacity,
   choice overload. The Modern House × Bring a Trailer × Coffee Meets Bagel:
   a fixed-hour daily drop of 5–8 verified, editorially-told homes beats infinite
   scroll. StreetEasy cannot copy this — their business IS the firehose.
5. **Trust is a feature you can see.** Verified-date stamps, "what didn't make it"
   counts, total-cost-to-keys (FARE-checked), hard memory of passed units, flaws
   disclosed in the copy. Every incumbent hides these; we lead with them.
6. **Speed beats access for ~75% of the market.** Most units are findable within
   24h of first post; a 15-minute poll loop on the fragmented channels front-runs
   most brokers without any insider access.

## The invention: owner-first, not listing-first

Flip the data model. Instead of *listings, enriched with building data*, VERA
becomes an **atlas of every small building in the focus areas** (6–20 units,
owner portfolio ≤10 buildings, healthy violation profile), where listings are
transient events that light buildings up. Three consequences:

- **The Ledger:** every listing gets an ownership dossier — who really owns it
  (deed → registration → portfolio), their whole-portfolio track record, protection
  tier (Good Cause exemption look-through: portfolio >10 units = covered),
  stabilization likelihood (rentstab_v2 join + pre-1974 + 6+ units).
- **The Radar:** per-building pre-listing signals (permits completing, deeds
  transferring, C of O issued) for the ~2,000 buildings that fit David's life.
- **The Kit:** for radar-hot buildings, an outreach-ready dossier (public HPD
  contact, building history, what to say, what to verify). VERA's read-only ethic
  holds — VERA never contacts anyone; it arms David to. "It's 1999, you have to
  know who to call" — we generate the call sheet.

## The product (new /vera)

1. **The Drop** — daily at a fixed hour: 5–8 full-fit, verified leads, each with a
   why-we-picked-it note, total-cost-to-keys, ownership chain, honest flaws.
   Countdown to the next drop. Empty state says "nothing met the bar today."
2. **The Market** — the wide net: whole-market pulse from StreetEasy's official
   free CDN CSVs (medianAskingRent et al.) + our multi-channel intake: brackets,
   focus areas, inventory trend, where-the-market-is-moving. Inspirational, not
   exhaustive.
3. **The Ledger** — per-listing verification theater: the chain-match, the scam
   kill-list checks, building health, protection tier, DHCR guidance.
4. **The Atlas** — the owner-first map: focus-area buildings colored by fitness,
   radar signals, portfolio links.
5. **The Wire** — email: instant full-fit alert (≥95% match, verified) + the daily
   drop digest at a fixed hour; hard cap 2/day; "we passed on 41" trust line.
   (v1 shipped 2026-08-03: scripts/send_alerts.py.)

Brand: keep VERA's identity core (warm black, radar green, IBM Plex data voice)
but rebuild the shell as editorial-warm: display serif for home-character
headlines, grain on dark surfaces, clay/ochre/brass accents, one cinematic moment
(the drop reveal), everything else 150–250ms restraint.

## Engine phases

- **A (now): widen the net.** New discoverers: openigloo, Listings Project
  (weekly diff), Reddit OAuth poller, dadi360 + hrw360 + rusrek + Bazarynka,
  Furnished Finder; fix Craigslist to the 2026 `www.craigslist.org/search/area/
  newyork?cat=hhh` endpoints; StreetEasy/Zillow via saved-search **alert-email
  ingestion** (rental-inbox pattern — ToS-safe), not scraping. Market layer from
  SE CDN CSVs. rentstab_v2 stabilization join.
- **B: the owner graph.** Local Postgres + nycdb (hpd_registrations, violations,
  complaints, litigations, acris, pluto, pad, rentstab_v2, marshal_evictions,
  oca, rodents); vendor Who-Owns-What portfoliograph for portfolio linking;
  chain-match scorer with proof-of-authority framing (mismatch = "ask for
  authority," never auto-"scam" — family/manager false positives are the norm).
- **C: the radar + kill-list.** DOB/ACRIS/C-of-O watchers per focus block;
  pHash clone detection, comps-delta bait detector, VOIP/email-age soft flags,
  vacate-order hard block. Scam kill-list codified (report 02 §KILL-LIST).

## What we do NOT build

Direct StreetEasy/Zillow scraping (WAF war, ToS); Facebook automation (ToS +
half of all scam reports); NYLTA lookups (dead end); openigloo review corpus
(inaccessible — link out); anything that contacts landlords autonomously.

## The one-line pitch

**StreetEasy shows you everything and verifies nothing. VERA watches everywhere,
verifies everything, and shows you only what survives.**

# The feed is 1.68 MB, and that is the whole page

**Measured:** 2026-08-04 · **Status:** measured and diagnosed; no change made

## What the page actually costs

Loading `/vera/` transfers **1,855 KB**, and **1,682 KB of it is
`public.json`** — ninety-one percent. Everything else is rounding: all the
JavaScript, CSS and fonts together come to under 5 KB transferred (they
cache well), and the neighbourhood polygons are 168 KB.

On a phone over cellular that is several seconds before anything appears
beyond the shell — for a product whose whole promise is a quick honest look
at eight apartments.

## Where the weight is

| Section | Size |
|---|---|
| `pool` (256 listings, ~5.8 KB each) | 1,476 KB |
| `manual_review` | 121 KB |
| `shortlist` | 25 KB |
| `transit_tables` | 19 KB |
| `market_context` | 16 KB |

Heaviest per-listing fields across the pool:

| Field | Total |
|---|---|
| `score_explanation_lines` | 82 KB |
| `what_to_verify_before_applying` | 82 KB |
| `image_urls` | 63 KB |
| `why_this_listing` | 58 KB |
| `component_scores` | 51 KB |
| `trust_caveats` | 32 KB |

## The obvious win, and why I did not take it

`manual_review` and `shortlist` are **complete duplicates** — every one of
their 19 and 4 entries already appears in `pool`, verified by uid. That is
146 KB shipped twice on every load.

But they are not dead: `vera-app.js` uses them as a **fallback pool** when
`pool` is absent. Deleting them saves 9% and silently removes a safety net
that exists for feeds published before `pool` did. That is a bad trade to
make without the owner, so it is written down instead of done.

**If David wants it:** publish them as uid-only references, and have
`make_public_data` guarantee `pool` is always present so the fallback is
provably unnecessary. Roughly 146 KB for half an hour of care.

## The larger opportunity

The real fix is architectural: the drop needs at most 8 listings, Browse
needs 256 rows of about fifteen fields, and the ledger needs everything —
but only for the one listing being read. A light index plus per-listing
detail fetched on open would cut first load by something like 80%.

That is a genuine refactor with a real regression surface (offline
caching, the service worker's feed strategy, deep links that open a ledger
before any index has loaded). It should be planned deliberately, not
squeezed in — but it is the single biggest remaining UX improvement
available, and it is invisible until someone opens VERA on a phone with
one bar.

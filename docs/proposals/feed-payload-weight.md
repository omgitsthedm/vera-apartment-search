# The feed is 122 KB on the wire — I measured the wrong thing

**Measured:** 2026-08-04 · **Status:** CORRECTED. The problem this file
originally described does not exist in production.

## The correction

An earlier version of this document claimed `/vera/` transfers 1.86 MB, that
`public.json` was 91% of it, and that an architectural refactor was "the
single biggest remaining UX improvement available".

That was measured against the **localhost dev server**, which serves the
staged feed uncompressed, and generalised to production without checking.

Production serves it Brotli-compressed:

```
raw JSON                1,722,168 bytes   (1.72 MB)
on the wire (br)          124,510 bytes   (122 KB)     -93%
```

`content-encoding: br` is present both on the feed origin
(vera-pipeline.netlify.app) and through the littlefightnyc.com proxy.

**122 KB is a perfectly reasonable payload** for 256 fully-verified listings
with their records, scores, reasoning and photo URLs. It is roughly one
mid-sized photograph. There is no first-load crisis, and the light-index
refactor is not needed — it would have been meaningful work solving an
imaginary problem.

## What still stands

The 211 KB of owner-only fields removed from the public lens
(`PUBLIC_DROP_FIELDS` in the dashboard's `make_public_data.py`) remains
correct on its own terms: those fields were grep-verified as never read by
any app module, and shipping data nobody reads is wrong regardless of how
well it compresses. The saving is real but modest once compressed — call it
15–20 KB rather than 211 KB.

## The lesson worth keeping

**Measure the thing users actually receive.** `performance.getEntriesByType('resource')`
reports `transferSize` for the environment you are in — and a dev server is
not production. Compression, CDN behaviour and proxy headers all differ.
Check `content-encoding` on the real origin before concluding anything about
payload weight.

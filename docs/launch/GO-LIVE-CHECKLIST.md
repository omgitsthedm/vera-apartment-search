# What's actually left — sorted by whether it helps David find an apartment

Rewritten 2026-08-04. The previous version listed five "gates" as if they
were all requirements. They were not. Most served other people, or served an
instruction that named a tool rather than a need. Sorted honestly here.

**Everything below is free.** No trials, no paid tiers, no API keys with
billing attached. Every commercial option was rejected during research, one
of them specifically because its free tier forbids commercial use.

---

## Worth doing — 2 items

### 1. Let VERA read StreetEasy and Zillow's own alert emails
The single biggest remaining improvement to the net. Those two carry the
most inventory, and reading their alert emails is the only route into them
that isn't scraping: no IP blocks, no terms problem, works from anywhere.

**Recommended: make a dedicated Gmail for this.** It keeps alert traffic out
of the personal inbox, scopes the app password to something disposable, and
means a leak is not the primary identity.

- New Gmail (free)
- Saved searches on StreetEasy and Zillow pointed at it, **instant alerts on**
- App password: Google Account → Security → 2-Step Verification → App passwords
- `bash scripts/setup.sh` writes `configs/mail_ingest.json` and live-tests the
  connection

### 2. A Netlify token, so the sweep publishes with the Mac asleep
Netlify already hosts the sites. One generated token and the site id.

```bash
gh secret set NETLIFY_AUTH_TOKEN -R omgitsthedm/vera-apartment-search
gh secret set NETLIFY_SITE_ID   -R omgitsthedm/vera-apartment-search
# site id: fcd6f741-d479-44f4-8ee1-51da2b321227
```

---

## One decision, no typing

**Enable the recalibrated HPD score?** Today six of seven verified buildings
score exactly 100 — including one with *zero* serious open violations — so
the alert gate rejects buildings for the crime of having been checked. The
replacement is built, tested, and locked with unit tests; it spreads the
range properly and keeps small owner-direct buildings reachable, which is
the whole point of VERA.

```bash
VERA_HPD_CALIBRATED=1 python3 scripts/enrich_listings.py   # try one run
```

Or set `"hpd_calibrated": true` in `configs/user_preferences.json` to keep it.

---

## Optional — helps other people, not the hunt

Skip all of this if the goal is simply to find an apartment. It exists
because the instruction said "GitHub, Hugging Face, all of it".

- **Reddit script app** — authenticated API instead of throttled RSS, worth
  roughly 15 listings a sweep. Only if a Reddit account already exists.
- **Hugging Face datasets** — 496 stations, 29 route timetables, 197
  neighbourhood polygons; staged and carded at `docs/launch/HF-DATASET-CARD.md`.
  A real gift to other developers, zero effect on this search.
- **r/NYCapartments and Show HN posts** — `docs/launch/POSTS.md`, written and
  fact-checked. The adoption lever, if adoption is wanted. **Do not post from
  a fresh account** — new accounts launching a project get flagged as spam.
  Real accounts with history, or not at all.

---

**Already done, nothing owed:** engine repo public with clean history; the
city-API outage that emptied the drop root-caused and fixed with retries;
verification coverage tripled by resolving neighbourhoods from coordinates;
the cloud sweep running daily on its own schedule; landlord portfolios via
JustFix; unlawful-demand detection against New York law; WCAG AA
accessibility; and the engine's first scoring tests.

# HPD risk saturates, and it is quietly gating your alerts

**Found:** 2026-08-04 · **Status:** diagnosed, NOT changed — scoring is David's call (AGENTS.md)

## The evidence

Of the seven listings in tonight's pool carrying real city records, **six
score exactly 100.0**. The one that doesn't scores 47.5. There is nothing
in between.

| Building | serious open violations | heat complaints 3y | HPD risk |
|---|---|---|---|
| 459 Keap St | 2 | 0 | **47.5** |
| 114 N Seventh St | **0** | 5 | **100.0** |
| 48 W 138 St | 3 | 2 | 100.0 |
| 5 Tudor City Pl | 7 | 14 | 100.0 |
| 137 W 137 St | 10 | 34 | 100.0 |
| 219 W 145 St | 12 | 73 | 100.0 |
| 580 St Nicholas Av | 23 | 50 | 100.0 |

**114 N Seventh Street has zero serious open violations and scores the same
as a building with twenty-three of them and fifty heat outages.** Whatever
that number is measuring, it is not "how much worse is this building than
that one".

## Why

`hpd_risk_score` (enrich_listings.py:388) is a weighted sum, capped at 100:

```
complaints×1.4 + open_violations×5.5 + litigation×8 + heat×0.9 + bedbug×6 + serious_open×10
```

Two problems compound:

1. **It saturates almost immediately.** 19 ordinary open violations alone
   reaches the cap. In NYC that is an unremarkable building — ordinary
   violations include peeling paint and missing signage. 114 N Seventh
   maxes out on those alone despite a clean serious-violation record.
2. **It ignores building size.** 5 Tudor City has ~799 apartments;
   48 W 138 has ~89. Seven serious violations across 799 units is a far
   better record than three across 89, and the formula scores them
   identically. (`apt_count` is on the engine record but is not published
   to the feed, so the app cannot show this either.)

## What it costs

The alert gate is `max_hpd_risk: 65`. Since virtually every
public-record-verified building lands at 100, **the gate rejects buildings
for the crime of having been verified**. Unverified buildings sit at the
synthetic 50.0 default and sail through that particular check.

That is backwards, and it is why so little reaches your inbox: tonight
four listings were recommended and only one could ever have been emailed.

## Proposed fix (needs approval)

Normalise by units and separate severity from noise — the metric JustFix
uses, and which VERA already fetches for portfolios
(`openviolationsperresunit`):

```
serious_open / units × 250     # a serious violation per 4 units ≈ 62
+ heat / units × 60            # chronic heat failure, per apartment
+ litigation / units × 120
+ bedbug × 6                   # rare enough to stay absolute
+ open_violations / units × 25 # ordinary violations, heavily discounted
```

capped at 100, with `apt_count` published so the app can show the working.
Against tonight's data this would separate 114 N Seventh (clean, small)
from 580 St Nicholas (23 serious, 50 heat outages) instead of calling them
the same building.

**Do not apply this without David.** It changes what gets recommended and
what gets emailed, which is exactly the class of change AGENTS.md reserves
to him. The diagnosis above stands on its own regardless of the remedy
chosen.

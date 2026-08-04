# HPD risk saturates, and it is quietly gating your alerts

**Found:** 2026-08-04 · **Status:** diagnosis confirmed. The rejected
per-unit experiment remains behind `VERA_HPD_PER_UNIT`, default OFF, and
must not be enabled. The calibrated, no-divisor formula documented later in
this file is the standing default since commit `368bef7`.

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
   identically. (Correction to an earlier draft of this file: the field is
   `unit_count`, and it **is** published — 5 Tudor City carries
   `unit_count: 799`. The data was there all along; only the formula and the
   UI ignored it.)

## What it costs

The alert gate is `max_hpd_risk: 65`. Since virtually every
public-record-verified building lands at 100, **the gate rejects buildings
for the crime of having been verified**. Unverified buildings sit at the
synthetic 50.0 default and sail through that particular check.

That is backwards, and it is why so little reaches your inbox: tonight
four listings were recommended and only one could ever have been emailed.

## First proposed fix (rejected; remains off)

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

**Do not apply this.** The measurement below disproved it. It remains here as
the research record for why per-unit normalization is wrong for VERA; the
diagnosis above stands independently of this rejected remedy.


---

# The proposed fix fails on VERA's own thesis

Implemented behind a flag and tested against tonight's real buildings. It
inverts exactly the preference VERA exists to express.

| Building | serious / heat / units | shipped | per-unit | gate |
|---|---|---|---|---|
| 459 Keap St | 2 / 0 / **2** | 42.0 (passes) | **100.0** | **BLOCKED** |
| 114 N Seventh | 0 / 5 / **7** | 100.0 | **100.0** | blocked |
| 48 W 138 St | 3 / 2 / 89 | 100.0 | 15.8 | passes |
| 5 Tudor City | 7 / 14 / **799** | 100.0 | **4.5** | **passes** |
| 580 St Nicholas | 23 / 50 / 60 | 100.0 | 100.0 | blocked |

Read the first and fourth rows together. Per-unit maths **blocks 459 Keap
Street** — the two-unit owner-direct building that is currently the single
listing clearing every gate and the one lead VERA has ever emailed — while
**passing 5 Tudor City Place**, a 799-unit complex with seven serious open
violations and a housing-court case, at a score of 4.5.

Dividing by units systematically flatters large buildings and punishes small
ones. VERA hunts small, owner-direct buildings. A two-unit building with two
serious violations is genuinely worth knowing about, but 2/2 is a rate of
1.0 and any per-unit formula will treat it as catastrophic, while a large
portfolio building dilutes real neglect across hundreds of apartments.

**So the honest conclusion: the diagnosis was right and the remedy was
wrong.** Saturation is real — six of seven verified buildings at exactly
100.0, including one with zero serious violations, is not a working
signal — but per-unit normalisation is the wrong correction for this
product.

## What to try instead

1. **Fix saturation without a divisor.** Lower the per-violation weights and
   use a soft curve (log or sqrt) so the score spreads across the real range
   instead of pinning at the cap. Keeps counts absolute; a small building
   with two serious violations still reads as two.
2. **Separate severity from noise.** Ordinary open violations — peeling
   paint, signage — should barely move the number; serious open violations,
   heat failure and litigation should carry it.
3. **Use size as context, not a divisor.** Show "7 serious across 799
   apartments" in the ledger, which now happens, and let the reader weigh it,
   rather than folding it into a single number.
4. **Reconsider the gate, not just the score.** `max_hpd_risk: 65` on a
   saturating score is what actually blocks alerts. A gate on serious open
   violations and heat failures might express the intent better than a gate
   on a composite.

The flag stays for experimenting. It should not be turned on as written.


---

# A working formula, tested — `VERA_HPD_CALIBRATED` (standing default)

Direction 1 and 2 from the list above, built and measured. Severity carries
the score, ordinary violations barely move it, an exponential curve spreads
the range, and there is **no per-unit divisor** — that was the mistake.

```
raw = serious×9.0 + heat×1.6 + litigation×7.0
    + ordinary_violations×0.7 + complaints×0.35 + bedbug×5.0
score = 100 × (1 − e^(−raw / 42))
```

| Building | serious / heat | shipped | calibrated | gate |
|---|---|---|---|---|
| clean small building | 0 / 0 | — | **1.7** | passes |
| clean, one complaint | 0 / 1 | — | **9.9** | passes |
| 459 Keap St (2 units) | 2 / 0 | 42.0 | **39.1** | passes |
| 114 N Seventh | **0** / 5 | **100.0** | **41.3** | passes |
| 48 W 138 St | 3 / 2 | 100.0 | **66.5** | blocked |
| 5 Tudor City | 7 / 14 | 100.0 | **94.3** | blocked |
| 580 St Nicholas | 23 / 50 | 100.0 | **100.0** | blocked |

The spread is the point: 1.7 → 9.9 → 39 → 41 → 66 → 94 → 100 is a signal.
Six identical 100s was not.

Three things it gets right that the shipped formula does not: a building
with **zero serious violations** stops scoring maximum risk; a small
owner-direct building with a couple of violations stays reachable, which is
VERA's whole point; and genuinely neglected buildings still block hard.

**Standing default since commit `368bef7`.** The calibrated path now runs
unless explicitly pinned off for a controlled comparison. To exercise the
legacy formula for one run without changing standing configuration:

```bash
VERA_HPD_CALIBRATED=0 python3 scripts/enrich_listings.py   # one comparison run
```

Worth deciding alongside it: `max_hpd_risk: 65` was tuned against a
saturating score. Against this one, 65 lands between 48 W 138 (66.5, just
blocked) and 459 Keap (39.1, comfortably through) — probably about right,
but it is now a real threshold on a real distribution rather than a filter
against a wall of 100s.

# PROPOSAL — feed the computed tells into listing confidence
**Status: APPROVED by David 2026-08-03 ("I approve of all of it") — APPLIED in config/listing_confidence.apply_forensic_deductions.**

The Phase-1.3 forensics publish as evidence only. This proposal makes them
count, as a new deduction inside `config/listing_confidence.py`'s penalty
model (0–1 scale; the published score is ×100):

| Signal | Deduction (0–1) | ≈ points on /100 | Rationale |
|---|---|---|---|
| `relist_suspect` | 0.10 | −10 | DOM-reset is a marketing move, not fraud — mild |
| `contact_reuse_count` > 3 | 0.15 | −15 | scaled operations reuse contacts; legit managers can too — moderate |
| `desc_clone_of` | 0.25 | −25 | template text at a different address is the classic scam fingerprint |
| `photo_clone_suspect` | 0.20 | −20 | stolen photos; hotlink-identity only in v1, so kept below desc |

Combined cap: −0.45 total from this component (a listing tripping
everything still keeps its other components' say). Each triggered signal
adds a named line to `score_explanation_lines` so the ledger's Score tab
shows exactly why, citation-style, consistent with the honesty spine.

Implementation on approval (~10 min): one `forensic_component(record)`
in `config/listing_confidence.py`, folded into `compute_listing_confidence`
with the cap; three suite checks (each signal moves the score by its
weight; cap holds; clean listing unchanged).

Reply "weights: yes" or adjust any number.

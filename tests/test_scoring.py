#!/usr/bin/env python3
"""Engine scoring tests. No pytest required: `python3 tests/test_scoring.py`.

The engine had no test coverage of its scoring at all, which is how a
saturating HPD formula went unnoticed while it quietly blocked every
verified building from the alert gate.

These lock down two things: that the SHIPPED formula is unchanged (so the
calibrated one behind VERA_HPD_CALIBRATED can never alter behaviour by
accident), and that the calibrated one actually discriminates if it is ever
switched on.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(name)


def load_enrich():
    spec = importlib.util.spec_from_file_location("en", ROOT / "scripts" / "enrich_listings.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def ref(serious=0, heat=0, litig=0, viol=0, complaints=0, bedbug=0, units=0):
    return {
        "serious_open_violations": serious,
        "heat_hot_water_complaints_3y": heat,
        "litigation_count_3y": litig,
        "hpd_open_violations": viol,
        "hpd_complaints_3y": complaints,
        "bedbug_reports_3y": bedbug,
        "unit_count": units,
    }


def test_shipped_formula_unchanged() -> None:
    os.environ.pop("VERA_HPD_CALIBRATED", None)
    m = load_enrich()
    print("\nshipped formula (flag off) — must not drift:")
    check("no public record stays synthetic 50.0", m.hpd_risk_score(None) == 50.0, str(m.hpd_risk_score(None)))
    expect = round(min(100.0, 5 * 1.4 + 20 * 5.5 + 2 * 0.9 + 3 * 10.0), 1)
    got = m.hpd_risk_score(ref(serious=3, heat=2, viol=20, complaints=5))
    check("weighted sum matches the documented weights", got == expect, f"{got} vs {expect}")
    check("a clean building scores 0", m.hpd_risk_score(ref()) == 0.0, str(m.hpd_risk_score(ref())))
    # the saturation this suite exists to document
    zero_serious = m.hpd_risk_score(ref(serious=0, heat=5, viol=19, complaints=3))
    check("KNOWN FLAW: zero serious violations still saturates at 100",
          zero_serious == 100.0, f"{zero_serious} — see docs/proposals/hpd-risk-calibration.md")


def test_calibrated_formula() -> None:
    os.environ["VERA_HPD_CALIBRATED"] = "1"
    m = load_enrich()
    print("\ncalibrated formula (flag on) — must discriminate:")
    try:
        clean = m.hpd_risk_score(ref(viol=1))
        keap = m.hpd_risk_score(ref(serious=2, viol=4))               # 2-unit owner-direct
        zero_serious = m.hpd_risk_score(ref(heat=5, viol=19, complaints=3))
        mid = m.hpd_risk_score(ref(serious=3, heat=2, viol=20, complaints=5))
        bad = m.hpd_risk_score(ref(serious=23, heat=50, litig=3, viol=80, complaints=60))

        check("unverified still synthetic 50.0", m.hpd_risk_score(None) == 50.0)
        check("a clean building stays near zero", clean < 5, str(clean))
        check("small owner-direct building stays reachable", keap < 65, f"{keap} (459 Keap St)")
        check("zero serious violations no longer maxes out", zero_serious < 65, f"{zero_serious} (was 100.0)")
        check("a neglected building still blocks", bad >= 95, str(bad))
        check("the range actually spreads", len({clean, keap, zero_serious, mid, bad}) == 5,
              f"{clean}, {keap}, {zero_serious}, {mid}, {bad}")
        check("scores never exceed the cap", all(0 <= v <= 100 for v in (clean, keap, zero_serious, mid, bad)))
        # the mistake worth never repeating
        check("NO per-unit divisor: unit_count must not change the score",
              m.hpd_risk_score(ref(serious=2, viol=4, units=2)) == m.hpd_risk_score(ref(serious=2, viol=4, units=799)),
              "per-unit maths blocked the best small lead and passed a 799-unit complex")
    finally:
        os.environ.pop("VERA_HPD_CALIBRATED", None)


def test_synthetic_risk_detection() -> None:
    spec = importlib.util.spec_from_file_location("sc", ROOT / "scripts" / "score_listings.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    print("\nsynthetic-risk detection — the honesty gate:")
    fake = {"hpd_risk_score": 50.0, "dob_risk_score": 45.0, "verification_status": "no_public_match"}
    real = {"hpd_risk_score": 47.5, "dob_risk_score": 7.5, "verification_status": "matched_public_records"}
    check("default 50/45 with no match reads as synthetic", m.has_synthetic_risk_scores(fake) is True)
    check("real matched numbers do not", m.has_synthetic_risk_scores(real) is False)


if __name__ == "__main__":
    test_shipped_formula_unchanged()
    test_calibrated_formula()
    test_synthetic_risk_detection()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        sys.exit(1)
    print("all scoring tests passed")

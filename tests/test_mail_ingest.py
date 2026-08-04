#!/usr/bin/env python3
"""Mail-ingestion tests. `python3 tests/test_mail_ingest.py`

Six defects were found in this path on 2026-08-04 before it had run once,
every one of them producing the same symptom: the stage reports success and
silently discards everything. These pin all six.
"""
from __future__ import annotations

import importlib.util
import json
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


def load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, ROOT / "scripts" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_price() -> None:
    """Bug 1: the pattern matched $2200 and missed $2,200 — the form both
    portals actually use — so every listing arrived priceless and was then
    dropped by the rent filter."""
    m = load("ingest_mail_alerts")
    print("\nprice parsing:")
    for text, want in [("$2,200 / month", "2,200"), ("$2,750", "2,750"),
                       ("$2,500/mo", "2,500"), ("$2200", "2200"),
                       ("$950", "950"), ("$12,500", "12,500")]:
        got = m.PRICE.findall(text)
        check(f"reads {text}", got == [want], str(got))


def test_address_recovery() -> None:
    """Bug 2: alerts carry no street address, so nothing could reach city
    records. Both portals encode it in the URL."""
    m = load("ingest_mail_alerts")
    print("\naddress recovered from the URL:")
    cases = [
        ("https://streeteasy.com/building/459-keap-st-brooklyn/garden", "459 Keap St", "Brooklyn"),
        ("https://www.zillow.com/homedetails/114-N-7th-St-1L-Brooklyn-NY-11249/998_zpid/", "114 N 7th St", "Brooklyn"),
        ("https://www.zillow.com/homedetails/45-W-83rd-St-New-York-NY-10024/1_zpid/", "45 W 83rd St", "Manhattan"),
    ]
    for url, addr, boro in cases:
        got_addr, got_boro, _ = m.address_from_url(url)
        check(f"{addr}", got_addr == addr and got_boro == boro, f"{got_addr} / {got_boro}")
    check("ordinals are not mangled (7th, not 7Th)",
          m.address_from_url(cases[1][0])[0] == "114 N 7th St")
    check("a bare rental id yields nothing rather than a guess",
          m.address_from_url("https://streeteasy.com/rental/4123456") == (None, None, None))


def test_beds() -> None:
    """Bug 6: without a bed count the authenticity classifier scores the
    listing 'low' and the scorer refuses to recommend anything low."""
    m = load("ingest_mail_alerts")
    print("\nbed count read from the alert body:")
    for text, want in [("Studio, 1 bath", 0.0), ("1 bd | 1 ba", 1.0),
                       ("2 beds", 2.0), ("$2,190/mo · 1 bedroom", 1.0),
                       ("no bed info", None)]:
        check(f"{text!r} -> {want}", m.beds_from_text(text) == want, str(m.beds_from_text(text)))


def test_cheap_filter_lets_prefiltered_through() -> None:
    """Bug 4: alerts carry no neighbourhood and no beds, so the cheap filter
    rejected 100% of them on missing data. They are pre-filtered by the saved
    search itself — unknown must not mean fail for this source."""
    n = load("normalize_listings")
    prefs = json.loads((ROOT / "configs" / "user_preferences.json").read_text())
    print("\ncheap filter, pre-filtered source:")

    def rec(src, **kw):
        d = {"source_name": src, "neighborhood": None, "beds": None, "rent": 2200,
             "room_share_flag": False, "sublet_flag": False}
        d.update(kw)
        return d

    check("email alert with unknown hood + beds passes",
          n.cheap_filter_status(rec("email_alerts"), prefs)[0] is True)
    check("a contradictory bed count still fails",
          n.cheap_filter_status(rec("email_alerts", beds=3), prefs)[0] is False)
    check("over budget still fails",
          n.cheap_filter_status(rec("email_alerts", rent=4200), prefs)[0] is False)
    check("every other source is unaffected",
          n.cheap_filter_status(rec("craigslist"), prefs)[0] is False)


def test_authenticity_lifts_with_beds() -> None:
    e = load("enrich_listings")
    print("\nauthenticity classification:")
    base = {"title": "459 Keap St garden", "full_description": None,
            "address_normalized": "459 keap st", "rent": 2200, "address_confidence": "high"}
    check("no beds scores low (why bug 6 mattered)",
          e.classify_listing_type({**base, "beds": None})[1] == "low")
    check("beds recovered lifts it to medium, which clears the gate",
          e.classify_listing_type({**base, "beds": 0})[1] == "medium")


def test_config_absent_is_a_clean_skip() -> None:
    """The source must never fail loudly when simply unconfigured."""
    d = load("discover_listings")
    print("\nunconfigured behaviour:")
    manifest: dict = {"sources": []}
    logs: list = []
    d.discover_email_alerts({"source_name": "email_alerts", "max_results_per_query": 5,
                             "access_mode": "manual_review"}, {}, manifest, logs)
    status = manifest["sources"][0]["status"]
    check("absent or rejected credentials never crash the sweep",
          status in ("skipped", "error"), status)


if __name__ == "__main__":
    test_price()
    test_address_recovery()
    test_beds()
    test_cheap_filter_lets_prefiltered_through()
    test_authenticity_lifts_with_beds()
    test_config_absent_is_a_clean_skip()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        sys.exit(1)
    print("all mail-ingestion tests passed")

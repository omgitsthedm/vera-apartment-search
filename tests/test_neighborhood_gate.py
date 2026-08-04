#!/usr/bin/env python3
"""Neighbourhood-gate tests. `python3 tests/test_neighborhood_gate.py`

The neighbourhood gate decides which listings are worth a city-record
lookup, and it is the single biggest filter in the pipeline: on 2026-08-04
it rejected 203 of 256 listings, more than every other rule combined. Three
separate faults were found in it that day, and each one was invisible
because the gate's verdict looked reasonable either way.

1. The target list was run through canonical_text(), which is the STREET
   ADDRESS normaliser — it abbreviates compass words. "East Village" became
   "e village" and "Upper East Side" became "upper e side", so five of the
   forty-two targets could never match, including the two David named first.
   The same mangling made "e village" a substring of "middle village", so
   Queens listings passed as East Village.

2. resolve_neighborhood() only filled in blank or borough-only labels, so a
   confidently wrong one survived. RentHop had four Brooklyn and Queens
   apartments labelled "East Village", and VERA published them that way.

3. NYC reuses neighbourhood names across boroughs. Flushing's NTA is
   "Murray Hill-Broadway Flushing", which matched the Manhattan target
   "Murray Hill" through the compound-part rule that exists to make
   "Upper East Side-Lenox Hill-Roosevelt Island" work.

Net on the live pool: 47 passes became 46 — but 11 of those 47 slots were
wrong. Five real target-neighbourhood listings had never been verified, and
six Queens/Bronx listings were consuming lookups.
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


from config.nta_lookup import (  # noqa: E402
    borough_at,
    in_target_area,
    neighborhood_at,
    neighborhood_matches,
    resolve_neighborhood,
    target_boroughs,
)

TARGETS = json.loads((ROOT / "configs" / "user_preferences.json").read_text())["neighborhoods"]


def test_compass_neighbourhoods_are_matchable() -> None:
    """Fault 1. The regression that hid five target neighbourhoods."""
    from workflow_support import canonical_text
    print("\ncompass-word neighbourhoods (the ones that silently vanished):")
    for hood in ("East Village", "West Village", "Lower East Side",
                 "Upper East Side", "Upper West Side"):
        check(f"{hood} matches its own target list", neighborhood_matches(hood, TARGETS), "")
    mangled = {canonical_text(t) for t in TARGETS}
    check("and the address normaliser is NOT used on the target list",
          not neighborhood_matches("East Village", mangled),
          "canonical_text('East Village') = " + repr(canonical_text("East Village")))
    check("the mangled form is what made Middle Village look like East Village",
          "e village" in canonical_text("Middle Village"))


def test_a_wrong_label_loses_to_the_city_polygon() -> None:
    """Fault 2. Four real RentHop records, with their real coordinates."""
    print("\nsource label vs the city's own boundary:")
    mislabelled = [
        ("126 grant ave", 40.6878, -73.8684, "Cypress Hills"),
        ("1751 85 st", 40.6084, -74.0026, "Bath Beach"),
        ("1940 79th st", 40.6092, -73.9954, "Bensonhurst"),
        ("215-07 jamaica ave", 40.7174, -73.7405, "Queens Village"),
    ]
    for addr, lat, lon, true_hood in mislabelled:
        listing = {"neighborhood": "East Village", "latitude": lat, "longitude": lon}
        got, was = resolve_neighborhood(listing)
        check(f"{addr} is corrected to {true_hood}",
              was and str(got) == true_hood, f"{got}")

    print("\n  but a label that agrees is never rewritten:")
    check("a compound NTA agrees with its own part",
          resolve_neighborhood({"neighborhood": "Lenox Hill", "latitude": 40.7662, "longitude": -73.9601})[1] is False,
          "")
    check("an exact match is left alone",
          resolve_neighborhood({"neighborhood": "East Village", "latitude": 40.7288, "longitude": -73.9828})[1] is False)
    check("no coordinates means no opinion",
          resolve_neighborhood({"neighborhood": "East Village"})[1] is False)
    check("a borough-only label is still filled in",
          resolve_neighborhood({"neighborhood": "Brooklyn", "latitude": 40.7143, "longitude": -73.9540})[1] is True)


def test_same_name_other_borough() -> None:
    """Fault 3. Flushing is not Murray Hill."""
    print("\nthe same name in another borough:")
    check("the target list covers Manhattan and Brooklyn only",
          set(target_boroughs(TARGETS)) == {"M", "B"}, str(sorted(target_boroughs(TARGETS))))
    check("an ambiguous target name does not widen the set",
          "Q" not in target_boroughs(TARGETS),
          "'Murray Hill' is both Manhattan and Flushing — it must authorise neither")

    flushing = {"neighborhood": "Murray Hill-Broadway Flushing", "latitude": 40.7606, "longitude": -73.7968}
    manhattan = {"neighborhood": "Murray Hill-Kips Bay", "latitude": 40.7479, "longitude": -73.9756}
    check("Flushing does not pass as Murray Hill", in_target_area(flushing, TARGETS) is False,
          f"borough {borough_at(40.7606, -73.7968)}")
    check("the real Murray Hill still does", in_target_area(manhattan, TARGETS) is True)
    check("the name alone would still have matched — the borough is what stops it",
          neighborhood_matches(flushing["neighborhood"], TARGETS) is True)


def test_the_gate_end_to_end() -> None:
    print("\nthe cheap filter, with all three faults fixed:")
    spec = importlib.util.spec_from_file_location("nl", ROOT / "scripts" / "normalize_listings.py")
    nl = importlib.util.module_from_spec(spec)
    sys.modules["nl"] = nl
    spec.loader.exec_module(nl)
    prefs = json.loads((ROOT / "configs" / "user_preferences.json").read_text())

    def rec(**kw):
        d = {"source_name": "craigslist", "rent": 2200, "beds": 1.0,
             "room_share_flag": False, "sublet_flag": False}
        d.update(kw)
        return d

    check("a real East Village listing passes",
          nl.cheap_filter_status(rec(neighborhood="East Village", latitude=40.7288, longitude=-73.9828), prefs)[0] is True)
    check("a real Upper West Side listing passes",
          nl.cheap_filter_status(rec(neighborhood="Upper West Side-Lincoln Square", latitude=40.7769, longitude=-73.9820), prefs)[0] is True)
    check("Middle Village, Queens does not",
          nl.cheap_filter_status(rec(neighborhood="Middle Village", latitude=40.7176, longitude=-73.8748), prefs)[0] is False)
    check("Flushing does not",
          nl.cheap_filter_status(rec(neighborhood="Murray Hill-Broadway Flushing", latitude=40.7606, longitude=-73.7968), prefs)[0] is False)
    check("a listing with no coordinates is judged on its name, not rejected for missing data",
          nl.cheap_filter_status(rec(neighborhood="East Village"), prefs)[0] is True)
    check("and the other rules still bite",
          nl.cheap_filter_status(rec(neighborhood="East Village", latitude=40.7288, longitude=-73.9828, rent=4200), prefs)[0] is False)


if __name__ == "__main__":
    test_compass_neighbourhoods_are_matchable()
    test_a_wrong_label_loses_to_the_city_polygon()
    test_same_name_other_borough()
    test_the_gate_end_to_end()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        sys.exit(1)
    print("all neighbourhood-gate tests passed")

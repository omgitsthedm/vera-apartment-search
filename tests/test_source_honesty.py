#!/usr/bin/env python3
"""Source-honesty tests. `python3 tests/test_source_honesty.py`

A source that reads green while contributing nothing is worse than a source
that reads red: it tells the operator coverage exists where it does not, and
the whole product rests on the claim that VERA does not pretend a gap is a
fact.

All nineteen discovery functions write `"status": "ok"` unconditionally. The
only thing that ever caught a silently-dead source was a history comparison
in build_snapshot, and cloud runs start from a fresh checkout with no
history — so on 2026-08-04 the published cloud feed carried streeteasy as
`ok` with zero listings.

These pin both halves of the fix, and both are deliberately history-free:
they have to be right on the first run on a brand-new machine, because that
is the case that failed.
"""
from __future__ import annotations

import importlib.util
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
    sys.modules[mod] = m
    spec.loader.exec_module(m)
    return m


def entry(name, status="ok", records=0, ok_q=0, total_q=0):
    return {"source_name": name, "status": status, "record_count": records,
            "queries_ok": ok_q, "queries_total": total_q}


def test_status_reflects_what_happened() -> None:
    dl = load("discover_listings")
    print("\nreported status vs what actually happened:")

    cases = [
        ("every query failed is not 'ok'",
         entry("streeteasy", records=0, ok_q=0, total_q=8), "failing"),
        ("a working source stays ok",
         entry("craigslist", records=223, ok_q=12, total_q=12), "ok"),
        ("some queries failing is partial",
         entry("openigloo", records=44, ok_q=3, total_q=5), "partial"),
        ("a skip is left alone — it was never contacted",
         entry("renthop", status="skipped", records=0, ok_q=0, total_q=0), "skipped"),
        ("an error is left alone",
         entry("nooklyn", status="error", records=0, ok_q=0, total_q=3), "error"),
        ("a source that reports no query counts is not guessed at",
         entry("listings_project", records=5, ok_q=0, total_q=0), "ok"),
    ]
    manifest = {"sources": [c[1] for c in cases]}
    dl.finalize_source_statuses(manifest, [])
    for label, e, want in cases:
        check(label, e["status"] == want, f"{e['source_name']} -> {e['status']}")

    failing = next(e for e in manifest["sources"] if e["source_name"] == "streeteasy")
    check("the failure carries a reason a human can act on",
          "8" in str(failing.get("reason")), str(failing.get("reason")))


def test_no_history_is_not_a_clean_bill_of_health() -> None:
    """The exact cloud case: nothing found, nothing remembered."""
    cls = load("build_snapshot").classify_source_status
    print("\nclassification with no history (every cloud run):")

    check("ran clean, found nothing, no history -> NOT healthy",
          cls("ok", "", 0, []) == "degraded", cls("ok", "", 0, []))
    check("found nothing where it reliably produced -> failing",
          cls("ok", "", 0, [30, 28, 31]) == "failing", cls("ok", "", 0, [30, 28, 31]))
    check("a long way down from a strong baseline -> degraded",
          cls("ok", "", 5, [40, 44, 38]) == "degraded", cls("ok", "", 5, [40, 44, 38]))
    check("producing normally -> healthy",
          cls("ok", "", 223, [210, 230]) == "healthy", cls("ok", "", 223, [210, 230]))
    check("first ever run that DID find listings -> healthy",
          cls("ok", "", 44, []) == "healthy", cls("ok", "", 44, []))

    print("\n  skips are not failures:")
    check("deliberately disabled -> disabled",
          cls("skipped", "disabled by operator", 0, []) == "disabled")
    check("blocked from this network -> not_scheduled, not broken",
          cls("skipped", "cloud_blocked", 0, []) == "not_scheduled")
    check("an errored source with partial records -> partial",
          cls("error", "", 12, []) == "partial")
    check("an errored source with nothing -> failing",
          cls("error", "", 0, []) == "failing")


def test_a_source_cannot_pad_its_count_with_index_pages() -> None:
    """The subtler version of a green-but-empty source: one that reports
    records which are not listings at all."""
    dl = load("discover_listings")
    junk = dl.is_index_page_not_a_listing
    print("\nindex pages vs listings:")
    check("a page with no price is not a listing", junk(None, "Listings") is True)
    check("even when it carried a bed count from a card on it",
          junk(None, "Listings") is True, "/listings/Austin came through with beds=5")
    check("a priced listing is kept", junk(2200, "Cozy 1BR in Greenpoint") is False)
    check("a cheap one too — the rule is about presence, not amount",
          junk(0.0, "") is False, "0 is a price; None is not a listing")


def test_a_source_is_never_asked_for_less_than_the_hunt_wants() -> None:
    """Five of nine enabled sources carried a stale 2500 cap while the user's
    ceiling was 3000, so a fifth of the price range was never requested."""
    dl = load("discover_listings")
    emr = dl.effective_max_rent
    print("\nthe ceiling a source is asked for:")
    check("a stale source cap does not undercut the hunt",
          emr({"max_price": 2500}, {"max_rent": 3000}) == 3000, str(emr({"max_price": 2500}, {"max_rent": 3000})))
    check("a genuinely wider source cap is still honoured",
          emr({"max_price": 4000}, {"max_rent": 3000}) == 4000)
    check("no source cap means the hunt's ceiling",
          emr({}, {"max_rent": 3000}) == 3000)
    check("no preference means the source cap",
          emr({"max_price": 2500}, {}) == 2500)
    check("neither means the documented default", emr({}, {}) == 2500)

    import json as _json
    prefs = _json.loads((ROOT / "configs" / "user_preferences.json").read_text())
    cat = _json.loads((ROOT / "configs" / "source_catalog.json").read_text())
    low = [s["source_name"] for s in cat["sources"] if s.get("enabled")
           and emr(s, prefs) < prefs["max_rent"]]
    check("no enabled source is asked for less than the ceiling today",
          not low, ", ".join(low) or "none")


def test_neighbourhood_queries_are_scoped_to_the_right_borough() -> None:
    dl = load("discover_listings")
    import json as _json
    prefs = _json.loads((ROOT / "configs" / "user_preferences.json").read_text())
    cat = _json.loads((ROOT / "configs" / "source_catalog.json").read_text())
    src = next(s for s in cat["sources"] if s["source_name"] == "openigloo")
    searches = dl.build_openigloo_searches(src, prefs)
    boro = [s for s in searches if s.get("scope") == "borough"]
    hood = [s for s in searches if s.get("scope") == "neighborhood"]
    by_label = {s["label"]: s["url"] for s in hood}

    print("\nneighbourhood-scoped queries:")
    check("the borough sweeps are kept — the wide net stays wide", len(boro) >= 4, str(len(boro)))
    check("and target neighbourhoods are queried directly", len(hood) >= 25, str(len(hood)))
    check("Manhattan hoods scope to manhattan",
          "borough:manhattan|nbr:upper-east-side" in by_label.get("Upper East Side", ""))
    check("Brooklyn hoods scope to brooklyn",
          "borough:brooklyn|nbr:williamsburg" in by_label.get("Williamsburg", ""))
    check("a name that spans boroughs is not scoped at all",
          "Murray Hill" not in by_label,
          "Manhattan and Flushing both — a guess would search the wrong half of the city")
    check("every query carries the hunt's real ceiling",
          all("price:-3000" in u for u in by_label.values()), "")


def test_the_result_budget_goes_where_the_targets_are() -> None:
    """Every kept craigslist listing costs a detail fetch, so the cap is a
    politeness limit. It was split evenly across five boroughs — 125 of the
    250 fetches went to Queens, the Bronx and Staten Island, which contain
    no target neighbourhood at all."""
    dl = load("discover_listings")
    import json as _json
    prefs = _json.loads((ROOT / "configs" / "user_preferences.json").read_text())
    cat = _json.loads((ROOT / "configs" / "source_catalog.json").read_text())
    src = next(s for s in cat["sources"] if s["source_name"] == "craigslist")
    caps = {s["label"]: s["result_cap"] for s in dl.build_craigslist_searches(src, prefs)}
    print("\ncraigslist result budget by borough:")
    for k, v in caps.items():
        print(f"     {k:<16}{v}")

    check("Manhattan and Brooklyn get the budget",
          caps.get("Manhattan", 0) > 60 and caps.get("Brooklyn", 0) > 60, str(caps))
    check("boroughs with no target get a small sample, not zero",
          0 < caps.get("Queens", 0) <= 20 and 0 < caps.get("Bronx", 0) <= 20,
          "the Market page promises the whole net")
    check("a target borough gets far more than a non-target one",
          caps.get("Brooklyn", 0) >= 4 * caps.get("Queens", 1))
    # measured availability on 2026-08-04
    avail = {"Manhattan": 89, "Brooklyn": 647, "Queens": 303, "Bronx": 83, "Staten Island": 25}
    total = sum(min(avail.get(k, 0), v) for k, v in caps.items())
    check("and the total fetch count stays inside the old budget",
          total <= 250, f"{total} detail fetches vs 250 before")


def test_a_landlord_reusing_their_own_photo_is_not_a_clone() -> None:
    """The clone detector accuses; the accusation has to be right.

    On 2026-08-04, the first night portfolio data reached the cloud, both
    flagged listings were 322 E 81 St and 321 E 75 St — filed under Round
    Hill Management and Frank & Walter Eberhart L.P. #1, which JustFix puts
    under Eberhart Brothers, LLC at the same business address, 46 buildings.
    One owner, two of their own walk-ups, one marketing photo. The flag costs
    20 points of confidence and both scored 59.6 and 59.9 against a 60 bar.
    """
    ph = load("refresh_photo_hashes")
    key = ph.owner_key
    print("\nsame photo, same owner:")

    eberhart = {"landlord_portfolio": {"topbusinessaddr": "312 EAST 82ND STREET 10028",
                                       "topcorp": "Eberhart Brothers, LLC"}}
    eberhart2 = {"landlord_portfolio": {"topbusinessaddr": "312 East 82nd Street 10028",
                                        "topcorp": "Eberhart Brothers, LLC"}}
    orchard = {"landlord_portfolio": {"topbusinessaddr": "17 STANTON STREET 2 10002",
                                      "topcorp": "ORCHARD STREET REALTY LLC"}}

    def suppressed(a, b):
        ka, kb = key(a), key(b)
        return bool(ka and kb and ka == kb)

    check("the real pair is recognised as one owner", suppressed(eberhart, eberhart2) is True)
    check("case and spacing do not defeat it", key(eberhart) == key(eberhart2))
    check("two unrelated owners still get flagged", suppressed(eberhart, orchard) is False)
    check("an unknown owner on either side still gets flagged",
          suppressed(eberhart, {}) is False, "silence is the more dangerous error")
    check("both unknown still gets flagged", suppressed({}, {}) is False)
    check("business address is preferred over the corporate name",
          key({"landlord_portfolio": {"topbusinessaddr": "1 main st", "topcorp": "X LLC"}}) == "1 main st",
          "names differ across a portfolio more often than the address they file from")
    check("falls back to owner_name when there is no portfolio yet",
          key({"owner_name": "KING ENTERPRISES"}) == "king enterprises")


def test_a_leasing_office_is_not_a_scam_ring() -> None:
    """Same blind spot as the photo clone, in the contact-reuse tell."""
    reuse = load("build_snapshot").distinct_owner_reuse
    uids = [f"u{i}" for i in range(5)]
    print("\none phone across five listings:")
    check("all five under one leasing office — not reuse",
          reuse(uids, {u: "312 east 82nd street 10028" for u in uids}) == 0)
    check("five different owners — a real ring, counted in full",
          reuse(uids, {u: f"owner{i}" for i, u in enumerate(uids)}) == 5)
    check("no public record for any of them — still counted",
          reuse(uids, {}) == 5, "an unknown owner is its own party")
    check("one outsider among an office's own — still counted",
          reuse(uids, {"u0": "x", "u1": "x", "u2": "elsewhere", "u3": "x", "u4": "x"}) == 5)
    check("a single listing is never reuse", reuse(["u0"], {"u0": "x"}) == 0)


def test_the_published_feed_would_have_caught_it() -> None:
    """A source with zero records must never reach the public feed as healthy."""
    pl = load("public_lens")
    print("\nwhat the public feed shows:")
    payload = {
        "generated_at": "2026-08-04T00:00:00+00:00",
        "shortlist": [], "reviewed_out": [],
        "sources": [
            {"source_name": "streeteasy", "status": "failing", "record_count": 0,
             "reason": "all 8 queries failed", "enabled": True},
            {"source_name": "craigslist", "status": "ok", "record_count": 223, "enabled": True},
        ],
    }
    extras = pl.build_public_extras(payload)
    by_name = {s["source_name"]: s for s in extras["sources"]}
    check("the failing source is published as failing",
          by_name["streeteasy"]["status"] == "failing")
    check("its record count is published too, so yield is visible",
          by_name["streeteasy"]["record_count"] == 0)
    check("the reason survives to the public Pipeline page",
          by_name["streeteasy"].get("reason") == "all 8 queries failed")
    check("the working source is unaffected", by_name["craigslist"]["status"] == "ok")


if __name__ == "__main__":
    test_status_reflects_what_happened()
    test_no_history_is_not_a_clean_bill_of_health()
    test_a_source_cannot_pad_its_count_with_index_pages()
    test_a_source_is_never_asked_for_less_than_the_hunt_wants()
    test_neighbourhood_queries_are_scoped_to_the_right_borough()
    test_the_result_budget_goes_where_the_targets_are()
    test_a_landlord_reusing_their_own_photo_is_not_a_clone()
    test_a_leasing_office_is_not_a_scam_ring()
    test_the_published_feed_would_have_caught_it()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        sys.exit(1)
    print("all source-honesty tests passed")

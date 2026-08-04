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
    test_the_published_feed_would_have_caught_it()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        sys.exit(1)
    print("all source-honesty tests passed")

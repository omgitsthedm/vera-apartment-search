#!/usr/bin/env python3
"""Offline publication tests using synthetic data only."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(name)


def load_publisher():
    spec = importlib.util.spec_from_file_location("publish_cloud_feed", ROOT / "scripts" / "publish_cloud_feed.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_snapshot(generated_at: object = "2026-09-24T05:55:28+00:00") -> dict:
    return {
        "generated_at": generated_at,
        "snapshot": {"status": "success"},
        "shortlist": [{
            "listing_uid": "synthetic-1",
            "address_normalized": "100 Example Street",
            "borough": "Brooklyn",
            "rent": 2200,
            "overall_score": 71,
            "listing_confidence_score": 70,
            "hpd_risk_score": 1,
            "dob_risk_score": 1,
            "recommendation": "pursue",
            "contact_phone": "917-555-0142",
            "analyst_notes": "private",
        }],
        "reviewed_out": [],
        "run": {"status": "success", "finished_at": "2026-09-24T05:55:00+00:00"},
    }


def publish(snapshot: dict) -> tuple[int, Path, tempfile.TemporaryDirectory[str]]:
    publisher = load_publisher()
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    latest = root / "latest_snapshot.json"
    latest.write_text(json.dumps(snapshot))
    publisher.LATEST = latest
    publisher.LKG = root / "last_known_good_snapshot.json"
    publisher.SNAPSHOTS = root
    output = root / "out"
    old_argv = sys.argv
    try:
        sys.argv = ["publish_cloud_feed.py", "--out", str(output)]
        result = publisher.main()
    finally:
        sys.argv = old_argv
    return result, output, temporary


def test_snapshot_timestamp_is_preserved() -> None:
    print("\npublisher freshness and privacy:")
    for timestamp, label in (("2026-09-24T05:55:28+00:00", "UTC"),
                             ("2026-09-24T05:55:28+05:00", "offset")):
        snapshot = synthetic_snapshot(timestamp)
        result, output, temporary = publish(snapshot)
        try:
            public = json.loads((output / "public.json").read_text())
            meta = json.loads((output / "meta.json").read_text())
            blob = json.dumps(public)
            publisher = load_publisher()
            check(f"the synthetic {label} snapshot publishes", result == 0)
            check(f"public.json keeps the {label} snapshot timestamp", public.get("generated_at") == timestamp)
            check(f"meta.json keeps the {label} snapshot timestamp", meta.get("generated_at") == timestamp)
            check(f"the {label} payload passes the independent privacy audit", publisher.audit_public_payload(public) == [])
            check(f"the {label} payload omits private fields", "contact_phone" not in blob and "917-555-0142" not in blob and "analyst_notes" not in blob)
        finally:
            temporary.cleanup()


def test_invalid_snapshot_timestamps_refuse_publication() -> None:
    for timestamp, label in ((None, "missing"),
                             ("2026-09-24T05:55:28", "naive"),
                             ("not-a-timestamp", "invalid")):
        result, output, temporary = publish(synthetic_snapshot(timestamp))
        try:
            check(f"a {label} source timestamp refuses publication", result == 1)
            check(f"a {label} timestamp writes no public feed",
                  not (output / "public.json").exists() and not (output / "meta.json").exists())
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    test_snapshot_timestamp_is_preserved()
    test_invalid_snapshot_timestamps_refuse_publication()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        raise SystemExit(1)
    print("all cloud-feed publisher tests passed")

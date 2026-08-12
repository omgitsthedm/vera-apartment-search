#!/usr/bin/env python3
"""Offline contract tests for the read-only first-party feed monitor."""
from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("feed_health", ROOT / "scripts" / "check_public_feed_health.py")
HEALTH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HEALTH
SPEC.loader.exec_module(HEALTH)

FAILURES: list[str] = []
NOW = datetime(2026, 8, 12, 7, 0, tzinfo=UTC)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail else ""))
    if not ok:
        FAILURES.append(name)


def meta(**overrides):
    value = {"origin": "cloud", "snapshot_source": "latest", "pool": 1, "generated_at": (NOW - timedelta(hours=1)).isoformat()}
    value.update(overrides)
    return value


def main() -> int:
    print("\nfirst-party feed health contract:")
    check("a recent non-empty cloud feed passes", HEALTH.validate_meta(meta(), NOW) == [])
    check("origin must be cloud", any("origin" in item for item in HEALTH.validate_meta(meta(origin="local"), NOW)))
    check("latest snapshot source passes", HEALTH.validate_meta(meta(snapshot_source="latest"), NOW) == [])
    check("fallback snapshot sources fail", all(
        any("snapshot_source" in item for item in HEALTH.validate_meta(meta(snapshot_source=source), NOW))
        for source in ("last_known_good", None)
    ))
    check("empty pools fail closed", any("pool" in item for item in HEALTH.validate_meta(meta(pool=0), NOW)))
    check("invalid JSON metadata timestamps fail closed", any("generated_at" in item for item in HEALTH.validate_meta(meta(generated_at="not-a-time"), NOW)))
    check("a feed older than 36 hours fails closed", any("36-hour" in item for item in HEALTH.validate_meta(meta(generated_at=(NOW - timedelta(hours=36, seconds=1)).isoformat()), NOW)))
    check("a feed exactly 36 hours old remains within the threshold", HEALTH.validate_meta(meta(generated_at=(NOW - timedelta(hours=36)).isoformat()), NOW) == [])
    check("future metadata fails closed", any("future" in item for item in HEALTH.validate_meta(meta(generated_at=(NOW + timedelta(minutes=6)).isoformat()), NOW)))
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: " + "; ".join(FAILURES))
        return 1
    print("all public-feed health tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

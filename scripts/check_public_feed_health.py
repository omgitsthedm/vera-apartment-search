#!/usr/bin/env python3
"""Read-only health check for VERA's first-party public feed metadata.

This is intentionally a monitor, not a publisher: it makes one GET request
to the Little Fight NYC first-party metadata route and exits non-zero when
the public contract is unavailable, invalid, empty, not cloud-produced from
the latest snapshot, or older than the documented freshness window.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

META_URL = "https://littlefightnyc.com/vera/data/meta.json"
MAX_AGE = timedelta(hours=36)
TIMEOUT_SECONDS = 20


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def validate_meta(meta: Any, now: datetime | None = None) -> list[str]:
    """Return every contract violation without printing feed contents."""
    if not isinstance(meta, dict):
        return ["metadata is not a JSON object"]

    problems: list[str] = []
    if meta.get("origin") != "cloud":
        problems.append("metadata origin is not 'cloud'")
    if meta.get("snapshot_source") != "latest":
        problems.append("metadata snapshot_source is not 'latest'")

    pool = meta.get("pool")
    if not isinstance(pool, int) or isinstance(pool, bool) or pool <= 0:
        problems.append("metadata pool is empty or invalid")

    generated_at = parse_timestamp(meta.get("generated_at"))
    if generated_at is None:
        problems.append("metadata generated_at is missing or invalid")
    else:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        age = current.astimezone(UTC) - generated_at.astimezone(UTC)
        if age < timedelta(minutes=-5):
            problems.append("metadata generated_at is implausibly in the future")
        elif age > MAX_AGE:
            problems.append("metadata is older than the 36-hour freshness window")
    return problems


def fetch_meta() -> dict[str, Any]:
    request = urllib.request.Request(
        META_URL,
        headers={"Accept": "application/json", "User-Agent": "VERA-feed-health/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RuntimeError(f"metadata returned HTTP {response.status}")
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"metadata request failed: {exc}") from exc

    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("metadata response is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("metadata response is not a JSON object")
    return decoded


def main() -> int:
    try:
        problems = validate_meta(fetch_meta())
    except RuntimeError as exc:
        print(f"VERA feed health FAILED: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("VERA feed health FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("VERA feed health passed: first-party cloud feed is fresh and non-empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Per-source reliability scoring and run trend tracking for VERA.

Computes a 0–100 reliability score per source based on:
  - Parser confidence (30%)
  - Success rate over trailing 7 runs (25%)
  - Freshness vs expected cadence (20%)
  - Anomaly status (15%)
  - Record stability vs trailing average (10%)

Also maintains a rolling history of the last 7 runs per source
in state/source_trends.json for trend analysis.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.paths import STATE_DIR

TREND_STATE_FILE = STATE_DIR / "source_trends.json"
MAX_TREND_RUNS = 7

CADENCE_MINUTES = {
    "hourly": 60,
    "daily": 1440,
    "weekly": 10080,
}


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _parse_iso(value: str | None) -> float:
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0


def _freshness_score(last_success_at: str | None, cadence: str) -> float:
    """Score 0–1 based on how recently the source last succeeded relative to cadence."""
    ts = _parse_iso(last_success_at)
    if not ts:
        return 0.0
    age_minutes = (_now_ts() - ts) / 60
    expected = CADENCE_MINUTES.get(cadence, 1440)
    # Full score if within 1x cadence, linear decay to 0 at 3x
    if age_minutes <= expected:
        return 1.0
    if age_minutes >= expected * 3:
        return 0.0
    return 1.0 - (age_minutes - expected) / (expected * 2)


def _record_stability_score(current_count: int, trailing_avg: float | None) -> float:
    """Score 0–1 based on how close current records are to trailing average."""
    if trailing_avg is None or trailing_avg <= 0:
        return 0.5  # No baseline yet, neutral
    ratio = current_count / trailing_avg
    if 0.7 <= ratio <= 1.5:
        return 1.0  # Within normal range
    if ratio < 0.3 or ratio > 3.0:
        return 0.0  # Way off
    # Linear interpolation in the gap zones
    if ratio < 0.7:
        return (ratio - 0.3) / 0.4
    return 1.0 - (ratio - 1.5) / 1.5


def compute_reliability_score(
    confidence: float | None,
    success_rate: float | None,
    last_success_at: str | None,
    cadence: str,
    anomaly_flag: bool,
    current_records: int,
    trailing_avg: float | None,
) -> tuple[int, float, float]:
    """Compute composite reliability score 0–100.

    Returns (score, freshness_raw, stability_raw) so callers can build breakdowns.
    """
    conf = min(max(confidence or 0.5, 0.0), 1.0)
    rate = min(max(success_rate or 0.5, 0.0), 1.0)
    fresh = _freshness_score(last_success_at, cadence)
    anomaly = 0.0 if anomaly_flag else 1.0
    stability = _record_stability_score(current_records, trailing_avg)

    weighted = (
        conf * 0.30
        + rate * 0.25
        + fresh * 0.20
        + anomaly * 0.15
        + stability * 0.10
    )
    return round(weighted * 100), fresh, stability


def record_source_run(
    source_name: str,
    run_id: str,
    status: str,
    records_found: int,
    confidence: float | None = None,
    parser_version: str | None = None,
) -> None:
    """Append a run entry to the source's trend history."""
    state = _read_json(TREND_STATE_FILE, default={})
    history = state.setdefault(source_name, [])

    history.append({
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "records_found": records_found,
        "confidence": confidence,
        "parser_version": parser_version,
    })

    # Trim to last N runs
    state[source_name] = history[-MAX_TREND_RUNS:]
    _write_json(TREND_STATE_FILE, state)


def get_source_trends(source_name: str) -> list[dict[str, Any]]:
    """Return the last N run entries for a source."""
    state = _read_json(TREND_STATE_FILE, default={})
    return state.get(source_name, [])


def get_all_source_trends() -> dict[str, list[dict[str, Any]]]:
    """Return all source trend data."""
    return _read_json(TREND_STATE_FILE, default={})


def success_rate_from_trends(trends: list[dict[str, Any]]) -> float | None:
    """Compute success rate from trend history."""
    if not trends:
        return None
    successes = sum(1 for t in trends if t.get("status") in ("ok", "healthy", "success"))
    return successes / len(trends)

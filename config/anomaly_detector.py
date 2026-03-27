"""Anomaly detection and HTML fingerprint change detection for VERA sources.

Tracks per-source record counts over time and detects:
- Record count drops > 50% vs trailing 7-day average
- HTML fingerprint changes (structural layout shifts)

State is persisted in state/source_anomalies.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.paths import STATE_DIR

ANOMALY_STATE_FILE = STATE_DIR / "source_anomalies.json"
MAX_HISTORY_DAYS = 30
DROP_THRESHOLD = 0.50  # Flag if record count drops by 50%+


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _trailing_average(history: list[dict[str, Any]], days: int = 7) -> float | None:
    """Compute trailing average record count over the last N days."""
    if not history:
        return None
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
    recent = []
    for entry in history:
        try:
            ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp()
            if ts >= cutoff:
                recent.append(entry.get("record_count", 0))
        except (KeyError, ValueError):
            continue
    return sum(recent) / len(recent) if recent else None


def compute_html_fingerprint(html: str) -> str:
    """Hash key structural features of an HTML page.

    Captures: title, canonical URL, JSON-LD presence, key element patterns.
    This fingerprint changes when the site's layout fundamentally shifts.
    """
    features = []

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if title_match:
        features.append(f"title:{title_match.group(1).strip()[:100]}")

    canonical_match = re.search(r'<link[^>]*rel="canonical"[^>]*href="([^"]*)"', html, re.I)
    if canonical_match:
        features.append(f"canonical:{canonical_match.group(1)[:100]}")

    has_jsonld = "application/ld+json" in html
    features.append(f"jsonld:{has_jsonld}")

    script_count = len(re.findall(r"<script[^>]*>", html, re.I))
    features.append(f"scripts:{script_count}")

    has_article = bool(re.search(r"<article", html, re.I))
    has_table = bool(re.search(r"<table", html, re.I))
    has_listing = bool(re.search(r'class="[^"]*listing[^"]*"', html, re.I))
    features.append(f"article:{has_article}")
    features.append(f"table:{has_table}")
    features.append(f"listing_class:{has_listing}")

    fingerprint_input = "|".join(sorted(features))
    return hashlib.sha256(fingerprint_input.encode()).hexdigest()[:16]


def check_source_anomalies(
    source_name: str,
    record_count: int,
    html_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Check a source for anomalies and update history.

    Returns anomaly report dict with fields:
      - anomaly_flag: bool
      - record_count_drop: float or None
      - trailing_7d_avg: float or None
      - layout_change_suspected: bool
      - reason: str or None
    """
    state = _read_json(ANOMALY_STATE_FILE, default={})
    source_state = state.setdefault(source_name, {"history": [], "last_fingerprint": None})

    history = source_state.get("history", [])
    avg_7d = _trailing_average(history, days=7)
    avg_30d = _trailing_average(history, days=30)

    anomaly_flag = False
    reasons = []
    record_count_drop = None

    if avg_7d is not None and avg_7d > 0:
        record_count_drop = round(1 - (record_count / avg_7d), 3)
        if record_count_drop >= DROP_THRESHOLD:
            anomaly_flag = True
            pct = round(record_count_drop * 100, 1)
            reasons.append(f"record count dropped {pct}% vs 7d avg ({record_count} vs {avg_7d:.0f})")

    layout_change = False
    if html_fingerprint:
        prev = source_state.get("last_fingerprint")
        if prev and prev != html_fingerprint:
            layout_change = True
            reasons.append("HTML layout fingerprint changed")
        source_state["last_fingerprint"] = html_fingerprint

    # Append to history
    history.append({
        "timestamp": _now_iso(),
        "record_count": record_count,
        "fingerprint": html_fingerprint,
    })

    # Trim history to MAX_HISTORY_DAYS
    cutoff = datetime.now(timezone.utc).timestamp() - (MAX_HISTORY_DAYS * 86400)
    source_state["history"] = [
        e for e in history
        if _parse_ts(e.get("timestamp")) >= cutoff
    ]

    state[source_name] = source_state
    _write_json(ANOMALY_STATE_FILE, state)

    return {
        "source": source_name,
        "anomaly_flag": anomaly_flag or layout_change,
        "record_count": record_count,
        "trailing_7d_avg": round(avg_7d, 1) if avg_7d is not None else None,
        "trailing_30d_avg": round(avg_30d, 1) if avg_30d is not None else None,
        "record_count_drop": record_count_drop,
        "layout_change_suspected": layout_change,
        "reason": "; ".join(reasons) if reasons else None,
    }


def _parse_ts(value: str | None) -> float:
    if not value:
        return 0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0


def get_all_anomaly_reports() -> dict[str, dict[str, Any]]:
    """Read current anomaly state and return latest report per source."""
    state = _read_json(ANOMALY_STATE_FILE, default={})
    reports = {}
    for source_name, source_state in state.items():
        history = source_state.get("history", [])
        latest = history[-1] if history else {}
        avg_7d = _trailing_average(history, days=7)
        reports[source_name] = {
            "last_record_count": latest.get("record_count"),
            "trailing_7d_avg": round(avg_7d, 1) if avg_7d is not None else None,
            "last_fingerprint": source_state.get("last_fingerprint"),
            "history_entries": len(history),
        }
    return reports

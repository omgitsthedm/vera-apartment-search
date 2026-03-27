"""Action recommendation engine for VERA sources and runs.

Given source health, reliability scores, and trend data,
produces short, actionable recommendations per source
and at the run level.
"""
from __future__ import annotations

from typing import Any


# -- Source-level recommendations ------------------------------------------

def _check_parser_confidence(source: dict[str, Any], threshold: float) -> str | None:
    conf = source.get("confidence")
    if conf is not None and conf < threshold:
        return f"Parser confidence low ({conf:.0%}). Review selector strategy for {source.get('extraction_strategy', 'unknown')} extraction."
    return None


def _check_record_drop(source: dict[str, Any], threshold_pct: float) -> str | None:
    reason = source.get("anomaly_reason")
    if source.get("anomaly_flag") and reason and "down" in reason:
        return f"Record count anomaly: {reason}. Check for layout change or anti-bot block."
    return None


def _check_freshness(source: dict[str, Any]) -> str | None:
    reliability = source.get("reliability_score", 100)
    cadence = source.get("cadence", "daily")
    # Freshness issues show up as low reliability + we can check the breakdown
    breakdown = source.get("reliability_breakdown", {})
    freshness_entry = breakdown.get("freshness")
    freshness_score = freshness_entry.get("raw") if isinstance(freshness_entry, dict) else freshness_entry
    if freshness_score is not None and freshness_score < 0.4:
        return f"Source stale for its {cadence} cadence. Agent may not be running or site may be blocking."
    return None


def _check_fallback_extraction(source: dict[str, Any]) -> str | None:
    strategy = source.get("extraction_strategy", "")
    if "fallback" in str(strategy).lower():
        return "Using fallback extraction path. Primary parser may need updating."
    return None


def _check_trend_decline(source: dict[str, Any]) -> str | None:
    trend = source.get("trend", [])
    if len(trend) < 3:
        return None
    recent = trend[-3:]
    records = [t.get("records", 0) for t in recent]
    if all(records[i] < records[i - 1] for i in range(1, len(records))) and records[0] > 0:
        decline_pct = round((1 - records[-1] / records[0]) * 100)
        if decline_pct >= 30:
            return f"Records declining over last 3 runs (down {decline_pct}%). Source may be drifting."
    return None


def _check_repeated_failures(source: dict[str, Any]) -> str | None:
    trend = source.get("trend", [])
    if len(trend) < 2:
        return None
    recent = trend[-3:]
    failures = sum(1 for t in recent if t.get("status") not in ("ok", "healthy", "success"))
    if failures >= 2:
        return f"Failed {failures} of last {len(recent)} runs. May need manual investigation."
    return None


def recommend_source_actions(
    source: dict[str, Any],
    confidence_threshold: float = 0.6,
    drop_threshold_pct: float = 50,
) -> list[str]:
    """Generate action recommendations for a single source.

    Returns a list of short, actionable strings (max ~3 per source).
    """
    checks = [
        _check_parser_confidence(source, confidence_threshold),
        _check_record_drop(source, drop_threshold_pct),
        _check_freshness(source),
        _check_fallback_extraction(source),
        _check_trend_decline(source),
        _check_repeated_failures(source),
    ]
    return [c for c in checks if c][:3]  # Cap at 3 per source


# -- Run-level recommendations ---------------------------------------------

def recommend_run_actions(
    source_health: dict[str, Any],
    stages: dict[str, dict[str, Any]],
    run: dict[str, Any],
) -> list[dict[str, str]]:
    """Generate run-level recommendations.

    Returns list of {"severity": "warn"|"error"|"info", "text": "..."}.
    """
    recommendations = []
    sources = source_health.get("sources", [])

    # Sources needing parser review
    parser_issues = [s["name"] for s in sources if s.get("confidence") is not None and s["confidence"] < 0.6]
    if parser_issues:
        recommendations.append({
            "severity": "warn",
            "text": f"{len(parser_issues)} source{'s' if len(parser_issues) > 1 else ''} need parser review: {', '.join(parser_issues)}",
        })

    # Stale sources
    def _freshness_raw(s: dict) -> float:
        entry = s.get("reliability_breakdown", {}).get("freshness", 1)
        return entry.get("raw") if isinstance(entry, dict) else (entry if isinstance(entry, (int, float)) else 1.0)
    stale_sources = [s["name"] for s in sources if _freshness_raw(s) < 0.4]
    if stale_sources:
        recommendations.append({
            "severity": "warn",
            "text": f"{len(stale_sources)} source{'s' if len(stale_sources) > 1 else ''} likely stale: {', '.join(stale_sources)}",
        })

    # Publish blocked
    publish_stage = stages.get("publish", {})
    if publish_stage.get("status") == "blocked":
        reason = publish_stage.get("blocked_reason", "unknown prerequisite failed")
        recommendations.append({
            "severity": "error",
            "text": f"Publish blocked: {reason}",
        })

    # Class-level health
    class_health = {}
    for s in sources:
        cls = s.get("source_class", "fallback")
        bucket = class_health.setdefault(cls, {"healthy": 0, "total": 0})
        bucket["total"] += 1
        if s.get("status") == "healthy":
            bucket["healthy"] += 1

    for cls, counts in class_health.items():
        if counts["total"] > 0 and counts["healthy"] == 0:
            recommendations.append({
                "severity": "error",
                "text": f"All {cls} sources are degraded or broken.",
            })
        elif counts["total"] > 1 and counts["healthy"] < counts["total"] / 2:
            recommendations.append({
                "severity": "warn",
                "text": f"{cls.capitalize()} inventory degraded ({counts['healthy']}/{counts['total']} healthy).",
            })

    # Low overall reliability
    scores = [s.get("reliability_score", 0) for s in sources if s.get("reliability_score") is not None]
    if scores:
        avg = sum(scores) / len(scores)
        if avg < 50:
            recommendations.append({
                "severity": "error",
                "text": f"Average source reliability is {avg:.0f}/100. System health is poor.",
            })
        elif avg < 70:
            recommendations.append({
                "severity": "warn",
                "text": f"Average source reliability is {avg:.0f}/100. Some sources need attention.",
            })

    # Discover failed
    discover_stage = stages.get("discover", {})
    if discover_stage.get("status") in ("failed", "error"):
        recommendations.append({
            "severity": "error",
            "text": "Discovery stage failed. No new listings were found this run.",
        })

    return recommendations[:6]  # Cap at 6


# -- Reliability breakdown -------------------------------------------------

def compute_reliability_breakdown(
    confidence: float | None,
    success_rate: float | None,
    freshness_score: float,
    anomaly_flag: bool,
    stability_score: float,
) -> dict[str, dict[str, Any]]:
    """Return per-component breakdown with raw scores and weighted contributions."""
    conf = min(max(confidence or 0.5, 0.0), 1.0)
    rate = min(max(success_rate or 0.5, 0.0), 1.0)
    anomaly = 0.0 if anomaly_flag else 1.0

    return {
        "parser_confidence": {"raw": round(conf, 2), "weight": 30, "points": round(conf * 30)},
        "success_rate": {"raw": round(rate, 2), "weight": 25, "points": round(rate * 25)},
        "freshness": {"raw": round(freshness_score, 2), "weight": 20, "points": round(freshness_score * 20)},
        "anomaly_status": {"raw": round(anomaly, 2), "weight": 15, "points": round(anomaly * 15)},
        "record_stability": {"raw": round(stability_score, 2), "weight": 10, "points": round(stability_score * 10)},
    }

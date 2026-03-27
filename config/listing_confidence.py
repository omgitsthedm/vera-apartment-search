"""Listing-level confidence scoring for VERA.

Measures how much you should trust that a listing is real, accurately
described, and worth acting on — independent of deal quality.

Score: 0–100 composite from 7 weighted components.
Band: high (≥75), medium (50–74), low (25–49), needs_review (<25).
"""
from __future__ import annotations

from typing import Any

# Component weights (must sum to 100)
WEIGHTS = {
    "source_reliability": 25,
    "source_redundancy": 15,
    "address_quality": 15,
    "verification_match": 20,
    "freshness": 10,
    "field_completeness": 10,
    "consistency_checks": 5,
}

CONFIDENCE_MAP = {"high": 1.0, "medium": 0.6, "low": 0.3, "none": 0.0}


def _conf_value(level: str | None) -> float:
    return CONFIDENCE_MAP.get(str(level or "").lower(), 0.3)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _source_reliability_score(listing: dict[str, Any], source_health: dict[str, Any]) -> float:
    """Score based on the reliability of the source(s) this listing came from."""
    sources_by_name = {s.get("name"): s for s in source_health.get("sources", [])}

    # Check primary source
    primary_source = listing.get("source_name", "")
    primary = sources_by_name.get(primary_source, {})
    primary_reliability = primary.get("reliability_score", 50)

    # Check all sources in cluster
    cluster_sources = listing.get("source_names") or [primary_source]
    if isinstance(cluster_sources, str):
        cluster_sources = [cluster_sources]

    reliabilities = []
    for sname in cluster_sources:
        s = sources_by_name.get(sname, {})
        reliabilities.append(s.get("reliability_score", 50))

    # Use best source reliability if seen on multiple sources
    best = max(reliabilities) if reliabilities else primary_reliability
    return _clamp(best / 100)


def _source_redundancy_score(listing: dict[str, Any]) -> float:
    """Score based on how many independent sources confirm this listing."""
    dup_count = listing.get("duplicate_count") or 1
    cluster_sources = listing.get("source_names") or []
    if isinstance(cluster_sources, str):
        cluster_sources = [cluster_sources]
    source_count = max(len(set(cluster_sources)), 1)

    if source_count >= 3:
        return 1.0
    if source_count == 2:
        return 0.8
    # Single source — check if it's a high-trust source type
    if listing.get("official_program_source"):
        return 0.7
    if listing.get("curated_source"):
        return 0.6
    return 0.3


def _address_quality_score(listing: dict[str, Any]) -> float:
    """Score based on address normalization and geocoding confidence."""
    addr_conf = _conf_value(listing.get("address_confidence"))
    neighborhood_conf = _conf_value(listing.get("neighborhood_confidence"))
    geo_conf = _conf_value(listing.get("geosearch_match_confidence"))

    # Boost for verified neighborhood
    map_verified = listing.get("neighborhood_verified_by_map")
    map_bonus = 0.15 if map_verified else 0.0

    # Penalty for geography flags
    geo_flags = listing.get("geography_flags") or []
    flag_penalty = min(len(geo_flags) * 0.2, 0.5)

    raw = (addr_conf * 0.4 + neighborhood_conf * 0.3 + geo_conf * 0.3 + map_bonus - flag_penalty)
    return _clamp(raw)


def _verification_match_score(listing: dict[str, Any]) -> float:
    """Score based on building verification against public records."""
    verification = listing.get("verification_status", "")
    record_link = listing.get("record_link_confidence", "")
    synthetic = listing.get("synthetic_risk_scores", False)

    # Best case: matched public records with strong link
    if verification == "matched_public_records":
        link_scores = {
            "exact_address_match": 1.0,
            "strong_partial_address_match": 0.85,
            "building_level_match": 0.75,
            "owner_name_assisted_match": 0.65,
        }
        return link_scores.get(record_link, 0.6)

    if verification == "partial_address_only":
        return 0.35

    # No match + synthetic scores = very low confidence
    if synthetic:
        return 0.1

    return 0.2


def _freshness_score(listing: dict[str, Any]) -> float:
    """Score based on how recently the listing was seen."""
    from datetime import datetime, timezone

    last_seen = listing.get("last_seen_at") or listing.get("scraped_at")
    if not last_seen:
        return 0.3

    try:
        ts = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600

        if age_hours <= 6:
            return 1.0
        if age_hours <= 24:
            return 0.85
        if age_hours <= 72:
            return 0.6
        if age_hours <= 168:
            return 0.4
        return 0.2
    except (ValueError, TypeError):
        return 0.3


def _field_completeness_score(listing: dict[str, Any]) -> float:
    """Score based on how many important fields are populated."""
    fields = [
        ("rent", lambda v: isinstance(v, (int, float)) and v > 0),
        ("beds", lambda v: v is not None),
        ("baths", lambda v: v is not None),
        ("address_normalized", lambda v: bool(v)),
        ("neighborhood", lambda v: bool(v)),
        ("contact_phone", lambda v: bool(v)),
        ("contact_email", lambda v: bool(v)),
        ("full_description", lambda v: bool(v) and len(str(v)) > 50),
        ("image_count", lambda v: isinstance(v, (int, float)) and v > 0),
        ("fee_status", lambda v: v and v != "unknown"),
    ]

    filled = sum(1 for field, check in fields if check(listing.get(field)))
    return filled / len(fields)


def _consistency_score(listing: dict[str, Any]) -> float:
    """Score based on internal consistency of listing data."""
    penalties = 0

    # Rent vs beds consistency
    rent = listing.get("rent")
    beds = listing.get("beds")
    if isinstance(rent, (int, float)) and isinstance(beds, (int, float)):
        if beds == 0 and rent > 4000:
            penalties += 0.2  # Expensive studio is unusual but possible
        if beds >= 2 and rent < 1200:
            penalties += 0.3  # Multi-bedroom under $1200 in NYC is suspicious

    # Geography consistency — flags already computed
    geo_flags = listing.get("geography_flags") or []
    if len(geo_flags) >= 2:
        penalties += 0.4

    # Listing type consistency
    listing_type = listing.get("listing_type", "")
    auth_conf = _conf_value(listing.get("listing_authenticity_confidence"))
    if listing_type in ("probable_scam", "off_market_lead_gen"):
        penalties += 0.5
    elif listing_type in ("broker_service_solicitation", "apartment_finder_locator_ad"):
        penalties += 0.4
    elif auth_conf < 0.4:
        penalties += 0.2

    return _clamp(1.0 - penalties)


def compute_listing_confidence(
    listing: dict[str, Any],
    source_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute listing confidence score and breakdown.

    Returns dict with:
      - listing_confidence_score: int (0-100)
      - listing_confidence_band: str
      - listing_confidence_breakdown: dict
    """
    source_health = source_health or {}

    components = {
        "source_reliability": _source_reliability_score(listing, source_health),
        "source_redundancy": _source_redundancy_score(listing),
        "address_quality": _address_quality_score(listing),
        "verification_match": _verification_match_score(listing),
        "freshness": _freshness_score(listing),
        "field_completeness": _field_completeness_score(listing),
        "consistency_checks": _consistency_score(listing),
    }

    breakdown = {}
    total = 0
    for key, raw in components.items():
        weight = WEIGHTS[key]
        points = round(raw * weight)
        total += points
        breakdown[key] = {"raw": round(raw, 2), "weight": weight, "points": points}

    score = min(total, 100)

    if score >= 75:
        band = "high"
    elif score >= 50:
        band = "medium"
    elif score >= 25:
        band = "low"
    else:
        band = "needs_review"

    return {
        "listing_confidence_score": score,
        "listing_confidence_band": band,
        "listing_confidence_breakdown": breakdown,
    }


def summarize_confidence_distribution(listings: list[dict[str, Any]]) -> dict[str, int]:
    """Count listings per confidence band."""
    counts = {"high": 0, "medium": 0, "low": 0, "needs_review": 0}
    for listing in listings:
        band = listing.get("listing_confidence_band", "needs_review")
        if band in counts:
            counts[band] += 1
    return counts

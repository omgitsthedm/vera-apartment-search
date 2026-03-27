"""Human-readable confidence explanations for VERA listings.

Generates short plain-English reasons that explain why a listing should
(or shouldn't) be trusted — independent of deal quality.  These surface
in the dashboard alongside the listing confidence badge.

Each generator inspects one facet of the listing and returns a sentence
or None.  `generate_listing_explanations()` collects them into an ordered
list: strengths first, then caveats.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# ── Strength generators ─────────────────────────────────────────────


def _source_redundancy(listing: dict[str, Any]) -> str | None:
    cluster_sources = listing.get("source_names") or []
    if isinstance(cluster_sources, str):
        cluster_sources = [cluster_sources]
    unique = list(set(cluster_sources))
    n = len(unique)
    if n >= 3:
        return f"Confirmed on {n} independent sources ({', '.join(sorted(unique)[:3])})"
    if n == 2:
        return f"Seen on 2 sources with matching rent ({', '.join(sorted(unique))})"
    if listing.get("official_program_source"):
        return "Listed through an official housing program"
    if listing.get("curated_source"):
        return "From a curated editorial source"
    return None


def _address_strength(listing: dict[str, Any]) -> str | None:
    addr_conf = str(listing.get("address_confidence") or "").lower()
    geo_conf = str(listing.get("geosearch_match_confidence") or "").lower()
    verified = listing.get("neighborhood_verified_by_map")

    if addr_conf == "high" and geo_conf == "high":
        return "Address normalized with strong geocode confidence"
    if addr_conf == "high":
        return "Address parsed and normalized with high confidence"
    if verified:
        return "Neighborhood verified against geographic boundaries"
    return None


def _verification_strength(listing: dict[str, Any]) -> str | None:
    status = listing.get("verification_status", "")
    link = listing.get("record_link_confidence", "")

    if status == "matched_public_records":
        if link == "exact_address_match":
            return "Building matched to public records with exact address"
        if link in ("strong_partial_address_match", "building_level_match"):
            return "Building registration appears active in public records"
        return "Linked to public building records"
    if status == "partial_address_only":
        return "Partial address match found in public records"
    return None


def _freshness_strength(listing: dict[str, Any]) -> str | None:
    last_seen = listing.get("last_seen_at") or listing.get("scraped_at")
    if not last_seen:
        return None
    try:
        ts = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        if age_hours <= 6:
            return "Fresh listing discovered within the last few hours"
        if age_hours <= 24:
            return "Seen within the last 24 hours"
    except (ValueError, TypeError):
        pass
    return None


def _rent_context(listing: dict[str, Any]) -> str | None:
    rent = listing.get("rent")
    beds = listing.get("beds")
    baseline = listing.get("rent_baseline") or listing.get("neighborhood_rent_baseline")

    if not isinstance(rent, (int, float)) or not isinstance(baseline, (int, float)):
        return None
    if baseline <= 0:
        return None

    pct_below = (baseline - rent) / baseline * 100
    if pct_below >= 10:
        return f"Rent is {pct_below:.0f}% below local baseline for this unit type"
    return None


def _completeness_strength(listing: dict[str, Any]) -> str | None:
    has_contact = bool(listing.get("contact_phone") or listing.get("contact_email"))
    has_desc = bool(listing.get("full_description") and len(str(listing.get("full_description", ""))) > 50)
    has_images = isinstance(listing.get("image_count"), (int, float)) and listing["image_count"] > 0
    has_fee = bool(listing.get("fee_status") and listing["fee_status"] != "unknown")

    positives = sum([has_contact, has_desc, has_images, has_fee])
    if positives >= 3:
        return "Listing includes contact info, description, and media"
    return None


# ── Caveat generators ───────────────────────────────────────────────


def _single_source_caveat(listing: dict[str, Any]) -> str | None:
    cluster_sources = listing.get("source_names") or []
    if isinstance(cluster_sources, str):
        cluster_sources = [cluster_sources]
    if len(set(cluster_sources)) <= 1 and not listing.get("official_program_source"):
        return "Only seen on a single source — verify independently"
    return None


def _stale_caveat(listing: dict[str, Any]) -> str | None:
    last_seen = listing.get("last_seen_at") or listing.get("scraped_at")
    if not last_seen:
        return "No timestamp found — freshness unknown"
    try:
        ts = datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        if age_hours > 168:
            return "Last seen over a week ago — may no longer be available"
        if age_hours > 72:
            return "Not seen in over 3 days — confirm availability"
    except (ValueError, TypeError):
        return "Timestamp could not be parsed — freshness unknown"
    return None


def _geo_flag_caveat(listing: dict[str, Any]) -> str | None:
    flags = listing.get("geography_flags") or []
    if len(flags) >= 2:
        return f"Multiple geography flags raised ({len(flags)})"
    if len(flags) == 1:
        return f"Geography flag: {flags[0]}"
    return None


def _authenticity_caveat(listing: dict[str, Any]) -> str | None:
    listing_type = listing.get("listing_type", "")
    if listing_type in ("probable_scam", "off_market_lead_gen"):
        return "Listing type flagged as potentially fraudulent"
    if listing_type in ("broker_service_solicitation", "apartment_finder_locator_ad"):
        return "This appears to be a broker solicitation, not a direct listing"
    return None


def _synthetic_caveat(listing: dict[str, Any]) -> str | None:
    if listing.get("synthetic_risk_scores"):
        return "Risk scores are estimated (not from verified data)"
    return None


def _no_verification_caveat(listing: dict[str, Any]) -> str | None:
    status = listing.get("verification_status", "")
    if not status or status == "unverified":
        return "Building not yet verified against public records"
    return None


# ── Public API ──────────────────────────────────────────────────────

_STRENGTH_GENERATORS = [
    _source_redundancy,
    _address_strength,
    _verification_strength,
    _freshness_strength,
    # _rent_context excluded: rent vs baseline is a deal signal, not trust
    _completeness_strength,
]

_CAVEAT_GENERATORS = [
    _single_source_caveat,
    _stale_caveat,
    _geo_flag_caveat,
    _authenticity_caveat,
    _synthetic_caveat,
    _no_verification_caveat,
]


def generate_listing_explanations(
    listing: dict[str, Any],
    *,
    max_strengths: int = 4,
    max_caveats: int = 3,
) -> dict[str, list[str]]:
    """Generate human-readable confidence explanations.

    Returns:
        {
            "strengths": ["Seen on 2 sources...", "Address normalized..."],
            "caveats": ["Only seen on a single source...", ...]
        }
    """
    strengths: list[str] = []
    for gen in _STRENGTH_GENERATORS:
        if len(strengths) >= max_strengths:
            break
        result = gen(listing)
        if result:
            strengths.append(result)

    caveats: list[str] = []
    for gen in _CAVEAT_GENERATORS:
        if len(caveats) >= max_caveats:
            break
        result = gen(listing)
        if result:
            caveats.append(result)

    return {"strengths": strengths, "caveats": caveats}


def format_why_this_listing(explanations: dict[str, list[str]]) -> str:
    """Format explanations into a single narrative string for the dashboard."""
    parts = []
    if explanations["strengths"]:
        parts.append(". ".join(explanations["strengths"]) + ".")
    if explanations["caveats"]:
        parts.append("Note: " + "; ".join(explanations["caveats"]) + ".")
    return " ".join(parts) if parts else "Insufficient data to assess listing confidence."

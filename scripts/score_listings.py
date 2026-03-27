#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.paths import (VERA_ROOT as ROOT, CONFIG_DIR as CONFIG_ROOT, ENRICHED_DIR as ENRICHED_ROOT,
    SCORED_DIR as SCORED_ROOT, REPORT_DIR as REPORT_ROOT, EXPORT_DIR as EXPORT_ROOT,
    LOG_DIR as LOG_ROOT, LEGACY_STATE_DIR as STATE_ROOT, DEDUPED_DIR as DEDUPED_ROOT)
from config.stage_tracker import write_stage_start, write_stage_end
from workflow_support import (
    SEARCH_MODE_BRIDGE,
    SEARCH_MODE_PERMANENT,
    ensure_dir,
    iso_age_days,
    latest_file,
    read_json,
    render_markdown_table,
    state_path_or_latest,
    top_keywords,
    utc_now_iso,
    utc_stamp,
    write_csv,
    write_json,
    write_text,
)

RUN_STAMP = utc_stamp()


def load_enriched_rows() -> list[dict[str, Any]]:
    state = read_json(STATE_ROOT / "current_enriched.json", default={})
    path = state_path_or_latest(state.get("enriched_path"), ENRICHED_ROOT, "enriched_listings_*.json")
    if not path:
        raise FileNotFoundError("No enriched dataset found")
    return read_json(path, default=[])


def load_duplicate_clusters() -> list[dict[str, Any]]:
    state = read_json(STATE_ROOT / "current_deduped.json", default={})
    path = state_path_or_latest(state.get("cluster_csv_path"), DEDUPED_ROOT, "duplicate_clusters_*.csv")
    if not path:
        return []
    from workflow_support import read_csv_rows

    return read_csv_rows(path)


def neighborhood_score(listing: dict[str, Any], preferences: dict[str, Any]) -> float:
    return 12.0 if listing.get("neighborhood") in preferences.get("neighborhoods", []) else 0.0


def price_score(listing: dict[str, Any], preferences: dict[str, Any]) -> float:
    rent = listing.get("rent")
    max_rent = preferences.get("max_rent")
    if rent is None or max_rent is None:
        return 0.0
    if rent <= max_rent - 200:
        return 10.0
    if rent <= max_rent - 100:
        return 9.0
    if rent <= max_rent:
        return 7.0
    if rent <= max_rent + 150:
        return 2.0
    return 0.0


def unit_score(listing: dict[str, Any]) -> float:
    beds = listing.get("beds")
    return 5.0 if beds in (0, 0.0, 1, 1.0) else 0.0


def independent_landlord_score(listing: dict[str, Any]) -> float:
    return round((float(listing.get("likely_independent_landlord_score") or 0.0) / 100.0) * 20.0, 1)


def safety_score(listing: dict[str, Any]) -> float:
    hpd_component = max(0.0, 8.0 - (float(listing.get("hpd_risk_score") or 50.0) / 12.5))
    dob_component = max(0.0, 4.0 - (float(listing.get("dob_risk_score") or 45.0) / 25.0))
    ownership_component = 4.0 if listing.get("owner_name") and listing.get("verification_status") == "matched_public_records" else 2.0 if listing.get("owner_name") else 0.0
    watch_component = 4.0 if not listing.get("bad_actor_hits") else 0.0
    return round(hpd_component + dob_component + ownership_component + watch_component, 1)


def stabilization_score(listing: dict[str, Any]) -> float:
    signal = listing.get("rent_stabilized_signal")
    if signal == "likely":
        return 10.0
    if signal == "possible":
        return 6.0
    if signal == "unclear":
        return 3.0
    return 0.0


def authenticity_penalty(listing: dict[str, Any]) -> float:
    """Penalty for non-apartment listing types. Returns a negative value."""
    listing_type = listing.get("listing_type", "actual_apartment_listing")
    if listing_type == "broker_service_solicitation":
        return -40.0
    if listing_type == "apartment_finder_locator_ad":
        return -40.0
    if listing_type == "off_market_lead_gen":
        return -30.0
    if listing_type == "probable_scam":
        return -35.0
    if listing_type == "bridge_housing":
        return -25.0
    if listing_type == "room_share":
        return -20.0
    if listing_type == "sublet":
        return -10.0
    if listing_type == "unclear":
        return -15.0
    return 0.0


def geography_penalty(listing: dict[str, Any]) -> float:
    """Penalty for geography mismatches. Returns a negative value.

    Only penalizes actual geographic mismatch flags (deal/fit signal).
    Neighborhood confidence level is a trust signal and lives in the
    listing confidence engine instead.
    """
    flags = listing.get("geography_flags") or []
    penalty = 0.0
    # Each geography flag is a mismatch
    penalty -= len(flags) * 8.0
    return penalty


def has_synthetic_risk_scores(listing: dict[str, Any]) -> bool:
    """Detect listings using default synthetic risk scores instead of real data.

    When there's no public-record match, hpd_risk_score defaults to 50.0 and
    dob_risk_score defaults to 45.0. These numbers are meaningless guesses that
    should not be trusted for shortlist decisions.
    """
    hpd = float(listing.get("hpd_risk_score") or 0)
    dob = float(listing.get("dob_risk_score") or 0)
    verification = listing.get("verification_status", "no_public_match")
    return (
        verification != "matched_public_records"
        and abs(hpd - 50.0) < 0.01
        and abs(dob - 45.0) < 0.01
    )


def quality_score(listing: dict[str, Any]) -> float:
    completeness = sum(
        listing.get(field) not in (None, "", [])
        for field in [
            "address_normalized",
            "neighborhood",
            "borough",
            "zip",
            "rent",
            "beds",
            "baths",
            "contact_name",
            "contact_phone",
            "contact_email",
        ]
    )
    completeness_component = min(5.0, completeness / 2.0)
    address_component = 3.0 if listing.get("verification_status") == "matched_public_records" else 1.5 if listing.get("address_normalized") else 0.0
    photos = float(listing.get("image_count") or 0)
    photo_component = 3.0 if photos >= 5 else 1.5 if photos >= 2 else 0.0
    contact_component = 2.0 if listing.get("contact_phone") or listing.get("contact_email") else 0.0
    # NOTE: Multi-source bonus removed. Source redundancy is a trust signal
    # now handled by listing_confidence.py (source_redundancy component).
    return round(completeness_component + address_component + photo_component + contact_component, 1)


def recommendation_for(listing: dict[str, Any], overall: float, synthetic_risk: bool = False) -> str:
    """Derive a recommendation label from deal score + trust evidence.

    Pipeline sequencing note (V1):
        score_listings.py runs *before* build_snapshot.py, so the canonical
        listing_confidence_band is not yet available during the first scoring
        pass.  When the band IS present (e.g. re-scoring enriched records),
        we use it directly.  Otherwise we fall back to raw per-field trust
        signals that are available at scoring time.

        Trust checks here gate the *recommendation label* only — they do NOT
        influence the numeric deal score (overall_score).

    TODO (post-Sprint 6): Ideal architecture computes fit → confidence →
        recommendation in strict sequence so recommendation_for() always
        has listing_confidence_band available.  Requires lifting confidence
        computation into score_listings.py or reordering the pipeline.
    """
    if not listing.get("qualification_passed"):
        return "skip"

    # --- Hard reject types (Part 2) ---
    listing_type = listing.get("listing_type", "actual_apartment_listing")
    if listing_type in (
        "broker_service_solicitation",
        "apartment_finder_locator_ad",
        "off_market_lead_gen",
        "probable_scam",
    ):
        return "skip"

    # Bridge housing never contaminates the permanent shortlist
    if listing_type == "bridge_housing":
        return "skip"

    if listing.get("bad_actor_hits") and listing.get("likely_landlord_type") == "management":
        return "skip"
    if listing.get("bad_actor_hits") and float(listing.get("hpd_risk_score") or 0) >= 40:
        return "skip"
    # Skip listings with very low landlord independence score (heavy broker/management)
    landlord_score = float(listing.get("likely_independent_landlord_score") or 50)
    if landlord_score <= 15:
        return "skip"
    # Skip listings with no address and no public record match
    if not listing.get("address_normalized") and listing.get("verification_status") != "matched_public_records":
        return "skip"

    # --- Manual review zone ---
    # Edge case listing types
    if listing_type in ("room_share", "sublet", "unclear"):
        return "manual review"

    # Synthetic risk scores: safety numbers are fabricated, not real
    if synthetic_risk:
        return "manual review"

    # Geography mismatches should prevent "pursue" — demote to manual review
    geography_flags = listing.get("geography_flags") or []
    if len(geography_flags) >= 2:
        return "manual review"

    # --- Confidence gates ---
    # The full listing confidence engine (listing_confidence.py) runs in
    # build_snapshot.py *after* scoring, so listing_confidence_band is not
    # yet available here.  These gates use the raw per-field signals as a
    # lightweight trust proxy.  They do NOT contribute to the deal score —
    # they only gate which recommendation label a listing receives.
    #
    # If listing_confidence_band is already present (e.g. re-scoring an
    # enriched record), prefer it over the raw fields.
    confidence_band = listing.get("listing_confidence_band")
    auth_conf = listing.get("listing_authenticity_confidence", "low")

    # NOTE: Thresholds recalibrated after Sprint 6 removed trust-inflating
    # signals from the deal score (~10-12 pts of freshness, verification,
    # multi-source bonus).  Raw deal scores now run lower than before.
    if confidence_band:
        # Full confidence engine has run — use the unified band
        if overall >= 70 and confidence_band == "high" and auth_conf == "high":
            return "pursue"
        if overall >= 70 and confidence_band in ("high", "medium") and auth_conf == "high":
            return "pursue cautiously"
        if overall >= 55 and confidence_band in ("high", "medium") and auth_conf != "low":
            return "pursue cautiously"
    else:
        # Fallback: raw field checks (first-pass scoring before snapshot)
        neighborhood_conf = listing.get("neighborhood_confidence", "low")
        verification = listing.get("verification_status", "no_public_match")
        address_conf = listing.get("address_confidence", "none")

        if (
            overall >= 70
            and auth_conf == "high"
            and neighborhood_conf != "low"
            and verification == "matched_public_records"
        ):
            return "pursue"
        if overall >= 70 and auth_conf == "high" and neighborhood_conf != "low":
            return "pursue cautiously"
        if (
            overall >= 55
            and auth_conf != "low"
            and address_conf not in ("low", "none")
            and neighborhood_conf != "low"
        ):
            return "pursue cautiously"

    # Listings that score decently but have weak trust go to manual review
    if overall >= 45:
        return "manual review"

    return "skip"


def summary_reason(listing: dict[str, Any], recommendation: str) -> str:
    reasons: list[str] = []
    search_mode = listing.get("search_mode", SEARCH_MODE_PERMANENT)
    source_tier = listing.get("source_tier", "primary")

    if search_mode == SEARCH_MODE_BRIDGE:
        reasons.append("MODE-B:bridge")
    if source_tier not in ("primary", ""):
        reasons.append(f"source={source_tier}")

    listing_type = listing.get("listing_type", "actual_apartment_listing")
    if listing_type != "actual_apartment_listing":
        reasons.append(f"type={listing_type}")
    if listing.get("lease_takeover"):
        reasons.append("lease-takeover")
    if listing.get("official_program_source"):
        reasons.append("official-program")
    if listing.get("neighborhood"):
        neighborhood_conf = listing.get("neighborhood_confidence", "unknown")
        reasons.append(f"neighborhood={listing['neighborhood']} ({neighborhood_conf})")
    if listing.get("rent") is not None:
        reasons.append(f"rent=${int(listing['rent'])}")
    reasons.append(f"landlord={listing.get('likely_landlord_type', 'unclear')}")
    fee_status = listing.get("fee_status", "unknown")
    if fee_status != "unknown":
        reasons.append(f"fee={fee_status}")
    reasons.append(f"stabilization={listing.get('rent_stabilized_signal', 'unclear')}")

    # Verification and confidence summary
    verification = listing.get("verification_status", "no_public_match")
    address_conf = listing.get("address_confidence", "none")
    auth_conf = listing.get("listing_authenticity_confidence", "low")
    if verification != "matched_public_records":
        reasons.append(f"verification={verification}")
    if address_conf in ("low", "none"):
        reasons.append(f"address_conf={address_conf}")
    if auth_conf != "high":
        reasons.append(f"auth_conf={auth_conf}")

    record_link = listing.get("record_link_confidence")
    if record_link and record_link != "exact_address_match":
        reasons.append(f"record-link={record_link}")

    if listing.get("geography_flags"):
        reasons.append("geography issues: " + "; ".join(listing["geography_flags"][:2]))
    if listing.get("bad_actor_hits"):
        non_geo_flags = [f for f in listing["bad_actor_hits"] if not f.startswith("neighborhood ") and not f.startswith("ZIP ") and not f.startswith("address has no")]
        if non_geo_flags:
            reasons.append("red flags present")
    if recommendation == "skip" and listing.get("hard_filter_failures"):
        reasons.append(", ".join(listing["hard_filter_failures"][:2]))
    return "; ".join(reasons)


def _survival_reason(listing: dict[str, Any], overall: float, recommendation: str) -> str:
    """Explain why a listing survived to the shortlist — for dashboard transparency."""
    parts: list[str] = []
    if recommendation == "pursue":
        parts.append(f"Score {overall} ≥ 80 with high auth confidence, good neighborhood, and verified public records")
    elif recommendation == "pursue cautiously":
        if overall >= 80:
            parts.append(f"Score {overall} ≥ 80 with high auth confidence but missing full verification")
        else:
            gap = round(68.0 - overall, 1) if overall < 68 else 0
            margin = round(overall - 68.0, 1) if overall >= 68 else 0
            if margin <= 2.0:
                parts.append(f"Score {overall} barely clears 68 threshold (margin: +{margin})")
            else:
                parts.append(f"Score {overall} ≥ 68 with decent auth/address/neighborhood confidence")

    verification = listing.get("verification_status", "no_public_match")
    if verification == "matched_public_records":
        parts.append("public-record verified")
    else:
        parts.append(f"unverified ({verification})")

    # Component-level detail for near-threshold
    landlord_type = listing.get("likely_landlord_type", "unclear")
    fee_status = listing.get("fee_status", "unknown")
    stabilization = listing.get("rent_stabilized_signal", "unclear")
    detail_parts: list[str] = []
    if landlord_type == "independent":
        detail_parts.append("independent landlord")
    elif landlord_type == "unclear":
        detail_parts.append("landlord type unclear")
    if fee_status == "no fee":
        detail_parts.append("no-fee")
    elif fee_status == "fee":
        detail_parts.append("has broker fee")
    if stabilization in ("likely", "possible"):
        detail_parts.append(f"stabilization={stabilization}")
    if detail_parts:
        parts.append(", ".join(detail_parts))

    source_tier = listing.get("source_tier", "primary")
    if source_tier != "primary":
        parts.append(f"from {source_tier} source")

    return "; ".join(parts)


def _demotion_reason(listing: dict[str, Any], overall: float, recommendation: str, synthetic_risk: bool) -> str:
    """Explain why a listing was demoted or skipped — for dashboard transparency."""
    parts: list[str] = []

    listing_type = listing.get("listing_type", "actual_apartment_listing")
    if listing_type in ("broker_service_solicitation", "apartment_finder_locator_ad", "off_market_lead_gen", "probable_scam"):
        parts.append(f"Hard reject: {listing_type}")
        return "; ".join(parts)
    if listing_type == "bridge_housing":
        parts.append("Bridge housing excluded from permanent shortlist")
        return "; ".join(parts)

    if not listing.get("qualification_passed"):
        failures = listing.get("hard_filter_failures") or []
        parts.append(f"Failed hard filters: {', '.join(failures[:3])}")
        return "; ".join(parts)

    if synthetic_risk:
        parts.append("Synthetic risk scores (no real HPD/DOB data) — routed to manual review")

    if recommendation == "manual review":
        if listing_type in ("room_share", "sublet", "unclear"):
            parts.append(f"Edge-case listing type: {listing_type}")
        if overall < 68:
            gap = round(68.0 - overall, 1)
            parts.append(f"Score {overall} is {gap} points below pursue-cautiously threshold of 68")
            # Identify which components are dragging it down
            weak_signals: list[str] = []
            if listing.get("likely_landlord_type") == "unclear":
                weak_signals.append("landlord type unclear")
            if listing.get("fee_status") == "unknown":
                weak_signals.append("fee status unknown")
            if listing.get("rent_stabilized_signal") in ("not indicated", "unclear"):
                weak_signals.append("no stabilization signal")
            if weak_signals:
                parts.append(f"Weak signals: {', '.join(weak_signals)}")
        auth_conf = listing.get("listing_authenticity_confidence", "low")
        address_conf = listing.get("address_confidence", "none")
        if auth_conf == "low":
            parts.append("Low authenticity confidence")
        if address_conf in ("low", "none"):
            parts.append(f"Weak address (confidence={address_conf})")

        # For near-threshold manual reviews, explain what would help
        if 60 <= overall < 68:
            improvement_hints: list[str] = []
            if listing.get("likely_landlord_type") != "independent":
                improvement_hints.append("stronger landlord-independence signals")
            if listing.get("rent_stabilized_signal") not in ("likely", "possible"):
                improvement_hints.append("rent stabilization evidence")
            if listing.get("fee_status") == "unknown":
                improvement_hints.append("confirmed no-fee status")
            if improvement_hints:
                parts.append(f"Could improve with: {', '.join(improvement_hints[:2])}")

    elif recommendation == "skip":
        if overall < 60:
            parts.append(f"Score {overall} too low")
        landlord_score = float(listing.get("likely_independent_landlord_score") or 50)
        if landlord_score <= 15:
            parts.append(f"Very low landlord independence score ({landlord_score})")
        if not listing.get("address_normalized"):
            parts.append("No address provided")

    return "; ".join(parts) if parts else f"Scored {overall}, did not meet shortlist criteria"


def reviewed_out_reason_code(listing: dict[str, Any], overall: float, recommendation: str, synthetic_risk: bool) -> str:
    if not listing.get("qualification_passed"):
        failures = listing.get("hard_filter_failures") or []
        if any("rent" in failure for failure in failures):
            return "hard_filter_budget"
        if any("neighborhood" in failure for failure in failures):
            return "hard_filter_neighborhood"
        if any("studio/1BR" in failure or "unit type" in failure for failure in failures):
            return "hard_filter_unit_type"
        if any("room-share" in failure for failure in failures):
            return "hard_filter_room_share"
        if any("sublet" in failure for failure in failures):
            return "hard_filter_sublet"
        return "hard_filter_other"

    listing_type = listing.get("listing_type", "actual_apartment_listing")
    if listing_type == "broker_service_solicitation":
        return "broker_service_ad"
    if listing_type == "apartment_finder_locator_ad":
        return "locator_service_ad"
    if listing_type == "off_market_lead_gen":
        return "lead_gen_listing"
    if listing_type == "probable_scam":
        return "probable_scam"
    if listing_type == "bridge_housing":
        return "bridge_housing_only"
    if synthetic_risk:
        return "unverified_risk_data"
    if listing.get("geography_flags"):
        return "map_mismatch"
    if float(listing.get("likely_independent_landlord_score") or 50) <= 15:
        return "management_heavy"
    if listing.get("bad_actor_hits"):
        return "bad_actor_or_building_risk"
    if not listing.get("address_normalized"):
        return "missing_address"
    if recommendation == "manual review":
        return "needs_manual_review"
    if overall < 60:
        return "score_too_low"
    return "filtered_out_other"


def score_explanation_lines(listing: dict[str, Any], component_scores: dict[str, float], overall: float) -> list[str]:
    lines = [
        f"Overall score {overall} is the sum of search fit, landlord fit, building safety, stabilization upside, and listing quality.",
    ]
    component_labels = {
        "search_fit": "Search fit",
        "independent_landlord_fit": "Independent-landlord fit",
        "building_landlord_safety": "Building and landlord safety",
        "rent_stability_upside": "Rent-stability upside",
        "listing_quality": "Listing quality",
        "authenticity_adjustment": "Authenticity adjustment",
        "geography_adjustment": "Geography adjustment",
        "verification_adjustment": "Verification adjustment",
    }
    for key, label in component_labels.items():
        value = component_scores.get(key)
        if value is None:
            continue
        lines.append(f"{label}: {value}")
    if listing.get("official_rent_stabilized_list_hit"):
        lines.append("Official rent-stabilized reference hit adds credibility to the stabilization signal.")
    if listing.get("synthetic_risk_scores"):
        lines.append("Risk numbers are synthetic here because the building did not resolve cleanly to public records.")
    return lines


def _classify_promotion_tier(
    listing: dict[str, Any],
    overall: float,
    recommendation: str,
    synthetic_risk: bool,
) -> str:
    """Classify listings into promotion quality bands for dashboard clarity.

    Tiers:
        "verified_promising" — matched HPD, clean record, good landlord signals
        "verified_borderline" — matched HPD but weak on landlord/stabilization
        "verified_undesirable" — matched HPD but building has serious issues
        "unverified_strong" — good score but no public record verification
        "unverified_weak" — low score, no verification
        "shortlisted" — already on the shortlist (pursue/pursue cautiously)
        "rejected" — hard-rejected types
    """
    listing_type = listing.get("listing_type", "actual_apartment_listing")
    if listing_type != "actual_apartment_listing":
        return "rejected"
    if recommendation in ("pursue", "pursue cautiously"):
        return "shortlisted"
    if recommendation == "skip":
        return "rejected"

    verification = listing.get("verification_status", "no_public_match")
    is_verified = verification == "matched_public_records"

    if not is_verified:
        if overall >= 60:
            return "unverified_strong"
        return "unverified_weak"

    # Verified listings — separate by building quality and landlord fit
    hpd_risk = listing.get("hpd_risk_score")
    hpd_risk_val = float(hpd_risk) if hpd_risk is not None else 50.0
    landlord_type = listing.get("likely_landlord_type", "unclear")
    landlord_raw = listing.get("likely_independent_landlord_score")
    landlord_score = float(landlord_raw) if landlord_raw is not None else 50.0
    litigation = listing.get("litigation_count_3y") or 0

    # Undesirable: high HPD risk or litigation or very low landlord score
    if hpd_risk_val >= 50 or float(litigation) >= 2:
        return "verified_undesirable"
    if landlord_score <= 30:
        return "verified_undesirable"

    # Promising: decent landlord signal + clean building
    if landlord_type == "independent" or landlord_score >= 65:
        if hpd_risk_val <= 25:
            return "verified_promising"

    # Borderline: verified but neither clearly good nor clearly bad
    return "verified_borderline"


def build_reports(
    scored_rows: list[dict[str, Any]],
    duplicate_clusters: list[dict[str, Any]],
    new_cluster_ids: set[str],
) -> dict[str, str]:
    daily_dir = REPORT_ROOT / "daily"
    weekly_dir = REPORT_ROOT / "weekly"
    shortlist_dir = REPORT_ROOT / "shortlist"
    ensure_dir(daily_dir)
    ensure_dir(weekly_dir)
    ensure_dir(shortlist_dir)

    shortlist = [
        row for row in scored_rows
        if row["recommendation"] in {"pursue", "pursue cautiously"}
        and row.get("listing_type", "actual_apartment_listing") == "actual_apartment_listing"
        and row.get("search_mode", SEARCH_MODE_PERMANENT) != SEARCH_MODE_BRIDGE
    ][:6]
    red_flags = [row for row in scored_rows if row.get("bad_actor_hits") or float(row.get("hpd_risk_score") or 0) >= 60][:6]

    daily_new_path = daily_dir / f"daily_new_listings_{RUN_STAMP}.md"
    shortlist_path = shortlist_dir / f"daily_shortlist_{RUN_STAMP}.md"
    weekly_summary_path = weekly_dir / f"weekly_market_summary_{RUN_STAMP}.md"
    duplicate_report_path = weekly_dir / f"duplicate_cluster_report_{RUN_STAMP}.md"
    red_flag_path = weekly_dir / f"red_flag_building_report_{RUN_STAMP}.md"

    new_rows = [
        [
            row.get("title"),
            row.get("neighborhood"),
            f"${int(row['rent'])}" if row.get("rent") is not None else "n/a",
            row.get("likely_landlord_type"),
            row.get("recommendation"),
            row.get("overall_score"),
        ]
        for row in scored_rows
        if row.get("duplicate_cluster_id") in new_cluster_ids
    ]
    shortlist_rows = [
        [
            row.get("title"),
            row.get("neighborhood"),
            f"${int(row['rent'])}" if row.get("rent") is not None else "n/a",
            row.get("listing_type", "actual_apartment_listing"),
            row.get("listing_authenticity_confidence", "?"),
            row.get("verification_status", "?"),
            row.get("recommendation"),
            row.get("survived_reason", ""),
        ]
        for row in shortlist
    ]
    duplicate_rows = [
        [
            row.get("duplicate_cluster_id"),
            row.get("member_count"),
            row.get("source_names"),
            row.get("match_evidence"),
        ]
        for row in duplicate_clusters
    ]
    red_flag_rows = [
        [
            row.get("title"),
            row.get("address_normalized"),
            row.get("owner_name"),
            row.get("hpd_risk_score"),
            "synthetic" if row.get("synthetic_risk_scores") else "real",
            "; ".join(row.get("bad_actor_hits") or []),
            row.get("recommendation"),
            row.get("demoted_reason", ""),
        ]
        for row in red_flags
    ]

    neighborhood_counts = Counter(row.get("neighborhood") or "Unknown" for row in scored_rows)
    keyword_rows = top_keywords((row.get("full_description") or "" for row in scored_rows), limit=8, stopwords={"with", "the", "and", "for", "this", "that"})

    write_text(
        daily_new_path,
        "\n".join(
            [
                "# Daily New Listings Report",
                "",
                f"- Generated at: {utc_now_iso()}",
                f"- New clusters this run: {len(new_cluster_ids)}",
                "",
                render_markdown_table(
                    ["Title", "Neighborhood", "Rent", "Landlord", "Recommendation", "Score"],
                    new_rows or [["No new clusters this run", "", "", "", "", ""]],
                ),
                "",
            ]
        ),
    )
    write_text(
        shortlist_path,
        "\n".join(
            [
                "# Daily Shortlist Report",
                "",
                render_markdown_table(
                    ["Title", "Neighborhood", "Rent", "Type", "Auth Conf", "Verification", "Recommendation", "Why It Survived"],
                    shortlist_rows or [["No shortlist listings yet", "", "", "", "", "", "", ""]],
                ),
                "",
            ]
        ),
    )
    write_text(
        weekly_summary_path,
        "\n".join(
            [
                "# Weekly Market Summary",
                "",
                f"- Generated at: {utc_now_iso()}",
                f"- Listings scored: {len(scored_rows)}",
                f"- Average scored rent: ${round(mean([row['rent'] for row in scored_rows if row.get('rent') is not None]), 1) if any(row.get('rent') is not None for row in scored_rows) else 'n/a'}",
                "",
                "## Neighborhood Mix",
                "",
                render_markdown_table(
                    ["Neighborhood", "Count"],
                    [[name, count] for name, count in neighborhood_counts.most_common()] or [["None", 0]],
                ),
                "",
                "## Recurring Listing Language",
                "",
                render_markdown_table(
                    ["Keyword", "Mentions"],
                    [[word, count] for word, count in keyword_rows] or [["None", 0]],
                ),
                "",
            ]
        ),
    )
    write_text(
        duplicate_report_path,
        "\n".join(
            [
                "# Duplicate Cluster Report",
                "",
                render_markdown_table(
                    ["Cluster", "Members", "Sources", "Evidence"],
                    duplicate_rows or [["None", 0, "", ""]],
                ),
                "",
            ]
        ),
    )
    write_text(
        red_flag_path,
        "\n".join(
            [
                "# Red-Flag Building Report",
                "",
                render_markdown_table(
                    ["Title", "Address", "Owner", "HPD Risk", "Risk Data", "Flags", "Recommendation", "Demotion Reason"],
                    red_flag_rows or [["No red-flag buildings on this run", "", "", "", "", "", "", ""]],
                ),
                "",
            ]
        ),
    )

    # Unconventional Source Watch Report
    source_watch_dir = REPORT_ROOT / "source_watch"
    ensure_dir(source_watch_dir)
    source_watch_path = source_watch_dir / f"unconventional_source_watch_{RUN_STAMP}.md"

    # Gather per-source stats for unconventional sources
    source_stats: dict[str, dict[str, Any]] = {}
    for row in scored_rows:
        tier = row.get("source_tier", "primary")
        if tier == "primary":
            continue
        sname = row.get("source_name", "unknown")
        if sname not in source_stats:
            source_stats[sname] = {
                "source_tier": tier,
                "search_mode": row.get("search_mode", SEARCH_MODE_PERMANENT),
                "found": 0,
                "qualified": 0,
                "rejected": 0,
                "rejection_reasons": Counter(),
                "record_link_counts": Counter(),
                "public_record_match": 0,
                "manual_review_worthy": [],
            }
        stats = source_stats[sname]
        stats["found"] += 1
        if row.get("qualification_passed"):
            stats["qualified"] += 1
        else:
            stats["rejected"] += 1
            for failure in (row.get("hard_filter_failures") or []):
                stats["rejection_reasons"][failure] += 1

        record_link = row.get("record_link_confidence", "no_record_match")
        stats["record_link_counts"][record_link] += 1
        if record_link in ("exact_address_match", "strong_partial_address_match", "building_level_match"):
            stats["public_record_match"] += 1

        # Manual review worthy: qualified + interesting but not top shortlist
        rec = row.get("recommendation", "skip")
        if rec in ("manual review", "pursue cautiously") and len(stats["manual_review_worthy"]) < 3:
            stats["manual_review_worthy"].append(
                f"{row.get('title', 'untitled')[:40]} | ${int(row.get('rent') or 0)} | {row.get('neighborhood', '?')}"
            )

    source_watch_rows = []
    for sname, stats in sorted(source_stats.items()):
        mode_label = "bridge" if stats["search_mode"] == SEARCH_MODE_BRIDGE else "permanent"
        total = stats["found"]
        link_success = stats["public_record_match"]
        link_rate = f"{round(link_success / total * 100)}%" if total > 0 else "n/a"
        top_rejections = ", ".join(f"{r} ({c})" for r, c in stats["rejection_reasons"].most_common(3)) or "none"
        manual_items = "; ".join(stats["manual_review_worthy"]) or "none"
        source_watch_rows.append([
            sname,
            stats["source_tier"],
            mode_label,
            total,
            stats["qualified"],
            stats["rejected"],
            top_rejections,
            link_rate,
            f"{link_success}/{total}",
            manual_items,
        ])

    write_text(
        source_watch_path,
        "\n".join([
            "# Unconventional Source Watch Report",
            "",
            f"- Generated at: {utc_now_iso()}",
            f"- Sources tracked: {len(source_stats)}",
            "",
            render_markdown_table(
                ["Source", "Tier", "Mode", "Found", "Qualified", "Rejected", "Top Rejections", "Record-Link Rate", "Public Record Matches", "Manual Review Worthy"],
                source_watch_rows or [["No unconventional sources in this run", "", "", 0, 0, 0, "", "", "", ""]],
            ),
            "",
        ]),
    )

    return {
        "daily_new_report": str(daily_new_path),
        "daily_shortlist_report": str(shortlist_path),
        "weekly_market_summary": str(weekly_summary_path),
        "duplicate_cluster_report": str(duplicate_report_path),
        "red_flag_building_report": str(red_flag_path),
        "unconventional_source_watch": str(source_watch_path),
    }


def main() -> int:
    write_stage_start("score")
    try:
        return _main_impl()
    except Exception:
        write_stage_end("score", "failed")
        raise


def _main_impl() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=["daily", "weekly"], default="daily")
    args = parser.parse_args()

    ensure_dir(SCORED_ROOT)
    ensure_dir(EXPORT_ROOT)
    ensure_dir(LOG_ROOT)
    ensure_dir(STATE_ROOT)

    enriched_rows = load_enriched_rows()
    duplicate_clusters = load_duplicate_clusters()
    scored_rows: list[dict[str, Any]] = []
    log_lines: list[str] = []

    preferences = read_json(CONFIG_ROOT / "user_preferences.json", default={})
    seen_cluster_path = STATE_ROOT / "seen_cluster_ids.json"
    previous_seen = set(read_json(seen_cluster_path, default=[]))

    for listing in enriched_rows:
        auth_pen = authenticity_penalty(listing)
        geo_pen = geography_penalty(listing)
        component_scores = {
            "search_fit": round(neighborhood_score(listing, preferences) + price_score(listing, preferences) + unit_score(listing), 1),
            "independent_landlord_fit": independent_landlord_score(listing),
            "building_landlord_safety": safety_score(listing),
            "rent_stability_upside": stabilization_score(listing),
            "listing_quality": quality_score(listing),
            "authenticity_adjustment": auth_pen,
            "geography_adjustment": geo_pen,
            # NOTE: freshness_score and verification_penalty removed from deal score.
            # Freshness and verification quality are trust signals now handled by
            # listing_confidence.py. Deal score reflects only fit/quality.
        }
        overall = round(max(0.0, sum(component_scores.values())), 1)
        synthetic_risk = has_synthetic_risk_scores(listing)
        recommendation = recommendation_for(listing, overall, synthetic_risk)
        why_it_made_the_cut = summary_reason(listing, recommendation)

        # Demotion/survival tracking for dashboard transparency (Part 7)
        survived_reason = ""
        demoted_reason = ""
        if recommendation in ("pursue", "pursue cautiously"):
            survived_reason = _survival_reason(listing, overall, recommendation)
        elif recommendation in ("manual review", "skip"):
            demoted_reason = _demotion_reason(listing, overall, recommendation, synthetic_risk)
        review_reason_code = reviewed_out_reason_code(listing, overall, recommendation, synthetic_risk)

        # Promotion tier: separate verified near-promotions into quality bands
        promotion_tier = _classify_promotion_tier(listing, overall, recommendation, synthetic_risk)
        score_lines = score_explanation_lines(listing, component_scores, overall)

        scored = {
            **listing,
            "component_scores": component_scores,
            "overall_score": overall,
            "recommendation": recommendation,
            "why_it_made_the_cut": why_it_made_the_cut,
            "synthetic_risk_scores": synthetic_risk,
            "survived_reason": survived_reason,
            "demoted_reason": demoted_reason,
            "review_out_reason_code": review_reason_code,
            "review_out_reason": demoted_reason or survived_reason or summary_reason(listing, recommendation),
            "score_explanation_lines": score_lines,
            "promotion_tier": promotion_tier,
        }
        scored_rows.append(scored)
        log_lines.append(
            f"{scored['listing_uid']}: score={overall} recommendation={recommendation} cluster={scored.get('duplicate_cluster_id')}"
        )

    scored_rows.sort(key=lambda item: (item["overall_score"], item.get("rent") is not None, -(item.get("rent") or 0)), reverse=True)
    current_cluster_ids = {row.get("duplicate_cluster_id") for row in scored_rows if row.get("duplicate_cluster_id")}
    new_cluster_ids = {cluster_id for cluster_id in current_cluster_ids if cluster_id not in previous_seen}

    for row in scored_rows:
        if row.get("duplicate_cluster_id") in new_cluster_ids:
            row["state_bucket"] = "new"
        elif row["recommendation"] in {"pursue", "pursue cautiously"}:
            row["state_bucket"] = "shortlisted"
        elif row["recommendation"] == "manual review":
            row["state_bucket"] = "needs_manual_review"
        else:
            row["state_bucket"] = "filtered_out"

    scored_json_path = SCORED_ROOT / f"scored_listings_{RUN_STAMP}.json"
    scored_csv_path = SCORED_ROOT / f"scored_listings_{RUN_STAMP}.csv"
    export_csv_path = EXPORT_ROOT / f"scored_inventory_{RUN_STAMP}.csv"
    shortlist_export_path = EXPORT_ROOT / f"shortlist_{RUN_STAMP}.csv"
    log_path = LOG_ROOT / f"score_{RUN_STAMP}.log"

    write_json(scored_json_path, scored_rows)
    write_csv(
        scored_csv_path,
        scored_rows,
        fieldnames=[
            "listing_uid",
            "duplicate_cluster_id",
            "title",
            "neighborhood",
            "rent",
            "likely_landlord_type",
            "likely_independent_landlord_score",
            "rent_stabilized_signal",
            "hpd_risk_score",
            "dob_risk_score",
            "overall_score",
            "recommendation",
            "state_bucket",
            "review_out_reason_code",
            "why_it_made_the_cut",
        ],
    )
    write_csv(export_csv_path, scored_rows)
    write_csv(
        shortlist_export_path,
        [row for row in scored_rows if row["recommendation"] in {"pursue", "pursue cautiously"}],
    )
    reports = build_reports(scored_rows, duplicate_clusters, new_cluster_ids)
    write_text(
        log_path,
        "\n".join([f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] {line}" for line in log_lines]) + "\n",
    )

    write_json(
        STATE_ROOT / "current_scored.json",
        {
            "run_stamp": RUN_STAMP,
            "scope": args.scope,
            "scored_json_path": str(scored_json_path),
            "scored_csv_path": str(scored_csv_path),
            "export_csv_path": str(export_csv_path),
            "shortlist_export_path": str(shortlist_export_path),
            "new_cluster_count": len(new_cluster_ids),
            "reports": reports,
        },
    )
    write_json(seen_cluster_path, sorted(cluster_id for cluster_id in current_cluster_ids if cluster_id))

    print(
        json.dumps(
            {
                "run_stamp": RUN_STAMP,
                "scope": args.scope,
                "scored_count": len(scored_rows),
                "new_cluster_count": len(new_cluster_ids),
                "pursue_count": sum(1 for row in scored_rows if row["recommendation"] == "pursue"),
                "cautious_count": sum(1 for row in scored_rows if row["recommendation"] == "pursue cautiously"),
                "manual_review_count": sum(1 for row in scored_rows if row["recommendation"] == "manual review"),
                "skip_count": sum(1 for row in scored_rows if row["recommendation"] == "skip"),
                "files": {
                    "scored_json": str(scored_json_path),
                    "scored_csv": str(scored_csv_path),
                    "export_csv": str(export_csv_path),
                    "shortlist_export": str(shortlist_export_path),
                    **reports,
                    "log": str(log_path),
                },
            },
            indent=2,
        )
    )
    write_stage_end("score", "success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

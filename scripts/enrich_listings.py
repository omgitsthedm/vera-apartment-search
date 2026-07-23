#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.paths import (VERA_ROOT as ROOT, CONFIG_DIR as CONFIG_ROOT, DEDUPED_DIR as DEDUPED_ROOT,
    ENRICHED_DIR as ENRICHED_ROOT, LOG_DIR as LOG_ROOT, LEGACY_STATE_DIR as STATE_ROOT,
    REFERENCE_DIR as REFERENCE_ROOT, WATCHLIST_DIR as WATCHLIST_ROOT)
from config.stage_tracker import write_stage_start, write_stage_end
from workflow_support import (
    SEARCH_MODE_BRIDGE,
    building_address,
    canonical_text,
    classify_record_link,
    ensure_dir,
    latest_file,
    parse_float,
    read_csv_rows,
    read_json,
    stable_hash,
    state_path_or_latest,
    utc_stamp,
    write_csv,
    write_json,
    write_text,
)

RUN_STAMP = utc_stamp()

POSITIVE_OWNER_CUES = {
    "by owner",
    "owner direct",
    "private landlord",
    "no broker",
    "small building",
    "landlord showing",
    "meet the landlord",
    "owner occupied",
    "owner managed",
    "family owned",
    "family-owned",
    "independent landlord",
    "deal directly with owner",
    "deal with owner",
    "speak to owner",
    "contact owner",
    "listed by owner",
    "owner listing",
}
NEGATIVE_OWNER_CUES = {
    "managed by",
    "leasing office",
    "online portal",
    "application through leasing office",
    "luxury building",
    "portfolio",
    "property management",
    "management company",
    "corporate housing",
    "professional management",
    "apply online",
    "streeteasy application",
    "guaranteed rent",
}
SCAM_CUES = {
    "send deposit",
    "wire transfer",
    "western union",
    "money order",
    "overseas",
    "currently abroad",
    "email me for showing",
    "text only",
    "no calls",
    "section 8 welcome cash only",
}

# --- Listing authenticity classifier cues ---
BROKER_SERVICE_CUES = {
    "hire a broker",
    "hire me to find",
    "hire him to find",
    "hire her to find",
    "this is not an apartment ad",
    "not an apartment ad",
    "ad to solicit for services",
    "services being offered",
    "apartment finder",
    "apartment locator",
    "locator service",
    "i will find you",
    "let me find you",
    "hire an experienced broker",
    "samples of apartments",
    "sample photos",
    "photos are samples",
}
LEAD_GEN_CUES = {
    "call for availability",
    "call for details on multiple units",
    "multiple apartments available",
    "many apartments available",
    "various locations",
    "we have apartments in",
    "several units to choose from",
}
NOT_A_LISTING_CUES = {
    "this is not an apartment",
    "this is an ad for services",
    "this is a service ad",
    "not a specific apartment",
}

# --- Geography cross-validation ---
# Manhattan ZIPs: 100xx, 101xx, 102xx; Brooklyn: 112xx; Queens: 11[0,1,3,4,5,6]xx
# Bronx: 104xx; Staten Island: 103xx
ZIP_BOROUGH_MAP: dict[str, list[str]] = {
    "Manhattan": ["100", "101", "102"],
    "Brooklyn": ["112"],
    "Queens": ["110", "111", "113", "114", "115", "116"],
    "Bronx": ["104"],
    "Staten Island": ["103"],
}

NEIGHBORHOOD_BOROUGH_MAP: dict[str, str] = {
    "east village": "Manhattan",
    "alphabet city": "Manhattan",
    "greenwich village": "Manhattan",
    "lower east side": "Manhattan",
    "stuytown": "Manhattan",
    "stuyvesant town": "Manhattan",
    "west village": "Manhattan",
    "tribeca": "Manhattan",
    "soho": "Manhattan",
    "chelsea": "Manhattan",
    "williamsburg": "Brooklyn",
    "greenpoint": "Brooklyn",
    "east williamsburg": "Brooklyn",
    "bushwick": "Brooklyn",
    "bedford stuyvesant": "Brooklyn",
    "bed-stuy": "Brooklyn",
    "prospect heights": "Brooklyn",
    "park slope": "Brooklyn",
    "fort greene": "Brooklyn",
    "clinton hill": "Brooklyn",
    "cobble hill": "Brooklyn",
    "boerum hill": "Brooklyn",
    "dumbo": "Brooklyn",
    "brooklyn heights": "Brooklyn",
    "crown heights": "Brooklyn",
    "cypress hills": "Brooklyn",
    "long island city": "Queens",
    "astoria": "Queens",
    "harlem": "Manhattan",
    "upper east side": "Manhattan",
    "upper west side": "Manhattan",
    "midtown": "Manhattan",
    "murray hill": "Manhattan",
    "gramercy": "Manhattan",
    "flatiron": "Manhattan",
    "nolita": "Manhattan",
    "little italy": "Manhattan",
    "chinatown": "Manhattan",
    "financial district": "Manhattan",
    "battery park city": "Manhattan",
}


def classify_listing_type(listing: dict[str, Any]) -> tuple[str, str]:
    """Classify a listing's authenticity type and confidence.

    Returns (listing_type, listing_authenticity_confidence).

    Confidence reflects how *certain* we are about the classification, not how
    good the listing is. "high" means the evidence strongly supports the type;
    "low" means the classification is a best-guess from sparse data.
    """
    text_blob = canonical_text(
        f"{listing.get('title')} {listing.get('full_description')}"
    )

    # --- Hard reject types (Parts 1 & 2) ---
    if any(cue in text_blob for cue in NOT_A_LISTING_CUES):
        return "broker_service_solicitation", "high"

    # Apartment-finder / locator ads: a broker offering to find you an apt
    finder_cues = BROKER_SERVICE_CUES - {"apartment finder", "apartment locator", "locator service"}
    locator_cues = {"apartment finder", "apartment locator", "locator service"}
    if any(cue in text_blob for cue in locator_cues):
        return "apartment_finder_locator_ad", "high"
    if any(cue in text_blob for cue in finder_cues):
        return "broker_service_solicitation", "high"

    if any(cue in text_blob for cue in SCAM_CUES):
        return "probable_scam", "medium"

    # Bridge housing: lease takeovers, furnished short-term, sublets in bridge mode
    search_mode = listing.get("search_mode", "mode_a_permanent")
    if search_mode == SEARCH_MODE_BRIDGE:
        return "bridge_housing", "high"

    if listing.get("room_share_flag"):
        return "room_share", "high"
    if listing.get("sublet_flag"):
        return "sublet", "medium"

    # Lead-gen: vague multi-unit ads with no specific address
    if any(cue in text_blob for cue in LEAD_GEN_CUES):
        if not listing.get("address_normalized") or listing.get("address_confidence") == "low":
            return "off_market_lead_gen", "medium"

    # --- Completeness check ---
    address = listing.get("address_normalized") or ""
    has_address = bool(address)
    has_street_number = has_address and any(c.isdigit() for c in address)
    has_rent = listing.get("rent") is not None
    has_beds = listing.get("beds") is not None
    description = listing.get("full_description") or ""
    has_description = len(description) > 40
    completeness = sum([has_address, has_rent, has_beds, has_description])

    if completeness <= 1:
        return "unclear", "low"

    # --- Confidence calibration for actual apartment listings ---
    # "high" requires: street-number address + rent + meaningful description
    # "medium": has address but missing street number or thin description
    # "low": barely qualifies as a listing
    if completeness <= 2:
        return "actual_apartment_listing", "low"
    if not has_street_number:
        return "actual_apartment_listing", "medium"
    if len(description) < 100:
        return "actual_apartment_listing", "medium"
    return "actual_apartment_listing", "high"


def check_geography_sanity(listing: dict[str, Any]) -> tuple[str, list[str]]:
    """Cross-validate borough, ZIP, and neighborhood.

    Returns (neighborhood_confidence, list of geography_flags).
    """
    flags: list[str] = []
    neighborhood = canonical_text(listing.get("neighborhood"))
    borough = listing.get("borough")
    zip_code = str(listing.get("zip") or "")

    # Check neighborhood → expected borough
    expected_borough = NEIGHBORHOOD_BOROUGH_MAP.get(neighborhood)
    if expected_borough and borough and canonical_text(borough) != canonical_text(expected_borough):
        flags.append(
            f"neighborhood '{listing.get('neighborhood')}' is in {expected_borough} "
            f"but borough is '{borough}'"
        )

    # Check ZIP → expected borough
    if zip_code and len(zip_code) >= 3 and borough:
        zip_prefix = zip_code[:3]
        borough_lower = canonical_text(borough)
        expected_boroughs_for_zip = [
            b for b, prefixes in ZIP_BOROUGH_MAP.items()
            if zip_prefix in prefixes
        ]
        if expected_boroughs_for_zip:
            if not any(canonical_text(b) == borough_lower for b in expected_boroughs_for_zip):
                flags.append(
                    f"ZIP {zip_code} belongs to {expected_boroughs_for_zip[0]} "
                    f"but borough is '{borough}'"
                )

    # Check for partial/vague addresses
    address = listing.get("address_normalized") or ""
    if address and not any(c.isdigit() for c in address):
        flags.append("address has no street number — likely partial")

    if len(flags) >= 2:
        confidence = "low"
    elif len(flags) == 1:
        confidence = "medium"
    elif not neighborhood:
        confidence = "low"
    else:
        confidence = "high"

    return confidence, flags


def load_deduped_rows() -> list[dict[str, Any]]:
    state = read_json(STATE_ROOT / "current_deduped.json", default={})
    path = state_path_or_latest(state.get("deduped_path"), DEDUPED_ROOT, "deduped_listings_*.json")
    if not path:
        raise FileNotFoundError("No deduped dataset found")
    return read_json(path, default=[])


def evaluate_hard_filters(listing: dict[str, Any], preferences: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    search_mode = listing.get("search_mode", "mode_a_permanent")

    neighborhoods = {canonical_text(item) for item in preferences.get("neighborhoods", [])}
    listing_neighborhood = canonical_text(listing.get("neighborhood"))
    if listing_neighborhood not in neighborhoods:
        # Bridge mode is more lenient on neighborhood — still note it but don't hard-reject
        if search_mode != SEARCH_MODE_BRIDGE:
            reasons.append("outside target neighborhood")

    beds = listing.get("beds")
    if beds not in (None, 0, 0.0, 1, 1.0):
        reasons.append("unit type outside studio/1BR target")

    rent = parse_float(listing.get("rent"))
    max_rent = parse_float(preferences.get("max_rent"))
    if rent is None or (max_rent is not None and rent > max_rent):
        reasons.append("above max rent or rent missing")

    # Room-share and sublet filters are relaxed for bridge mode
    if listing.get("room_share_flag") and search_mode != SEARCH_MODE_BRIDGE:
        reasons.append("room-share signal")
    if listing.get("sublet_flag") and search_mode != SEARCH_MODE_BRIDGE:
        reasons.append("sublet-only signal")

    return len(reasons) == 0, reasons


def build_reference_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        building_key = canonical_text(row.get("building_address"))
        if building_key:
            index[f"addr:{building_key}"] = row
        if row.get("bbl"):
            index[f"bbl:{row['bbl']}"] = row
        if row.get("bin"):
            index[f"bin:{row['bin']}"] = row
    return index


def merged_reference_index() -> dict[str, dict[str, Any]]:
    seed_rows = read_json(REFERENCE_ROOT / "public_records_seed.json", default=[])
    live_rows = read_json(REFERENCE_ROOT / "current_public_records_live.json", default=[])
    seed_index = build_reference_index(seed_rows)
    merged = dict(seed_index)
    for row in live_rows:
        key = canonical_text(row.get("building_address"))
        if not key or row.get("lookup_status") != "matched":
            continue
        merged[f"addr:{key}"] = {**seed_index.get(f"addr:{key}", {}), **row}
        if row.get("bbl"):
            merged[f"bbl:{row['bbl']}"] = merged[f"addr:{key}"]
        if row.get("bin"):
            merged[f"bin:{row['bin']}"] = merged[f"addr:{key}"]
    return merged


def reference_for_listing(listing: dict[str, Any], reference_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    candidates = []
    if listing.get("bbl"):
        candidates.append(f"bbl:{listing['bbl']}")
    if listing.get("bin"):
        candidates.append(f"bin:{listing['bin']}")
    building_key = canonical_text(building_address(listing.get("address_normalized") or listing.get("address_raw")))
    if building_key:
        candidates.append(f"addr:{building_key}")
    for key in candidates:
        if key in reference_index:
            return reference_index[key]
    return None


def load_watchlist_set(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = canonical_text(row.get(key))
        if value:
            items[value] = row
    return items


def hpd_risk_score(reference: dict[str, Any] | None) -> float:
    if not reference:
        return 50.0
    complaints = float(reference.get("hpd_complaints_3y") or 0)
    violations = float(reference.get("hpd_open_violations") or 0)
    litigation = float(reference.get("litigation_count_3y") or 0)
    heat = float(reference.get("heat_hot_water_complaints_3y") or 0)
    bedbug = float(reference.get("bedbug_reports_3y") or 0)
    serious_open = float(reference.get("serious_open_violations") or 0)
    return round(
        min(
            100.0,
            complaints * 1.4 + violations * 5.5 + litigation * 8.0 + heat * 0.9 + bedbug * 6.0 + serious_open * 10.0,
        ),
        1,
    )


def dob_risk_score(reference: dict[str, Any] | None) -> float:
    if not reference:
        return 45.0
    incidents = float(reference.get("dob_incidents_3y") or 0)
    serious = float(reference.get("serious_violations_3y") or 0)
    return round(
        min(
            100.0,
            incidents * 18.0 + float(reference.get("hpd_total_violations_3y") or reference.get("hpd_open_violations") or 0) * 1.5 + serious * 5.0,
        ),
        1,
    )


def contact_matches_owner(listing: dict[str, Any], owner_name: str | None) -> bool:
    if not owner_name:
        return False
    contact = canonical_text(listing.get("contact_name"))
    owner = canonical_text(owner_name)
    return bool(contact and owner and (contact in owner or owner in contact))


def classify_landlord(
    listing: dict[str, Any],
    reference: dict[str, Any] | None,
    owner_watch: dict[str, dict[str, Any]],
    building_watch: dict[str, dict[str, Any]],
    bad_actor_watch: dict[str, dict[str, Any]],
) -> tuple[float, list[str], list[str]]:
    score = 50.0
    reasons: list[str] = []
    red_flags: list[str] = []

    text_blob = canonical_text(f"{listing.get('title')} {listing.get('full_description')}")
    owner_name = reference.get("owner_name") if reference else None
    building_key = canonical_text(building_address(listing.get("address_normalized") or listing.get("address_raw")))

    if listing.get("by_owner_signal") or any(cue in text_blob for cue in POSITIVE_OWNER_CUES):
        score += 18.0
        reasons.append("owner-direct listing language")
    if listing.get("fee_status") == "no fee":
        score += 8.0
        reasons.append("no-fee signal")
    if reference and reference.get("owner_type") == "individual":
        score += 20.0
        source = reference.get("owner_source") or "public record"
        reasons.append(f"public record suggests individual owner ({source})")
    if reference and reference.get("owner_type") == "coop_hdfc":
        score += 10.0
        reasons.append("HDFC cooperative ownership (resident-run, non-corporate)")
    if reference and reference.get("is_coop"):
        score += 12.0
        reasons.append(f"co-op building (class {reference.get('coop_class') or '?'}) — rental offered in a cooperative")
    portfolio = reference.get("owner_portfolio_estimate") if reference else None
    if portfolio is not None:
        if portfolio <= 2:
            score += 8.0
            reasons.append(f"owner registered on only {int(portfolio)} building(s) — single-building owner signal")
        elif portfolio >= 10:
            score -= 12.0
            label = "50+" if portfolio >= 50 else str(int(portfolio))
            reasons.append(f"owner registered on {label} buildings — portfolio landlord")
    if reference and float(reference.get("unit_count") or 0) <= 6:
        score += 10.0
        reasons.append("small-building signal")
    if contact_matches_owner(listing, owner_name):
        score += 10.0
        reasons.append("contact name aligns with owner record")

    # HPD registration recency: recently registered = active/engaged owner
    if reference and reference.get("lastregistrationdate"):
        try:
            reg_date = datetime.fromisoformat(str(reference["lastregistrationdate"]).replace("Z", "+00:00").split("T")[0])
            reg_age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - reg_date).days
            if reg_age_days <= 365:
                score += 6.0
                reasons.append("HPD registration current (within 1 year)")
            elif reg_age_days <= 730:
                score += 3.0
                reasons.append("HPD registration recent (within 2 years)")
        except (ValueError, TypeError):
            pass

    # Clean building bonus: low complaints + no open violations = responsible owner
    if reference and reference.get("lookup_status") == "matched":
        complaints = float(reference.get("hpd_complaints_3y") or 0)
        open_violations = float(reference.get("hpd_open_violations") or 0)
        litigation = float(reference.get("litigation_count_3y") or 0)
        if complaints <= 5 and open_violations == 0 and litigation == 0:
            score += 8.0
            reasons.append(f"clean building record ({int(complaints)} complaints, 0 open violations, 0 litigation)")
        elif complaints <= 15 and open_violations <= 2 and litigation == 0:
            score += 4.0
            reasons.append(f"moderate building record ({int(complaints)} complaints, {int(open_violations)} violations)")

    if listing.get("management_company_signal") or any(cue in text_blob for cue in NEGATIVE_OWNER_CUES):
        score -= 20.0
        reasons.append("management or leasing-office language")
    if listing.get("broker_name"):
        score -= 10.0
        reasons.append("broker or leasing brand present")
    if listing.get("fee_status") == "fee":
        score -= 8.0
        reasons.append("broker fee listed")
    if any(cue in text_blob for cue in SCAM_CUES):
        score -= 25.0
        red_flags.append("scam-indicative language detected")
    if not listing.get("address_normalized") and not listing.get("address_raw"):
        score -= 12.0
        reasons.append("no address provided — vague listing")
    elif listing.get("address_confidence") == "low":
        score -= 6.0
        reasons.append("address confidence is low")
    if reference and reference.get("owner_type") == "llc":
        score -= 15.0
        reasons.append("public record suggests LLC ownership")
    if reference and float(reference.get("unit_count") or 0) >= 20:
        score -= 10.0
        reasons.append("larger-building ownership scale")

    owner_key = canonical_text(owner_name)
    if owner_key and owner_key in bad_actor_watch:
        score -= 18.0
        red_flags.append(f"bad-actor owner watch hit: {bad_actor_watch[owner_key].get('reason')}")
    if building_key and building_key in bad_actor_watch:
        score -= 12.0
        red_flags.append(f"bad-actor building watch hit: {bad_actor_watch[building_key].get('reason')}")
    if owner_key and owner_key in owner_watch:
        reasons.append(f"manual owner watchlist note: {owner_watch[owner_key].get('notes')}")
    if building_key and building_key in building_watch:
        reasons.append(f"manual building watchlist note: {building_watch[building_key].get('notes')}")

    return round(max(0.0, min(100.0, score)), 1), reasons, red_flags


def _is_likely_prewar_zip(zip_code: str | None, borough: str | None) -> bool:
    """Estimate whether a building is likely pre-war based on ZIP and borough.

    Manhattan below 96th St (ZIPs 10001-10028) and brownstone Brooklyn (112xx)
    have overwhelmingly pre-war housing stock. This is a heuristic, not definitive.
    """
    if not zip_code:
        return False
    try:
        zip_num = int(str(zip_code)[:5])
    except (ValueError, TypeError):
        return False
    # Manhattan: most of below-96th-St is ZIPs 10001-10028
    if borough and canonical_text(borough) == "manhattan" and 10001 <= zip_num <= 10028:
        return True
    # Brooklyn brownstone belt
    if borough and canonical_text(borough) == "brooklyn" and zip_num in (
        11201, 11205, 11206, 11211, 11215, 11216, 11217, 11218, 11225, 11226, 11238,
    ):
        return True
    return False


def rent_stabilization_signal(
    reference: dict[str, Any] | None,
    listing: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    if not reference:
        return "unclear", "low", "No public-record match yet."
    if reference.get("rent_stabilized_reference_hit"):
        return "likely", "high", "Seeded public reference hit suggests regulated-building potential."

    age_band = canonical_text(reference.get("building_age_band"))
    unit_count = float(reference.get("unit_count") or 0)

    # Seed data has building_age_band
    if age_band == "prewar" and unit_count >= 6:
        return "possible", "medium", "Prewar building size suggests possible regulation, but no direct hit is loaded."
    if age_band == "prewar":
        return "possible", "low", "Prewar building clue only."

    # Live HPD data: use ZIP/borough heuristic + registration status for older buildings
    if reference.get("lookup_status") == "matched" and listing:
        zip_code = listing.get("zip") or reference.get("zip")
        borough = listing.get("borough") or reference.get("borough_resolved")
        registration_signal = reference.get("registration_signal")
        building_id = reference.get("buildingid")

        # Low building IDs generally correspond to older buildings in HPD's database
        is_old_building_id = False
        if building_id:
            try:
                is_old_building_id = int(building_id) < 100000
            except (ValueError, TypeError):
                pass

        prewar_zip = _is_likely_prewar_zip(zip_code, borough)

        if prewar_zip and registration_signal == "registered":
            if is_old_building_id:
                return "possible", "medium", (
                    f"Building in pre-war ZIP ({zip_code}), HPD-registered, "
                    f"low building ID ({building_id}) suggests older building — "
                    "rent stabilization possible."
                )
            return "possible", "low", (
                f"Building in pre-war ZIP ({zip_code}) and HPD-registered — "
                "stabilization possible but not confirmed."
            )

    return "not indicated", "low", "No regulation clue found in the visible reference layer."


def verification_status(listing: dict[str, Any], reference: dict[str, Any] | None, qualified: bool) -> str:
    if not qualified:
        return "not_qualified_for_enrichment"
    if reference:
        return "matched_public_records"
    if listing.get("address_normalized"):
        return "partial_address_only"
    return "no_public_match"


def neighborhood_verified_by_map(listing: dict[str, Any], reference: dict[str, Any] | None) -> tuple[bool | None, str]:
    if not reference:
        return None, "No map-backed building record matched this listing."
    resolved = canonical_text(reference.get("resolved_neighborhood"))
    listing_neighborhood = canonical_text(listing.get("neighborhood"))
    if resolved and listing_neighborhood:
        if resolved == listing_neighborhood:
            return True, f"GeoSearch resolved this building in {reference.get('resolved_neighborhood')}."
        return False, f"GeoSearch resolved this building in {reference.get('resolved_neighborhood')}, not {listing.get('neighborhood')}."
    if reference.get("resolved_borough") and listing.get("borough"):
        if canonical_text(reference.get("resolved_borough")) == canonical_text(listing.get("borough")):
            return True, f"Map logic confirms borough match: {reference.get('resolved_borough')}."
        return False, f"Map logic resolved borough {reference.get('resolved_borough')} but listing says {listing.get('borough')}."
    return None, "Map logic did not return enough neighborhood detail to verify the source label."


def move_in_cash_estimate(listing: dict[str, Any]) -> tuple[float | None, str]:
    rent = parse_float(listing.get("rent"))
    if rent is None:
        return None, "Rent missing, so move-in cash estimate is unavailable."
    fee_status = canonical_text(listing.get("fee_status"))
    if fee_status == "no fee":
        estimate = rent * 2
        return estimate, "Estimated as first month plus one-month security on a no-fee listing."
    if fee_status == "fee":
        estimate = rent * 3
        return estimate, "Estimated as first month, one-month security, and roughly one month of broker fee."
    estimate = rent * 2.5
    return estimate, "Estimated with first month, one-month security, and a partial fee reserve because fee status is unclear."


def rent_control_candidate(reference: dict[str, Any] | None, listing: dict[str, Any]) -> tuple[bool, str]:
    if not reference:
        return False, "No building record match, so rent-control heuristics are too weak."
    zip_code = listing.get("zip") or reference.get("zip")
    borough = listing.get("borough") or reference.get("borough_resolved")
    unit_count = float(reference.get("unit_count") or 0)
    building_id = reference.get("buildingid")
    old_building_id = False
    if building_id:
        try:
            old_building_id = int(building_id) < 100000
        except (TypeError, ValueError):
            old_building_id = False
    if _is_likely_prewar_zip(zip_code, borough) and unit_count and unit_count <= 6 and old_building_id:
        return True, "Older-looking small building in a pre-war area. This is only a heuristic, never a confirmation."
    return False, "No strong rent-control heuristic triggered."


def unit_status_note(reference: dict[str, Any] | None, record_status: str, listing: dict[str, Any]) -> tuple[str, str]:
    address = canonical_text(listing.get("address_normalized") or listing.get("address_raw"))
    has_unit = " apt " in address or "#" in str(listing.get("address_raw") or "")
    if record_status == "matched_public_records" and has_unit:
        return "not confirmed", "Building verification succeeded, but public data does not confirm that this exact unit is currently available."
    if record_status == "matched_public_records":
        return "not confirmed", "The building matched official records, but unit availability is not independently confirmed."
    return "not confirmed", "No exact unit verification exists in the current source and public-record stack."


def verify_before_applying(listing: dict[str, Any], reference: dict[str, Any] | None, record_status: str) -> list[str]:
    checklist = [
        "Confirm the exact unit number, lease term, and whether the apartment is still available.",
        "Ask for the exact move-in amount due at signing and whether any broker fee applies.",
        "Verify the source contact is authorized to rent the unit.",
    ]
    if record_status != "matched_public_records":
        checklist.append("Verify the full street address independently before sharing personal information.")
    if listing.get("rent_stabilized_signal") in ("possible", "likely"):
        checklist.append("Ask for the rent history and whether the unit is rent stabilized.")
    if float(listing.get("heat_hot_water_complaints_3y") or 0) > 0:
        checklist.append("Ask about the building's heat and hot-water complaint history.")
    if float(listing.get("bedbug_reports_3y") or 0) > 0:
        checklist.append("Ask directly about recent bed bug disclosures and treatment history.")
    if float(listing.get("serious_open_violations") or 0) > 0:
        checklist.append("Review the building's open Class C / serious violations before applying.")
    return checklist


def main() -> int:
    write_stage_start("enrich")
    try:
        return _main_impl()
    except Exception:
        write_stage_end("enrich", "failed")
        raise


def _main_impl() -> int:
    ensure_dir(ENRICHED_ROOT)
    ensure_dir(LOG_ROOT)
    ensure_dir(STATE_ROOT)

    deduped_rows = load_deduped_rows()
    preferences = read_json(CONFIG_ROOT / "user_preferences.json", default={})
    reference_index = merged_reference_index()
    owner_watch = load_watchlist_set(read_csv_rows(WATCHLIST_ROOT / "owners" / "manual_owner_watchlist.csv"), "owner_name")
    building_watch = load_watchlist_set(read_csv_rows(WATCHLIST_ROOT / "buildings" / "manual_building_watchlist.csv"), "building_address")
    bad_actor_rows = read_csv_rows(WATCHLIST_ROOT / "bad_actors" / "known_bad_actors.csv")
    bad_actor_watch = {}
    for row in bad_actor_rows:
        key = canonical_text(row.get("match_value"))
        if key:
            bad_actor_watch[key] = row

    enriched_rows: list[dict[str, Any]] = []
    risk_rows: list[dict[str, Any]] = []
    log_lines: list[str] = []

    for listing in deduped_rows:
        qualified, hard_filter_failures = evaluate_hard_filters(listing, preferences)
        building_key = canonical_text(building_address(listing.get("address_normalized") or listing.get("address_raw")))
        reference = reference_for_listing(listing, reference_index)

        # Listing authenticity classification
        listing_type, listing_authenticity_confidence = classify_listing_type(listing)

        # Geography sanity checks
        neighborhood_confidence, geography_flags = check_geography_sanity(listing)

        independent_score, landlord_reasons, red_flags = classify_landlord(
            listing,
            reference,
            owner_watch,
            building_watch,
            bad_actor_watch,
        )

        # Fold geography flags into red_flags for downstream visibility
        if geography_flags:
            red_flags.extend(geography_flags)

        stabilized_signal, stabilized_confidence, stabilized_notes = rent_stabilization_signal(reference, listing)
        owner_name = reference.get("owner_name") if reference else listing.get("owner_name")
        hpd_score = hpd_risk_score(reference)
        dob_score = dob_risk_score(reference)
        record_status = verification_status(listing, reference, qualified)
        neighborhood_verified, neighborhood_verification_note = neighborhood_verified_by_map(listing, reference)
        move_in_cash, move_in_cash_note = move_in_cash_estimate(listing)
        rent_control_flag, rent_control_note = rent_control_candidate(reference, listing)
        unit_status, unit_status_note_text = unit_status_note(reference, record_status, listing)
        likely_landlord_type = "independent" if independent_score >= 70 else "management" if independent_score <= 35 else "unclear"

        # Verification confidence based on record match quality
        if record_status == "matched_public_records":
            verification_conf = "high"
        elif record_status == "partial_address_only":
            verification_conf = "medium"
        else:
            verification_conf = "low"

        # Address confidence: how much we trust the address data
        address_raw = listing.get("address_normalized") or listing.get("address_raw") or ""
        has_street_num = bool(address_raw) and any(c.isdigit() for c in address_raw)
        if record_status == "matched_public_records":
            address_conf = "high"
        elif has_street_num and listing.get("zip"):
            address_conf = "high"
        elif has_street_num:
            address_conf = "medium"
        elif address_raw:
            address_conf = "low"
        else:
            address_conf = "none"

        # Source quality confidence: how much we trust this source's data quality
        source_tier = listing.get("source_tier", "primary")
        source_status = listing.get("source_status", "live")
        if source_tier == "primary" and source_status == "live":
            source_quality_conf = "high"
        elif source_tier in ("primary", "unconventional_high") and source_status in ("live", "partial"):
            source_quality_conf = "medium"
        elif source_tier == "unconventional_secondary":
            source_quality_conf = "low"
        else:
            source_quality_conf = "low"

        # Record-link confidence classification
        record_link_confidence = classify_record_link(
            listing.get("address_normalized") or listing.get("address_raw"),
            reference.get("building_address") if reference else None,
            listing.get("contact_name") or listing.get("owner_name"),
            reference.get("owner_name") if reference else None,
            listing.get("neighborhood"),
        )

        # Source-specific enrichment notes
        source_enrichment_notes: list[str] = []
        search_mode = listing.get("search_mode", "mode_a_permanent")

        if listing.get("lease_takeover"):
            source_enrichment_notes.append("Lease takeover listing — check assignment terms and remaining lease duration")
        if listing.get("official_program_source"):
            source_enrichment_notes.append("Official NYC housing program source — high trust, may have application deadlines")
        if listing.get("curated_source"):
            source_enrichment_notes.append("Curated/human-screened source — enrichment limited to available address evidence")
        if search_mode == SEARCH_MODE_BRIDGE:
            source_enrichment_notes.append("Bridge/temporary housing — not a permanent apartment candidate")
        if source_tier in ("unconventional_high", "unconventional_secondary"):
            source_enrichment_notes.append(f"Unconventional source (tier: {source_tier})")
        if source_tier == "fallback":
            source_enrichment_notes.append("Fallback source — bridge/temporary/roommate only")

        # Source-specific: for NYBits, note usefulness for small-operator detection
        if listing.get("source_name") == "nybits":
            if listing.get("contact_name"):
                source_enrichment_notes.append(f"NYBits landlord/manager clue: {listing['contact_name']}")

        analyst_notes = []
        if listing_type != "actual_apartment_listing":
            analyst_notes.append(f"Listing type: {listing_type}")
        if address_conf in ("low", "none"):
            analyst_notes.append(f"Weak address (confidence={address_conf}) — treat scores with skepticism")
        if geography_flags:
            analyst_notes.append("Geography: " + "; ".join(geography_flags))
        if hard_filter_failures:
            analyst_notes.append("Hard filter issues: " + ", ".join(hard_filter_failures))
        if landlord_reasons:
            analyst_notes.append("Landlord signal notes: " + "; ".join(landlord_reasons[:3]))
        if red_flags:
            analyst_notes.append("Red flags: " + "; ".join(red_flags))
        if source_enrichment_notes:
            analyst_notes.append("Source notes: " + "; ".join(source_enrichment_notes))
        if reference and reference.get("notes"):
            analyst_notes.append("Reference note: " + str(reference["notes"]))
        analyst_notes.append("Neighborhood verification: " + neighborhood_verification_note)
        analyst_notes.append("Unit status: " + unit_status_note_text)
        analyst_notes.append("Move-in cash: " + move_in_cash_note)
        if rent_control_flag:
            analyst_notes.append("Rent-control heuristic: " + rent_control_note)

        enriched = {
            **listing,
            "bbl": reference.get("bbl") if reference else None,
            "bin": reference.get("bin") if reference else None,
            "building_key": building_key or None,
            "owner_name": owner_name,
            "owner_type": reference.get("owner_type") if reference else None,
            "unit_count": reference.get("unit_count") if reference else None,
            "qualification_passed": qualified,
            "hard_filter_failures": hard_filter_failures,
            "listing_type": listing_type,
            "listing_authenticity_confidence": listing_authenticity_confidence,
            "neighborhood_confidence": neighborhood_confidence,
            "geography_flags": geography_flags,
            "verification_status": record_status,
            "verification_confidence": verification_conf,
            "address_confidence": address_conf,
            "source_quality_confidence": source_quality_conf,
            "likely_independent_landlord_score": independent_score,
            "likely_landlord_type": likely_landlord_type,
            "landlord_reason_summary": landlord_reasons,
            "bad_actor_hits": red_flags,
            "rent_stabilized_signal": stabilized_signal,
            "rent_stabilized_confidence": stabilized_confidence,
            "rent_stabilized_notes": stabilized_notes,
            "official_rent_stabilized_list_hit": bool(reference.get("rent_stabilized_reference_hit")) if reference else False,
            "official_rent_stabilized_list_source": reference.get("rent_stabilized_reference_source") if reference else None,
            "possible_rent_control_candidate": rent_control_flag,
            "possible_rent_control_candidate_note": rent_control_note,
            "hpd_risk_score": hpd_score,
            "dob_risk_score": dob_score,
            "heat_hot_water_complaints_3y": reference.get("heat_hot_water_complaints_3y") if reference else 0,
            "bedbug_reports_3y": reference.get("bedbug_reports_3y") if reference else 0,
            "serious_violations_3y": reference.get("serious_violations_3y") if reference else 0,
            "serious_open_violations": reference.get("serious_open_violations") if reference else 0,
            "court_signal": reference.get("court_signal") if reference else "no record match",
            "registration_signal": reference.get("registration_signal") if reference else None,
            "public_record_id": f"record-{stable_hash(building_key, owner_name)}" if reference else None,
            "public_record_notes": reference.get("notes") if reference else None,
            "public_record_lookup_source": reference.get("lookup_source") if reference else None,
            "public_record_lookup_status": reference.get("lookup_status") if reference else None,
            "litigation_count_3y": reference.get("litigation_count_3y") if reference else None,
            "record_link_confidence": record_link_confidence,
            "geosearch_match_confidence": reference.get("geosearch_match_confidence") if reference else None,
            "geosearch_match_type": reference.get("geosearch_match_type") if reference else None,
            "neighborhood_verified_by_map": neighborhood_verified,
            "neighborhood_verification_note": neighborhood_verification_note,
            "unit_status": unit_status,
            "unit_status_note": unit_status_note_text,
            "estimated_move_in_cash": move_in_cash,
            "estimated_move_in_cash_note": move_in_cash_note,
            "source_enrichment_notes": source_enrichment_notes,
            "what_to_verify_before_applying": [],
            "analyst_notes": " | ".join(analyst_notes) if analyst_notes else "No major enrichment note yet.",
        }
        enriched["what_to_verify_before_applying"] = verify_before_applying(enriched, reference, record_status)
        enriched_rows.append(enriched)
        risk_rows.append(
            {
                "listing_uid": enriched["listing_uid"],
                "duplicate_cluster_id": enriched["duplicate_cluster_id"],
                "title": enriched.get("title"),
                "address_normalized": enriched.get("address_normalized"),
                "owner_name": owner_name,
                "qualification_passed": qualified,
                "verification_status": record_status,
                "address_confidence": address_conf,
                "source_quality_confidence": source_quality_conf,
                "listing_type": listing_type,
                "listing_authenticity_confidence": listing_authenticity_confidence,
                "likely_landlord_type": likely_landlord_type,
                "likely_independent_landlord_score": independent_score,
                "hpd_risk_score": hpd_score,
                "dob_risk_score": dob_score,
                "rent_stabilized_signal": stabilized_signal,
                "heat_hot_water_complaints_3y": enriched["heat_hot_water_complaints_3y"],
                "bedbug_reports_3y": enriched["bedbug_reports_3y"],
                "serious_open_violations": enriched["serious_open_violations"],
                "court_signal": enriched["court_signal"],
                "bad_actor_hits": "; ".join(red_flags),
            }
        )
        log_lines.append(
            f"{enriched['listing_uid']}: qualified={qualified} verification={record_status} landlord_score={independent_score} hpd={hpd_score} dob={dob_score}"
        )

    enriched_path = ENRICHED_ROOT / f"enriched_listings_{RUN_STAMP}.json"
    risk_csv_path = ENRICHED_ROOT / f"risk_records_{RUN_STAMP}.csv"
    log_path = LOG_ROOT / f"enrich_{RUN_STAMP}.log"

    write_json(enriched_path, enriched_rows)
    write_csv(risk_csv_path, risk_rows)
    write_text(
        log_path,
        "\n".join([f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] {line}" for line in log_lines]) + "\n",
    )
    write_json(
        STATE_ROOT / "current_enriched.json",
        {
            "run_stamp": RUN_STAMP,
            "enriched_path": str(enriched_path),
            "risk_csv_path": str(risk_csv_path),
            "qualified_count": sum(1 for row in enriched_rows if row["qualification_passed"]),
            "record_count": len(enriched_rows),
        },
    )

    print(
        json.dumps(
            {
                "run_stamp": RUN_STAMP,
                "enriched_count": len(enriched_rows),
                "qualified_count": sum(1 for row in enriched_rows if row["qualification_passed"]),
                "enriched_path": str(enriched_path),
                "risk_csv_path": str(risk_csv_path),
                "log": str(log_path),
            },
            indent=2,
        )
    )
    write_stage_end("enrich", "success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

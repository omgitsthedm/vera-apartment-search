#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow_support import (
    SEARCH_MODE_BRIDGE,
    SEARCH_MODE_PERMANENT,
    canonical_address,
    canonical_text,
    ensure_dir,
    first_present,
    infer_borough,
    normalize_borough,
    parse_bool,
    parse_float,
    parse_string_list,
    read_json,
    relocated_path,
    stable_hash,
    state_path_or_latest,
    utc_now_iso,
    utc_stamp,
    write_csv,
    write_json,
    write_text,
)

from config.paths import VERA_ROOT as ROOT, CONFIG_DIR as CONFIG_ROOT, NORMALIZED_DIR as NORMALIZED_ROOT, LOG_DIR as LOG_ROOT, LEGACY_STATE_DIR as STATE_ROOT
from config.stage_tracker import write_stage_start, write_stage_end

RUN_STAMP = utc_stamp()
PARSER_VERSION = "2026-03-25a"

OWNER_CUES = {
    "by owner",
    "owner direct",
    "private landlord",
    "no broker",
    "small building",
    "walk-up",
}
MANAGEMENT_CUES = {
    "managed by",
    "leasing office",
    "online portal",
    "luxury building",
    "portfolio",
    "application through leasing office",
}

# Fee detection patterns — applied to canonical_text (lowercase, abbreviated)
NO_FEE_CUES = {
    "no fee",
    "no broker fee",
    "no broker's fee",
    "no brokers fee",
    "fee paid by owner",
    "owner pays fee",
    "owner pays broker",
    "fee-free",
    "zero fee",
    "0 fee",
    "no application fee",
}
BROKER_FEE_CUES = {
    "broker fee",
    "broker's fee",
    "brokers fee",
    "one month fee",
    "1 month fee",
    "15% fee",
    "12% fee",
    "fee will apply",
    "fee applies",
    "agent fee",
    "commission",
}


def cheap_filter_status(listing: dict[str, Any], preferences: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    allowed_neighborhoods = {canonical_text(item) for item in preferences.get("neighborhoods", [])}
    neighborhood = canonical_text(listing.get("neighborhood"))
    rent = listing.get("rent")
    max_rent = preferences.get("max_rent")
    beds = listing.get("beds")

    if allowed_neighborhoods and neighborhood not in allowed_neighborhoods:
        failures.append("outside target neighborhoods")
    if rent is None or (max_rent is not None and rent > max_rent):
        failures.append("above max rent or rent missing")
    if beds not in (0, 0.0, 1, 1.0):
        failures.append("not studio or 1br")
    if listing.get("room_share_flag"):
        failures.append("room-share signal")
    if listing.get("sublet_flag") and listing.get("search_mode") != SEARCH_MODE_BRIDGE:
        failures.append("sublet-only signal")

    return len(failures) == 0, failures


def load_raw_manifest() -> dict[str, Any]:
    manifest_path = STATE_ROOT / "current_raw_snapshots.json"
    manifest = read_json(manifest_path)
    if not manifest:
        raise FileNotFoundError(f"Missing raw manifest: {manifest_path}")
    return manifest


def source_listing_id(source_name: str, record: dict[str, Any]) -> str:
    return str(
        first_present(
            record,
            "listing_id",
            "id",
            "marketplace_id",
            "zpid",
            "source_listing_id",
        )
        or f"{source_name}-{stable_hash(first_present(record, 'url', 'listingUrl'), first_present(record, 'address', 'map_address', 'streetAddress'), first_present(record, 'price', 'rent'))}"
    )


def infer_neighborhood(record: dict[str, Any], description: str, preferences: dict[str, Any]) -> str | None:
    direct = first_present(record, "neighborhood", "area", "neighborhood_hint")
    if direct:
        return str(direct)
    lowered = canonical_text(description)
    for neighborhood in preferences.get("neighborhoods", []):
        if canonical_text(neighborhood) in lowered:
            return neighborhood
    return None


def infer_unit_type(beds: float | None) -> str | None:
    if beds is None:
        return None
    if beds == 0:
        return "studio"
    if beds == 1:
        return "1 bedroom"
    return f"{int(beds)} bedroom"


def infer_beds_from_text(text: str) -> float | None:
    lowered = canonical_text(text)
    if "studio" in lowered:
        return 0.0
    if re.search(r"\b1\s*(?:br|bed|bedroom)\b", lowered):
        return 1.0
    if re.search(r"\bone\s*(?:bed|bedroom)\b", lowered):
        return 1.0
    return None


def _source_catalog_lookup() -> dict[str, dict[str, Any]]:
    """Build a lookup from source_name to source catalog entry."""
    catalog = read_json(CONFIG_ROOT / "source_catalog.json", default={"sources": []})
    return {s["source_name"]: s for s in catalog.get("sources", []) if s.get("source_name")}


_SOURCE_CATALOG: dict[str, dict[str, Any]] | None = None


def source_catalog() -> dict[str, dict[str, Any]]:
    global _SOURCE_CATALOG
    if _SOURCE_CATALOG is None:
        _SOURCE_CATALOG = _source_catalog_lookup()
    return _SOURCE_CATALOG


def normalize_record(source_name: str, record: dict[str, Any], captured_at: str, preferences: dict[str, Any], history: dict[str, Any]) -> dict[str, Any]:
    title = str(first_present(record, "title", "headline") or "").strip()
    description = str(first_present(record, "description", "body") or "").strip()
    combined_text = f"{title} {description}".strip()

    address_raw = first_present(record, "address", "map_address", "streetAddress", "address_text")
    address_normalized = canonical_address(address_raw)
    rent = parse_float(first_present(record, "price", "rent"))
    beds = parse_float(first_present(record, "beds", "bedrooms"))
    baths = parse_float(first_present(record, "baths", "bathrooms"))
    square_feet = parse_float(first_present(record, "square_feet", "sqft"))
    contact_phone = first_present(record, "contact_phone", "phone", "contactPhone")
    contact_email = first_present(record, "contact_email", "email", "contactEmail")
    contact_name = first_present(record, "contact_name", "contactName")
    broker_name = first_present(record, "broker_name", "brokerName")

    amenity_list = parse_string_list(first_present(record, "amenities"))
    image_urls = parse_string_list(first_present(record, "image_urls", "photos"))
    image_count = int(parse_float(first_present(record, "image_count")) or len(image_urls))
    posted_at = str(first_present(record, "posted_at") or captured_at)

    if beds is None:
        beds = infer_beds_from_text(combined_text)

    lower_blob = canonical_text(combined_text)
    by_owner_signal = any(cue in lower_blob for cue in OWNER_CUES)
    management_signal = any(cue in lower_blob for cue in MANAGEMENT_CUES) or bool(broker_name)
    room_share_flag = "roommate" in lower_blob or "shared apartment" in lower_blob or "room available" in lower_blob
    sublet_flag = parse_bool(first_present(record, "sublet_flag")) or "sublet" in lower_blob
    furnished_flag = "furnished" in lower_blob

    # --- Borough inference and normalization ---
    # Sources like StreetEasy omit borough; others use non-standard names.
    # Resolve from neighborhood, then from ZIP, then normalize whatever we have.
    raw_borough = first_present(record, "borough")
    zip_code = first_present(record, "zip", "postal_code")
    neighborhood = infer_neighborhood(record, combined_text, preferences)

    # Step 1: Normalize the raw borough (handles "New York" → "Manhattan", etc.)
    resolved_borough = normalize_borough(raw_borough)

    # Step 2: If still None, infer from neighborhood
    if not resolved_borough and neighborhood:
        resolved_borough = infer_borough(neighborhood, zip_code)

    # Step 3: If still None, try ZIP prefix
    if not resolved_borough and zip_code:
        resolved_borough = infer_borough(None, zip_code)

    # Convert to display form (capitalize)
    borough_display = resolved_borough.title() if resolved_borough else None
    borough_inferred = resolved_borough is not None and not normalize_borough(raw_borough)

    listing_uid = f"listing-{stable_hash(source_name, source_listing_id(source_name, record), first_present(record, 'url', 'listingUrl'))}"
    prior = history.get(listing_uid, {})
    first_seen_at = prior.get("first_seen_at", captured_at)
    last_seen_at = captured_at
    history[listing_uid] = {
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "source_url": str(first_present(record, "url", "listingUrl") or ""),
    }

    laundry = parse_bool(first_present(record, "laundry")) or ("laundry" in lower_blob)
    dishwasher = parse_bool(first_present(record, "dishwasher")) or ("dishwasher" in lower_blob)

    # Fee status inference: prefer explicit source field, then mine description
    raw_fee_status = first_present(record, "fee_status")
    if raw_fee_status and raw_fee_status not in ("unknown", ""):
        fee_status = str(raw_fee_status)
    elif any(cue in lower_blob for cue in NO_FEE_CUES):
        fee_status = "no fee"
    elif any(cue in lower_blob for cue in BROKER_FEE_CUES):
        fee_status = "fee"
    else:
        fee_status = "unknown"

    # Source catalog metadata
    catalog_entry = source_catalog().get(source_name, {})
    record_search_mode = str(record.get("source_search_mode") or catalog_entry.get("search_mode") or "permanent")
    if record_search_mode == "bridge":
        search_mode = SEARCH_MODE_BRIDGE
    else:
        search_mode = SEARCH_MODE_PERMANENT
    source_tier = str(catalog_entry.get("source_tier", "primary"))
    source_status = str(catalog_entry.get("status", "live"))

    # Source-specific flags
    lease_takeover = parse_bool(first_present(record, "lease_takeover")) or False
    official_program_source = parse_bool(first_present(record, "official_program_source")) or False
    curated_source = parse_bool(first_present(record, "curated_source")) or False

    normalized = {
        "listing_uid": listing_uid,
        "source_name": source_name,
        "source_listing_id": source_listing_id(source_name, record),
        "source_url": str(first_present(record, "url", "listingUrl") or ""),
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "scraped_at": captured_at,
        "title": title,
        "full_description": description,
        "address_raw": address_raw,
        "address_normalized": address_normalized,
        "address_confidence": "high" if address_raw and address_normalized else "low",
        "neighborhood": neighborhood,
        "borough": borough_display,
        "borough_raw": str(raw_borough) if raw_borough else None,
        "borough_inferred": borough_inferred,
        "zip": zip_code,
        "latitude": parse_float(first_present(record, "latitude", "lat")),
        "longitude": parse_float(first_present(record, "longitude", "lng", "lon")),
        "rent": rent,
        "beds": beds,
        "baths": baths,
        "square_feet": square_feet,
        "unit_type": infer_unit_type(beds),
        "fee_status": fee_status,
        "broker_name": broker_name,
        "owner_name": None,
        "contact_name": contact_name,
        "contact_phone": contact_phone,
        "contact_email": contact_email,
        "amenities": amenity_list,
        "pet_policy": first_present(record, "pet_policy"),
        "laundry": laundry,
        "dishwasher": dishwasher,
        "furnished_flag": furnished_flag,
        "sublet_flag": bool(sublet_flag),
        "room_share_flag": bool(room_share_flag),
        "by_owner_signal": by_owner_signal,
        "management_company_signal": management_signal,
        "likely_independent_landlord_score": None,
        "duplicate_cluster_id": None,
        "verification_status": "pending",
        "rent_stabilized_signal": "unclear",
        "hpd_risk_score": None,
        "dob_risk_score": None,
        "court_signal": None,
        "overall_score": None,
        "recommendation": None,
        "analyst_notes": "Normalized from source-specific raw data.",
        "image_count": image_count,
        "search_mode": search_mode,
        "source_tier": source_tier,
        "source_status": source_status,
        "lease_takeover": lease_takeover,
        "official_program_source": official_program_source,
        "curated_source": curated_source,
        "parser_version": PARSER_VERSION,
        "raw_payload_source": source_name,
        "raw_snapshot_path": str(first_present(record, "_snapshot_path") or ""),
        "raw_record_index": first_present(record, "_record_index"),
    }
    cheap_passed, cheap_failures = cheap_filter_status(normalized, preferences)
    normalized["cheap_filter_passed"] = cheap_passed
    normalized["cheap_filter_failures"] = cheap_failures
    return normalized


def main() -> int:
    write_stage_start("normalize")
    try:
        return _main_impl()
    except Exception as e:
        write_stage_end("normalize", "failed", errors=[str(e)])
        raise


def _main_impl() -> int:
    ensure_dir(NORMALIZED_ROOT)
    ensure_dir(LOG_ROOT)
    ensure_dir(STATE_ROOT)

    manifest = load_raw_manifest()
    preferences = read_json(CONFIG_ROOT / "user_preferences.json", default={})
    history_path = STATE_ROOT / "listing_history.json"
    history = read_json(history_path, default={})
    normalized_rows: list[dict[str, Any]] = []
    parse_failed_rows: list[dict[str, Any]] = []
    log_lines: list[str] = []
    records_in = 0

    for source in manifest.get("sources", []):
        if source.get("status") != "ok":
            continue
        source_name = source.get("source_name", "unknown")
        snapshot_path = relocated_path(source.get("snapshot_path"), ROOT / "raw" / source_name)
        if not snapshot_path:
            log_lines.append(f"{source_name}: missing snapshot path {source.get('snapshot_path')}")
            parse_failed_rows.append(
                {
                    "source_name": source_name,
                    "snapshot_path": source.get("snapshot_path"),
                    "parser_version": PARSER_VERSION,
                    "error": "snapshot_not_found",
                }
            )
            continue

        snapshot = read_json(snapshot_path, default={})
        captured_at = str(snapshot.get("captured_at") or utc_now_iso())
        records = snapshot.get("records", [])
        source_name = snapshot.get("source_name", source_name)
        records_in += len(records)
        normalized_count = 0
        for index, record in enumerate(records):
            try:
                record_with_meta = {
                    **record,
                    "_snapshot_path": str(snapshot_path),
                    "_record_index": index,
                }
                normalized_rows.append(normalize_record(source_name, record_with_meta, captured_at, preferences, history))
                normalized_count += 1
            except Exception as exc:  # noqa: BLE001
                parse_failed_rows.append(
                    {
                        "source_name": source_name,
                        "snapshot_path": str(snapshot_path),
                        "record_index": index,
                        "source_listing_id": source_listing_id(source_name, record),
                        "parser_version": PARSER_VERSION,
                        "error": str(exc),
                    }
                )
        log_lines.append(f"{source_name}: normalized {normalized_count} records")

    normalized_path = NORMALIZED_ROOT / f"normalized_listings_{RUN_STAMP}.json"
    normalized_csv_path = NORMALIZED_ROOT / f"normalized_listings_{RUN_STAMP}.csv"
    parse_failed_path = NORMALIZED_ROOT / f"parse_failed_{RUN_STAMP}.json"
    write_json(normalized_path, normalized_rows)
    write_json(parse_failed_path, parse_failed_rows)
    write_csv(
        normalized_csv_path,
        normalized_rows,
        fieldnames=[
            "listing_uid",
            "source_name",
            "source_listing_id",
            "source_url",
            "title",
            "address_raw",
            "address_normalized",
            "neighborhood",
            "borough",
            "zip",
            "rent",
            "beds",
            "baths",
            "unit_type",
            "fee_status",
            "contact_name",
            "contact_phone",
            "contact_email",
            "parser_version",
            "cheap_filter_passed",
            "cheap_filter_failures",
            "by_owner_signal",
            "management_company_signal",
            "room_share_flag",
            "sublet_flag",
        ],
    )
    write_json(history_path, history)
    write_json(
        STATE_ROOT / "current_normalized.json",
        {
            "run_stamp": RUN_STAMP,
            "normalized_path": str(normalized_path),
            "normalized_csv_path": str(normalized_csv_path),
            "parse_failed_path": str(parse_failed_path),
            "record_count": len(normalized_rows),
            "parse_failed_count": len(parse_failed_rows),
        },
    )

    log_path = LOG_ROOT / f"normalize_{RUN_STAMP}.log"
    log_header = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    write_text(log_path, "\n".join([f"[{log_header}] {line}" for line in log_lines]) + "\n")

    print(
        json.dumps(
            {
                "run_stamp": RUN_STAMP,
                "normalized_count": len(normalized_rows),
                "normalized_path": str(normalized_path),
                "normalized_csv_path": str(normalized_csv_path),
                "parse_failed_path": str(parse_failed_path),
                "parse_failed_count": len(parse_failed_rows),
                "log": str(log_path),
            },
            indent=2,
        )
    )
    write_stage_end("normalize", "success", records_in=records_in, records_out=len(normalized_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

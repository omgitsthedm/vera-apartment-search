#!/usr/bin/env python3
from __future__ import annotations

import json
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.paths import (VERA_ROOT as ROOT, DEDUPED_DIR as DEDUPED_ROOT, LOG_DIR as LOG_ROOT,
    REFERENCE_DIR as REFERENCE_ROOT, LEGACY_STATE_DIR as STATE_ROOT)

from workflow_support import (
    borough_code,
    borough_name,
    building_address,
    canonical_text,
    ensure_dir,
    infer_borough,
    latest_file,
    normalize_borough,
    read_json,
    state_path_or_latest,
    utc_now_iso,
    utc_stamp,
    write_json,
    write_text,
)

RUN_STAMP = utc_stamp()
LOOKBACK_START = (datetime.now(timezone.utc) - timedelta(days=365 * 3)).strftime("%Y-%m-%dT00:00:00")
CACHE_TTL_HOURS = 24 * 7
PARSER_VERSION = "2026-03-25a"

GEOSEARCH_URL = "https://geosearch.planninglabs.nyc/v2/search"
REQUEST_HEADERS = {
    "User-Agent": "VERA-ApartmentSearch/2.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

DATASETS = {
    "buildings": "https://data.cityofnewyork.us/resource/kj4p-ruqc.json",
    "complaints": "https://data.cityofnewyork.us/resource/ygpa-z7cr.json",
    "violations": "https://data.cityofnewyork.us/resource/wvxf-dwi5.json",
    "registrations": "https://data.cityofnewyork.us/resource/tesw-yqqr.json",
    "litigation": "https://data.cityofnewyork.us/resource/59kj-x8nc.json",
    "complaints_311": "https://data.cityofnewyork.us/resource/erm2-nwe9.json",
}


def load_deduped_rows() -> list[dict[str, Any]]:
    state = read_json(STATE_ROOT / "current_deduped.json", default={})
    path = state_path_or_latest(state.get("deduped_path"), DEDUPED_ROOT, "deduped_listings_*.json")
    if not path:
        path = latest_file(DEDUPED_ROOT, "deduped_listings_*.json")
    if not path:
        raise FileNotFoundError("No deduped dataset found")
    return read_json(path, default=[])


def read_cache() -> dict[str, Any]:
    return read_json(REFERENCE_ROOT / "building_intel_cache.json", default={}) or {}


def write_cache(cache: dict[str, Any]) -> None:
    write_json(REFERENCE_ROOT / "building_intel_cache.json", cache)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def cache_is_fresh(entry: dict[str, Any]) -> bool:
    refreshed_at = parse_iso(entry.get("lookup_refreshed_at"))
    if not refreshed_at:
        return False
    return refreshed_at >= datetime.now(timezone.utc) - timedelta(hours=CACHE_TTL_HOURS)


def read_json_url(url: str, timeout: int = 30) -> Any:
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except Exception as exc:  # noqa: BLE001
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        insecure_context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=insecure_context) as response:
            return json.load(response)


def socrata_request(url: str, params: dict[str, str]) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return read_json_url(f"{url}?{query}")


def count_query(url: str, where_clause: str) -> int:
    rows = socrata_request(url, {"$select": "count(*)", "$where": where_clause})
    if not rows:
        return 0
    return int(rows[0].get("count", 0))


def first_row_query(url: str, select_clause: str, where_clause: str) -> dict[str, Any] | None:
    rows = socrata_request(url, {"$select": select_clause, "$where": where_clause, "$limit": "1"})
    return rows[0] if rows else None


def bbl_parts(bbl: str | None) -> tuple[str | None, str | None, str | None]:
    text = str(bbl or "").strip()
    if len(text) != 10 or not text.isdigit():
        return None, None, None
    return text[:1], text[1:6].lstrip("0") or "0", text[6:].lstrip("0") or "0"


def borough_text_from_id(boro_id: str | None) -> str | None:
    if not boro_id:
        return None
    mapping = {
        "1": "MANHATTAN",
        "2": "BRONX",
        "3": "BROOKLYN",
        "4": "QUEENS",
        "5": "STATEN ISLAND",
    }
    return mapping.get(str(boro_id))


def build_block_lot_where(block: str | None, lot: str | None, borough_text: str | None) -> str | None:
    if not block or not lot or not borough_text:
        return None
    return f"block='{block}' AND lot='{lot}' AND boro='{borough_text}'"


def geosearch_lookup(listing: dict[str, Any]) -> dict[str, Any]:
    address = listing.get("address_normalized") or listing.get("address_raw")
    neighborhood = listing.get("neighborhood")
    borough = listing.get("borough") or infer_borough(neighborhood, listing.get("zip"))
    query_parts = [part for part in [address, neighborhood, borough, "New York NY"] if part]
    query_text = ", ".join(str(part) for part in query_parts)
    if not query_text:
        return {
            "query_text": "",
            "lookup_status": "insufficient_address",
        }

    query = urllib.parse.urlencode({"text": query_text, "size": "5"})
    payload = read_json_url(f"{GEOSEARCH_URL}?{query}")
    features = payload.get("features") or []
    if not features:
        return {
            "query_text": query_text,
            "lookup_status": "no_match",
        }

    top = features[0]
    props = top.get("properties") or {}
    addendum = ((props.get("addendum") or {}).get("pad") or {})
    coords = ((top.get("geometry") or {}).get("coordinates") or [None, None])
    return {
        "query_text": query_text,
        "lookup_status": "matched",
        "match_confidence": props.get("confidence"),
        "match_type": props.get("match_type"),
        "resolved_label": props.get("label"),
        "resolved_name": props.get("name"),
        "resolved_street": props.get("street"),
        "resolved_housenumber": props.get("housenumber"),
        "resolved_postalcode": props.get("postalcode"),
        "resolved_borough": props.get("borough"),
        "resolved_neighborhood": props.get("neighbourhood"),
        "latitude": coords[1] if len(coords) > 1 else None,
        "longitude": coords[0] if coords else None,
        "bbl": addendum.get("bbl"),
        "bin": addendum.get("bin"),
        "pad_version": addendum.get("version"),
    }


def address_where_clauses(geo: dict[str, Any], listing: dict[str, Any]) -> dict[str, str | None]:
    resolved_borough = geo.get("resolved_borough") or borough_name(
        normalize_borough(listing.get("borough")) or infer_borough(listing.get("neighborhood"), listing.get("zip"))
    )
    housenumber = str(geo.get("resolved_housenumber") or "").strip()
    street = str(geo.get("resolved_street") or "").strip()
    if resolved_borough:
        resolved_borough = str(resolved_borough).upper()

    address_where = None
    complaint_where = None
    if housenumber and street and resolved_borough:
        address_where = (
            f"housenumber='{housenumber}' AND streetname='{street}' AND boro='{resolved_borough}'"
        )
        complaint_where = (
            f"house_number='{housenumber}' AND street_name='{street}' AND borough='{resolved_borough}'"
        )
    return {
        "address_where": address_where,
        "complaint_where": complaint_where,
        "resolved_borough": resolved_borough,
    }


def live_reference_from_sources(listing: dict[str, Any], geo: dict[str, Any]) -> dict[str, Any]:
    bbl = str(geo.get("bbl") or "").strip()
    bin_value = str(geo.get("bin") or "").strip()
    borough_id, block, lot = bbl_parts(bbl)
    borough_text = borough_text_from_id(borough_id)
    where_map = address_where_clauses(geo, listing)
    address_where = where_map["address_where"]
    complaint_where = where_map["complaint_where"]

    if bbl and borough_text and block and lot:
        building_where = build_block_lot_where(block, lot, borough_text)
    else:
        building_where = address_where

    building_row = None
    if building_where:
        building_row = first_row_query(
            DATASETS["buildings"],
            "buildingid,registrationid,boro,housenumber,streetname,block,lot",
            building_where,
        )

    building_id = str((building_row or {}).get("buildingid") or "").strip()

    registration_where = None
    if bin_value:
        registration_where = f"bin='{bin_value}'"
    elif building_where:
        registration_where = building_where

    registration_row = None
    if registration_where:
        registration_rows = socrata_request(
            DATASETS["registrations"],
            {
                "$select": "registrationid,lastregistrationdate,zip,bin",
                "$where": registration_where,
                "$order": "lastregistrationdate DESC",
                "$limit": "1",
            },
        )
        registration_row = registration_rows[0] if registration_rows else None

    complaints_where = None
    if building_id:
        complaints_where = f"building_id='{building_id}' AND received_date >= '{LOOKBACK_START}'"
    elif complaint_where:
        complaints_where = f"{complaint_where} AND received_date >= '{LOOKBACK_START}'"

    complaint_count = count_query(DATASETS["complaints"], complaints_where) if complaints_where else 0

    violations_base = None
    if building_id:
        violations_base = f"buildingid='{building_id}'"
    elif building_where:
        violations_base = building_where

    total_violations = 0
    open_violations = 0
    serious_violations = 0
    serious_open_violations = 0
    if violations_base:
        total_violations = count_query(
            DATASETS["violations"],
            f"{violations_base} AND novissueddate >= '{LOOKBACK_START}'",
        )
        open_violations = count_query(
            DATASETS["violations"],
            f"{violations_base} AND currentstatus NOT LIKE '%CLOSED%' AND currentstatus NOT LIKE '%DISMISSED%'",
        )
        serious_violations = count_query(
            DATASETS["violations"],
            f"{violations_base} AND class='C' AND novissueddate >= '{LOOKBACK_START}'",
        )
        serious_open_violations = count_query(
            DATASETS["violations"],
            f"{violations_base} AND class='C' AND currentstatus NOT LIKE '%CLOSED%' AND currentstatus NOT LIKE '%DISMISSED%'",
        )

    litigation_where = None
    if bbl:
        litigation_where = f"bbl='{bbl}' AND caseopendate >= '{LOOKBACK_START}'"
    elif bin_value:
        litigation_where = f"bin='{bin_value}' AND caseopendate >= '{LOOKBACK_START}'"
    elif building_id:
        litigation_where = f"buildingid='{building_id}' AND caseopendate >= '{LOOKBACK_START}'"
    litigation_count = count_query(DATASETS["litigation"], litigation_where) if litigation_where else 0

    heat_count = 0
    bedbug_count = 0
    if bbl:
        heat_count = count_query(
            DATASETS["complaints_311"],
            f"bbl='{bbl}' AND complaint_type='HEAT/HOT WATER' AND created_date >= '{LOOKBACK_START}'",
        )
        bedbug_count = count_query(
            DATASETS["complaints_311"],
            f"bbl='{bbl}' AND lower(descriptor) LIKE '%bedbug%' AND created_date >= '{LOOKBACK_START}'",
        )

    lookup_status = "matched" if (building_row or registration_row or bbl or bin_value) else "no_match"
    notes = (
        "Building joined through NYC GeoSearch with BBL/BIN-first lookups. "
        "Building-health counts are from HPD and NYC Open Data; unit-level status remains unconfirmed."
    )

    return {
        "building_address": building_address(
            f"{geo.get('resolved_housenumber') or ''} {geo.get('resolved_street') or ''}".strip()
            or geo.get("resolved_name")
            or listing.get("address_normalized")
            or listing.get("address_raw")
        ),
        "lookup_status": lookup_status,
        "lookup_source": "nyc_geosearch_plus_open_data",
        "lookup_refreshed_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "bbl": bbl or None,
        "bin": bin_value or None,
        "buildingid": building_id or (building_row or {}).get("buildingid"),
        "registrationid": (registration_row or {}).get("registrationid") or (building_row or {}).get("registrationid"),
        "registration_signal": "registered" if (registration_row or {}).get("registrationid") or (building_row or {}).get("registrationid") else "not found",
        "lastregistrationdate": (registration_row or {}).get("lastregistrationdate"),
        "zip": (registration_row or {}).get("zip") or geo.get("resolved_postalcode") or listing.get("zip"),
        "borough_resolved": normalize_borough(geo.get("resolved_borough")) or normalize_borough(listing.get("borough")) or infer_borough(listing.get("neighborhood"), listing.get("zip")),
        "resolved_borough": geo.get("resolved_borough"),
        "resolved_neighborhood": geo.get("resolved_neighborhood"),
        "geosearch_query": geo.get("query_text"),
        "geosearch_match_confidence": geo.get("match_confidence"),
        "geosearch_match_type": geo.get("match_type"),
        "geosearch_label": geo.get("resolved_label"),
        "latitude": geo.get("latitude"),
        "longitude": geo.get("longitude"),
        "hpd_complaints_3y": complaint_count,
        "hpd_open_violations": open_violations,
        "hpd_total_violations_3y": total_violations,
        "serious_violations_3y": serious_violations,
        "serious_open_violations": serious_open_violations,
        "heat_hot_water_complaints_3y": heat_count,
        "bedbug_reports_3y": bedbug_count,
        "litigation_count_3y": litigation_count,
        "court_signal": (
            "no housing litigation found in the last 3 years"
            if litigation_count == 0
            else f"{litigation_count} housing-litigation record(s) found in the last 3 years"
        ),
        "notes": notes,
    }


def cache_key_for(reference: dict[str, Any]) -> str | None:
    if reference.get("bbl"):
        return f"bbl:{reference['bbl']}"
    if reference.get("bin"):
        return f"bin:{reference['bin']}"
    if reference.get("building_address"):
        return f"addr:{canonical_text(reference['building_address'])}"
    return None


def listing_cache_key(listing: dict[str, Any], geo: dict[str, Any]) -> str | None:
    if geo.get("bbl"):
        return f"bbl:{geo['bbl']}"
    if geo.get("bin"):
        return f"bin:{geo['bin']}"
    building_key = building_address(listing.get("address_normalized") or listing.get("address_raw"))
    if building_key:
        return f"addr:{canonical_text(building_key)}"
    return None


def should_refresh(listing: dict[str, Any]) -> tuple[bool, str]:
    if not (listing.get("cheap_filter_passed") or listing.get("qualification_passed")):
        return False, "cheap_filter_failed"
    if not (listing.get("address_normalized") or listing.get("address_raw")):
        return False, "missing_address"
    return True, "ok"


def refresh_record(listing: dict[str, Any], cache: dict[str, Any]) -> dict[str, Any]:
    should_run, reason = should_refresh(listing)
    if not should_run:
        return {
            "building_address": building_address(listing.get("address_normalized") or listing.get("address_raw")),
            "lookup_status": "skipped",
            "lookup_source": "nyc_geosearch_plus_open_data",
            "lookup_refreshed_at": utc_now_iso(),
            "parser_version": PARSER_VERSION,
            "notes": f"Skipped expensive building lookup: {reason}.",
        }

    geo = geosearch_lookup(listing)
    cache_key = listing_cache_key(listing, geo)
    if cache_key:
        cached = cache.get(cache_key)
        if isinstance(cached, dict) and cache_is_fresh(cached):
            return {**cached, "lookup_cache_status": "hit"}

    if geo.get("lookup_status") != "matched":
        reference = {
            "building_address": building_address(listing.get("address_normalized") or listing.get("address_raw")),
            "lookup_status": "no_match",
            "lookup_source": "nyc_geosearch_plus_open_data",
            "lookup_refreshed_at": utc_now_iso(),
            "parser_version": PARSER_VERSION,
            "geosearch_query": geo.get("query_text"),
            "notes": "GeoSearch could not confidently resolve the listing address.",
        }
    else:
        reference = live_reference_from_sources(listing, geo)

    key = cache_key_for(reference) or cache_key
    if key:
        cache[key] = reference
    return reference


def main() -> int:
    ensure_dir(LOG_ROOT)
    ensure_dir(REFERENCE_ROOT)
    ensure_dir(STATE_ROOT)

    deduped_rows = load_deduped_rows()
    cache = read_cache()

    refreshed_rows: list[dict[str, Any]] = []
    log_lines: list[str] = []
    seen_keys: set[str] = set()

    for row in deduped_rows:
        try:
            reference = refresh_record(row, cache)
            ref_key = cache_key_for(reference) or f"addr:{canonical_text(reference.get('building_address'))}"
            if ref_key in seen_keys:
                continue
            seen_keys.add(ref_key)
            refreshed_rows.append(reference)
            log_lines.append(
                f"{reference.get('building_address')}: status={reference.get('lookup_status')} "
                f"bbl={reference.get('bbl', 'n/a')} bin={reference.get('bin', 'n/a')} "
                f"heat={reference.get('heat_hot_water_complaints_3y', 'n/a')} "
                f"bedbug={reference.get('bedbug_reports_3y', 'n/a')} "
                f"serious_open={reference.get('serious_open_violations', 'n/a')}"
            )
        except Exception as exc:  # noqa: BLE001
            fallback_address = building_address(row.get("address_normalized") or row.get("address_raw"))
            refreshed_rows.append(
                {
                    "building_address": fallback_address,
                    "lookup_status": "error",
                    "lookup_source": "nyc_geosearch_plus_open_data",
                    "lookup_refreshed_at": utc_now_iso(),
                    "parser_version": PARSER_VERSION,
                    "notes": str(exc),
                }
            )
            log_lines.append(f"{fallback_address}: error={exc}")

    versioned_path = REFERENCE_ROOT / f"public_records_live_{RUN_STAMP}.json"
    current_path = REFERENCE_ROOT / "current_public_records_live.json"
    log_path = LOG_ROOT / f"refresh_public_records_{RUN_STAMP}.log"

    write_json(versioned_path, refreshed_rows)
    write_json(current_path, refreshed_rows)
    write_cache(cache)
    write_text(
        log_path,
        "\n".join(
            [f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] {line}" for line in log_lines]
        )
        + "\n",
    )
    write_json(
        STATE_ROOT / "current_public_records_refresh.json",
        {
            "run_stamp": RUN_STAMP,
            "lookback_start": LOOKBACK_START,
            "record_count": len(refreshed_rows),
            "matched_count": sum(1 for row in refreshed_rows if row.get("lookup_status") == "matched"),
            "live_reference_path": str(current_path),
            "versioned_path": str(versioned_path),
            "cache_path": str(REFERENCE_ROOT / "building_intel_cache.json"),
            "log_path": str(log_path),
        },
    )

    print(
        json.dumps(
            {
                "run_stamp": RUN_STAMP,
                "lookback_start": LOOKBACK_START,
                "address_count": len(refreshed_rows),
                "matched_count": sum(1 for row in refreshed_rows if row.get("lookup_status") == "matched"),
                "live_reference_path": str(current_path),
                "versioned_path": str(versioned_path),
                "cache_path": str(REFERENCE_ROOT / "building_intel_cache.json"),
                "log": str(log_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

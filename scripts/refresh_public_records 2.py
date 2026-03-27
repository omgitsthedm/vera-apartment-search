#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from workflow_support import (
    address_lookup_parts,
    borough_code,
    borough_name,
    building_address,
    canonical_text,
    ensure_dir,
    infer_borough,
    latest_file,
    normalize_borough,
    official_street_name,
    read_json,
    utc_now_iso,
    utc_stamp,
    write_json,
    write_text,
)

ROOT = Path(__file__).resolve().parents[1]
DEDUPED_ROOT = ROOT / "deduped"
LOG_ROOT = ROOT / "logs"
REFERENCE_ROOT = ROOT / "cache" / "reference_data"
STATE_ROOT = ROOT / "cache" / "state"

RUN_STAMP = utc_stamp()
LOOKBACK_START = (datetime.now(timezone.utc) - timedelta(days=365 * 3)).strftime("%Y-%m-%dT00:00:00")

DATASETS = {
    "buildings": "https://data.cityofnewyork.us/resource/kj4p-ruqc.json",
    "complaints": "https://data.cityofnewyork.us/resource/ygpa-z7cr.json",
    "violations": "https://data.cityofnewyork.us/resource/wvxf-dwi5.json",
    "registrations": "https://data.cityofnewyork.us/resource/tesw-yqqr.json",
    "litigation": "https://data.cityofnewyork.us/resource/59kj-x8nc.json",
}


def load_deduped_rows() -> list[dict[str, Any]]:
    state = read_json(STATE_ROOT / "current_deduped.json", default={})
    path = Path(state["deduped_path"]) if state.get("deduped_path") else latest_file(DEDUPED_ROOT, "deduped_listings_*.json")
    if not path:
        raise FileNotFoundError("No deduped dataset found")
    return read_json(path, default=[])


def socrata_request(url: str, params: dict[str, str]) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "VERA-ApartmentSearch/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def count_query(url: str, where_clause: str) -> int:
    rows = socrata_request(url, {"$select": "count(*)", "$where": where_clause})
    if not rows:
        return 0
    return int(rows[0].get("count", 0))


def first_row_query(url: str, select_clause: str, where_clause: str) -> dict[str, Any] | None:
    rows = socrata_request(url, {"$select": select_clause, "$where": where_clause, "$limit": "1"})
    return rows[0] if rows else None


def build_where(field_house: str, field_street: str, house_number: str, street_name: str, borough_field: str, borough_value: str) -> str:
    return f"{field_house}='{house_number}' AND {field_street}='{street_name}' AND {borough_field}='{borough_value}'"


def refresh_record(listing: dict[str, Any]) -> dict[str, Any]:
    house_number, _ = address_lookup_parts(listing.get("address_normalized") or listing.get("address_raw"))
    street_name = official_street_name(listing.get("address_normalized") or listing.get("address_raw"))
    building_key = building_address(listing.get("address_normalized") or listing.get("address_raw"))

    # Borough resolution: try direct value, then infer from neighborhood/ZIP
    raw_borough = listing.get("borough")
    resolved_borough = normalize_borough(raw_borough)
    if not resolved_borough:
        resolved_borough = infer_borough(listing.get("neighborhood"), listing.get("zip"))

    borough_text = borough_name(resolved_borough) if resolved_borough else borough_name(raw_borough)
    borough_id = borough_code(resolved_borough) if resolved_borough else borough_code(raw_borough)

    record = {
        "building_address": building_key,
        "borough": raw_borough,
        "borough_resolved": resolved_borough,
        "zip": listing.get("zip"),
        "lookup_house_number": house_number,
        "lookup_street_name": street_name,
        "lookup_status": "skipped",
        "lookup_source": "nyc_open_data",
        "lookup_refreshed_at": utc_now_iso(),
    }

    if not house_number or not street_name or not borough_text or not borough_id:
        record["lookup_status"] = "insufficient_address"
        missing = []
        if not house_number:
            missing.append("house number")
        if not street_name:
            missing.append("street name")
        if not borough_text:
            missing.append(f"borough (raw={raw_borough!r}, resolved={resolved_borough!r})")
        record["notes"] = f"Missing: {', '.join(missing)}. Address could not be normalized into an official lookup form."
        return record

    base_where = build_where("housenumber", "streetname", house_number, street_name, "boro", borough_text)
    complaints_where = build_where("house_number", "street_name", house_number, street_name, "borough", borough_text)
    litigation_where = build_where("housenumber", "streetname", house_number, street_name, "boroid", borough_id)

    building_row = first_row_query(
        DATASETS["buildings"],
        "buildingid,registrationid,boro,housenumber,streetname",
        base_where,
    )

    if not building_row:
        record["lookup_status"] = "no_match"
        record["notes"] = "No official HPD building row matched the normalized address."
        return record

    registration_row = first_row_query(
        DATASETS["registrations"],
        "max(lastregistrationdate) AS lastregistrationdate,max(registrationid) AS registrationid,max(zip) AS zip",
        base_where,
    )
    complaint_count = count_query(
        DATASETS["complaints"],
        f"{complaints_where} AND received_date >= '{LOOKBACK_START}'",
    )
    total_violations = count_query(
        DATASETS["violations"],
        f"{base_where} AND novissueddate >= '{LOOKBACK_START}'",
    )
    open_violations = count_query(
        DATASETS["violations"],
        f"{base_where} AND novissueddate >= '{LOOKBACK_START}' AND currentstatus NOT LIKE '%CLOSED%' AND currentstatus NOT LIKE '%DISMISSED%'",
    )
    litigation_count = count_query(
        DATASETS["litigation"],
        f"{litigation_where} AND caseopendate >= '{LOOKBACK_START}'",
    )

    registration_found = bool((registration_row or {}).get("registrationid") or building_row.get("registrationid"))
    record.update(
        {
            "lookup_status": "matched",
            "buildingid": building_row.get("buildingid"),
            "registrationid": (registration_row or {}).get("registrationid") or building_row.get("registrationid"),
            "registration_signal": "registered" if registration_found else "not found",
            "lastregistrationdate": (registration_row or {}).get("lastregistrationdate"),
            "zip": (registration_row or {}).get("zip") or listing.get("zip"),
            "hpd_complaints_3y": complaint_count,
            "hpd_open_violations": open_violations,
            "hpd_total_violations_3y": total_violations,
            "litigation_count_3y": litigation_count,
            "court_signal": "no housing litigation found in the last 3 years" if litigation_count == 0 else f"{litigation_count} housing-litigation record(s) found in the last 3 years",
            "notes": "Counts refreshed from official NYC HPD open datasets. Owner and stabilization fields may still rely on local reference inputs if not available from these endpoints.",
        }
    )
    return record


def main() -> int:
    ensure_dir(LOG_ROOT)
    ensure_dir(REFERENCE_ROOT)
    ensure_dir(STATE_ROOT)

    deduped_rows = load_deduped_rows()

    # Include listings that have a building address AND either a borough or a
    # neighborhood we can infer borough from. Previously, listings without a
    # direct borough value (e.g. from StreetEasy) were silently skipped.
    addressable = []
    for row in deduped_rows:
        bldg = building_address(row.get("address_normalized") or row.get("address_raw"))
        if not bldg:
            continue
        raw_borough = row.get("borough")
        resolved = normalize_borough(raw_borough) if raw_borough else None
        if not resolved:
            resolved = infer_borough(row.get("neighborhood"), row.get("zip"))
        if resolved:
            addressable.append(row)

    unique_rows: dict[str, dict[str, Any]] = {}
    for row in addressable:
        bldg = building_address(row.get("address_normalized") or row.get("address_raw"))
        raw_borough = row.get("borough")
        resolved = normalize_borough(raw_borough) if raw_borough else None
        if not resolved:
            resolved = infer_borough(row.get("neighborhood"), row.get("zip"))
        key = canonical_text(bldg) + "::" + (resolved or "")
        if key not in unique_rows:
            unique_rows[key] = row

    refreshed_rows: list[dict[str, Any]] = []
    log_lines: list[str] = []

    for row in unique_rows.values():
        try:
            refreshed = refresh_record(row)
            refreshed_rows.append(refreshed)
            log_lines.append(
                f"{refreshed.get('building_address')}: status={refreshed.get('lookup_status')} complaints_3y={refreshed.get('hpd_complaints_3y', 'n/a')} open_violations={refreshed.get('hpd_open_violations', 'n/a')} litigation_3y={refreshed.get('litigation_count_3y', 'n/a')}"
            )
        except Exception as exc:  # noqa: BLE001
            refreshed_rows.append(
                {
                    "building_address": building_address(row.get("address_normalized") or row.get("address_raw")),
                    "borough": row.get("borough"),
                    "lookup_status": "error",
                    "lookup_source": "nyc_open_data",
                    "lookup_refreshed_at": utc_now_iso(),
                    "notes": str(exc),
                }
            )
            log_lines.append(f"{building_address(row.get('address_normalized') or row.get('address_raw'))}: error={exc}")

    versioned_path = REFERENCE_ROOT / f"public_records_live_{RUN_STAMP}.json"
    current_path = REFERENCE_ROOT / "current_public_records_live.json"
    log_path = LOG_ROOT / f"refresh_public_records_{RUN_STAMP}.log"

    write_json(versioned_path, refreshed_rows)
    write_json(current_path, refreshed_rows)
    write_text(
        log_path,
        "\n".join([f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] {line}" for line in log_lines]) + "\n",
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
            "log_path": str(log_path),
        },
    )

    print(
        json.dumps(
            {
                "run_stamp": RUN_STAMP,
                "lookback_start": LOOKBACK_START,
                "address_count": len(unique_rows),
                "matched_count": sum(1 for row in refreshed_rows if row.get("lookup_status") == "matched"),
                "live_reference_path": str(current_path),
                "versioned_path": str(versioned_path),
                "log": str(log_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

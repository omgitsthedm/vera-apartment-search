#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.paths import (VERA_ROOT as ROOT, CONFIG_DIR as CONFIG_ROOT, LOG_DIR as LOG_ROOT,
    LEGACY_STATE_DIR as STATE_ROOT, REFERENCE_DIR as REFERENCE_ROOT, SCORED_DIR as SCORED_ROOT,
    ENRICHED_DIR as ENRICHED_ROOT, REPORT_DIR as REPORT_ROOT, EXPORT_DIR as EXPORT_ROOT,
    NORMALIZED_DIR as NORMALIZED_ROOT, DEDUPED_DIR as DEDUPED_ROOT, SNAPSHOT_DIR as SNAPSHOT_ROOT,
    SNAPSHOT_METADATA_DIR as METADATA_ROOT, STATE_DIR)
from config.stage_tracker import read_all_stage_states, read_latest_run, record_run_trend, read_run_trends
from config.source_reliability import compute_reliability_score, get_all_source_trends, success_rate_from_trends
from config.anomaly_detector import get_all_anomaly_reports
from config.source_recommendations import recommend_source_actions, recommend_run_actions, compute_reliability_breakdown
from config.listing_confidence import apply_forensic_deductions, compute_listing_confidence, summarize_confidence_distribution
from config.listing_explanations import generate_listing_explanations, format_why_this_listing
from workflow_support import ensure_dir, latest_file, read_csv_rows, read_json, state_path_or_latest, utc_now_iso, write_json

PUBLISH_STATE_PATH = ROOT / ".publish_state.json"
MAX_TREND_DISPLAY = 7

LATEST_SNAPSHOT_PATH = SNAPSHOT_ROOT / "latest_snapshot.json"
LKG_SNAPSHOT_PATH = SNAPSHOT_ROOT / "last_known_good_snapshot.json"
LATEST_ATTEMPT_PATH = METADATA_ROOT / "latest_attempt.json"
LAST_SUCCESS_PATH = METADATA_ROOT / "last_success.json"


def _platform_version() -> str:
    """Platform version from the repo-root VERSION file (see CHANGELOG.md)."""
    try:
        return (ROOT / "VERSION").read_text().strip()
    except OSError:
        return "unknown"


def relocated(path_like: str | None, fallback_dir: Path) -> Path | None:
    return state_path_or_latest(path_like, fallback_dir, "*")


def latest_path(directory: Path, pattern: str) -> Path | None:
    return latest_file(directory, pattern)


def parse_run_times(log_text: str) -> tuple[str | None, str | None]:
    start_match = re.search(r"\[(.*?)\] VERA (?:autonomous )?(?:hourly|daily|weekly) (?:run|cycle) starting", log_text)
    end_match = re.search(r"\[(.*?)\] VERA (?:autonomous )?(?:hourly|daily|weekly) (?:run|cycle) complete", log_text)
    return (
        start_match.group(1) if start_match else None,
        end_match.group(1) if end_match else None,
    )


def format_price(value: Any) -> str:
    try:
        return f"${int(float(value)):,}"
    except (TypeError, ValueError):
        return "unknown rent"


def recommendation_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"pursue": 0, "pursue cautiously": 0, "manual review": 0, "skip": 0}
    for record in records:
        rec = record.get("recommendation")
        if rec in counts:
            counts[rec] += 1
    return counts


def publish_state_label(publish_state: dict[str, Any]) -> str:
    result = publish_state.get("last_deploy_result")
    verified_at = publish_state.get("last_verified_at")
    if result == "success" and verified_at:
        return "deployed_and_verified"
    if result == "verification_failed":
        return "deployed_verification_failed"
    if result == "skipped":
        return "skipped_no_change"
    if result == "failed":
        return "deploy_failed"
    return "no_deploys_recorded"


def confidence_label(value: Any) -> str:
    return str(value or "unknown")


def load_current_paths() -> dict[str, Path | None]:
    current_scored = read_json(STATE_ROOT / "current_scored.json", default={})
    current_deduped = read_json(STATE_ROOT / "current_deduped.json", default={})
    current_enriched = read_json(STATE_ROOT / "current_enriched.json", default={})
    current_normalized = read_json(STATE_ROOT / "current_normalized.json", default={})
    current_public = read_json(STATE_ROOT / "current_public_records_refresh.json", default={})

    return {
        "scored_json": state_path_or_latest(current_scored.get("scored_json_path"), SCORED_ROOT, "scored_listings_*.json"),
        "duplicate_csv": state_path_or_latest(current_deduped.get("cluster_csv_path"), DEDUPED_ROOT, "duplicate_clusters_*.csv"),
        "deduped_json": state_path_or_latest(current_deduped.get("deduped_path"), DEDUPED_ROOT, "deduped_listings_*.json"),
        "enriched_json": state_path_or_latest(current_enriched.get("enriched_path"), ENRICHED_ROOT, "enriched_listings_*.json"),
        "normalized_json": state_path_or_latest(current_normalized.get("normalized_path"), NORMALIZED_ROOT, "normalized_listings_*.json"),
        "parse_failed_json": state_path_or_latest(current_normalized.get("parse_failed_path"), NORMALIZED_ROOT, "parse_failed_*.json"),
        "public_records_json": state_path_or_latest(current_public.get("live_reference_path"), REFERENCE_ROOT, "current_public_records_live.json"),
        "shortlist_report": latest_path(REPORT_ROOT / "shortlist", "daily_shortlist_*.md"),
        "daily_report": latest_path(REPORT_ROOT / "daily", "daily_new_listings_*.md"),
        "weekly_report": latest_path(REPORT_ROOT / "weekly", "weekly_market_summary_*.md"),
        "red_flags_report": latest_path(REPORT_ROOT / "weekly", "red_flag_building_report_*.md"),
        "duplicate_report": latest_path(REPORT_ROOT / "weekly", "duplicate_cluster_report_*.md"),
        "shortlist_csv": latest_path(EXPORT_ROOT, "shortlist_*.csv"),
        "scored_csv": latest_path(EXPORT_ROOT, "scored_inventory_*.csv"),
        "run_log": latest_path(LOG_ROOT, "run_hourly_*.log") or latest_path(LOG_ROOT, "run_daily_*.log") or latest_path(LOG_ROOT, "run_weekly_*.log"),
    }


def artifact_descriptor(source_path: Path | None, destination_name: str, label: str, kind: str) -> dict[str, Any] | None:
    if not source_path or not source_path.exists():
        return None
    return {
        "label": label,
        "kind": kind,
        "source_path": str(source_path),
        "destination_name": destination_name,
    }


def listing_sections(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "facts": {
            "monthly_rent": record.get("rent"),
            "unit_type": record.get("unit_type"),
            "address": record.get("address_normalized") or record.get("address_raw"),
            "fee_status": record.get("fee_status"),
            "estimated_move_in_cash": record.get("estimated_move_in_cash"),
            "bbl": record.get("bbl"),
            "bin": record.get("bin"),
            "contact_name": record.get("contact_name"),
            "contact_phone": record.get("contact_phone"),
            "contact_email": record.get("contact_email"),
        },
        "derived": {
            "likely_landlord_type": record.get("likely_landlord_type"),
            "official_rent_stabilized_list_hit": record.get("official_rent_stabilized_list_hit"),
            "rent_stabilized_signal": record.get("rent_stabilized_signal"),
            "possible_rent_control_candidate": record.get("possible_rent_control_candidate"),
            "review_out_reason_code": record.get("review_out_reason_code"),
            "state_bucket": record.get("state_bucket"),
        },
        "confidence": {
            "address_confidence": record.get("address_confidence"),
            "verification_confidence": record.get("verification_confidence"),
            "listing_authenticity_confidence": record.get("listing_authenticity_confidence"),
            "neighborhood_confidence": record.get("neighborhood_confidence"),
            "geosearch_match_confidence": record.get("geosearch_match_confidence"),
            "listing_confidence_score": record.get("listing_confidence_score"),
            "listing_confidence_band": record.get("listing_confidence_band"),
            "listing_confidence_breakdown": record.get("listing_confidence_breakdown"),
        },
        "narrative": {
            "why_it_made_the_cut": record.get("why_it_made_the_cut"),
            "review_out_reason": record.get("review_out_reason"),
            "analyst_notes": record.get("analyst_notes"),
            "score_explanation_lines": record.get("score_explanation_lines") or [],
            "what_to_verify_before_applying": record.get("what_to_verify_before_applying") or [],
            "why_this_listing": record.get("why_this_listing"),
            "trust_strengths": record.get("trust_strengths") or [],
            "trust_caveats": record.get("trust_caveats") or [],
        },
        "changes": {
            "change_badge": record.get("change_badge"),
            "change_detail": record.get("change_detail"),
        },
    }


def bucketized_payload(scored_records: list[dict[str, Any]], duplicate_rows: list[dict[str, Any]], parse_failed_rows: list[dict[str, Any]], history: dict[str, Any], source_health: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    # Price memory: recorded post-run by record_price_history.py, attached on
    # the next compose. Gives every listing its price path and honest
    # days-on-market (StreetEasy retired theirs; VERA keeps its own).
    # NOTE: STATE_ROOT here is cache/state (pipeline scratch); the durable
    # cross-run stores live in the engine's top-level state/ dir, where the
    # runners' STATE_DIR and record_price_history.py write.
    durable_state = STATE_ROOT.parents[1] / "state"
    price_store = read_json(durable_state / "price_history.json", default={})

    # Relist memory: per-address uid spans. A fresh uid at an address whose
    # previous uid went dark ≥2 days earlier, ≥21 days after the address
    # first advertised, is a reset days-on-market counter — Scam School
    # tell #13, now computed instead of merely taught.
    addr_store = read_json(durable_state / "address_history.json", default={})
    photo_flags = read_json(durable_state / "photo_clone_flags.json", default={})

    # The real subway universe (MTA GTFS static, derived weekly). When
    # present, every listing gets transit{} — station, ≈walk, true lines —
    # so the client stops leaning on its 95-station fallback table.
    gtfs_stations = read_json(durable_state / "transit_stations.json", default=[])
    import math as _math

    def _nearest_station(lat, lon):
        best, best_d = None, 1e12
        cos = _math.cos(lat * _math.pi / 180)
        for s in gtfs_stations:
            dy = (lat - s["lat"]) * 111320
            dx = (lon - s["lon"]) * 111320 * cos
            d = (dx * dx + dy * dy) ** 0.5
            if d < best_d:
                best, best_d = s, d
        return best, best_d

    # In-run forensics over the full (pre-sanitize) records. Only COUNTS and
    # uid references reach the feed; the contacts themselves never do.
    from datetime import date as _date
    phone_map: dict[str, set] = {}
    email_map: dict[str, set] = {}
    desc_map: dict[str, str] = {}
    photo_map: dict[str, str] = {}
    _addr_of = {}
    for _r in scored_records:
        _uid = _r.get("listing_uid") or ""
        _ak = " ".join(str(_r.get("address_normalized") or "").strip().lower().split())
        _addr_of[_uid] = _ak
        _ph = "".join(ch for ch in str(_r.get("contact_phone") or "") if ch.isdigit())[-10:]
        if len(_ph) == 10:
            phone_map.setdefault(_ph, set()).add(_uid)
        _em = str(_r.get("contact_email") or "").strip().lower()
        if "@" in _em:
            email_map.setdefault(_em, set()).add(_uid)

    shortlisted = []
    manual_review = []
    filtered_out = []
    new_rows = []
    for record in scored_records:
        # Compute listing confidence and trust explanations
        conf = compute_listing_confidence(record, source_health)
        record.update(conf)
        explanations = generate_listing_explanations(record)
        record["why_this_listing"] = format_why_this_listing(explanations)
        record["trust_strengths"] = explanations["strengths"]
        record["trust_caveats"] = explanations["caveats"]

        _uid2 = record.get("listing_uid") or ""
        _ak2 = _addr_of.get(_uid2, "")

        # relist detection against address memory
        spans = addr_store.get(_ak2) or []
        if _ak2 and len(spans) >= 2:
            try:
                mine = next((s for s in spans if s.get("uid") == _uid2), None)
                others = [s for s in spans if s.get("uid") != _uid2]
                if mine and others:
                    oldest_first = min(_date.fromisoformat(s["first"]) for s in spans)
                    my_first = _date.fromisoformat(mine["first"])
                    prior_last = max(_date.fromisoformat(s["last"]) for s in others)
                    my_rent = mine.get("rent")
                    rent_close = any(
                        s.get("rent") and my_rent and abs(s["rent"] - my_rent) / max(s["rent"], my_rent) <= 0.03
                        for s in others
                    )
                    if rent_close and (my_first - prior_last).days >= 2 and (my_first - oldest_first).days > 21:
                        record["relist_suspect"] = True
                    record["true_days_on_market"] = max(0, (_date.today() - oldest_first).days)
            except (ValueError, KeyError):
                pass

        # contact reuse (counts only — the contact itself never leaves)
        _reuse = 0
        _phn = "".join(ch for ch in str(record.get("contact_phone") or "") if ch.isdigit())[-10:]
        if len(_phn) == 10:
            _reuse = max(_reuse, len(phone_map.get(_phn, ())))
        _eml = str(record.get("contact_email") or "").strip().lower()
        if "@" in _eml:
            _reuse = max(_reuse, len(email_map.get(_eml, ())))
        if _reuse > 3:
            record["contact_reuse_count"] = _reuse

        # voucher welcome — EXPLICIT statements only, never inferred (fair-
        # housing value lives in the accuracy, not the coverage)
        _txt = (str(record.get("description") or "") + " " + str(record.get("body") or "") + " " + str(record.get("title") or "")).lower()
        if _txt and __import__("re").search(r"\b(vouchers?\s+(?:are\s+)?(?:welcome|accepted|ok)|section\s*8\s+(?:welcome|accepted|ok)|hasa\s+(?:ok|welcome|accepted)|cityfheps\s+(?:ok|welcome|accepted))\b", _txt):
            record["voucher_signal"] = True

        # template descriptions and hotlink-identical photos across addresses
        _body = "".join(ch for ch in str(record.get("description") or record.get("body") or "").lower() if ch.isalnum())[:400]
        if len(_body) >= 200:
            prev = desc_map.get(_body)
            if prev and _addr_of.get(prev) != _ak2:
                record["desc_clone_of"] = prev
            else:
                desc_map.setdefault(_body, _uid2)
        for _img in (record.get("image_urls") or [])[:1]:
            if isinstance(_img, str) and _img.startswith("https://"):
                prev_ak = photo_map.get(_img)
                if prev_ak is not None and prev_ak != _ak2:
                    record["photo_clone_suspect"] = True
                else:
                    photo_map.setdefault(_img, _ak2)

        if gtfs_stations and record.get("latitude") is not None and record.get("longitude") is not None:
            try:
                _st, _d = _nearest_station(float(record["latitude"]), float(record["longitude"]))
                if _st is not None and _d <= 2400:
                    record["transit"] = {
                        "station": _st["name"],
                        # straight-line × 1.3 street detour at 80 m/min — approximate by construction
                        "walk_mins": max(1, round(_d * 1.3 / 80)),
                        "lines": [ln for ln in _st["lines"] if not ln.endswith("X")][:6] or _st["lines"][:6],
                        "approx": True,
                    }
            except (TypeError, ValueError):
                pass

        # perceptual-hash clones (refresh_photo_hashes.py) join the hotlink check
        if photo_flags.get(_uid2):
            record["photo_clone_suspect"] = True

        # tells attached above — now let them count (approved 2026-08-03)
        apply_forensic_deductions(record)

        ph = price_store.get(record.get("listing_uid") or "")
        if ph and ph.get("points"):
            record["price_history"] = ph["points"][-12:]
            try:
                from datetime import date as _date
                first = _date.fromisoformat(ph["points"][0][0])
                record["days_seen"] = max(0, (_date.today() - first).days)
            except (ValueError, KeyError, IndexError):
                pass

        enriched = {**record, "sections": listing_sections(record)}
        if record.get("state_bucket") == "new":
            new_rows.append(enriched)
        if record.get("recommendation") in {"pursue", "pursue cautiously"}:
            shortlisted.append(enriched)
        elif record.get("recommendation") == "manual review":
            manual_review.append(enriched)
        else:
            filtered_out.append(enriched)

    duplicates = [
        row for row in duplicate_rows
        if int(float(row.get("member_count") or 0)) > 1
    ]

    current_listing_ids = {record.get("listing_uid") for record in scored_records if record.get("listing_uid")}
    archived = []
    for listing_uid, item in history.items():
        if listing_uid in current_listing_ids:
            continue
        archived.append(
            {
                "listing_uid": listing_uid,
                "last_seen_at": item.get("last_seen_at"),
                "source_url": item.get("source_url"),
                "state_bucket": "archived",
            }
        )

    return {
        "new": sorted(new_rows, key=lambda item: item.get("overall_score", 0), reverse=True),
        "duplicate": duplicates,
        # Best-first, like every other bucket. Ascending order meant any caller
        # taking a head slice got the worst rejects and never saw the near-misses.
        "filtered_out": sorted(filtered_out, key=lambda item: item.get("overall_score", 0), reverse=True),
        "needs_manual_review": sorted(manual_review, key=lambda item: item.get("overall_score", 0), reverse=True),
        "shortlisted": sorted(shortlisted, key=lambda item: item.get("overall_score", 0), reverse=True),
        "archived": sorted(archived, key=lambda item: item.get("last_seen_at") or "", reverse=True),
        "parse_failed": parse_failed_rows,
    }


def build_snapshot() -> tuple[dict[str, Any], bool]:
    ensure_dir(SNAPSHOT_ROOT)
    ensure_dir(METADATA_ROOT)

    paths = load_current_paths()
    source_catalog = read_json(CONFIG_ROOT / "source_catalog.json", default={"sources": []})
    raw_manifest = read_json(STATE_ROOT / "current_raw_snapshots.json", default={"sources": []})
    publish_state = read_json(PUBLISH_STATE_PATH, default={})
    history = read_json(STATE_ROOT / "listing_history.json", default={})

    failure_reason = None
    scored_records = []
    if paths["scored_json"] and paths["scored_json"].exists():
        scored_records = read_json(paths["scored_json"], default=[])
    else:
        failure_reason = "missing_scored_inventory"

    duplicate_rows = read_csv_rows(paths["duplicate_csv"]) if paths["duplicate_csv"] and paths["duplicate_csv"].exists() else []
    parse_failed_rows = read_json(paths["parse_failed_json"], default=[]) if paths["parse_failed_json"] and paths["parse_failed_json"].exists() else []
    public_records = read_json(paths["public_records_json"], default=[]) if paths["public_records_json"] and paths["public_records_json"].exists() else []

    run_log_text = paths["run_log"].read_text() if paths["run_log"] and paths["run_log"].exists() else ""
    last_run_started_at, last_run_finished_at = parse_run_times(run_log_text)

    enabled_sources = [source for source in source_catalog.get("sources", []) if source.get("enabled")]
    ok_sources = [source for source in raw_manifest.get("sources", []) if source.get("status") == "ok"]
    if not enabled_sources:
        failure_reason = failure_reason or "no_enabled_sources"
    if not ok_sources:
        failure_reason = failure_reason or "no_successful_source_snapshots"

    summary_counts = recommendation_counts(scored_records)
    matched_count = sum(1 for row in public_records if row.get("lookup_status") == "matched")
    address_count = len(public_records)
    records_seen = sum(int(source.get("record_count") or 0) for source in raw_manifest.get("sources", []))

    # bucketed_payload is called after source_health is built (see below)

    discovery_mode = "mixed"
    if enabled_sources and all(str(source.get("access_mode", "")).startswith("live") or source.get("access_mode") == "manual_review" for source in enabled_sources):
        discovery_mode = "live"
    elif enabled_sources and all(source.get("access_mode") == "sample_fixture" for source in enabled_sources):
        discovery_mode = "sample_fixture"

    stale = False
    if last_run_finished_at:
        try:
            last_run_dt = datetime.fromisoformat(last_run_finished_at.replace("Z", "+00:00"))
            stale = (datetime.now(timezone.utc) - last_run_dt).total_seconds() > 6 * 3600
        except ValueError:
            stale = False

    messages = [
        {
            "kind": "brief",
            "label": "VERA Brief",
            "text": (
                "VERA is operating as a bullshit filter for NYC rentals. "
                f"{summary_counts['pursue']} pursue, {summary_counts['pursue cautiously']} cautious, "
                f"{summary_counts['manual review']} manual review, {summary_counts['skip']} filtered out."
            ),
        },
        {
            "kind": "ops",
            "label": "Building Join",
            "text": f"Public-record join matched {matched_count} of {address_count} candidate buildings using BBL/BIN-first lookups where possible.",
        },
    ]
    if failure_reason:
        messages.append(
            {
                "kind": "warning",
                "label": "Snapshot Warning",
                "text": f"Latest snapshot build is degraded: {failure_reason}. The publisher should fall back to last-known-good.",
            }
        )
    if stale:
        messages.append(
            {
                "kind": "warning",
                "label": "Stale Data",
                "text": "The latest local run is older than the expected schedule window.",
            }
        )

    artifacts = [
        artifact_descriptor(paths["shortlist_report"], "latest-shortlist.md", "Latest shortlist report", "markdown"),
        artifact_descriptor(paths["shortlist_csv"], "latest-shortlist.csv", "Latest shortlist export", "csv"),
        artifact_descriptor(paths["daily_report"], "latest-daily-report.md", "Daily new listings report", "markdown"),
        artifact_descriptor(paths["weekly_report"], "latest-weekly-summary.md", "Weekly market summary", "markdown"),
        artifact_descriptor(paths["red_flags_report"], "latest-red-flags.md", "Red-flag building report", "markdown"),
        artifact_descriptor(paths["duplicate_report"], "latest-duplicate-clusters.md", "Duplicate cluster report", "markdown"),
        artifact_descriptor(paths["run_log"], "latest-run.log", "Latest VERA run log", "log"),
        artifact_descriptor(paths["scored_json"], "latest-scored-listings.json", "Scored inventory JSON", "json"),
        artifact_descriptor(paths["scored_csv"], "latest-scored-inventory.csv", "Scored inventory CSV", "csv"),
        artifact_descriptor(paths["public_records_json"], "current-public-records.json", "Current public-record matches", "json"),
    ]
    artifacts = [item for item in artifacts if item]

    # Stage timestamps and source health
    stage_states = read_all_stage_states()
    latest_run = read_latest_run()

    all_trends = get_all_source_trends()
    all_anomalies = get_all_anomaly_reports()
    catalog_by_name = {s.get("source_name"): s for s in source_catalog.get("sources", [])}

    source_health_list = []
    for source in raw_manifest.get("sources", []):
        sname = source.get("source_name", "")
        catalog_entry = catalog_by_name.get(sname, {})
        cadence = catalog_entry.get("cadence", "unknown")
        source_class = catalog_entry.get("source_class", "fallback")
        confidence = source.get("extraction_confidence")
        records_found = source.get("record_count", 0)
        # A source that was never contacted is not "broken". The old one-liner
        # classified every skipped entry as broken purely because a skip carries
        # no record_count — which labelled 9 deliberately-disabled sources as
        # failures and, far worse, left craigslist green while it went 229 -> 0.
        raw_status = source.get("status")
        skip_reason = str(source.get("reason") or "").lower()
        if raw_status == "skipped":
            status = "disabled" if "disab" in skip_reason or "not_feasible" in skip_reason else "not_scheduled"
        elif raw_status == "ok":
            # Healthy unless this run collapsed against its own recent history.
            prior = [t.get("records", 0) for t in all_trends.get(sname, [])[:-1] if t.get("status") == "ok"]
            baseline = (sum(prior) / len(prior)) if prior else 0
            if baseline >= 5 and records_found == 0:
                status = "failing"      # produced nothing where it reliably produced records
            elif baseline >= 20 and records_found < baseline * 0.4:
                status = "degraded"     # still returning, but a long way down
            else:
                status = "healthy"
        elif records_found > 0:
            status = "partial"
        else:
            status = "failing"

        trends = all_trends.get(sname, [])
        rate = success_rate_from_trends(trends)

        anomaly_report = all_anomalies.get(sname, {})
        anomaly_flag = anomaly_report.get("last_record_count") is not None and anomaly_report.get("trailing_7d_avg") is not None
        trailing_avg = anomaly_report.get("trailing_7d_avg")

        # Build human-readable anomaly reason
        anomaly_reason = None
        if trailing_avg and anomaly_report.get("last_record_count") is not None:
            last_count = anomaly_report["last_record_count"]
            if trailing_avg > 0:
                pct = round((1 - last_count / trailing_avg) * 100, 1)
                if pct >= 50:
                    anomaly_flag = True
                    anomaly_reason = f"records down {pct}% vs 7d avg ({last_count} vs {trailing_avg:.0f})"
                elif pct <= -100:
                    anomaly_flag = True
                    anomaly_reason = f"records up {abs(pct)}% vs 7d avg ({last_count} vs {trailing_avg:.0f})"
                else:
                    anomaly_flag = False

        reliability, freshness_raw, stability_raw = compute_reliability_score(
            confidence=confidence,
            success_rate=rate,
            last_success_at=source.get("fetched_at"),
            cadence=cadence,
            anomaly_flag=anomaly_flag,
            current_records=records_found,
            trailing_avg=trailing_avg,
        )

        breakdown = compute_reliability_breakdown(
            confidence=confidence,
            success_rate=rate,
            freshness_score=freshness_raw,
            anomaly_flag=anomaly_flag,
            stability_score=stability_raw,
        )

        sh = {
            "name": sname,
            "source_class": source_class,
            "cadence": cadence,
            "status": status,
            "records_found": records_found,
            "parser_version": source.get("parser_version", "unknown"),
            "confidence": confidence,
            "reliability_score": reliability,
            "reliability_breakdown": breakdown,
            "last_attempted_at": source.get("fetched_at"),
            "extraction_strategy": source.get("extraction_strategy"),
            "anomaly_flag": anomaly_flag,
            "anomaly_reason": anomaly_reason,
            "trend": [
                {
                    "run_id": t.get("run_id"),
                    "records": t.get("records_found"),
                    "status": t.get("status"),
                    "confidence": t.get("confidence"),
                }
                for t in trends[-MAX_TREND_DISPLAY:]
            ] if trends else [],
        }

        # Per-source action recommendations
        catalog_thresholds = catalog_entry.get("alert_thresholds", {})
        actions = recommend_source_actions(
            sh,
            confidence_threshold=catalog_thresholds.get("confidence_min", 0.6),
            drop_threshold_pct=catalog_thresholds.get("drop_threshold_pct", 50),
        )
        if actions:
            sh["recommended_actions"] = actions
        source_health_list.append(sh)

    # "active" now means sources the pipeline actually tries to fetch, so the
    # headline reads "5 of 10 scheduled sources healthy" instead of counting
    # nine switched-off sources as part of the fleet.
    SCHEDULED = ("healthy", "degraded", "partial", "failing")
    scheduled_list = [s for s in source_health_list if s["status"] in SCHEDULED]
    active_sources = len(scheduled_list)
    healthy_sources = sum(1 for s in source_health_list if s["status"] == "healthy")
    partial_sources = sum(1 for s in source_health_list if s["status"] in ("partial", "degraded"))
    # Keep the legacy key meaning "needs attention" — but only for sources that
    # were supposed to run. Disabled and not-scheduled no longer inflate it.
    broken_sources = sum(1 for s in source_health_list if s["status"] == "failing")
    disabled_sources = sum(1 for s in source_health_list if s["status"] in ("disabled", "not_scheduled"))

    # Build source_health dict for listing confidence computation
    source_health_data = {
        "active": active_sources,
        "healthy": healthy_sources,
        "partial": partial_sources,
        "broken": broken_sources,
        "disabled": disabled_sources,
        "sources": source_health_list,
    }

    # Bucket listings with listing confidence scored per-record
    bucketed = bucketized_payload(scored_records, duplicate_rows, parse_failed_rows, history, source_health=source_health_data)
    # No caps. The dashboard's `pool` is built from shortlist + reviewed_out, so
    # a [:10] here silently threw away 50 of 63 scored listings — and because
    # filtered_out is sorted worst-first, the ten it kept were the 1.2-6.3 junk
    # while every near-miss was discarded. Rejects carry their
    # review_out_reason_code, which is exactly what makes "why was this skipped"
    # answerable in the UI.
    shortlist = bucketed["shortlisted"]
    reviewed_out = (bucketed["filtered_out"] + bucketed["needs_manual_review"])
    risk_watch = sorted(
        [
            {
                "title": row.get("title"),
                "neighborhood": row.get("neighborhood"),
                "rent": row.get("rent"),
                "recommendation": row.get("recommendation"),
                "flag_summary": row.get("review_out_reason") or row.get("analyst_notes"),
            }
            for row in scored_records
            if row.get("recommendation") == "skip"
        ],
        key=lambda item: item.get("rent") or 10**9,
    )[:6]

    # Confidence distribution across all scored listings
    confidence_dist = summarize_confidence_distribution(scored_records)

    top_listing = shortlist[0] if shortlist else None
    hero_summary = (
        f"{summary_counts['pursue']} pursue, {summary_counts['pursue cautiously']} cautious, "
        f"{summary_counts['manual review']} manual review, {summary_counts['skip']} skip. "
        f"Best lead: {top_listing.get('title')} at {format_price(top_listing.get('rent'))}."
        if top_listing
        else "No shortlist listings in the current snapshot."
    )

    sources = []
    source_records = {item.get("source_name"): item for item in raw_manifest.get("sources", [])}
    for source in enabled_sources:
        merged = dict(source)
        merged.update(source_records.get(source.get("source_name"), {}))
        sources.append(merged)

    stats = [
        {"label": "Raw records discovered", "value": str(records_seen)},
        {"label": "Listings scored", "value": str(len(scored_records))},
        {"label": "Shortlist cards", "value": str(len(bucketed["shortlisted"]))},
        {"label": "Manual review", "value": str(len(bucketed["needs_manual_review"]))},
        {"label": "Filtered out", "value": str(len(bucketed["filtered_out"]))},
        {"label": "Duplicates", "value": str(len(bucketed["duplicate"]))},
        {"label": "Parse failed", "value": str(len(bucketed["parse_failed"]))},
        {"label": "Public-record matches", "value": f"{matched_count}/{address_count}"},
        {"label": "Verified by BBL/BIN", "value": str(sum(1 for row in scored_records if row.get("bbl") or row.get("bin")))},
        {"label": "Building cache entries", "value": str(len(read_json(REFERENCE_ROOT / "building_intel_cache.json", default={}) or {}))},
    ]

    snapshot_status = "success" if not failure_reason else "degraded"

    # Scheduled ride-time tables (MTA GTFS, derived weekly) — ~20KB that lets
    # the app quote the timetable instead of inventing commute minutes.
    transit_tables = read_json(ROOT / "state" / "transit_routes.json", default=None)

    payload = {
        "generated_at": utc_now_iso(),
        "transit_tables": transit_tables,
        "app": {
            "name": "NYC Apartment Search",
            "subtitle": "VERA Ops Terminal",
            "version": _platform_version(),
        },
        "snapshot": {
            "status": snapshot_status,
            "failure_reason": failure_reason,
            "stale": stale,
            "latest_snapshot_path": str(LATEST_SNAPSHOT_PATH),
            "last_known_good_snapshot_path": str(LKG_SNAPSHOT_PATH),
        },
        "vera": {
            "codename": "VERA",
            "full_name": "Verified Evaluation for Rental Analysis",
            "status": "healthy" if snapshot_status == "success" else "degraded",
            "status_note": (
                "Latest snapshot built successfully."
                if snapshot_status == "success"
                else f"Latest snapshot is degraded: {failure_reason}."
            ),
            "run_note": "Timestamp of the latest VERA local pipeline run.",
            "last_run_started_at": last_run_started_at,
            "last_run_finished_at": last_run_finished_at,
            "project_root": str(ROOT),
        },
        "publish": {
            "last_deployed_at": publish_state.get("last_deployed_at"),
            "last_deploy_result": publish_state.get("last_deploy_result"),
            "last_verified_at": publish_state.get("last_verified_at"),
            "last_deployed_hash": publish_state.get("last_deployed_hash"),
            "last_skip_reason": publish_state.get("last_skip_reason"),
            "publish_state_label": publish_state_label(publish_state),
        },
        "stages": {
            name: {
                "status": state.get("status"),
                "started_at": state.get("started_at"),
                "finished_at": state.get("finished_at"),
                "run_id": state.get("run_id"),
                "records_in": state.get("records_in"),
                "records_out": state.get("records_out"),
                "errors": state.get("errors", []),
                "blocked_reason": state.get("blocked_reason"),
                "publish_outcome": state.get("publish_outcome"),
            }
            for name, state in stage_states.items()
            if state
        },
        "run": {
            "run_id": latest_run.get("run_id"),
            "cadence": latest_run.get("cadence"),
            "status": latest_run.get("status"),
            "started_at": latest_run.get("started_at"),
            "finished_at": latest_run.get("finished_at"),
            "pipeline_status": latest_run.get("pipeline_status"),
            "publish_status": latest_run.get("publish_status"),
            "publish_blocked_reason": latest_run.get("publish_blocked_reason"),
        },
        "source_health": source_health_data,
        "listing_confidence": {
            "distribution": confidence_dist,
        },
        "recommendations": recommend_run_actions(
            source_health_data,
            {name: {"status": state.get("status"), "blocked_reason": state.get("blocked_reason")} for name, state in stage_states.items() if state},
            latest_run,
        ),
        "summary": {
            "hero_summary": hero_summary,
            "pursue_count": summary_counts["pursue"],
            "cautious_count": summary_counts["pursue cautiously"],
            "manual_review_count": summary_counts["manual review"],
            "skip_count": summary_counts["skip"],
        },
        "pipeline": {
            "discovery_mode": discovery_mode,
            "discovery_note": (
                "Static snapshot built from the latest local pipeline outputs."
                if snapshot_status == "success"
                else "Publisher should fall back to last-known-good because the latest snapshot is degraded."
            ),
            "last_attempted_at": utc_now_iso(),
            "last_successful_at": last_run_finished_at,
            "stage_counts": {
                "records_seen": records_seen,
                "scored": len(scored_records),
                "shortlisted": len(bucketed["shortlisted"]),
                "manual_review": len(bucketed["needs_manual_review"]),
                "filtered_out": len(bucketed["filtered_out"]),
                "parse_failed": len(bucketed["parse_failed"]),
            },
        },
        "messages": messages,
        "shortlist": shortlist,
        "reviewed_out": reviewed_out,
        "risk_watch": risk_watch,
        "sources": sources,
        "stats": stats,
        "artifacts": artifacts,
        "state_buckets": bucketed,
    }

    # Record run trend and attach history to payload
    scores = [s.get("reliability_score", 0) for s in source_health_list if s.get("reliability_score") is not None]
    avg_reliability = sum(scores) / len(scores) if scores else 0

    discover_state = stage_states.get("discover", {})
    try:
        record_run_trend(
            run_id=latest_run.get("run_id", "unknown"),
            records_discovered=discover_state.get("records_out", 0) if discover_state else 0,
            records_published=len(shortlist),
            healthy_sources=healthy_sources,
            active_sources=active_sources,
            avg_reliability=avg_reliability,
            pipeline_status=latest_run.get("pipeline_status", snapshot_status),
        )
    except Exception:
        pass

    payload["run_trends"] = read_run_trends()

    # Daily change tracking summary (from track_changes.py)
    daily_changes_dir = STATE_DIR / "daily_changes"
    if daily_changes_dir.exists():
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        today_changes = read_json(daily_changes_dir / f"changes_{today}.json", default={})
        if today_changes:
            payload["daily_changes"] = today_changes
            # Add change counts to summary
            change_counts = today_changes.get("counts", {})
            payload["summary"]["new_today"] = change_counts.get("new", 0)
            payload["summary"]["price_drops"] = change_counts.get("price_drop", 0)
            payload["summary"]["price_hikes"] = change_counts.get("price_hike", 0)
            payload["summary"]["back_again"] = change_counts.get("back", 0)
            payload["summary"]["gone"] = change_counts.get("gone", 0)

    success = snapshot_status == "success"
    return payload, success


def main() -> int:
    payload, success = build_snapshot()
    attempt = {
        "attempted_at": utc_now_iso(),
        "status": payload["snapshot"]["status"],
        "failure_reason": payload["snapshot"]["failure_reason"],
        "stale": payload["snapshot"]["stale"],
    }
    write_json(LATEST_ATTEMPT_PATH, attempt)
    write_json(LATEST_SNAPSHOT_PATH, payload)

    if success:
        write_json(LKG_SNAPSHOT_PATH, payload)
        write_json(
            LAST_SUCCESS_PATH,
            {
                "successful_at": utc_now_iso(),
                "last_run_finished_at": payload["vera"].get("last_run_finished_at"),
                "content_hash": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16],
            },
        )

    print(
        json.dumps(
            {
                "latest_snapshot_path": str(LATEST_SNAPSHOT_PATH),
                "last_known_good_snapshot_path": str(LKG_SNAPSHOT_PATH),
                "status": payload["snapshot"]["status"],
                "failure_reason": payload["snapshot"]["failure_reason"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

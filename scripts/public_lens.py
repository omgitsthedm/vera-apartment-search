#!/usr/bin/env python3
"""The public lens: snapshot -> the sanitized payload the world may read.

WHY THIS LIVES IN THE ENGINE REPO
---------------------------------
The privacy boundary belongs beside the engine data it protects. GitHub
Actions runs against this repository, so the scheduled sweep can apply this
single implementation before publishing the sanitized `feed` branch. The
Little Fight NYC application consumes that output through its first-party
`/vera/data/*` contract; it does not carry a second copy of the transformation
logic.

THE BOUNDARY
------------
Public: real addresses, rents, scores, ownership reads, HPD/DOB/litigation
counts. That is the product, and it is all public record.

Private: the owner's personal layer — contact details, analyst notes, the
manual watchlist — plus any editorial accusation sourced from a private
watchlist (neutralized to a factual phrase instead).

The public payload is a schema projection, not a copy of the hunt payload
with a few fields removed. New engine data is private by default until this
file deliberately admits it, and the independent audit checks every node of
the finished publication before the publisher can write it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parents[1]

# ── Public schema and sensitive-data guard ────────────────────────────
#
# This is deliberately a positive contract. `build_hunt_payload()` remains an
# owner-facing private lens, so it may retain new engine fields. The public
# lens below may only emit these named fields and named nested shapes.
PUBLIC_TOP_LEVEL_FIELDS = frozenset({
    "app", "daily_changes", "generated_at", "lens", "manual_review", "origin",
    "pool", "records_health", "run", "run_trends", "shortlist",
    "skip_insights", "source_health", "sources", "stages",
    "state_buckets", "summary", "transit_tables", "market_context", "vera",
})

PUBLIC_LISTING_FIELDS = frozenset({
    "address_confidence", "address_normalized", "address_raw", "ai_enriched",
    "ai_photo_probability", "ai_photo_suspect", "amenities", "baths", "bbl",
    "bedbug_reports_3y", "beds", "bin", "borough", "borough_inferred",
    "borough_raw", "broker_name", "building_key", "by_owner_signal",
    "change_badge", "change_detail", "cheap_filter_passed", "component_scores",
    "contact_reuse_count", "court_signal", "days_seen", "desc_clone_of",
    "dishwasher", "dob_risk_score", "duplicate_cluster_id", "duplicate_count",
    "estimated_move_in_cash", "fee_status", "first_seen_at", "furnished_flag",
    "heat_hot_water_complaints_3y", "hpd_open_violations", "hpd_risk_score", "illegal_demands",
    "image_count", "image_urls", "landlord_portfolio", "landlord_reason_summary",
    "last_seen_at", "latitude", "laundry", "lease_takeover",
    "likely_independent_landlord_score", "likely_landlord_type",
    "listing_authenticity_confidence", "listing_confidence_band",
    "listing_confidence_notes", "listing_confidence_score", "listing_type",
    "listing_uid", "litigation_count_3y", "longitude", "management_company_signal",
    "neighborhood", "neighborhood_confidence", "neighborhood_resolved_from_coords",
    "neighborhood_source", "neighborhood_verification_note", "neighborhood_verified_by_map",
    "next_move", "official_rent_stabilized_list_hit",
    "official_rent_stabilized_list_source", "overall_score", "owner_name",
    "owner_read", "owner_type", "pet_policy", "photo_clone_suspect",
    "photo_declares_ai", "possible_rent_control_candidate", "price_history",
    "promotion_tier", "public_record_id", "public_record_lookup_source",
    "public_record_lookup_status", "public_record_notes", "qualification_passed",
    "recommendation", "record_link_confidence", "registration_signal", "relist_suspect",
    "rent", "rent_stabilized_confidence", "rent_stabilized_notes",
    "rent_stabilized_signal", "room_share_flag", "scam_cues_found",
    "score_explanation_lines", "scraped_at", "serious_open_violations",
    "serious_violations_3y", "source_listing_id", "source_name", "source_names",
    "source_quality_confidence", "source_status", "source_tier", "source_url",
    "square_feet", "state_bucket", "sublet_flag", "title", "transit",
    "true_days_on_market", "trust_caveats", "trust_strengths", "unit_count",
    "unit_status", "unit_type", "value_delta", "verification_confidence",
    "verification_status", "voucher_signal", "what_to_verify_before_applying",
    "why_this_listing",
})

PUBLIC_COMPONENT_SCORE_FIELDS = frozenset({
    "authenticity_adjustment", "building_landlord_safety", "geography_adjustment",
    "independent_landlord_fit", "listing_quality", "rent_stability_upside", "search_fit",
})
PUBLIC_PORTFOLIO_FIELDS = frozenset({
    "avgevictions", "bldgs", "openviolationsperresunit", "topcorp", "topowners",
    "totalevictions", "totalopenviolations", "totalrsdiff", "units",
})
PUBLIC_TRANSIT_FIELDS = frozenset({"lines", "station", "walk_mins"})
PUBLIC_CHANGE_DETAIL_FIELDS = frozenset({
    "address_normalized", "change_badge", "first_seen", "first_seen_at", "last_rent",
    "last_seen_at", "listing_uid", "neighborhood", "price_change", "reason", "rent",
    "title",
})
PUBLIC_ILLEGAL_DEMAND_FIELDS = frozenset({"law", "quote", "says"})
PUBLIC_SCAM_CUE_FIELDS = frozenset({"quote", "says"})
PUBLIC_APP_FIELDS = frozenset({"name", "subtitle", "version"})
PUBLIC_SUMMARY_FIELDS = frozenset({
    "back_again", "cautious_count", "gone", "hero_summary", "manual_review_count",
    "new_today", "price_drops", "price_hikes", "pursue_count", "skip_count",
})
PUBLIC_SOURCE_HEALTH_FIELDS = frozenset({"active", "broken", "healthy", "partial"})
PUBLIC_RUN_FIELDS = frozenset({"cadence", "finished_at", "log_url", "run_id", "status"})
PUBLIC_VERA_FIELDS = frozenset({"codename", "full_name", "status", "status_note"})
PUBLIC_SOURCE_FIELDS = frozenset({
    "enabled", "last_success_at", "listing_yield", "reason", "record_count",
    "reliability_score", "source_name", "status", "tier",
})
PUBLIC_STAGE_FIELDS = frozenset({"finished_at", "records_in", "records_out", "started_at", "status"})
PUBLIC_STAGE_NAMES = frozenset({"dedupe", "discover", "enrich", "normalize", "publish", "score"})
PUBLIC_TREND_FIELDS = frozenset({
    "active_sources", "avg_reliability", "healthy_sources", "pipeline_status",
    "records_discovered", "records_published", "run_id", "timestamp",
})
PUBLIC_RECORDS_HEALTH_FIELDS = frozenset({"attempted", "degraded", "errors", "matched", "skipped", "total"})
PUBLIC_DAILY_CHANGE_FIELDS = frozenset({"counts", "date", "generated_at", "gone_listings", "new_listings", "price_changes", "run_id"})
PUBLIC_DAILY_COUNT_FIELDS = frozenset({"back", "gone", "new", "price_drop", "price_hike", "stale", "unchanged"})
PUBLIC_MARKET_CONTEXT_FIELDS = frozenset({"months", "series"})
PUBLIC_MARKET_SERIES_FIELDS = frozenset({"area_type", "median_asking_rent", "median_asking_rent_latest", "rental_inventory_latest"})

# A count is a public aggregate, not a contact channel. Keep this exception
# narrow and type-checked: spelling it like a contact field must not let a
# name, email, phone, or free-form value bypass the generic sensitive-key
# guard.
PUBLIC_AGGREGATE_FIELDS = frozenset({"contact_reuse_count"})

# Existing direct fields remain explicitly denied even if a future schema edit
# accidentally adds one. These are owner-only inspection/runtime details, not
# browser UI input.
PERSONAL_FIELDS = frozenset({
    "contact_name", "contact_email", "contact_phone", "contact_brief", "analyst_notes",
})
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:^|[_\-.])(api[_-]?key|authorization|cookie|credential|e-?mail|email|"
    r"mobile|phone|telephone|cell|contact|secret|token|password|session|"
    r"private|watchlist|outreach|analyst|brief|raw[_-]?(?:snapshot|payload)|"
    r"snapshot[_-]?path|payload[_-]?path|file[_-]?path)(?:$|[_\-.])",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-])\d{3}[\s.-]\d{4}(?!\d)")
LOCAL_PATH_PATTERN = re.compile(r"(?:^|[\s\"'])/(?:Users|home|var|tmp)/|[A-Z]:\\\\", re.IGNORECASE)

# Editorial accusation patterns (owner watchlists). Neutralized publicly:
# the counts are public record, the accusation is the owner's opinion.
WATCHLIST_PATTERN = re.compile(
    r"bad[\s_-]*actor|watch[\s_-]*list|black[\s_-]*list|known\s+scammer",
    re.IGNORECASE,
)
NEUTRAL_RISK = "Elevated public-record risk"


def neutralize(value: Any) -> Any:
    """Recursively replace watchlist-flavored strings with neutral wording."""
    if isinstance(value, str):
        return NEUTRAL_RISK if WATCHLIST_PATTERN.search(value) else value
    if isinstance(value, list):
        out = [neutralize(v) for v in value]
        seen: list[Any] = []
        for item in out:
            if item == NEUTRAL_RISK and item in seen:
                continue
            seen.append(item)
        return seen
    if isinstance(value, dict):
        return {k: neutralize(v) for k, v in value.items()}
    return value


def _scalar(value: Any) -> Any:
    """Return a JSON scalar or None. Containers require a named schema."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return neutralize(value)
    return None


def _object(value: Any, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in fields:
        if key not in value:
            continue
        scalar = _scalar(value[key])
        if scalar is not None:
            result[key] = scalar
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [neutralize(item) for item in value if isinstance(item, str)]


def _object_list(value: Any, fields: frozenset[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_object(item, fields) for item in value if isinstance(item, dict)]


def _price_history(value: Any) -> list[list[Any]]:
    """A date-and-rent series; retain only primitive two-value observations."""
    if not isinstance(value, list):
        return []
    rows: list[list[Any]] = []
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue
        when, rent = _scalar(row[0]), _scalar(row[1])
        if isinstance(when, str) and isinstance(rent, (int, float)):
            rows.append([when, rent])
    return rows


def _listing_value(key: str, value: Any) -> Any:
    if key == "contact_reuse_count":
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None
    if key == "component_scores":
        return _object(value, PUBLIC_COMPONENT_SCORE_FIELDS)
    if key == "landlord_portfolio":
        result = _object(value, PUBLIC_PORTFOLIO_FIELDS - {"topowners"})
        if isinstance(value, dict) and "topowners" in value:
            result["topowners"] = _string_list(value["topowners"])
        return result
    if key == "transit":
        result = _object(value, PUBLIC_TRANSIT_FIELDS - {"lines"})
        if isinstance(value, dict) and "lines" in value:
            result["lines"] = _string_list(value["lines"])
        return result
    if key == "change_detail":
        return _object(value, PUBLIC_CHANGE_DETAIL_FIELDS)
    if key == "illegal_demands":
        return _object_list(value, PUBLIC_ILLEGAL_DEMAND_FIELDS)
    if key == "scam_cues_found":
        return _object_list(value, PUBLIC_SCAM_CUE_FIELDS)
    if key == "price_history":
        return _price_history(value)
    if key in {"amenities", "image_urls", "landlord_reason_summary", "listing_confidence_notes", "score_explanation_lines", "source_names", "trust_caveats", "trust_strengths", "what_to_verify_before_applying"}:
        return _string_list(value)
    return _scalar(value)


def sanitize_listing(entry: Any) -> dict[str, Any]:
    """Project one record through the explicit public listing contract."""
    if not isinstance(entry, dict):
        return {}
    result: dict[str, Any] = {}
    for key in PUBLIC_LISTING_FIELDS:
        if key not in entry:
            continue
        value = _listing_value(key, entry[key])
        if value is not None:
            result[key] = value
    return result


def _market_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    if isinstance(value.get("months"), list):
        result["months"] = _string_list(value["months"])
    series = value.get("series")
    if isinstance(series, dict):
        projected: dict[str, dict[str, Any]] = {}
        for name, data in series.items():
            if not isinstance(name, str) or not isinstance(data, dict):
                continue
            item = _object(data, PUBLIC_MARKET_SERIES_FIELDS - {"median_asking_rent"})
            if isinstance(data.get("median_asking_rent"), list):
                item["median_asking_rent"] = [
                    value for value in data["median_asking_rent"]
                    if value is None or isinstance(value, (int, float))
                ]
            projected[name] = item
        result["series"] = projected
    return result


def _transit_tables(value: Any) -> dict[str, list[list[Any]]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[list[Any]]] = {}
    for route, stops in value.items():
        if not isinstance(route, str) or not isinstance(stops, list):
            continue
        kept = []
        for stop in stops:
            if isinstance(stop, (list, tuple)) and len(stop) == 2 and isinstance(stop[0], str) and isinstance(stop[1], (int, float)):
                kept.append([stop[0], stop[1]])
        result[route] = kept
    return result


# Fields the engine computes for the OWNER's hunt view that the public app
# never reads. Grep-verified against every module in the app's js on
# 2026-08-04. They cost 240KB across a 256-listing pool — 16% of it — on a
# feed that is already 91% of what the page transfers. They stay in the
# engine record and in the private hunt lens; they stop riding to phones.
PUBLIC_DROP_FIELDS = frozenset({
    "source_urls",
    "estimated_move_in_cash_note",
    "unit_status_note",
    "apt_status_note",
    "why_it_made_the_cut",
    "survived_reason",
    "demoted_reason",
    "review_out_reason",
    "review_out_reason_code",
    "possible_rent_control_candidate_note",
    "raw_snapshot_path",
    "raw_payload_source",
    "raw_record_index",
    "duplicate_match_evidence",
    "cluster_member_ids",
    "cheap_filter_failures",
    "hard_filter_failures",
})

# Fields stripped from listing entries in hunt.json. Denylist (not allowlist)
# so new pipeline fields (owner_portfolio_estimate, is_coop, image_urls, ...)
# flow through to the HUNT view automatically.
HUNT_ENTRY_DENY_FIELDS = frozenset({
    "sections",
    "full_description",
    "listing_confidence_breakdown",
    "synthetic_risk_scores",
    "raw_snapshot_path",
    "raw_payload_source",
    "raw_record_index",
    "duplicate_match_evidence",
    "cluster_member_ids",
    "cheap_filter_failures",
    "hard_filter_failures",
    "geography_flags",
    "bad_actor_hits",
    "geosearch_match_confidence",
    "geosearch_match_type",
    "parser_version",
    "curated_source",
    "source_enrichment_notes",
    "official_program_source",
    "search_mode",
})

HUNT_DAILY_CHANGE_LIST_CAP = 30


def slim_listing_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k not in HUNT_ENTRY_DENY_FIELDS}


# ── Hunt lens (owner-facing, private) ─────────────────────────────────
def build_hunt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Small decision-first payload for the HUNT view (target <500KB).

    Includes shortlist + manual-review entries, today's changes, and a
    skip-reason distribution so the empty state can say what the pipeline
    DID find. OPS-only telemetry stays in the full engine snapshot.
    """
    reviewed_out = payload.get("reviewed_out") or []
    manual_review = [
        slim_listing_entry(e)
        for e in reviewed_out
        if isinstance(e, dict) and e.get("state_bucket") == "needs_manual_review"
    ]
    skips = [
        e
        for e in reviewed_out
        if isinstance(e, dict) and e.get("state_bucket") != "needs_manual_review"
    ]
    reason_counts: dict[tuple[str, str], int] = {}
    for e in skips:
        key = (
            str(e.get("review_out_reason_code") or "unspecified"),
            str(e.get("review_out_reason") or "No reason recorded"),
        )
        reason_counts[key] = reason_counts.get(key, 0) + 1
    skip_insights = {
        "total": len(skips),
        "reasons": [
            {"code": code, "label": label, "count": count}
            for (code, label), count in sorted(
                reason_counts.items(), key=lambda item: -item[1]
            )
        ],
    }

    daily_changes = payload.get("daily_changes")
    if isinstance(daily_changes, dict):
        daily_changes = json.loads(json.dumps(daily_changes))
        for list_key in ("new_listings", "price_changes", "gone_listings"):
            items = daily_changes.get(list_key)
            if isinstance(items, list):
                daily_changes[list_key] = [
                    slim_listing_entry(i) if isinstance(i, dict) else i
                    for i in items[:HUNT_DAILY_CHANGE_LIST_CAP]
                ]

    hunt: dict[str, Any] = {
        "generated_at": payload.get("generated_at"),
        "app": payload.get("app"),
        "summary": payload.get("summary"),
        "shortlist": [
            slim_listing_entry(e) if isinstance(e, dict) else e
            for e in payload.get("shortlist") or []
        ],
        "manual_review": manual_review,
        "skip_insights": skip_insights,
        "recommendations": payload.get("recommendations"),
        "daily_changes": daily_changes,
        "messages": payload.get("messages"),
    }
    # Overlay-dependent sections: present only on runs that produce them.
    for optional_key in ("watchlist", "morning_readiness", "risk_watch", "market_intelligence"):
        value = payload.get(optional_key)
        if value is not None:
            hunt[optional_key] = value
    health = payload.get("source_health")
    if isinstance(health, dict):
        hunt["source_health"] = {
            k: health.get(k) for k in ("active", "healthy", "partial", "broken")
        }
    run = payload.get("run")
    if isinstance(run, dict):
        hunt["run"] = {
            k: run.get(k)
            # log_url is a public Actions URL for the run that built this
            # feed. A product whose whole posture is receipts should let
            # anyone read the log that produced the numbers.
            for k in ("run_id", "cadence", "status", "finished_at", "log_url")
            if k in run
        }
    vera = payload.get("vera")
    if isinstance(vera, dict):
        hunt["vera"] = {
            k: vera.get(k) for k in ("codename", "full_name", "status", "status_note")
        }
    return hunt


def build_public_extras(payload: dict[str, Any],
                        snapshot_root: Path | None = None) -> dict[str, Any]:
    """Sanitizable slices of the full payload that power the public app:
    the whole scored pool, run trends, per-source health, bucket counts,
    and slim stage telemetry. Listing entries are slimmed here and
    person-sanitized in build_public_payload."""
    pool: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in (payload.get("shortlist") or []) + (payload.get("reviewed_out") or []):
        if not isinstance(entry, dict):
            continue
        uid = str(entry.get("listing_uid") or id(entry))
        if uid in seen:
            continue
        seen.add(uid)
        pool.append(slim_listing_entry(entry))

    sources = []
    for s in payload.get("sources") or []:
        if isinstance(s, dict):
            sources.append({
                k: s.get(k)
                for k in ("source_name", "status", "tier", "reliability_score",
                          "last_success_at", "enabled", "listing_yield",
                          # record_count was collected but never published, so the
                          # public Pipeline page could not show per-source yield —
                          # a source could read green while contributing nothing.
                          "record_count", "reason")
                if k in s
            })

    stages = {}
    for name, st in (payload.get("stages") or {}).items():
        if isinstance(st, dict):
            stages[name] = {
                k: st.get(k)
                for k in ("status", "started_at", "finished_at", "records_in", "records_out")
            }

    # Whole-market aggregates from StreetEasy's official public CSVs — written
    # by the engine's refresh_market_context.py, aggregate-only by construction.
    root = snapshot_root or (ENGINE_ROOT / "snapshots")
    mc_path = root / "market_context.json"
    market_context = json.loads(mc_path.read_text()) if mc_path.exists() else None

    return {
        "pool": pool,
        "run_trends": payload.get("run_trends") or [],
        "sources": sources,
        "state_buckets": payload.get("state_buckets") or {},
        "stages": stages,
        "market_context": market_context,
        "transit_tables": payload.get("transit_tables"),
        "records_health": payload.get("records_health"),
    }


# ── Public lens ───────────────────────────────────────────────────────
def build_public_payload(hunt: dict[str, Any],
                         extras: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the browser contract from approved fields only.

    This intentionally ignores unknown hunt/extras keys. Extending the public
    product is a schema change in this file plus a regression test; it is never
    an accidental consequence of adding engine data.
    """
    public: dict[str, Any] = {"lens": "public"}

    generated_at = _scalar(hunt.get("generated_at"))
    if generated_at is not None:
        public["generated_at"] = generated_at

    for key, fields in (("app", PUBLIC_APP_FIELDS), ("summary", PUBLIC_SUMMARY_FIELDS),
                        ("source_health", PUBLIC_SOURCE_HEALTH_FIELDS),
                        ("run", PUBLIC_RUN_FIELDS), ("vera", PUBLIC_VERA_FIELDS)):
        if isinstance(hunt.get(key), dict):
            public[key] = _object(hunt[key], fields)

    for key in ("shortlist", "manual_review"):
        if isinstance(hunt.get(key), list):
            public[key] = [sanitize_listing(item) for item in hunt[key] if isinstance(item, dict)]

    daily = hunt.get("daily_changes")
    if isinstance(daily, dict):
        projected = _object(daily, PUBLIC_DAILY_CHANGE_FIELDS - {"counts", "new_listings", "price_changes", "gone_listings"})
        if isinstance(daily.get("counts"), dict):
            projected["counts"] = _object(daily["counts"], PUBLIC_DAILY_COUNT_FIELDS)
        for list_key in ("new_listings", "price_changes", "gone_listings"):
            if isinstance(daily.get(list_key), list):
                projected[list_key] = [
                    sanitize_listing(item) for item in daily[list_key] if isinstance(item, dict)
                ]
        public["daily_changes"] = projected

    # skip_insights is derived from counts; only its compact public shape is
    # needed. The prior optional overlays were owner-only and are intentionally
    # absent from this public schema.
    skip = hunt.get("skip_insights")
    if isinstance(skip, dict):
        projected = _object(skip, frozenset({"total"}))
        if isinstance(skip.get("reasons"), list):
            projected["reasons"] = _object_list(skip["reasons"], frozenset({"code", "count", "label"}))
        public["skip_insights"] = projected

    if extras:
        if isinstance(extras.get("pool"), list):
            public["pool"] = [sanitize_listing(item) for item in extras["pool"] if isinstance(item, dict)]
        if isinstance(extras.get("run_trends"), list):
            public["run_trends"] = _object_list(extras["run_trends"], PUBLIC_TREND_FIELDS)
        if isinstance(extras.get("sources"), list):
            public["sources"] = _object_list(extras["sources"], PUBLIC_SOURCE_FIELDS)
        if isinstance(extras.get("stages"), dict):
            public["stages"] = {
                name: _object(extras["stages"][name], PUBLIC_STAGE_FIELDS)
                for name in PUBLIC_STAGE_NAMES
                if isinstance(extras["stages"].get(name), dict)
            }
        if extras.get("market_context") is not None:
            public["market_context"] = _market_context(extras["market_context"])
        if extras.get("transit_tables") is not None:
            public["transit_tables"] = _transit_tables(extras["transit_tables"])
        if isinstance(extras.get("records_health"), dict):
            public["records_health"] = _object(extras["records_health"], PUBLIC_RECORDS_HEALTH_FIELDS)

        # State buckets used to ship every scored record a second time. Counts
        # preserve the UI's aggregate view without opening another data path.
        buckets = extras.get("state_buckets")
        if isinstance(buckets, dict):
            public["state_buckets"] = {
                key: (len(value) if isinstance(value, list) else value)
                for key, value in buckets.items()
                if isinstance(key, str) and isinstance(value, (int, float, bool, list))
            }

    return public


def _archive_entry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = _object(value, frozenset({"date", "run_id"}))
    if isinstance(value.get("listings"), list):
        listing_fields = frozenset({
            "address_normalized", "first_seen_at", "listing_uid", "neighborhood",
            "overall_score", "rent", "source_name", "title",
        })
        result["listings"] = [
            _object(item, listing_fields) for item in value["listings"] if isinstance(item, dict)
        ]
    return result


def sanitize_archive(value: Any) -> list[dict[str, Any]]:
    """Apply the archive's narrower immutable public-record schema."""
    if not isinstance(value, list):
        return []
    return [_archive_entry(item) for item in value if isinstance(item, dict)]


def maintain_archive(public: dict[str, Any], data_root: Path | str) -> dict[str, Any]:
    """Append today's drop to the sanitized public receipts (`archive.json`).

    The drop is computed server-side with the same full-fit gate the
    emailer uses, over the ALREADY-SANITIZED pool — the archive can never
    carry a field public.json would not. One entry per calendar day
    (re-publishes replace it), capped at 60 days, append-only otherwise. The
    Little Fight site exposes this file at `/vera/data/archive.json`.
    """
    archive_path = Path(data_root) / "archive.json"
    try:
        archive = sanitize_archive(json.loads(archive_path.read_text()))
    except (OSError, json.JSONDecodeError):
        archive = []

    def full_fit(l: dict) -> bool:
        rec = str(l.get("recommendation") or "").lower()
        if rec not in ("pursue", "pursue cautiously"):
            return False
        conf = l.get("listing_confidence_score")
        rent = l.get("rent")
        return (
            (l.get("overall_score") or 0) >= 60
            and conf is not None and conf >= 60
            and (l.get("hpd_risk_score") or 0) < 65
            and (l.get("dob_risk_score") or 0) < 65
            and isinstance(rent, (int, float)) and 0 < rent <= 3000
        )

    fits = sorted(
        [l for l in public.get("pool") or [] if isinstance(l, dict) and full_fit(l)],
        key=lambda l: l.get("overall_score") or 0,
        reverse=True,
    )[:8]
    day = str(public.get("generated_at") or "")[:10]
    if not day:
        return {"archived": 0}
    entry = {
        "date": day,
        "run_id": (public.get("run") or {}).get("run_id"),
        "listings": [
            {
                "listing_uid": l.get("listing_uid"),
                "address_normalized": l.get("address_normalized"),
                "title": l.get("title"),
                "rent": l.get("rent"),
                "neighborhood": l.get("neighborhood"),
                "overall_score": l.get("overall_score"),
                "first_seen_at": l.get("first_seen_at"),
                "source_name": l.get("source_name"),
            }
            for l in fits
        ],
    }
    archive = [e for e in archive if e.get("date") != day]
    archive.insert(0, entry)
    archive = archive[:60]
    archive_path.write_text(json.dumps(sanitize_archive(archive)) + "\n")
    return {"archived": len(entry["listings"]), "days": len(archive)}


# ── The guard ─────────────────────────────────────────────────────────
def audit_public_payload(public: Any) -> list[str]:
    """Walk a finished public payload and report anything that must not ship.

    Cheap, total, and independent of how the payload was built — so it holds
    even if someone later adds a section and forgets the lens entirely. The
    cloud publisher refuses to commit when this returns anything.
    """
    problems: list[str] = []

    def schema_keys(node: Any, path: str, allowed: frozenset[str]) -> None:
        if not isinstance(node, dict):
            return
        for key in node:
            if key not in allowed:
                problems.append(f"{path}.{key} — not in public schema")

    def listing_rows(node: Any, path: str) -> None:
        if not isinstance(node, list):
            return
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            schema_keys(item, item_path, PUBLIC_LISTING_FIELDS)
            if not isinstance(item, dict):
                continue
            schema_keys(item.get("component_scores"), f"{item_path}.component_scores", PUBLIC_COMPONENT_SCORE_FIELDS)
            schema_keys(item.get("landlord_portfolio"), f"{item_path}.landlord_portfolio", PUBLIC_PORTFOLIO_FIELDS)
            schema_keys(item.get("transit"), f"{item_path}.transit", PUBLIC_TRANSIT_FIELDS)
            schema_keys(item.get("change_detail"), f"{item_path}.change_detail", PUBLIC_CHANGE_DETAIL_FIELDS)
            if "contact_reuse_count" in item:
                count = item["contact_reuse_count"]
                if not (isinstance(count, (int, float)) and not isinstance(count, bool) and count >= 0):
                    problems.append(f"{item_path}.contact_reuse_count — not a non-negative public aggregate")
            for key, fields in (("illegal_demands", PUBLIC_ILLEGAL_DEMAND_FIELDS),
                                ("scam_cues_found", PUBLIC_SCAM_CUE_FIELDS)):
                if isinstance(item.get(key), list):
                    for child_index, child in enumerate(item[key]):
                        schema_keys(child, f"{item_path}.{key}[{child_index}]", fields)

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if (k not in PUBLIC_AGGREGATE_FIELDS
                        and (k in PERSONAL_FIELDS or SENSITIVE_KEY_PATTERN.search(k))):
                    problems.append(f"{path}.{k} — sensitive key")
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            if WATCHLIST_PATTERN.search(node):
                problems.append(f"{path} — un-neutralized watchlist wording")
            if EMAIL_PATTERN.search(node):
                problems.append(f"{path} — email-like value")
            if PHONE_PATTERN.search(node):
                problems.append(f"{path} — phone-like value")
            if LOCAL_PATH_PATTERN.search(node):
                problems.append(f"{path} — local filesystem path")

    walk(public, "$")
    if not isinstance(public, dict):
        problems.append("$ — public payload is not an object")
        return problems
    schema_keys(public, "$", PUBLIC_TOP_LEVEL_FIELDS)
    if public.get("lens") != "public":
        problems.append("$.lens is not 'public'")
    if "origin" in public and public["origin"] != "cloud":
        problems.append("$.origin is not 'cloud'")
    for key in ("pool", "shortlist", "manual_review"):
        listing_rows(public.get(key), f"$.{key}")
    daily = public.get("daily_changes")
    schema_keys(daily, "$.daily_changes", PUBLIC_DAILY_CHANGE_FIELDS)
    if isinstance(daily, dict):
        schema_keys(daily.get("counts"), "$.daily_changes.counts", PUBLIC_DAILY_COUNT_FIELDS)
        for key in ("new_listings", "price_changes", "gone_listings"):
            listing_rows(daily.get(key), f"$.daily_changes.{key}")
    schema_keys(public.get("app"), "$.app", PUBLIC_APP_FIELDS)
    schema_keys(public.get("summary"), "$.summary", PUBLIC_SUMMARY_FIELDS)
    schema_keys(public.get("source_health"), "$.source_health", PUBLIC_SOURCE_HEALTH_FIELDS)
    schema_keys(public.get("run"), "$.run", PUBLIC_RUN_FIELDS)
    schema_keys(public.get("vera"), "$.vera", PUBLIC_VERA_FIELDS)
    skip = public.get("skip_insights")
    schema_keys(skip, "$.skip_insights", frozenset({"total", "reasons"}))
    if isinstance(skip, dict) and isinstance(skip.get("reasons"), list):
        for index, reason in enumerate(skip["reasons"]):
            schema_keys(reason, f"$.skip_insights.reasons[{index}]", frozenset({"code", "count", "label"}))
    if isinstance(public.get("sources"), list):
        for index, source in enumerate(public["sources"]):
            schema_keys(source, f"$.sources[{index}]", PUBLIC_SOURCE_FIELDS)
    if isinstance(public.get("run_trends"), list):
        for index, trend in enumerate(public["run_trends"]):
            schema_keys(trend, f"$.run_trends[{index}]", PUBLIC_TREND_FIELDS)
    if isinstance(public.get("stages"), dict):
        for name, stage in public["stages"].items():
            if name not in PUBLIC_STAGE_NAMES:
                problems.append(f"$.stages.{name} — not in public schema")
            schema_keys(stage, f"$.stages.{name}", PUBLIC_STAGE_FIELDS)
    schema_keys(public.get("records_health"), "$.records_health", PUBLIC_RECORDS_HEALTH_FIELDS)
    market_context = public.get("market_context")
    schema_keys(market_context, "$.market_context", PUBLIC_MARKET_CONTEXT_FIELDS)
    if isinstance(market_context, dict) and isinstance(market_context.get("series"), dict):
        for name, series in market_context["series"].items():
            schema_keys(series, f"$.market_context.series.{name}", PUBLIC_MARKET_SERIES_FIELDS)
    return problems

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

strip_personal_deep() runs last over the whole finished payload, so a
future section added without remembering to sanitize it still cannot leak.
Every leak found so far arrived exactly that way.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ENGINE_ROOT = Path(__file__).resolve().parents[1]

# ── The personal layer ────────────────────────────────────────────────
PERSONAL_FIELDS = (
    "contact_name",
    "contact_email",
    "contact_phone",
    "contact_brief",
    "analyst_notes",
)

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


def slim_public(entry: Any) -> Any:
    """Drop owner-only fields from a public listing record."""
    if not isinstance(entry, dict):
        return entry
    return {k: v for k, v in entry.items() if k not in PUBLIC_DROP_FIELDS}


def slim_listing_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k not in HUNT_ENTRY_DENY_FIELDS}


def sanitize_listing(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return entry
    e = {k: v for k, v in entry.items() if k not in PERSONAL_FIELDS}
    return neutralize(e)


def strip_personal_deep(value: Any) -> Any:
    """Remove PERSONAL_FIELDS at EVERY depth of an arbitrary structure.

    sanitize_listing only strips the top level of one record, so a personal
    field nested inside a sub-object (entry["sections"]["facts"]["contact_phone"])
    or inside a section nobody remembered to sanitize survived it. This is the
    belt-and-braces pass: run it over the finished payload so no future
    section can leak by omission.
    """
    if isinstance(value, dict):
        return {
            k: strip_personal_deep(v)
            for k, v in value.items()
            if k not in PERSONAL_FIELDS
        }
    if isinstance(value, list):
        return [strip_personal_deep(v) for v in value]
    return value


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
    public = json.loads(json.dumps(hunt))
    public["lens"] = "public"
    public.pop("watchlist", None)  # owner's manual watch state stays private

    for key in ("shortlist", "manual_review"):
        if isinstance(public.get(key), list):
            public[key] = [sanitize_listing(x) for x in public[key]]

    daily = public.get("daily_changes")
    if isinstance(daily, dict):
        for list_key in ("new_listings", "price_changes", "gone_listings"):
            if isinstance(daily.get(list_key), list):
                daily[list_key] = [sanitize_listing(x) for x in daily[list_key]]

    for key in ("skip_insights", "risk_watch", "messages", "recommendations", "summary"):
        if key in public:
            public[key] = neutralize(public[key])

    # Workspace extras: the full scored pool + ops slices for the public
    # app. Every listing goes through the same personal-layer strip and
    # watchlist neutralization as the shortlist.
    if extras:
        if isinstance(extras.get("pool"), list):
            public["pool"] = [slim_public(sanitize_listing(x)) for x in extras["pool"]]
        for key in ("run_trends", "sources", "stages", "market_context", "transit_tables", "records_health"):
            if extras.get(key) is not None:
                public[key] = neutralize(extras[key])
        # state_buckets used to ship every scored record a SECOND time, in full.
        # That is where contact_phone / contact_brief / analyst_notes leaked to
        # the public feed: this key was only neutralize()d, never run through
        # sanitize_listing(). The records now live once, in `pool`, so publish
        # counts here instead of bodies — smaller payload, no second surface.
        buckets = extras.get("state_buckets")
        if isinstance(buckets, dict):
            public["state_buckets"] = {
                k: (len(v) if isinstance(v, list) else v) for k, v in buckets.items()
            }

    # Final guarantee, applied to the WHOLE payload regardless of which key or
    # nesting level a field arrived through. Every leak so far has come from a
    # new section being added without remembering to sanitize it; this makes
    # remembering unnecessary.
    return strip_personal_deep(public)


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
        archive = json.loads(archive_path.read_text())
        if not isinstance(archive, list):
            archive = []
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
    archive_path.write_text(json.dumps(strip_personal_deep(archive)) + "\n")
    return {"archived": len(entry["listings"]), "days": len(archive)}


# ── The guard ─────────────────────────────────────────────────────────
def audit_public_payload(public: Any) -> list[str]:
    """Walk a finished public payload and report anything that must not ship.

    Cheap, total, and independent of how the payload was built — so it holds
    even if someone later adds a section and forgets the lens entirely. The
    cloud publisher refuses to commit when this returns anything.
    """
    problems: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in PERSONAL_FIELDS:
                    problems.append(f"{path}.{k} — personal field")
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node[:400]):   # bounded: leaks are systemic, not one-off
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and WATCHLIST_PATTERN.search(node):
            problems.append(f"{path} — un-neutralized watchlist wording")

    walk(public, "$")
    if isinstance(public, dict) and public.get("lens") != "public":
        problems.append("$.lens is not 'public'")
    return problems

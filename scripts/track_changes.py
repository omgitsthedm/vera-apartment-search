#!/usr/bin/env python3
"""VERA Change Tracker — detects new listings, price changes, relisted, stale, gone.

This module runs AFTER ai_enrich.py and BEFORE build_snapshot.py.
It maintains a persistent history file and stamps each listing with a
change_badge field that the dashboard renders as a visual indicator.

Badges:
    "new"         — first time seeing this listing_uid
    "price_drop"  — rent decreased since last seen
    "price_hike"  — rent increased since last seen
    "back"        — listing disappeared for 2+ days and reappeared
    "stale"       — listing hasn't been updated by source in 5+ days
    "gone"        — listing was in previous run but not in this one
    None          — no change worth flagging

Architecture:
    - Reads latest scored JSON
    - Loads persistent change_history.json (keyed by listing_uid)
    - Computes diffs per listing
    - Writes change_badge + change_detail into each listing record
    - Updates change_history.json with current state
    - Writes daily_changes_YYYYMMDD.json summary for dashboard

Usage:
    python scripts/track_changes.py             # normal mode
    python scripts/track_changes.py --verbose    # show change details
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.paths import (
    VERA_ROOT as ROOT,
    SCORED_DIR as SCORED_ROOT,
    STATE_DIR,
)
from workflow_support import (
    ensure_dir,
    latest_file,
    read_json,
    write_json,
    utc_stamp,
    utc_now_iso,
)

# ── Config ────────────────────────────────────────────────────────

CHANGE_HISTORY_PATH = STATE_DIR / "change_history.json"
DAILY_CHANGES_DIR = STATE_DIR / "daily_changes"

# How many days absent before "back again" badge (vs just a gap in scraping)
ABSENT_THRESHOLD_DAYS = 2

# How many days since source last updated before "stale"
STALE_THRESHOLD_DAYS = 5

VERBOSE = "--verbose" in sys.argv


# ── Core Logic ────────────────────────────────────────────────────

def compute_change(
    listing: dict[str, Any],
    prior: dict[str, Any] | None,
    now: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """Compare a listing against its history. Returns (badge, detail) or (None, None)."""

    uid = listing.get("listing_uid", "")
    current_rent = listing.get("rent")

    # Try to parse rent as float for comparison
    try:
        current_rent_f = float(current_rent) if current_rent else None
    except (TypeError, ValueError):
        current_rent_f = None

    # Brand new listing — never seen before
    if prior is None:
        return "new", {"reason": "first_appearance", "first_seen": now}

    prior_rent = prior.get("last_rent")
    try:
        prior_rent_f = float(prior_rent) if prior_rent else None
    except (TypeError, ValueError):
        prior_rent_f = None

    # Back again — listing was absent for 2+ days
    last_seen = prior.get("last_seen_at", "")
    was_absent = prior.get("absent_since")
    if was_absent:
        try:
            absent_dt = datetime.fromisoformat(was_absent.replace("Z", "+00:00"))
            now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
            absent_days = (now_dt - absent_dt).total_seconds() / 86400
            if absent_days >= ABSENT_THRESHOLD_DAYS:
                return "back", {
                    "reason": "relisted",
                    "absent_since": was_absent,
                    "absent_days": round(absent_days, 1),
                }
        except (ValueError, TypeError):
            pass

    # Price change
    if current_rent_f is not None and prior_rent_f is not None:
        if current_rent_f < prior_rent_f:
            drop_pct = round((1 - current_rent_f / prior_rent_f) * 100, 1)
            return "price_drop", {
                "reason": "rent_decreased",
                "previous_rent": prior_rent_f,
                "current_rent": current_rent_f,
                "drop_pct": drop_pct,
            }
        elif current_rent_f > prior_rent_f:
            hike_pct = round((current_rent_f / prior_rent_f - 1) * 100, 1)
            return "price_hike", {
                "reason": "rent_increased",
                "previous_rent": prior_rent_f,
                "current_rent": current_rent_f,
                "hike_pct": hike_pct,
            }

    # Stale — listing exists but source hasn't refreshed it
    first_seen = prior.get("first_seen_at", "")
    if first_seen and last_seen:
        try:
            first_dt = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
            now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
            age_days = (now_dt - first_dt).total_seconds() / 86400
            if age_days >= STALE_THRESHOLD_DAYS:
                # Only flag stale if listing hasn't changed at all
                if prior.get("last_rent") == current_rent and prior.get("run_count", 0) >= 3:
                    return "stale", {
                        "reason": "unchanged_for_days",
                        "first_seen": first_seen,
                        "age_days": round(age_days, 1),
                        "runs_unchanged": prior.get("run_count", 0),
                    }
        except (ValueError, TypeError):
            pass

    return None, None


def detect_gone(
    current_uids: set[str],
    history: dict[str, Any],
    now: str,
) -> list[dict[str, Any]]:
    """Find listings in history that are no longer in the current run."""
    gone = []
    for uid, entry in history.items():
        if uid in current_uids:
            continue
        if entry.get("absent_since"):
            # Already marked absent — don't re-flag
            continue
        gone.append({
            "listing_uid": uid,
            "change_badge": "gone",
            "change_detail": {
                "reason": "not_in_current_run",
                "last_seen_at": entry.get("last_seen_at"),
                "last_rent": entry.get("last_rent"),
                "title": entry.get("title", ""),
                "neighborhood": entry.get("neighborhood", ""),
            },
        })
    return gone


# ── Main ──────────────────────────────────────────────────────────

def main():
    print("\n[track_changes] Starting change detection")

    # Find latest scored file
    scored_path = latest_file(SCORED_ROOT, "scored_*.json")
    if not scored_path:
        scored_path = latest_file(SCORED_ROOT, "ai_enriched_*.json")
    if not scored_path:
        print("[track_changes] No scored listings found. Skipping.")
        return

    print(f"[track_changes] Reading: {scored_path.name}")
    listings = read_json(scored_path, default=[])
    if not listings:
        print("[track_changes] No listings to track.")
        return

    # Load persistent history
    history = read_json(CHANGE_HISTORY_PATH, default={})
    now = utc_now_iso()

    # Compute changes for each listing
    changes_summary = {"new": 0, "price_drop": 0, "price_hike": 0, "back": 0, "stale": 0, "gone": 0, "unchanged": 0}
    current_uids = set()

    for listing in listings:
        uid = listing.get("listing_uid", "")
        if not uid:
            continue
        current_uids.add(uid)

        prior = history.get(uid)
        badge, detail = compute_change(listing, prior, now)

        # Write badge into listing record
        listing["change_badge"] = badge
        listing["change_detail"] = detail

        if badge:
            changes_summary[badge] = changes_summary.get(badge, 0) + 1
            if VERBOSE:
                rent_str = f"${int(float(listing.get('rent', 0))):,}" if listing.get("rent") else "?"
                print(f"  [{badge}] {listing.get('title', '?')[:50]} — {rent_str}")
                if detail:
                    print(f"    {detail.get('reason', '')}")
        else:
            changes_summary["unchanged"] += 1

        # Update history entry
        current_rent = listing.get("rent")
        try:
            current_rent_f = float(current_rent) if current_rent else None
        except (TypeError, ValueError):
            current_rent_f = None

        run_count = (history.get(uid, {}).get("run_count", 0) + 1) if uid in history else 1

        history[uid] = {
            "first_seen_at": (prior or {}).get("first_seen_at", now),
            "last_seen_at": now,
            "last_rent": current_rent_f,
            "title": listing.get("title", ""),
            "neighborhood": listing.get("neighborhood", ""),
            "borough": listing.get("borough", ""),
            "source_name": listing.get("source_name", ""),
            "recommendation": listing.get("recommendation", ""),
            "absent_since": None,  # clear absence — it's present now
            "run_count": run_count,
            "price_history": _update_price_history(
                (prior or {}).get("price_history", []),
                current_rent_f,
                now,
            ),
        }

    # Detect gone listings
    gone_listings = detect_gone(current_uids, history, now)
    changes_summary["gone"] = len(gone_listings)

    # Mark absent in history
    for gone_item in gone_listings:
        uid = gone_item["listing_uid"]
        if uid in history:
            history[uid]["absent_since"] = now

    # Write updated listings back to scored file
    write_json(scored_path, listings)

    # Write updated history
    ensure_dir(STATE_DIR)
    write_json(CHANGE_HISTORY_PATH, history)

    # Write daily changes summary
    ensure_dir(DAILY_CHANGES_DIR)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    daily_summary = {
        "date": today,
        "generated_at": now,
        "run_id": str(Path(scored_path.name)),
        "counts": changes_summary,
        "new_listings": [
            {
                "listing_uid": l.get("listing_uid"),
                "title": l.get("title", ""),
                "neighborhood": l.get("neighborhood", ""),
                "rent": l.get("rent"),
                "recommendation": l.get("recommendation", ""),
            }
            for l in listings
            if l.get("change_badge") == "new"
        ],
        "price_changes": [
            {
                "listing_uid": l.get("listing_uid"),
                "title": l.get("title", ""),
                "change_badge": l.get("change_badge"),
                "detail": l.get("change_detail"),
            }
            for l in listings
            if l.get("change_badge") in ("price_drop", "price_hike")
        ],
        "gone_listings": gone_listings,
    }
    write_json(DAILY_CHANGES_DIR / f"changes_{today}.json", daily_summary)

    # Print summary
    active_changes = {k: v for k, v in changes_summary.items() if v > 0 and k != "unchanged"}
    print(f"[track_changes] {len(listings)} listings tracked | {len(history)} in history")
    if active_changes:
        parts = [f"{v} {k}" for k, v in active_changes.items()]
        print(f"[track_changes] Changes: {', '.join(parts)}")
    else:
        print("[track_changes] No changes detected")
    print(f"[track_changes] History: {CHANGE_HISTORY_PATH.name}")


def _update_price_history(
    existing: list[dict[str, Any]],
    current_rent: float | None,
    now: str,
) -> list[dict[str, Any]]:
    """Append to price history if rent changed. Keep last 10 entries."""
    if current_rent is None:
        return existing

    # Only add if price actually changed from last entry
    if existing and existing[-1].get("rent") == current_rent:
        return existing

    entry = {"rent": current_rent, "seen_at": now}
    updated = existing + [entry]
    return updated[-10:]  # keep last 10


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Maintain state/price_history.json — the memory portals delete.

After each successful pipeline, append (date, rent) per listing_uid when
the price is new or changed, stamp last_seen, and prune listings gone for
90+ days. build_snapshot attaches this history to every listing on the
NEXT compose, which gives the app true days-on-market and the price path
— StreetEasy removed its DOM counter in 2025; VERA keeps its own.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "latest_snapshot.json"
STORE = ROOT / "state" / "price_history.json"
ADDR_STORE = ROOT / "state" / "address_history.json"
PRUNE_DAYS = 90


def address_key(rec: dict) -> str | None:
    """Unit-level identity that survives a relist under a fresh uid."""
    a = str(rec.get("address_normalized") or "").strip().lower()
    if not a:
        return None
    return " ".join(a.split())


def read(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return fallback


def main() -> int:
    snap = read(SNAPSHOT, {})
    pool: list = []
    seen = set()
    for key in ("shortlist", "reviewed_out"):
        for rec in snap.get(key) or []:
            uid = rec.get("listing_uid")
            if uid and uid not in seen:
                seen.add(uid)
                pool.append(rec)
    if not pool:
        print("[price-history] empty snapshot — nothing recorded")
        return 0

    today = datetime.now(timezone.utc).date().isoformat()
    store = read(STORE, {})
    added = changed = 0
    for rec in pool:
        uid = rec["listing_uid"]
        rent = rec.get("rent")
        if not isinstance(rent, (int, float)) or rent <= 0:
            continue
        entry = store.setdefault(uid, {"points": [], "last_seen": today})
        entry["last_seen"] = today
        pts = entry["points"]
        if not pts:
            pts.append([today, round(float(rent))])
            added += 1
        elif pts[-1][1] != round(float(rent)) and pts[-1][0] != today:
            pts.append([today, round(float(rent))])
            changed += 1

    # Address history: the relist detector's memory. Per unit-level address
    # key, every uid that has advertised it with first/last dates and rent —
    # a fresh uid at a known address after a gap is a reset DOM counter.
    addr = read(ADDR_STORE, {})
    for rec in pool:
        key = address_key(rec)
        uid = rec["listing_uid"]
        if not key:
            continue
        entry = addr.setdefault(key, [])
        hit = next((x for x in entry if x.get("uid") == uid), None)
        rent = rec.get("rent")
        if hit:
            hit["last"] = today
            if isinstance(rent, (int, float)) and rent > 0:
                hit["rent"] = round(float(rent))
        else:
            entry.append({
                "uid": uid,
                "first": today,
                "last": today,
                "rent": round(float(rent)) if isinstance(rent, (int, float)) and rent > 0 else None,
            })
    for key in list(addr.keys()):
        addr[key] = [x for x in addr[key] if (datetime.now(timezone.utc).date() - datetime.fromisoformat(x.get("last", today)).date()).days <= 180]
        if not addr[key]:
            del addr[key]
    ADDR_STORE.write_text(json.dumps(addr, separators=(",", ":"), sort_keys=True))

    kept = {}
    for uid, entry in store.items():
        try:
            gone_days = (datetime.now(timezone.utc).date() - datetime.fromisoformat(entry.get("last_seen", today)).date()).days
        except ValueError:
            gone_days = 0
        if gone_days <= PRUNE_DAYS:
            kept[uid] = entry

    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(kept, separators=(",", ":"), sort_keys=True))
    print(f"[price-history] {len(kept)} tracked; +{added} new, {changed} price moves, {len(store) - len(kept)} pruned")
    return 0


if __name__ == "__main__":
    sys.exit(main())

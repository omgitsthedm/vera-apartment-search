#!/usr/bin/env python3
"""Landlord portfolios from JustFix's Who Owns What.

A building's own violation file says how this address is kept. It says
nothing about the person keeping it. WOW links every NYC building to its
landlord portfolio through HPD registration contacts and shared business
addresses, so VERA can finally ask the question that actually matters
before you sign: what does this owner do to their OTHER tenants?

Per BBL it records portfolio size, the top corporate entity and named
officers, open violations per residential unit, eviction totals, and
rent-stabilized units lost — each a public-record fact, each shown with
its source.

Courtesy infrastructure: JustFix publishes no rate limits or terms for
this endpoint, so this is deliberately gentle — a descriptive User-Agent,
a 60-day cache (portfolios move slowly), a hard per-run cap, a delay
between calls, and silent degradation on any failure. VERA never depends
on it; the building's own record remains the primary signal.

Writes state/landlord_portfolios.json keyed by BBL.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "latest_snapshot.json"
OUT = ROOT / "state" / "landlord_portfolios.json"
API = "https://api.justfix.org/api/address/aggregate?bbl="
UA = "VERA-ApartmentSearch/1.2 (personal apartment-hunt tool; info@afterhoursagenda.com)"
PER_RUN = 40
DELAY_S = 1.2
TTL_DAYS = 60

KEEP = (
    "bldgs", "units", "age", "topcorp", "topowners", "topbusinessaddr",
    "totalopenviolations", "openviolationsperresunit", "openviolationsperbldg",
    "totalevictions", "avgevictions", "totalrsdiff", "rsproportion",
)


def read(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return fallback


def fresh(entry: dict) -> bool:
    try:
        when = datetime.fromisoformat(str(entry.get("checked_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return when >= datetime.now(timezone.utc) - timedelta(days=TTL_DAYS)


def fetch(bbl: str) -> dict | None:
    req = urllib.request.Request(API + bbl, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    rows = payload.get("result") or []
    if not rows:
        return None
    row = rows[0]
    out = {k: row.get(k) for k in KEEP if row.get(k) is not None}
    if isinstance(out.get("topowners"), list):
        out["topowners"] = out["topowners"][:5]
    out["checked_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out["source"] = "JustFix Who Owns What"
    return out


def main() -> int:
    snap = read(SNAPSHOT, {})
    bbls, seen = [], set()
    for key in ("shortlist", "reviewed_out"):
        for rec in snap.get(key) or []:
            bbl = str(rec.get("bbl") or "").strip()
            if len(bbl) == 10 and bbl.isdigit() and bbl not in seen:
                seen.add(bbl)
                bbls.append(bbl)

    store = read(OUT, {})
    fetched = flagged = 0
    for bbl in bbls:
        if fetched >= PER_RUN:
            break
        if bbl in store and fresh(store[bbl]):
            continue
        info = fetch(bbl)
        fetched += 1
        if info:
            store[bbl] = info
            if (info.get("totalevictions") or 0) >= 5 or (info.get("openviolationsperresunit") or 0) >= 2:
                flagged += 1
        time.sleep(DELAY_S)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(store, separators=(",", ":")))
    print(f"[portfolios] {len(store)} known (+{fetched} looked up this run) · {flagged} portfolios carry a heavy eviction or violation load")
    return 0


if __name__ == "__main__":
    sys.exit(main())

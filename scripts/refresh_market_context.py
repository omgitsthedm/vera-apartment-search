#!/usr/bin/env python3
"""Pull StreetEasy's official market-data CSVs into snapshots/market_context.json.

These are the free, public, city-pipelined aggregates (cdn-charts.streeteasy.com)
— the honest way to show the whole market next to VERA's net without scraping
anyone. Keeps borough/city series plus every focus-area neighborhood, last 36
months, both median asking rent and rental inventory.

Non-fatal by design: on any failure the previous market_context.json stays.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "snapshots" / "market_context.json"
PREFS = ROOT / "configs" / "user_preferences.json"

FEEDS = {
    "median_asking_rent": "https://cdn-charts.streeteasy.com/rentals/All/medianAskingRent_All.zip",
    "rental_inventory": "https://cdn-charts.streeteasy.com/rentals/All/rentalInventory_All.zip",
}
MONTHS_KEPT = 36
HEADERS = {"User-Agent": "vera-personal-market-context/1.0 (read-only, nightly)"}


def fetch_csv(url: str) -> list[dict[str, str]]:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=45) as resp:
        blob = resp.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".csv"))
        text = zf.read(name).decode("utf-8", "ignore")
    return list(csv.DictReader(io.StringIO(text)))


def main() -> int:
    prefs = json.loads(PREFS.read_text()) if PREFS.exists() else {}
    focus = {str(h).lower() for h in prefs.get("neighborhoods", [])}

    out: dict = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "StreetEasy public market data CSVs (cdn-charts.streeteasy.com)",
        "series": {},
    }

    months: list[str] = []
    for key, url in FEEDS.items():
        try:
            rows = fetch_csv(url)
        except Exception as exc:
            print(f"[market] {key}: fetch failed ({exc}) — keeping previous data")
            continue
        if not rows:
            continue
        month_cols = [c for c in rows[0].keys() if len(c) == 7 and c[4] == "-"]
        month_cols = month_cols[-MONTHS_KEPT:]
        months = month_cols
        for row in rows:
            area = (row.get("areaName") or "").strip()
            atype = (row.get("areaType") or "").strip().lower()
            keep = atype in ("city", "borough") or area.lower() in focus
            if not keep:
                continue
            vals = []
            for c in month_cols:
                v = (row.get(c) or "").strip()
                try:
                    vals.append(round(float(v)))
                except ValueError:
                    vals.append(None)
            entry = out["series"].setdefault(area, {
                "borough": row.get("Borough"),
                "area_type": atype,
            })
            entry[key] = vals
            latest = next((v for v in reversed(vals) if v is not None), None)
            entry[f"{key}_latest"] = latest

    if not out["series"]:
        print("[market] nothing fetched — leaving previous market_context.json untouched")
        return 0

    out["months"] = months
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, sort_keys=True))
    city = out["series"].get("NYC") or out["series"].get("New York City") or {}
    print(f"[market] wrote {len(out['series'])} series over {len(months)} months"
          + (f"; citywide median ask latest ${city.get('median_asking_rent_latest'):,}" if city.get("median_asking_rent_latest") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

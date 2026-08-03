#!/usr/bin/env python3
"""Derive the real subway universe from MTA GTFS static.

Replaces the app's ~95 hand-picked stations with every parent station in
the official feed, each with its true served lines, plus one
representative scheduled stop-sequence per route (cumulative seconds) so
same-line ride times can be estimated from the timetable instead of
invented. Cached: the ~45MB zip is refetched only when older than 7 days.

Outputs (durable state/):
  transit_stations.json  [{id, name, lat, lon, lines:[..]}]
  transit_routes.json    {route_id: [[station_name, secs_from_start], ..]}
"""
from __future__ import annotations

import csv
import io
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
CACHE = STATE / "gtfs_cache"
ZIP_PATH = CACHE / "gtfs_subway.zip"
URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"
MAX_AGE_S = 7 * 86400


def fetch_zip() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists() and time.time() - ZIP_PATH.stat().st_mtime < MAX_AGE_S:
        print(f"[gtfs] cache fresh ({ZIP_PATH.stat().st_size // 1_000_000}MB) — not refetching")
        return ZIP_PATH
    req = urllib.request.Request(URL, headers={"User-Agent": "vera-transit-derive/1.0 (weekly, cached)"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        ZIP_PATH.write_bytes(resp.read())
    print(f"[gtfs] fetched {ZIP_PATH.stat().st_size // 1_000_000}MB")
    return ZIP_PATH


def hms_to_s(v: str) -> int | None:
    try:
        h, m, s = v.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    except (ValueError, AttributeError):
        return None


def main() -> int:
    zpath = fetch_zip()
    with zipfile.ZipFile(zpath) as zf:
        def rows(name):
            with zf.open(name) as fh:
                yield from csv.DictReader(io.TextIOWrapper(fh, "utf-8-sig"))

        parents: dict[str, dict] = {}
        child_to_parent: dict[str, str] = {}
        for r in rows("stops.txt"):
            sid = r["stop_id"]
            if r.get("location_type") == "1":
                parents[sid] = {"id": sid, "name": r["stop_name"], "lat": float(r["stop_lat"]), "lon": float(r["stop_lon"]), "lines": set()}
            else:
                child_to_parent[sid] = r.get("parent_station") or sid

        trip_route: dict[str, str] = {}
        rep_trip: dict[str, str] = {}
        for r in rows("trips.txt"):
            rid = r["route_id"]
            trip_route[r["trip_id"]] = rid
            key = rid + "|" + r.get("direction_id", "0")
            rep_trip.setdefault(key, r["trip_id"])
        rep_set = set(rep_trip.values())

        route_seq: dict[str, list] = {}
        for r in rows("stop_times.txt"):
            tid = r["trip_id"]
            rid = trip_route.get(tid)
            if rid is None:
                continue
            parent = child_to_parent.get(r["stop_id"], r["stop_id"])
            st = parents.get(parent)
            if st is not None:
                st["lines"].add(rid)
            if tid in rep_set:
                secs = hms_to_s(r.get("arrival_time") or r.get("departure_time") or "")
                if secs is not None and st is not None:
                    route_seq.setdefault(rid + "|" + tid, []).append((int(r.get("stop_sequence") or 0), st["name"], secs))

    stations = []
    for st in parents.values():
        if st["lines"]:
            stations.append({"id": st["id"], "name": st["name"], "lat": round(st["lat"], 5), "lon": round(st["lon"], 5), "lines": sorted(st["lines"])})

    routes: dict[str, list] = {}
    for key, seq in route_seq.items():
        rid = key.split("|")[0]
        if rid in routes:
            continue
        seq.sort()
        base = seq[0][2]
        routes[rid] = [[name, secs - base] for _, name, secs in seq]

    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "transit_stations.json").write_text(json.dumps(stations, separators=(",", ":")))
    (STATE / "transit_routes.json").write_text(json.dumps(routes, separators=(",", ":")))
    print(f"[gtfs] {len(stations)} stations, {len(routes)} routes derived")
    return 0


if __name__ == "__main__":
    sys.exit(main())

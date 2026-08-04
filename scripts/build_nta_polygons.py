#!/usr/bin/env python3
"""Build the full NTA2020 neighborhood polygon set.

The app ships a focus-area subset (70 hoods) because it loads them in the
browser. The engine has no such budget and needs COVERAGE: a listing whose
source only said "Brooklyn" can only be resolved if its actual
neighborhood has a polygon. With the subset, 117 borough-only listings
stayed unresolved on 2026-08-04.

Source: NYC Open Data 9nt8-h7nd (DCP NTA2020).
Output: config/geo/nta_hoods_full.json in the same shape the app uses —
{bounds, src, hoods:[{n,b,a,r}]} with rings as [[lat, lon], ...].

Rerun when DCP publishes a new NTA vintage (rare — 2020 is current).
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "config" / "geo" / "nta_hoods_full.json"
URL = "https://data.cityofnewyork.us/resource/9nt8-h7nd.json?$limit=400"
TOLERANCE_DEG = 0.0002  # ~22m, matching the app's vendored subset


def rdp(points: list, eps: float) -> list:
    """Ramer–Douglas–Peucker simplification on [lat, lon] pairs."""
    if len(points) < 3:
        return points
    start, end = points[0], points[-1]
    dmax, index = 0.0, 0
    for i in range(1, len(points) - 1):
        d = _perp(points[i], start, end)
        if d > dmax:
            dmax, index = d, i
    if dmax > eps:
        left = rdp(points[: index + 1], eps)
        right = rdp(points[index:], eps)
        return left[:-1] + right
    return [start, end]


def _perp(p, a, b) -> float:
    dy, dx = b[0] - a[0], b[1] - a[1]
    if dy == 0 and dx == 0:
        return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5
    t = ((p[0] - a[0]) * dy + (p[1] - a[1]) * dx) / (dy * dy + dx * dx)
    t = max(0.0, min(1.0, t))
    return ((p[0] - (a[0] + t * dy)) ** 2 + (p[1] - (a[1] + t * dx)) ** 2) ** 0.5


def rings_of(geom: dict) -> list:
    """MultiPolygon/Polygon -> list of exterior rings as [lat, lon]."""
    if not geom:
        return []
    gtype = geom.get("type")
    coords = geom.get("coordinates") or []
    polys = coords if gtype == "MultiPolygon" else [coords]
    out = []
    for poly in polys:
        if not poly:
            continue
        exterior = poly[0]  # ignore holes: neighborhoods do not have donuts
        ring = [[round(pt[1], 5), round(pt[0], 5)] for pt in exterior if len(pt) >= 2]
        if len(ring) >= 4:
            simplified = rdp(ring, TOLERANCE_DEG)
            if len(simplified) >= 4:
                out.append(simplified)
    return out


BORO_LETTER = {"Manhattan": "M", "Brooklyn": "B", "Queens": "Q", "Bronx": "X", "Staten Island": "S"}


def main() -> int:
    with urllib.request.urlopen(URL, timeout=90) as resp:
        rows = json.load(resp)
    hoods = []
    s = n = w = e = None
    for row in rows:
        if str(row.get("ntatype") or "0") != "0":
            continue  # 0 = residential NTA; skip parks/airports/cemeteries
        rings = rings_of(row.get("the_geom"))
        if not rings:
            continue
        hoods.append({
            "n": row.get("ntaname"),
            "b": BORO_LETTER.get(row.get("boroname"), "?"),
            "a": row.get("ntaabbrev"),
            "r": rings,
        })
        for ring in rings:
            for la, lo in ring:
                s = la if s is None else min(s, la)
                n = la if n is None else max(n, la)
                w = lo if w is None else min(w, lo)
                e = lo if e is None else max(e, lo)
    payload = {
        "bounds": {"s": round(s, 4), "n": round(n, 4), "w": round(w, 4), "e": round(e, 4)},
        "src": "NYC DCP NTA2020 (nyc open data 9nt8-h7nd), residential NTAs, simplified ~22m",
        "hoods": hoods,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    pts = sum(len(r) for h in hoods for r in h["r"])
    print(f"[nta] {len(hoods)} neighborhoods, {pts} points, {OUT.stat().st_size // 1024}KB -> {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

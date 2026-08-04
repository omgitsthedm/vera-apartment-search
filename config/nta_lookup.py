"""Resolve a coordinate to its real NYC neighborhood (NTA2020).

Most sources put a BOROUGH in the neighborhood field — "Brooklyn", not
"Williamsburg". The cheap filter compares that field against the target
neighborhoods, so a listing sitting on a target block was rejected as
"outside target neighborhoods", never got a city-record lookup, fell
back to synthetic risk scores, and could never be recommended. On
2026-08-03 that described 174 of 248 listings.

This resolves the coordinate to its actual NTA polygon so the filter
compares like with like. It does NOT loosen any criterion: a listing
genuinely outside the target neighborhoods still fails — it just fails
for the true reason.

Polygons: NYC DCP NTA2020 (open data 9nt8-h7nd), simplified to ~22m,
vendored at config/geo/nta_hoods.json and shared with the web app.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

GEO_PATH = Path(__file__).resolve().parent / "geo" / "nta_hoods.json"


@lru_cache(maxsize=1)
def _hoods() -> list[dict[str, Any]]:
    try:
        data = json.loads(GEO_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for h in data.get("hoods") or []:
        rings = h.get("r")
        if isinstance(rings, str):
            try:
                rings = json.loads(rings)
            except json.JSONDecodeError:
                continue
        if not rings:
            continue
        # precompute a bounding box per ring — the cheap reject
        boxes = []
        for ring in rings:
            lats = [p[0] for p in ring]
            lons = [p[1] for p in ring]
            boxes.append((min(lats), max(lats), min(lons), max(lons)))
        out.append({"name": h.get("n"), "boro": h.get("b"), "rings": rings, "boxes": boxes})
    return out


def _in_ring(lat: float, lon: float, ring: list) -> bool:
    """Ray casting. Ring points are [lat, lon]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        yi, xi = ring[i][0], ring[i][1]
        yj, xj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            x_at = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < x_at:
                inside = not inside
        j = i
    return inside


def neighborhood_at(lat: Any, lon: Any) -> str | None:
    """Return the NTA name containing this point, or None."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    for h in _hoods():
        for ring, (s, n, w, e) in zip(h["rings"], h["boxes"]):
            if not (s <= la <= n and w <= lo <= e):
                continue
            if _in_ring(la, lo, ring):
                return h["name"]
    return None


BOROUGH_WORDS = {
    "manhattan", "brooklyn", "queens", "bronx", "the bronx",
    "staten island", "new york", "nyc", "new york city",
}


def is_borough_only(value: Any) -> bool:
    """True when the neighborhood field is really just a borough."""
    return str(value or "").strip().lower() in BOROUGH_WORDS


def resolve_neighborhood(listing: dict[str, Any]) -> tuple[str | None, bool]:
    """(neighborhood, was_resolved). Only fills borough-only/empty fields."""
    current = listing.get("neighborhood")
    if current and not is_borough_only(current):
        return current, False
    resolved = neighborhood_at(listing.get("latitude"), listing.get("longitude"))
    if resolved:
        return resolved, True
    return current, False


def neighborhood_matches(value: Any, targets: set[str] | list[str]) -> bool:
    """Compound-aware target match.

    NTA2020 names are compound — "Upper East Side-Lenox Hill-Roosevelt
    Island", "East Harlem (South)". Exact set membership misses every one
    of them, so a listing genuinely on the Upper East Side reads as
    outside the target list. Compare on the parts as well as the whole.
    The target list itself is never modified.
    """
    n = str(value or "").strip().lower()
    if not n:
        return False
    tset = {str(t).strip().lower() for t in targets if str(t).strip()}
    if n in tset:
        return True
    parts = [p.strip() for p in n.replace("(", " ").replace(")", " ").split("-")]
    for p in parts:
        if p and p in tset:
            return True
    for t in tset:
        if t and t in n:
            return True
    return False

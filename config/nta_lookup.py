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

GEO_DIR = Path(__file__).resolve().parent / "geo"
# Full city coverage first (all 197 residential NTAs, built by
# scripts/build_nta_polygons.py); the app's focus-area subset is the
# fallback so this still works if the full file is absent.
GEO_PATHS = (GEO_DIR / "nta_hoods_full.json", GEO_DIR / "nta_hoods.json")


@lru_cache(maxsize=1)
def _hoods() -> list[dict[str, Any]]:
    data = None
    for path in GEO_PATHS:
        try:
            data = json.loads(path.read_text())
            break
        except (OSError, json.JSONDecodeError):
            continue
    if data is None:
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


def borough_at(lat: Any, lon: Any) -> str | None:
    """Borough code (M/B/Q/X/S) containing this point, or None."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    for h in _hoods():
        for ring, (s, n, w, e) in zip(h["rings"], h["boxes"]):
            if not (s <= la <= n and w <= lo <= e):
                continue
            if _in_ring(la, lo, ring):
                return h.get("boro")
    return None


_TARGET_BORO_CACHE: dict[tuple, frozenset] = {}


def target_boroughs(targets: set[str] | list[str]) -> frozenset:
    """Which boroughs the target list actually covers.

    Derived from the target names rather than hardcoded, so adding a Queens
    neighbourhood to the preferences opens Queens automatically and nothing
    here has to be remembered.
    """
    key = tuple(sorted(str(t).strip().lower() for t in targets if str(t).strip()))
    if key in _TARGET_BORO_CACHE:
        return _TARGET_BORO_CACHE[key]

    hoods = _hoods()
    boros = set()
    for target in key:
        # Which boroughs does THIS one target name reach?
        hit = {h["boro"] for h in hoods
               if h.get("boro") and neighborhood_matches(h.get("name"), [target])}
        # A name that spans boroughs proves nothing about intent — "Murray
        # Hill" is both Manhattan and Flushing — and letting it widen the
        # allowed set is circular: the ambiguity being guarded against would
        # authorise itself. Only unambiguous targets contribute.
        if len(hit) == 1:
            boros |= hit
    result = frozenset(boros)
    _TARGET_BORO_CACHE[key] = result
    return result


def in_target_area(listing: dict[str, Any], targets: set[str] | list[str]) -> bool:
    """Target match that a same-named neighbourhood elsewhere cannot fake.

    NYC reuses names across boroughs, and the compound-part match that makes
    "Upper East Side-Lenox Hill-Roosevelt Island" work also lets Queens in:
    two Craigslist listings at 40.7606,-73.7968 — Flushing — passed as the
    Manhattan target "Murray Hill" because the NTA there is called
    "Murray Hill-Broadway Flushing". One of them was titled "apt in flushing".

    So when the listing carries coordinates, the borough those coordinates
    fall in has to be one the target list actually covers. Without
    coordinates this is exactly the old name match — no listing is rejected
    for lacking data.
    """
    if not neighborhood_matches(listing.get("neighborhood"), targets):
        return False
    boro = borough_at(listing.get("latitude"), listing.get("longitude"))
    if not boro:
        return True
    allowed = target_boroughs(targets)
    if not allowed:          # nothing resolvable — do not invent a constraint
        return True
    return boro in allowed


BOROUGH_WORDS = {
    "manhattan", "brooklyn", "queens", "bronx", "the bronx",
    "staten island", "new york", "nyc", "new york city",
}


def is_borough_only(value: Any) -> bool:
    """True when the neighborhood field is really just a borough."""
    return str(value or "").strip().lower() in BOROUGH_WORDS


def resolve_neighborhood(listing: dict[str, Any]) -> tuple[str | None, bool]:
    """(neighborhood, was_resolved) from the city's own NTA polygons.

    This used to fill in only empty or borough-only fields, which left a
    confidently WRONG label untouched. RentHop was labelling 126 Grant Ave
    (Cypress Hills), 1751 85 St (Bath Beach), 1940 79 St (Bensonhurst) and
    215-07 Jamaica Ave (Queens Village) all as "East Village" — and VERA
    published every one of them that way, on the map and in the table.

    A listing carries its own coordinates. When those coordinates fall in a
    polygon that contradicts the label, the label is wrong: the point is the
    source's own data and the polygon is the city's official boundary.

    Compared in both directions because NTA names are compound — a listing
    labelled "Lenox Hill" sitting in "Upper East Side-Lenox Hill-Roosevelt
    Island" agrees, and must not be rewritten.
    """
    current = listing.get("neighborhood")
    resolved = neighborhood_at(listing.get("latitude"), listing.get("longitude"))

    if not current or is_borough_only(current):
        return (resolved, True) if resolved else (current, False)
    if not resolved:
        return current, False
    if neighborhood_matches(current, [resolved]) or neighborhood_matches(resolved, [current]):
        return current, False
    return resolved, True


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

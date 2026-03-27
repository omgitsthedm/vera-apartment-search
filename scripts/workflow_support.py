from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Sequence


# Search modes
SEARCH_MODE_PERMANENT = "mode_a_permanent"
SEARCH_MODE_BRIDGE = "mode_b_bridge"

# Record-link confidence tiers (ordered strongest → weakest)
RECORD_LINK_TIERS = [
    "exact_address_match",
    "strong_partial_address_match",
    "building_level_match",
    "owner_name_assisted_match",
    "neighborhood_only",
    "no_record_match",
]

# Source tier classification
SOURCE_TIERS = ["primary", "unconventional_high", "unconventional_secondary", "fallback"]

# Source status classification
SOURCE_STATUSES = ["live", "partial", "weekly_review", "fallback_only", "experimental", "not_feasible"]


BOROUGH_TO_HPD_CODE = {
    "manhattan": "1",
    "bronx": "2",
    "brooklyn": "3",
    "queens": "4",
    "staten island": "5",
}

BOROUGH_TO_NAME = {
    "manhattan": "MANHATTAN",
    "bronx": "BRONX",
    "brooklyn": "BROOKLYN",
    "queens": "QUEENS",
    "staten island": "STATEN ISLAND",
}

# Non-standard borough labels → official borough key.
# Sources use "New York", sub-neighborhoods, or city names instead of boroughs.
BOROUGH_ALIASES: dict[str, str] = {
    "new york": "manhattan",
    "new york city": "manhattan",
    "nyc": "manhattan",
    "ny": "manhattan",
    "far rockaway": "queens",
    "east elmhurst": "queens",
    "e elmhurst": "queens",
    "jackson heights": "queens",
    "corona": "queens",
    "flushing": "queens",
    "jamaica": "queens",
    "ridgewood": "queens",
    "woodside": "queens",
    "sunnyside": "queens",
    "lic": "queens",
    "long island city": "queens",
    "maspeth": "queens",
    "kew gardens": "queens",
    "astoria": "queens",
    "forest hills": "queens",
    "rego park": "queens",
    "bayside": "queens",
    "howard beach": "queens",
    "ozone park": "queens",
    "south ozone park": "queens",
    "woodhaven": "queens",
    "east new york": "brooklyn",
    "e new york": "brooklyn",
    "brownsville": "brooklyn",
    "flatbush": "brooklyn",
    "east flatbush": "brooklyn",
    "e flatbush": "brooklyn",
    "canarsie": "brooklyn",
    "bay ridge": "brooklyn",
    "bensonhurst": "brooklyn",
    "sunset park": "brooklyn",
    "red hook": "brooklyn",
    "gowanus": "brooklyn",
    "gravesend": "brooklyn",
    "sheepshead bay": "brooklyn",
    "brighton beach": "brooklyn",
    "kensington": "brooklyn",
    "ditmas park": "brooklyn",
    "inwood": "manhattan",
    "washington heights": "manhattan",
    "east harlem": "manhattan",
    "e harlem": "manhattan",
    "morningside heights": "manhattan",
    "riverdale": "bronx",
    "mott haven": "bronx",
    "fordham": "bronx",
    "pelham bay": "bronx",
    "kingsbridge": "bronx",
    "throgs neck": "bronx",
    "hunts point": "bronx",
    "highbridge": "bronx",
    "morris park": "bronx",
}

# Neighborhood → official borough key. Used to infer borough when source doesn't
# provide one. This is the authoritative mapping — a listing in "Chelsea" is
# definitely in Manhattan regardless of what the source says (or doesn't say).
NEIGHBORHOOD_BOROUGH: dict[str, str] = {
    "east village": "manhattan",
    "e village": "manhattan",
    "alphabet city": "manhattan",
    "greenwich village": "manhattan",
    "lower east side": "manhattan",
    "lower e side": "manhattan",
    "les": "manhattan",
    "stuytown": "manhattan",
    "stuyvesant town": "manhattan",
    "west village": "manhattan",
    "w village": "manhattan",
    "tribeca": "manhattan",
    "soho": "manhattan",
    "noho": "manhattan",
    "chelsea": "manhattan",
    "hells kitchen": "manhattan",
    "clinton": "manhattan",
    "harlem": "manhattan",
    "east harlem": "manhattan",
    "e harlem": "manhattan",
    "upper east side": "manhattan",
    "upper e side": "manhattan",
    "upper west side": "manhattan",
    "upper w side": "manhattan",
    "midtown": "manhattan",
    "midtown e": "manhattan",
    "midtown east": "manhattan",
    "midtown w": "manhattan",
    "midtown west": "manhattan",
    "murray hill": "manhattan",
    "gramercy": "manhattan",
    "gramercy park": "manhattan",
    "flatiron": "manhattan",
    "nolita": "manhattan",
    "little italy": "manhattan",
    "chinatown": "manhattan",
    "financial district": "manhattan",
    "fidi": "manhattan",
    "battery park city": "manhattan",
    "two bridges": "manhattan",
    "kips bay": "manhattan",
    "yorkville": "manhattan",
    "inwood": "manhattan",
    "washington heights": "manhattan",
    "morningside heights": "manhattan",
    "hamilton heights": "manhattan",
    "williamsburg": "brooklyn",
    "greenpoint": "brooklyn",
    "east williamsburg": "brooklyn",
    "e williamsburg": "brooklyn",
    "bushwick": "brooklyn",
    "bedford stuyvesant": "brooklyn",
    "bed-stuy": "brooklyn",
    "bed stuy": "brooklyn",
    "prospect heights": "brooklyn",
    "park slope": "brooklyn",
    "south slope": "brooklyn",
    "fort greene": "brooklyn",
    "clinton hill": "brooklyn",
    "cobble hill": "brooklyn",
    "boerum hill": "brooklyn",
    "dumbo": "brooklyn",
    "brooklyn heights": "brooklyn",
    "crown heights": "brooklyn",
    "cypress hills": "brooklyn",
    "windsor terrace": "brooklyn",
    "prospect lefferts gardens": "brooklyn",
    "plg": "brooklyn",
    "gowanus": "brooklyn",
    "red hook": "brooklyn",
    "carroll gardens": "brooklyn",
    "long island city": "queens",
    "lic": "queens",
    "astoria": "queens",
    "sunnyside": "queens",
    "woodside": "queens",
    "jackson heights": "queens",
    "ridgewood": "queens",
    "maspeth": "queens",
    "forest hills": "queens",
    "flushing": "queens",
    "mott haven": "bronx",
    "south bronx": "bronx",
    "s bronx": "bronx",
    "fordham": "bronx",
    "riverdale": "bronx",
    "pelham bay": "bronx",
}

OFFICIAL_DIRECTIONALS = {
    "e": "EAST",
    "w": "WEST",
    "n": "NORTH",
    "s": "SOUTH",
}

OFFICIAL_STREET_TYPES = {
    "st": "STREET",
    "ave": "AVENUE",
    "rd": "ROAD",
    "pl": "PLACE",
    "blvd": "BOULEVARD",
    "dr": "DRIVE",
    "ct": "COURT",
    "ln": "LANE",
    "ter": "TERRACE",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")


def read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str] | None = None) -> None:
    ensure_dir(path.parent)
    normalized_rows = list(rows)
    if fieldnames is None:
        discovered: list[str] = []
        for row in normalized_rows:
            for key in row.keys():
                if key not in discovered:
                    discovered.append(key)
        fieldnames = discovered
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in normalized_rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def stable_hash(*parts: Any, length: int = 12) -> str:
    joined = "||".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered)
    return lowered.strip("-") or "item"


def canonical_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"#\s*([a-z0-9-]+)", r" apartment \1", text)
    text = re.sub(r"\beast\b", "e", text)
    text = re.sub(r"\bwest\b", "w", text)
    text = re.sub(r"\bnorth\b", "n", text)
    text = re.sub(r"\bsouth\b", "s", text)
    text = re.sub(r"\bavenue\b", "ave", text)
    text = re.sub(r"\bstreet\b", "st", text)
    text = re.sub(r"\broad\b", "rd", text)
    text = re.sub(r"\bplace\b", "pl", text)
    text = re.sub(r"\bapartment\b", "apt", text)
    text = re.sub(r"\bunit\b", "apt", text)
    text = re.sub(r"[^a-z0-9#@.\-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonical_address(value: Any) -> str:
    return canonical_text(value)


def building_address(value: Any) -> str:
    text = canonical_address(value)
    text = re.sub(r"\bapt\b\s+[a-z0-9-]+", "", text)
    text = re.sub(r"\b(?:floor|fl)\b\s+[a-z0-9-]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _looks_like_house_number(token: str) -> bool:
    """Return True if the token could be a NYC house number.

    NYC house numbers are digits, optionally hyphenated (e.g. "21-46").
    Pure alphabetic tokens like "madison" or "w" are NOT house numbers.
    """
    return bool(re.fullmatch(r"\d[\d\-]*[a-z]?", token))


def address_lookup_parts(value: Any) -> tuple[str | None, list[str]]:
    """Extract (house_number, street_tokens) for HPD lookup.

    Returns (None, street_tokens) if no house number can be identified.
    This prevents pure-street addresses like "madison st" from having
    "madison" treated as the house number.
    """
    text = building_address(value)
    if not text:
        return None, []
    tokens = text.split()
    if not tokens:
        return None, []

    # First token must look like a house number (starts with digit)
    if _looks_like_house_number(tokens[0]):
        house_number = tokens[0]
        rest = tokens[1:]
    else:
        house_number = None
        rest = tokens

    street_tokens: list[str] = []
    for token in rest:
        if token == "apt":
            break
        street_tokens.append(token)
    return house_number, street_tokens


def official_street_name(value: Any) -> str | None:
    """Convert street tokens into the HPD official street name format.

    Examples:
        "e 5th st" → "EAST 5 STREET"
        "kent ave." → "KENT AVENUE"
        "ocean parkway" → "OCEAN PARKWAY"
    """
    _, street_tokens = address_lookup_parts(value)
    if not street_tokens:
        return None
    normalized: list[str] = []
    for token in street_tokens:
        # Strip trailing periods (common in abbreviations like "ave.", "st.")
        clean = token.rstrip(".")
        if not clean:
            continue
        if clean in OFFICIAL_DIRECTIONALS:
            normalized.append(OFFICIAL_DIRECTIONALS[clean])
            continue
        if clean in OFFICIAL_STREET_TYPES:
            normalized.append(OFFICIAL_STREET_TYPES[clean])
            continue
        match = re.fullmatch(r"(\d+)(st|nd|rd|th)", clean)
        if match:
            normalized.append(match.group(1))
            continue
        normalized.append(clean.upper())
    return " ".join(normalized) if normalized else None


def normalize_borough(value: Any) -> str | None:
    """Convert any borough-like string to the official lowercase key.

    Handles official names ("Manhattan"), aliases ("New York"),
    sub-neighborhoods used as boroughs ("Far Rockaway" → "queens"), etc.
    Returns None if the value can't be mapped.
    """
    if not value:
        return None
    text = canonical_text(value)
    # Direct match first
    if text in BOROUGH_TO_NAME:
        return text
    # Alias lookup
    return BOROUGH_ALIASES.get(text)


def infer_borough(neighborhood: str | None, zip_code: str | None = None) -> str | None:
    """Infer borough from neighborhood name, falling back to ZIP prefix.

    This is the main tool for filling in missing borough data. StreetEasy
    and other sources often provide neighborhood but not borough.
    """
    if neighborhood:
        key = canonical_text(neighborhood)
        if key in NEIGHBORHOOD_BOROUGH:
            return NEIGHBORHOOD_BOROUGH[key]
        # Also try the alias map (some neighborhoods are also borough aliases)
        if key in BOROUGH_ALIASES:
            return BOROUGH_ALIASES[key]

    # ZIP prefix fallback
    if zip_code and len(str(zip_code)) >= 3:
        prefix = str(zip_code)[:3]
        zip_to_borough = {
            "100": "manhattan", "101": "manhattan", "102": "manhattan",
            "103": "staten island",
            "104": "bronx",
            "110": "queens", "111": "queens", "113": "queens",
            "114": "queens", "115": "queens", "116": "queens",
            "112": "brooklyn",
        }
        return zip_to_borough.get(prefix)

    return None


def borough_name(value: Any) -> str | None:
    """Map to official HPD borough name (uppercase). Handles aliases."""
    text = normalize_borough(value)
    if not text:
        # Try the raw value too
        raw = canonical_text(value) if value else None
        if raw:
            text = BOROUGH_ALIASES.get(raw)
    return BOROUGH_TO_NAME.get(text) if text else None


def borough_code(value: Any) -> str | None:
    """Map to HPD borough code (1-5). Handles aliases."""
    text = normalize_borough(value)
    if not text:
        raw = canonical_text(value) if value else None
        if raw:
            text = BOROUGH_ALIASES.get(raw)
    return BOROUGH_TO_HPD_CODE.get(text) if text else None


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text == "studio":
        return 0.0
    text = text.replace(",", "")
    text = re.sub(r"[^0-9.\-]+", "", text)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "present", "available"}:
        return True
    if text in {"0", "false", "no", "n", "absent", "unavailable"}:
        return False
    return None


def parse_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    parts = text.split("|") if "|" in text else text.split(",")
    return [part.strip() for part in parts if part.strip()]


def tokenize(*chunks: Any) -> list[str]:
    text = " ".join("" if chunk is None else str(chunk) for chunk in chunks).lower()
    return re.findall(r"[a-z0-9]+", text)


def first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def address_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def iso_age_days(iso_text: str | None) -> int | None:
    if not iso_text:
        return None
    try:
        value = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    except ValueError:
        return None
    delta = datetime.now(timezone.utc) - value.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() // 86400))


def latest_file(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.glob(pattern))
    return matches[-1] if matches else None


def relocated_path(path_like: str | Path | None, fallback_dir: Path | None = None) -> Path | None:
    if not path_like:
        return None
    candidate = Path(path_like)
    if candidate.exists():
        return candidate
    if fallback_dir:
        fallback = fallback_dir / candidate.name
        if fallback.exists():
            return fallback
    return None


def state_path_or_latest(path_like: str | Path | None, directory: Path, pattern: str) -> Path | None:
    resolved = relocated_path(path_like, directory)
    if resolved and resolved.exists():
        return resolved
    return latest_file(directory, pattern)


def render_markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join(["---"] * len(headers)) + " |"
    body_lines = [
        "| " + " | ".join("" if value is None else str(value) for value in row) + " |"
        for row in rows
    ]
    return "\n".join([header_line, divider, *body_lines])


def top_keywords(texts: Iterable[str], limit: int = 10, stopwords: set[str] | None = None) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    blocked = stopwords or set()
    for text in texts:
        for token in tokenize(text):
            if len(token) < 3 or token in blocked:
                continue
            counts[token] = counts.get(token, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def classify_record_link(
    listing_address: str | None,
    reference_address: str | None,
    listing_owner: str | None,
    reference_owner: str | None,
    listing_neighborhood: str | None,
) -> str:
    """Classify the record-link confidence between a listing and a public record match."""
    if not listing_address and not reference_address:
        if listing_neighborhood:
            return "neighborhood_only"
        return "no_record_match"

    if not listing_address or not reference_address:
        if listing_neighborhood:
            return "neighborhood_only"
        return "no_record_match"

    canon_listing = canonical_address(listing_address)
    canon_ref = canonical_address(reference_address)

    if not canon_listing or not canon_ref:
        return "no_record_match"

    similarity = address_similarity(canon_listing, canon_ref)

    if similarity >= 0.95:
        return "exact_address_match"
    if similarity >= 0.80:
        # Check building-level match
        building_listing = building_address(listing_address)
        building_ref = building_address(reference_address)
        building_sim = address_similarity(building_listing, building_ref)
        if building_sim >= 0.90:
            return "building_level_match"
        return "strong_partial_address_match"
    if similarity >= 0.65:
        return "strong_partial_address_match"

    # Weak address — check if owner name helps
    if listing_owner and reference_owner:
        owner_sim = address_similarity(
            canonical_text(listing_owner), canonical_text(reference_owner)
        )
        if owner_sim >= 0.70:
            return "owner_name_assisted_match"

    if listing_neighborhood:
        return "neighborhood_only"
    return "no_record_match"


def search_mode_for_source(source: dict) -> str:
    """Return the search mode constant for a source catalog entry."""
    mode = str(source.get("search_mode", "permanent")).lower()
    if mode == "bridge":
        return SEARCH_MODE_BRIDGE
    return SEARCH_MODE_PERMANENT

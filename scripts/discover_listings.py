#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow_support import ensure_dir, read_json, utc_now_iso, utc_stamp, write_json, write_text

from config.paths import VERA_ROOT as ROOT, CONFIG_DIR as CONFIG_ROOT, LOG_DIR as LOG_ROOT, LEGACY_STATE_DIR as STATE_ROOT, RAW_DIR
from config.stage_tracker import write_stage_start, write_stage_end, get_run_id
from config.anomaly_detector import check_source_anomalies
from config.source_reliability import record_source_run

RUN_STAMP = utc_stamp()
PARSER_VERSION = "2026-07-29a"

# Per-source extraction strategy metadata.
# strategy_used: primary extraction method for each source.
# base_confidence: baseline confidence when parser succeeds without errors.
SOURCE_STRATEGIES: dict[str, dict[str, Any]] = {
    "streeteasy": {"strategy_used": "embedded_search_nodes", "base_confidence": 0.90},
    "renthop": {"strategy_used": "json_ld_detail_page", "base_confidence": 0.92},
    "craigslist": {"strategy_used": "search_api_json_detail_html", "base_confidence": 0.80},
    "leasebreak": {"strategy_used": "html_dom_selectors", "base_confidence": 0.65},
    "nybits": {"strategy_used": "html_dom_selectors", "base_confidence": 0.60},
    "housing_connect": {"strategy_used": "html_dom_selectors", "base_confidence": 0.50},
    "hdc_hpd_rerentals": {"strategy_used": "html_dom_selectors", "base_confidence": 0.50},
    "nooklyn": {"strategy_used": "html_dom_selectors", "base_confidence": 0.55},
    "listings_project": {"strategy_used": "html_text_heuristic", "base_confidence": 0.45},
    "reddit_nycapartments": {"strategy_used": "atom_feed_leads", "base_confidence": 0.35},
    "spareroom": {"strategy_used": "html_dom_selectors", "base_confidence": 0.55},
}


def source_extraction_meta(source_name: str, ok_queries: int = 0, total_queries: int = 0) -> dict[str, Any]:
    """Compute extraction strategy and confidence for a source."""
    meta = SOURCE_STRATEGIES.get(source_name, {"strategy_used": "unknown", "base_confidence": 0.50})
    base = meta["base_confidence"]
    if total_queries > 0:
        query_success_rate = ok_queries / total_queries
        confidence = round(base * query_success_rate, 2)
    else:
        confidence = base
    return {
        "strategy_used": meta["strategy_used"],
        "extraction_confidence": confidence,
        # Carried so finalize_source_statuses() can tell a source that failed
        # from one that genuinely found nothing. Every discovery function
        # hardcodes "status": "ok" in its manifest entry, so without these
        # two numbers the manifest cannot distinguish the two cases at all.
        "queries_ok": ok_queries,
        "queries_total": total_queries,
    }


def finalize_source_statuses(manifest: dict[str, Any], log_lines: list[str]) -> None:
    """Replace asserted success with what actually happened.

    All nineteen discovery functions write `"status": "ok"` unconditionally,
    so a source could fail every single query and still report green. The
    only thing catching that was a history comparison in build_snapshot —
    which needs a baseline of past runs, and cloud runs start from a fresh
    checkout with no history at all. On 2026-08-04 that combination had
    streeteasy reading `ok` in the published cloud feed while contributing
    zero listings.

    This is deliberately history-free: it reads only this run's own query
    outcomes, so it is correct on the very first run on a new machine.
    """
    for entry in manifest.get("sources", []):
        if entry.get("status") != "ok":
            continue
        total = entry.get("queries_total") or 0
        ok = entry.get("queries_ok") or 0
        if total <= 0:
            continue
        name = entry.get("source_name", "?")
        if ok == 0:
            entry["status"] = "failing"
            entry["reason"] = f"all {total} queries failed"
            log_lines.append(f"{name}: every query failed — reported as failing, not ok")
        elif ok < total:
            entry["status"] = "partial"
            entry["reason"] = f"{total - ok} of {total} queries failed"
            log_lines.append(f"{name}: {total - ok}/{total} queries failed — reported as partial")


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

BOROUGH_NAME_TO_SITE = {
    "manhattan": "mnh",
    "brooklyn": "brk",
    "queens": "que",
    "bronx": "brx",
    "staten island": "stn",
}

BOROUGH_SITE_TO_NAME = {
    "mnh": "Manhattan",
    "brk": "Brooklyn",
    "que": "Queens",
    "brx": "Bronx",
    "stn": "Staten Island",
}

PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4}))\b")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PRICE_RE = re.compile(r"\$([0-9oO,]{3,})")
URL_RE = re.compile(r"https://newyork\.craigslist\.org/[^\"]+/apa/d/[^\"]+\.html")
SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.S | re.I)
STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")


def source_output_dir(source: dict[str, Any]) -> Path:
    return ensure_dir(ROOT / "raw" / source["source_name"])


def snapshot_path_for_source(source_name: str, snapshot_path: str | None) -> Path | None:
    if not snapshot_path:
        return None
    candidate = Path(snapshot_path)
    if candidate.exists():
        return candidate
    fallback = ROOT / "raw" / source_name / candidate.name
    if fallback.exists():
        return fallback
    return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def read_text_url(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore")


def read_text_url_final(url: str, timeout: int = 25) -> tuple[str, str]:
    """Fetch a URL and return (body, final_url) so redirects reveal the canonical URL."""
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "ignore"), str(response.url or url)


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def clean_html_text(fragment: str, preserve_newlines: bool = False) -> str:
    text = SCRIPT_RE.sub(" ", fragment)
    text = STYLE_RE.sub(" ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\r", "\n")
    if preserve_newlines:
        text = re.sub(r"[ \t\f\v]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return "\n".join(line.strip() for line in text.splitlines()).strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def normalize_numeric_text(value: str) -> str:
    return value.replace("o", "0").replace("O", "0").replace(",", "").strip()


def extract_price(*texts: str) -> int | None:
    for text in texts:
        for raw in PRICE_RE.findall(text or ""):
            normalized = normalize_numeric_text(raw)
            if normalized.isdigit():
                value = int(normalized)
                if 400 <= value <= 20000:
                    return value
    return None


def extract_phone(text: str) -> str | None:
    match = PHONE_RE.search(text)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def extract_email(text: str) -> str | None:
    match = EMAIL_RE.search(text or "")
    return match.group(0) if match else None


def extract_contact_name(body_lines: list[str], phone: str | None, email: str | None) -> str | None:
    pivots = [value for value in [phone, email] if value]
    for pivot in pivots:
        for index, line in enumerate(body_lines):
            if pivot in line and index + 1 < len(body_lines):
                candidate = body_lines[index + 1].strip(" -")
                if re.fullmatch(r"[A-Za-z][A-Za-z .'\-]{1,60}", candidate):
                    return candidate
    return None


def extract_address(body_lines: list[str], ld_address: dict[str, Any]) -> str | None:
    street_address = str(ld_address.get("streetAddress") or "").strip()
    if street_address:
        return street_address
    pattern = re.compile(
        r"\b\d{1,5}\s+[A-Za-z0-9.'\- ]+\b(?:street|st|avenue|ave|road|rd|boulevard|blvd|place|pl|court|ct|lane|ln|drive|dr|terrace|ter)\b(?:\s+(?:apt|#)\s*[A-Za-z0-9-]+)?",
        re.I,
    )
    for line in body_lines:
        match = pattern.search(line)
        if match:
            return match.group(0).strip(" ,")
    return None


def extract_posted_at(page: str) -> str | None:
    match = re.search(r'<time class="date(?: timeago)?" datetime="([^"]+)"', page)
    if not match:
        return None
    raw = match.group(1).strip()
    for parser in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, parser).isoformat()
        except ValueError:
            continue
    return raw


def extract_square_feet(page: str, body: str, title: str) -> int | None:
    for text in [page, body, title]:
        match = re.search(r"\b([0-9]{2,4})\s*ft", text, re.I)
        if match:
            return int(match.group(1))
    return None


def extract_image_urls(page: str) -> list[str]:
    """Up to 6 unique full-size gallery images.

    Detail pages list every image twice (600x450 full + 50x50c thumb); skip thumbs
    and dedupe by the image id so each photo appears once at full size.
    """
    urls = re.findall(r"https://images\.craigslist\.org/[A-Za-z0-9_/-]+\.jpg", page)
    full_size: list[str] = []
    seen_ids: set[str] = set()
    for url in urls:
        if "50x50" in url:
            continue
        image_id = re.sub(r"_\d+x\d+c?\.jpg$", "", url.rsplit("/", 1)[-1])
        if image_id in seen_ids:
            continue
        seen_ids.add(image_id)
        full_size.append(url)
        if len(full_size) >= 6:
            break
    return full_size


def extract_ld_posting_data(page: str) -> dict[str, Any]:
    match = re.search(r'<script[^>]+id="ld_posting_data"[^>]*>(.*?)</script>', page, re.S | re.I)
    if not match:
        return {}
    try:
        return json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return {}


def borough_from_craigslist_url(url: str) -> str | None:
    # Restrict to real borough codes: sapi-era detail URLs omit the subarea segment,
    # and a generic 3-letter match would wrongly capture the "apa" category segment.
    match = re.search(r"newyork\.craigslist\.org/(mnh|brk|que|brx|stn)/", url)
    if not match:
        return None
    return BOROUGH_SITE_TO_NAME.get(match.group(1))


def listing_id_from_url(url: str) -> str | None:
    match = re.search(r"/([0-9]{7,})\.html", url)
    return match.group(1) if match else None


# 2026-07-28: craigslist detail pages moved to www.craigslist.org/view/d/<slug>/<opaque-id>.
# The opaque id is not the posting id and the URL carries no borough subarea, but the page's
# ld_breadcrumb_data still links craigslist.org/area/newyork and craigslist.org/subarea/<code>.
CRAIGSLIST_SUBAREA_RE = re.compile(r"craigslist\.org/(?:search/)?subarea/(mnh|brk|que|brx|stn)\b")
CRAIGSLIST_VIEW_SLUG_RE = re.compile(r"craigslist\.org/view/d/([^/]+)/")


def canonical_craigslist_url(requested_url: str, final_url: str, page: str) -> str:
    """Return the borough-scoped newyork.craigslist.org detail URL for a posting.

    Craigslist used to 301 /apa/d/<slug>/<id>.html to the canonical borough URL; as of
    2026-07-28 it 301s to www.craigslist.org/view/d/<slug>/<opaque-id> instead. Rebuild
    the historical URL from the search-side posting id plus the breadcrumb subarea so the
    posting id, borough inference and downstream listing_uid stay stable. Fall back to the
    redirect target when the page is not a recognizable NYC-borough posting -- the caller's
    off-area filter then drops it, which is the correct outcome.
    """
    if "newyork.craigslist.org" in final_url and borough_from_craigslist_url(final_url):
        return final_url
    posting_id = listing_id_from_url(requested_url) or listing_id_from_url(final_url)
    subarea_match = CRAIGSLIST_SUBAREA_RE.search(page)
    slug_match = CRAIGSLIST_VIEW_SLUG_RE.search(final_url) or re.search(r"/apa/d/([^/]+)/", requested_url)
    if not (posting_id and subarea_match and slug_match):
        return final_url
    return (
        f"https://newyork.craigslist.org/{subarea_match.group(1)}/apa/d/"
        f"{slug_match.group(1)}/{posting_id}.html"
    )


def infer_fee_status(title: str, body: str) -> str:
    lowered = f"{title} {body}".lower()
    if "no fee" in lowered or "no broker" in lowered or "no broker fee" in lowered:
        return "no fee"
    if "broker fee" in lowered or "fee applies" in lowered:
        return "fee"
    return "unknown"


def infer_pet_policy(page: str, body: str) -> str | None:
    lowered = f"{page} {body}".lower()
    cats = "cats are ok" in lowered or "cats allowed" in lowered
    dogs = "dogs are ok" in lowered or "dogs allowed" in lowered
    if cats and dogs:
        return "Cats and dogs allowed"
    if cats:
        return "Cats allowed"
    if dogs:
        return "Dogs allowed"
    if "no pets" in lowered:
        return "No pets"
    return None


def infer_amenities(page: str, body: str) -> list[str]:
    lowered = f"{page} {body}".lower()
    amenity_map = {
        "dishwasher": "dishwasher",
        "laundry": "laundry",
        "hardwood": "hardwood floors",
        "street parking": "street parking",
        "garage": "garage",
        "roof deck": "roof deck",
        "furnished": "furnished",
        "air conditioning": "air conditioning",
        "elevator": "elevator",
    }
    amenities = [label for needle, label in amenity_map.items() if needle in lowered]
    return unique_strings(amenities)


CRAIGSLIST_SAPI_BASE = "https://sapi.craigslist.org/web/v8/postings/search/full"


def build_craigslist_searches(source: dict[str, Any], preferences: dict[str, Any]) -> list[dict[str, str]]:
    """Build craigslist search-API URLs.

    2026-07: newyork.craigslist.org/search/apa now 301s to a www.craigslist.org JS shell
    with no result links in the HTML (JSON-LD there has no URLs either). The shell loads
    results from the public sapi.craigslist.org JSON endpoint, which works with plain
    urllib + the browser UA, so that endpoint is now the search data source.
    "batch=3-0-360-0-0" scopes the search to area 3 (newyork).
    """
    query_terms = list(source.get("query_terms") or preferences.get("neighborhoods") or [])
    max_rent = source.get("max_price") or preferences.get("max_rent") or 2500
    configured = str(source.get("search_base_url") or "")
    base_url = configured if "sapi.craigslist.org" in configured else CRAIGSLIST_SAPI_BASE
    searches: list[dict[str, str]] = []
    for term in query_terms:
        # Borough-name terms become borough-scoped searches (searchPath=mnh/apa etc.).
        # Posters pick their neighborhood from a dropdown and often never write it in
        # the ad text, so free-text neighborhood queries miss most real inventory
        # while attracting keyword-stuffed spam. Non-borough terms stay text queries.
        borough_code = BOROUGH_NAME_TO_SITE.get(term.strip().lower())
        params = {
            "batch": "3-0-360-0-0",
            "cc": "US",
            "lang": "en",
            "searchPath": f"{borough_code}/apa" if borough_code else "apa",
            "max_price": str(int(float(max_rent))),
            "min_bedrooms": "0",
            "max_bedrooms": "1",
            # Newest first (the old HTML search default). Relevance order front-loads
            # stale cross-borough spam clusters into the per-query candidate slots.
            "sort": "date",
        }
        if not borough_code:
            params["query"] = term
        searches.append(
            {
                "label": term,
                "url": f"{base_url}?{urllib.parse.urlencode(params)}",
            }
        )
    return searches


def allowed_craigslist_boroughs(preferences: dict[str, Any]) -> set[str]:
    boroughs = preferences.get("boroughs") or []
    allowed = {
        BOROUGH_NAME_TO_SITE.get(str(borough).strip().lower())
        for borough in boroughs
        if str(borough).strip()
    }
    return {code for code in allowed if code}


def cache_is_fresh(entry: dict[str, Any], ttl_hours: int) -> bool:
    fetched_at = parse_iso(entry.get("fetched_at"))
    if not fetched_at:
        return False
    return fetched_at >= now_utc() - timedelta(hours=ttl_hours)


def extract_listing_urls(search_body: str, max_results: int) -> list[str]:
    """Extract detail-page URLs from a craigslist search response.

    Primary path (2026-07): the response is sapi.craigslist.org JSON. Each item array
    carries a posting-id offset at index 0 (real id = decode.minPostingId + offset) and
    a [6, "<slug>"] element with the URL slug. The borough subarea cannot be decoded
    reliably from the item, so URLs are built without it -- craigslist 301s
    /apa/d/<slug>/<id>.html to the canonical borough URL at fetch time.
    Falls back to the legacy HTML regex for old-style search pages.
    """
    try:
        payload = json.loads(search_body)
    except json.JSONDecodeError:
        return unique_strings(URL_RE.findall(search_body))[:max_results]
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    decode = data.get("decode") if isinstance(data.get("decode"), dict) else {}
    min_posting_id = int(decode.get("minPostingId") or 0)
    # Items after firstNearbyResultId belong to other craigslist areas (New Haven,
    # Boston, ...) and 404 when built against newyork; take in-area results only.
    first_nearby_id = data.get("firstNearbyResultId")
    total_in_area = data.get("totalResultCount")
    items = list(data.get("items") or [])
    if isinstance(total_in_area, int) and 0 <= total_in_area < len(items):
        items = items[:total_in_area]
    urls: list[str] = []
    for item in items:
        if not (isinstance(item, list) and item and isinstance(item[0], int)):
            continue
        posting_id = min_posting_id + item[0]
        if posting_id <= 0:
            continue
        if isinstance(first_nearby_id, int) and posting_id == first_nearby_id:
            break
        slug = "apt"
        for element in item:
            if (
                isinstance(element, list)
                and len(element) >= 2
                and element[0] == 6
                and isinstance(element[1], str)
                and element[1]
            ):
                slug = element[1]
                break
        urls.append(f"https://newyork.craigslist.org/apa/d/{slug}/{posting_id}.html")
    return unique_strings(urls)[:max_results]


def parse_craigslist_detail(url: str, query_label: str) -> dict[str, Any]:
    page, final_url = read_text_url_final(url)
    # 2026-07-28: craigslist stopped redirecting /apa/d/<slug>/<id>.html to the borough
    # canonical URL and now serves www.craigslist.org/view/d/<slug>/<opaque-id>, which
    # carries neither the numeric posting id nor the borough subarea. Rebuild the
    # borough-scoped URL from the posting id plus the page's ld_breadcrumb_data so ids,
    # borough inference and listing_uid stay stable across the migration.
    url = canonical_craigslist_url(url, final_url, page)
    ld_posting = extract_ld_posting_data(page)
    ld_address = ld_posting.get("address") if isinstance(ld_posting.get("address"), dict) else {}

    title_match = re.search(r'<span id="titletextonly">(.*?)</span>', page, re.S)
    title = clean_html_text(title_match.group(1)) if title_match else str(ld_posting.get("name") or "").strip()
    title = re.sub(r"^\$[0-9oO,]+\s*", "", title).strip(" -") or "Craigslist apartment listing"

    body_match = re.search(r'<section id="postingbody">(.*?)</section>', page, re.S)
    raw_body = body_match.group(1) if body_match else ""
    body = clean_html_text(raw_body, preserve_newlines=True)
    body = body.replace("QR Code Link to This Post", "").strip()
    body_lines = [line.strip() for line in body.splitlines() if line.strip()]
    body_text = "\n".join(body_lines)

    price = extract_price(body_text, title, page)
    bedrooms = ld_posting.get("numberOfBedrooms")
    bathrooms = ld_posting.get("numberOfBathroomsTotal")
    square_feet = extract_square_feet(page, body_text, title)
    phone = extract_phone(body_text)
    email = extract_email(body_text)
    contact_name = extract_contact_name(body_lines, phone, email)
    posted_at = extract_posted_at(page) or utc_now_iso()
    image_urls = extract_image_urls(page)

    record = {
        "id": f"cl-live-{listing_id_from_url(url) or RUN_STAMP}",
        "url": url,
        "title": title,
        "body": body_text,
        "map_address": extract_address(body_lines, ld_address),
        "borough": borough_from_craigslist_url(url),
        "neighborhood_hint": query_label,
        "postal_code": ld_address.get("postalCode"),
        "price": price,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "sqft": square_feet,
        "fee_status": infer_fee_status(title, body_text),
        "contact_name": contact_name,
        "phone": phone,
        "email": email,
        "pet_policy": infer_pet_policy(page, body_text),
        "amenities": infer_amenities(page, body_text),
        "image_urls": image_urls,
        "posted_at": posted_at,
        "lat": ld_posting.get("latitude"),
        "lon": ld_posting.get("longitude"),
        "source_listing_id": listing_id_from_url(url),
    }
    return record


STREETEASY_NEIGHBORHOOD_SLUGS = {
    "East Village": "east-village",
    "Alphabet City": "east-village",
    "Greenwich Village": "greenwich-village",
    "Lower East Side": "les",
    "Stuytown": "stuyvesant-town",
    "West Village": "west-village",
    "Tribeca": "tribeca",
    "SoHo": "soho",
    "Chelsea": "chelsea",
    "Williamsburg": "williamsburg",
    "Greenpoint": "greenpoint",
    "East Williamsburg": "east-williamsburg",
}

RENTHOP_NEIGHBORHOOD_NAMES = [
    "East Village",
    "Alphabet City",
    "Greenwich Village",
    "Lower East Side",
    "Stuyvesant Town",
    "West Village",
    "Tribeca",
    "SoHo",
    "Chelsea",
    "Williamsburg",
    "Greenpoint",
    "East Williamsburg",
]

SE_LISTING_DATA_RE = re.compile(r"listingData\\\\\":\{\\\\\"search\\\\\":\{\\\\\"criteria\\\\\":\\\\\"[^\"]+\\\\\"\},\\\\\"totalCount\\\\\":\d+,\\\\\"edges\\\\\":\[(.+?)\]\}")
SE_NODE_RE = re.compile(r"\{\\\\\"node\\\\\":\{(.*?)\}\}(?:,\{\\\\\"node\\\\\"|\])")
RH_DETAIL_URL_RE = re.compile(r'href="(https://www\.renthop\.com/listings/[^"]+)"')
RH_LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


NEXT_FLIGHT_PUSH_RE = re.compile(
    r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\s*\]\)', re.S
)
NEXT_FLIGHT_CHUNK_RE = re.compile(r"(?:^|\n)([0-9a-fA-F]{1,4}):")


def _next_flight_stream(page_html: str) -> str:
    """Reassemble a Next.js React Flight stream from its script segments.

    Used for StreetEasy and openigloo (both Next.js App Router sites). Chunks can be
    split mid-JSON across consecutive self.__next_f.push() calls, so the string
    payloads must be concatenated in document order before chunk parsing.
    """
    segments = NEXT_FLIGHT_PUSH_RE.findall(page_html)
    decoded: list[str] = []
    for segment in segments:
        try:
            decoded.append(json.loads(f'"{segment}"'))
        except json.JSONDecodeError:
            # Manual unescape; \x00 placeholder keeps escaped backslashes intact.
            cleaned = segment.replace("\\\\", "\x00").replace('\\"', '"').replace("\\n", "\n")
            decoded.append(cleaned.replace("\x00", "\\"))
    return "".join(decoded)


def _next_flight_chunks(stream: str) -> dict[str, Any]:
    """Parse a reassembled flight stream into its JSON-parseable numbered chunks."""
    chunks: dict[str, Any] = {}
    boundaries = list(NEXT_FLIGHT_CHUNK_RE.finditer(stream))
    for index, boundary in enumerate(boundaries):
        end = boundaries[index + 1].start() if index + 1 < len(boundaries) else len(stream)
        body = stream[boundary.end() : end].strip()
        if not body or body[0] not in "{[":
            continue
        try:
            chunks[boundary.group(1)] = json.loads(body)
        except json.JSONDecodeError:
            continue
    return chunks


def _resolve_flight_ref(value: Any, chunks: dict[str, Any], depth: int = 0) -> Any:
    """Resolve React Flight "$<chunk-id>" references against the chunk map."""
    if depth > 4:
        return value
    if isinstance(value, str) and value.startswith("$"):
        key = value[1:]
        if key[:1] in {"L", "@"}:
            key = key[1:]
        if key in chunks:
            return _resolve_flight_ref(chunks[key], chunks, depth + 1)
        return value
    if isinstance(value, list):
        return [_resolve_flight_ref(entry, chunks, depth + 1) for entry in value]
    return value


def extract_streeteasy_nodes(page_html: str) -> list[dict[str, Any]]:
    """Extract listing nodes from StreetEasy's embedded search state.

    2026-07: search results moved into the Next.js React Flight stream. listingData's
    "edges" now holds only a "$<id>" reference; each edge wrapper and listing node is
    its own numbered flight chunk (node field names are unchanged). Parse the chunk
    map, take every edge-wrapper chunk, and resolve node/geoPoint/photos references.
    Falls back to the pre-2026-07 inline "edges":[{"node":{...}}] blob format.
    """
    stream = _next_flight_stream(page_html)
    if stream:
        chunks = _next_flight_chunks(stream)
        nodes: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for chunk in chunks.values():
            if not (
                isinstance(chunk, dict)
                and "node" in chunk
                and str(chunk.get("__typename") or "").endswith("Edge")
            ):
                continue
            node = _resolve_flight_ref(chunk["node"], chunks)
            if not (isinstance(node, dict) and node.get("id") is not None and "urlPath" in node):
                continue
            node = dict(node)
            node["geoPoint"] = _resolve_flight_ref(node.get("geoPoint"), chunks)
            node["photos"] = _resolve_flight_ref(node.get("photos"), chunks)
            node_id = str(node.get("id"))
            if node_id in seen_ids:
                continue
            seen_ids.add(node_id)
            nodes.append(node)
        if nodes:
            return nodes

    # Legacy fallback: inline "edges":[{"node":{...}}] blob (pre-2026-07 markup).
    idx = page_html.find("listingData")
    if idx < 0:
        return []
    chunk = page_html[idx : idx + 200000]
    unescaped = chunk.replace('\\"', '"').replace("\\\\", "\\")
    edges_start = unescaped.find('"edges":[{"node"')
    if edges_start < 0:
        return []
    data_str = unescaped[edges_start + 9:]
    nodes = []
    pos = 0
    while pos < len(data_str) and len(nodes) < 100:
        node_start = data_str.find('{"node":{', pos)
        if node_start < 0:
            break
        depth = 0
        i = node_start
        while i < len(data_str):
            if data_str[i] == "{":
                depth += 1
            elif data_str[i] == "}":
                depth -= 1
            if depth == 0:
                break
            i += 1
        wrapper_str = data_str[node_start : i + 1]
        try:
            wrapper = json.loads(wrapper_str)
            node = wrapper.get("node", wrapper)
            nodes.append(node)
        except json.JSONDecodeError:
            pass
        pos = i + 1
    return nodes


def streeteasy_node_to_record(node: dict[str, Any], query_label: str) -> dict[str, Any]:
    """Convert a StreetEasy listing node to a raw record."""
    listing_id = str(node.get("id") or "")
    street = str(node.get("street") or "").strip()
    unit = str(node.get("displayUnit") or node.get("unit") or "").strip()
    address = f"{street} {unit}".strip() if street else None
    photos = node.get("photos") or []
    image_urls = [p["url"] for p in photos if isinstance(p, dict) and p.get("url")]
    geo = node.get("geoPoint") or {}
    url_path = node.get("urlPath") or ""
    full_url = f"https://streeteasy.com{url_path}" if url_path else None

    return {
        "id": f"se-live-{listing_id}",
        "url": full_url,
        "title": f"{street} {unit}".strip() or "StreetEasy listing",
        "body": "",
        "map_address": address,
        "borough": None,
        "neighborhood_hint": node.get("areaName") or query_label,
        "postal_code": node.get("zipCode"),
        "price": node.get("price"),
        "bedrooms": node.get("bedroomCount"),
        "bathrooms": (node.get("fullBathroomCount") or 0) + (node.get("halfBathroomCount") or 0) * 0.5,
        "sqft": node.get("livingAreaSize") if node.get("livingAreaSize") else None,
        "fee_status": "unknown",
        "contact_name": None,
        "phone": None,
        "email": None,
        "pet_policy": None,
        "amenities": ["furnished"] if node.get("furnished") else [],
        "image_urls": image_urls,
        "posted_at": node.get("availableAt") or utc_now_iso(),
        "lat": geo.get("latitude"),
        "lon": geo.get("longitude"),
        "source_listing_id": listing_id,
    }


def build_streeteasy_searches(source: dict[str, Any], preferences: dict[str, Any]) -> list[dict[str, str]]:
    """Build StreetEasy search URLs per neighborhood, deduplicating shared slugs."""
    neighborhoods = list(source.get("query_terms") or preferences.get("neighborhoods") or [])
    max_rent = source.get("max_price") or preferences.get("max_rent") or 2500
    searches: list[dict[str, str]] = []
    seen_slugs: set[str] = set()
    for neighborhood in neighborhoods:
        slug = STREETEASY_NEIGHBORHOOD_SLUGS.get(neighborhood)
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        url = f"https://streeteasy.com/for-rent/{slug}/price:-{int(max_rent)}%7Cbeds%3C=1"
        searches.append({"label": neighborhood, "url": url})
    return searches


def discover_streeteasy_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover listings from StreetEasy using embedded search result data."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    request_delay_ms = int(source.get("request_delay_ms", 2000))
    max_results_per_query = int(source.get("max_results_per_query", 8))
    cache_ttl_hours = int(source.get("cache_ttl_hours", 12))
    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 2500)
    searches = build_streeteasy_searches(source, preferences)
    cache_path = STATE_ROOT / f"{source_name}_listing_cache.json"
    cache = read_json(cache_path, default={})

    records_by_id: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    fresh_fetches = 0
    query_summaries: list[dict[str, Any]] = []

    for search in searches:
        query_label = search["label"]
        query_url = search["url"]
        try:
            search_html = read_text_url(query_url)
            fresh_fetches += 1
        except Exception as exc:
            query_summaries.append({"query": query_label, "status": "error", "error": str(exc), "result_count": 0})
            log_lines.append(f"{source_name}: query '{query_label}' failed with {exc}")
            continue

        time.sleep(request_delay_ms / 1000)
        nodes = extract_streeteasy_nodes(search_html)
        kept_for_query = 0

        for node in nodes[:max_results_per_query]:
            listing_id = str(node.get("id") or "")
            if not listing_id:
                continue
            price = node.get("price")
            if isinstance(price, (int, float)) and price > max_rent:
                continue
            if node.get("status") and str(node["status"]).upper() != "ACTIVE":
                continue

            cached_entry = cache.get(listing_id)
            if isinstance(cached_entry, dict) and cache_is_fresh(cached_entry, cache_ttl_hours):
                record = copy.deepcopy(cached_entry.get("record", {}))
                cache_hits += 1
            else:
                record = streeteasy_node_to_record(node, query_label)
                cache[listing_id] = {"fetched_at": utc_now_iso(), "record": record}

            record.setdefault("query_terms", [])
            if query_label not in record["query_terms"]:
                record["query_terms"].append(query_label)
            record.setdefault("neighborhood_hint", query_label)

            if listing_id not in records_by_id:
                records_by_id[listing_id] = record
                kept_for_query += 1
            else:
                existing = records_by_id[listing_id]
                qt = existing.setdefault("query_terms", [])
                if query_label not in qt:
                    qt.append(query_label)

        query_summaries.append({"query": query_label, "status": "ok", "result_count": kept_for_query, "search_url": query_url})
        log_lines.append(f"{source_name}: query '{query_label}' kept {kept_for_query} listings from {len(nodes)} nodes")

    records = sorted(records_by_id.values(), key=lambda r: str(r.get("posted_at") or ""), reverse=True)
    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
        "query_summaries": query_summaries,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    write_json(cache_path, cache)

    ok_queries = sum(1 for qs in query_summaries if qs.get("status") == "ok")
    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
        "cache_path": str(cache_path),
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
        "search_count": len(searches),
        **source_extraction_meta(source_name, ok_queries, len(searches)),
    })
    log_lines.append(
        f"{source_name}: wrote {len(records)} live records to {snapshot_path} "
        f"(cache hits: {cache_hits}, fresh fetches: {fresh_fetches})"
    )


def build_renthop_searches(source: dict[str, Any], preferences: dict[str, Any]) -> list[dict[str, str]]:
    """Build RentHop search URLs per neighborhood."""
    neighborhoods = list(source.get("query_terms") or preferences.get("neighborhoods") or RENTHOP_NEIGHBORHOOD_NAMES)
    max_rent = source.get("max_price") or preferences.get("max_rent") or 2500
    searches: list[dict[str, str]] = []
    for neighborhood in neighborhoods:
        params = urllib.parse.urlencode({
            "min_price": "0",
            "max_price": str(int(max_rent)),
            "bedrooms[]": ["0", "1"],
            "neighborhoods[]": neighborhood,
            "sort": "hopscore",
            "page": "1",
        }, doseq=True)
        url = f"https://www.renthop.com/search/nyc?{params}"
        searches.append({"label": neighborhood, "url": url})
    return searches


def parse_renthop_detail(url: str, query_label: str) -> dict[str, Any] | None:
    """Fetch a RentHop detail page and extract listing data from JSON-LD."""
    try:
        page = read_text_url(url)
    except Exception:
        return None

    listing_id = url.rstrip("/").split("/")[-1]
    record: dict[str, Any] = {
        "id": f"rh-live-{listing_id}",
        "url": url,
        "title": "",
        "body": "",
        "map_address": None,
        "borough": None,
        "neighborhood_hint": query_label,
        "postal_code": None,
        "price": None,
        "bedrooms": None,
        "bathrooms": None,
        "sqft": None,
        "fee_status": "unknown",
        "contact_name": None,
        "phone": None,
        "email": None,
        "pet_policy": None,
        "amenities": [],
        "image_urls": [],
        "posted_at": utc_now_iso(),
        "lat": None,
        "lon": None,
        "source_listing_id": listing_id,
    }

    for ld_text in RH_LD_JSON_RE.findall(page):
        try:
            ld_data = json.loads(ld_text)
        except json.JSONDecodeError:
            continue
        items = ld_data if isinstance(ld_data, list) else [ld_data]
        for item in items:
            if not isinstance(item, dict):
                continue
            entity = item.get("mainEntity") or {}
            about = item.get("about") or {}
            if entity.get("@type") == "Apartment":
                record["title"] = str(entity.get("name") or "").strip()
                record["body"] = str(entity.get("description") or about.get("description") or "").strip()
                addr = entity.get("address") or {}
                record["map_address"] = addr.get("streetAddress")
                record["borough"] = addr.get("addressLocality")
                record["postal_code"] = addr.get("postalCode")
                geo = entity.get("geo") or {}
                record["lat"] = float(geo["latitude"]) if geo.get("latitude") else None
                record["lon"] = float(geo["longitude"]) if geo.get("longitude") else None
                images = entity.get("image") or []
                if isinstance(images, str):
                    images = [images]
                record["image_urls"] = images
                rooms = entity.get("numberOfRooms")
                if rooms is not None:
                    try:
                        record["bedrooms"] = int(rooms)
                    except (TypeError, ValueError):
                        pass
            offers = about.get("offers") or {}
            if offers.get("price"):
                try:
                    record["price"] = int(float(offers["price"]))
                except (TypeError, ValueError):
                    pass

    phone = extract_phone(record.get("body") or "")
    email = extract_email(record.get("body") or "")
    if phone:
        record["phone"] = phone
    if email:
        record["email"] = email
    fee_status = infer_fee_status(record.get("title") or "", record.get("body") or "")
    record["fee_status"] = fee_status

    if not record["title"] and not record["map_address"]:
        return None
    return record


def discover_renthop_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover listings from RentHop by fetching search pages and detail pages."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    request_delay_ms = int(source.get("request_delay_ms", 2000))
    max_results_per_query = int(source.get("max_results_per_query", 6))
    cache_ttl_hours = int(source.get("cache_ttl_hours", 12))
    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 2500)
    searches = build_renthop_searches(source, preferences)
    cache_path = STATE_ROOT / f"{source_name}_listing_cache.json"
    cache = read_json(cache_path, default={})

    records_by_id: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    fresh_fetches = 0
    query_summaries: list[dict[str, Any]] = []

    for search in searches:
        query_label = search["label"]
        query_url = search["url"]
        try:
            search_html = read_text_url(query_url)
        except Exception as exc:
            query_summaries.append({"query": query_label, "status": "error", "error": str(exc), "result_count": 0})
            log_lines.append(f"{source_name}: query '{query_label}' failed with {exc}")
            continue

        time.sleep(request_delay_ms / 1000)
        detail_urls = list(dict.fromkeys(RH_DETAIL_URL_RE.findall(search_html)))[:max_results_per_query]
        kept_for_query = 0

        for detail_url in detail_urls:
            listing_id = detail_url.rstrip("/").split("/")[-1]
            if not listing_id or not listing_id.isdigit():
                continue
            if listing_id in records_by_id:
                existing = records_by_id[listing_id]
                qt = existing.setdefault("query_terms", [])
                if query_label not in qt:
                    qt.append(query_label)
                continue

            cached_entry = cache.get(listing_id)
            if isinstance(cached_entry, dict) and cache_is_fresh(cached_entry, cache_ttl_hours):
                record = copy.deepcopy(cached_entry.get("record", {}))
                cache_hits += 1
            else:
                record = parse_renthop_detail(detail_url, query_label)
                if not record:
                    log_lines.append(f"{source_name}: detail fetch failed for {detail_url}")
                    continue
                cache[listing_id] = {"fetched_at": utc_now_iso(), "record": record}
                fresh_fetches += 1
                time.sleep(request_delay_ms / 1000)

            price = record.get("price")
            if isinstance(price, (int, float)) and price > max_rent:
                continue

            record.setdefault("query_terms", [])
            if query_label not in record["query_terms"]:
                record["query_terms"].append(query_label)
            record.setdefault("neighborhood_hint", query_label)
            records_by_id[listing_id] = record
            kept_for_query += 1

        query_summaries.append({"query": query_label, "status": "ok", "result_count": kept_for_query, "search_url": query_url})
        log_lines.append(f"{source_name}: query '{query_label}' kept {kept_for_query} listings from {len(detail_urls)} detail links")

    records = sorted(records_by_id.values(), key=lambda r: str(r.get("posted_at") or ""), reverse=True)
    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
        "query_summaries": query_summaries,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    write_json(cache_path, cache)

    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
        "cache_path": str(cache_path),
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
        "search_count": len(searches),
    })
    log_lines.append(
        f"{source_name}: wrote {len(records)} live records to {snapshot_path} "
        f"(cache hits: {cache_hits}, fresh fetches: {fresh_fetches})"
    )


def discover_sample_fixture(source: dict[str, Any], manifest: dict[str, Any], log_lines: list[str]) -> None:
    source_name = source["source_name"]
    fixture_path = Path(source["fixture_path"])
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    records = read_json(fixture_path, default=[])
    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    manifest["sources"].append(
        {
            "source_name": source_name,
            "status": "ok",
            "record_count": len(records),
            "snapshot_path": str(snapshot_path),
            "parser_version": PARSER_VERSION,
            "fixture_path": str(fixture_path),
        }
    )
    log_lines.append(f"{source_name}: wrote {len(records)} records from fixture {fixture_path}")


def discover_craigslist_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    request_delay_ms = int(source.get("request_delay_ms", 1200))
    max_results_per_query = int(source.get("max_results_per_query", 6))
    cache_ttl_hours = int(source.get("cache_ttl_hours", 18))
    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 0)
    searches = build_craigslist_searches(source, preferences)
    allowed_codes = allowed_craigslist_boroughs(preferences)
    # Catalog-configured borough searches define the discovery scope: if the catalog
    # explicitly asks for a borough (e.g. Queens), keep its records even when the
    # preferences borough list (used to trim text-query noise) is narrower.
    for term in source.get("query_terms") or []:
        term_code = BOROUGH_NAME_TO_SITE.get(str(term).strip().lower())
        if term_code:
            allowed_codes.add(term_code)
    cache_path = STATE_ROOT / f"{source_name}_listing_cache.json"
    cache = read_json(cache_path, default={})

    records_by_id: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    fresh_fetches = 0
    off_canonical = 0
    query_summaries: list[dict[str, Any]] = []

    for search in searches:
        query_label = search["label"]
        query_url = search["url"]
        try:
            search_html = read_text_url(query_url)
        except Exception as exc:  # pragma: no cover - network failures are runtime-state dependent
            query_summaries.append(
                {
                    "query": query_label,
                    "status": "error",
                    "error": str(exc),
                    "result_count": 0,
                }
            )
            log_lines.append(f"{source_name}: query '{query_label}' failed with {exc}")
            continue

        time.sleep(request_delay_ms / 1000)
        result_urls = extract_listing_urls(search_html, max_results_per_query)
        kept_for_query = 0

        for url in result_urls:
            listing_id = listing_id_from_url(url)
            if not listing_id:
                continue

            borough_code_match = re.search(r"newyork\.craigslist\.org/(mnh|brk|que|brx|stn)/", url)
            borough_code = borough_code_match.group(1) if borough_code_match else None
            if allowed_codes and borough_code and borough_code not in allowed_codes:
                continue

            if listing_id in records_by_id:
                record = records_by_id[listing_id]
                query_terms = record.setdefault("query_terms", [])
                if query_label not in query_terms:
                    query_terms.append(query_label)
                continue

            cached_entry = cache.get(listing_id)
            cached_record = cached_entry.get("record") if isinstance(cached_entry, dict) else None
            # Entries captured between 2026-07-28 and this fix hold the www/view URL with no
            # posting id and no borough; treat them as stale so they are refetched instead of
            # being served back and dropped by the off-area filter below.
            if (
                isinstance(cached_record, dict)
                and cached_record.get("source_listing_id")
                and cache_is_fresh(cached_entry, cache_ttl_hours)
            ):
                record = copy.deepcopy(cached_record)
                cache_hits += 1
            else:
                try:
                    record = parse_craigslist_detail(url, query_label)
                    cache[listing_id] = {
                        "fetched_at": utc_now_iso(),
                        "record": record,
                    }
                    fresh_fetches += 1
                    time.sleep(request_delay_ms / 1000)
                except Exception as exc:  # pragma: no cover - network failures are runtime-state dependent
                    log_lines.append(f"{source_name}: detail fetch failed for {url} with {exc}")
                    continue

            record.setdefault("query_terms", [])
            if query_label not in record["query_terms"]:
                record["query_terms"].append(query_label)
            record.setdefault("neighborhood_hint", query_label)

            # Post-fetch borough filter: sapi-era search URLs carry no subarea, so the
            # borough is only known after the detail fetch resolves the canonical URL.
            record_url = str(record.get("url") or url)
            if "craigslist.org" in record_url and "newyork.craigslist.org" not in record_url:
                # Either a genuinely off-area posting or a canonical-URL shape change that
                # canonical_craigslist_url could not undo. Count the second case so a silent
                # 100% drop shows up in the discovery log instead of just as record_count 0.
                if "www.craigslist.org/view/" in record_url:
                    off_canonical += 1
                continue  # posting redirected to another craigslist area entirely
            record_code = BOROUGH_NAME_TO_SITE.get(str(record.get("borough") or "").strip().lower())
            if allowed_codes and record_code and record_code not in allowed_codes:
                continue

            lowered_blob = f"{record.get('title', '')} {record.get('body', '')}".lower()
            price = record.get("price")
            if max_rent and isinstance(price, int | float) and float(price) > float(max_rent):
                continue
            if "already rented" in lowered_blob or "no longer available" in lowered_blob:
                continue

            records_by_id[listing_id] = record
            kept_for_query += 1

        query_summaries.append(
            {
                "query": query_label,
                "status": "ok",
                "result_count": kept_for_query,
                "search_url": query_url,
            }
        )
        log_lines.append(f"{source_name}: query '{query_label}' kept {kept_for_query} listings")

    if off_canonical:
        log_lines.append(
            f"{source_name}: WARNING {off_canonical} listings dropped with an unresolved "
            "www.craigslist.org/view/ canonical URL -- canonical_craigslist_url may need updating"
        )

    records = sorted(
        records_by_id.values(),
        key=lambda item: str(item.get("posted_at") or ""),
        reverse=True,
    )
    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
        "query_summaries": query_summaries,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    write_json(cache_path, cache)

    manifest["sources"].append(
        {
            "source_name": source_name,
            "status": "ok",
            "record_count": len(records),
            "snapshot_path": str(snapshot_path),
            "parser_version": PARSER_VERSION,
            "cache_path": str(cache_path),
            "cache_hits": cache_hits,
            "fresh_fetches": fresh_fetches,
            "search_count": len(searches),
        }
    )
    log_lines.append(
        f"{source_name}: wrote {len(records)} live records to {snapshot_path} "
        f"(cache hits: {cache_hits}, fresh fetches: {fresh_fetches})"
    )


# ---------------------------------------------------------------------------
# Unconventional source adapters
# ---------------------------------------------------------------------------

def is_index_page_not_a_listing(price: Any, title: str = "") -> bool:
    """True when a fetched 'detail' page is really a site index page.

    LEASEBREAK_LISTING_RE matches any href under /listings/, which includes
    leasebreak's own region navigation. On 2026-08-04 that put ten records in
    the pool — /listings/Manhattan, /listings/Bronx, /listings/Austin,
    /listings/New+Jersey, /listings/Westchester and more — every one titled
    "Listings", none with a price, one carrying a street address in Austin,
    Texas. The source reported ok with record_count 10 while contributing
    nothing usable, which reads worse than reporting zero.

    Price is the discriminator, not bed count: an index page lists other
    apartments, so a stray "3 Bed" from a card on it is enough to make the
    page look real — /listings/Austin came through with beds=5. A real
    listing prices its unit, and a record with no rent is rejected downstream
    regardless, so this drops no real lead.

    Content-based rather than URL-shaped on purpose: leasebreak 403s both the
    runners and this machine, so the true listing-URL pattern cannot be
    confirmed, and guessing it could silently reject everything.
    """
    return price is None


LEASEBREAK_LISTING_RE = re.compile(
    r'<a[^>]+href="(/listings/[^"]+)"[^>]*>',
    re.I,
)
LEASEBREAK_PRICE_RE = re.compile(r"\$([0-9,]{3,})")
LEASEBREAK_BEDS_RE = re.compile(r"(\d)\s*(?:BR|Bed|bed)", re.I)
LEASEBREAK_TAKEOVER_RE = re.compile(r"lease\s*(?:takeover|assignment|break|transfer)", re.I)


def discover_leasebreak_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover lease takeover listings from Leasebreak."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    request_delay_ms = int(source.get("request_delay_ms", 2500))
    max_results = int(source.get("max_results_per_query", 10))
    cache_ttl_hours = int(source.get("cache_ttl_hours", 24))
    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 2500)
    cache_path = STATE_ROOT / f"{source_name}_listing_cache.json"
    cache = read_json(cache_path, default={})

    base_url = str(source.get("search_base_url") or "https://www.leasebreak.com/listings")
    boroughs = preferences.get("boroughs", ["Manhattan", "Brooklyn"])

    records_by_id: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    fresh_fetches = 0
    skipped_index_pages = 0
    query_summaries: list[dict[str, Any]] = []

    for borough in boroughs:
        params = urllib.parse.urlencode({
            "city": "New York",
            "state": "NY",
            "neighborhood": borough,
            "max_price": str(max_rent),
            "min_bedrooms": "0",
            "max_bedrooms": "1",
        })
        search_url = f"{base_url}?{params}"
        try:
            search_html = read_text_url(search_url)
            fresh_fetches += 1
        except Exception as exc:
            query_summaries.append({"query": borough, "status": "error", "error": str(exc), "result_count": 0})
            log_lines.append(f"{source_name}: search for '{borough}' failed: {exc}")
            continue

        time.sleep(request_delay_ms / 1000)

        listing_paths = LEASEBREAK_LISTING_RE.findall(search_html)[:max_results]
        kept = 0

        for path in listing_paths:
            listing_id = path.rstrip("/").split("/")[-1]
            if not listing_id or listing_id in records_by_id:
                continue

            cached_entry = cache.get(listing_id)
            if isinstance(cached_entry, dict) and cache_is_fresh(cached_entry, cache_ttl_hours):
                record = copy.deepcopy(cached_entry.get("record", {}))
                cache_hits += 1
            else:
                detail_url = f"https://www.leasebreak.com{path}"
                try:
                    detail_html = read_text_url(detail_url)
                except Exception:
                    log_lines.append(f"{source_name}: detail fetch failed for {detail_url}")
                    continue

                title_match = re.search(r"<h1[^>]*>(.*?)</h1>", detail_html, re.S)
                title = clean_html_text(title_match.group(1)) if title_match else "Leasebreak listing"
                body = clean_html_text(detail_html, preserve_newlines=True)[:3000]

                price = extract_price(body, title)
                beds_match = LEASEBREAK_BEDS_RE.search(f"{title} {body}")
                beds = int(beds_match.group(1)) if beds_match else None
                if "studio" in f"{title} {body}".lower():
                    beds = 0

                # LEASEBREAK_LISTING_RE matches any href under /listings/,
                # which includes the site's own region navigation —
                # /listings/Manhattan, /listings/Queens, and on 2026-08-04
                # /listings/Austin, /listings/New+Jersey, /listings/Westchester.
                # Every one was fetched as if it were an apartment and emitted
                # as a record: ten of them, all titled "Listings", none with a
                # price, one carrying a street address in Austin, Texas. The
                # source reported ok with record_count 10 and contributed
                # nothing, which is worse than reporting zero.
                #
                # Checked on content rather than URL shape because the real
                # listing-URL pattern cannot be confirmed from here (leasebreak
                # 403s this machine as well as the runners). An index page has
                # no price and no bed count; a real listing has at least one.
                # Price alone is the discriminator. Bed count is not: an index
                # page lists other apartments, so a stray "3 Bed" from one of
                # the cards on it is enough to make the page look real —
                # /listings/Austin came through carrying beds=5. A leasebreak
                # detail page always prices the unit, and a record with no rent
                # is rejected downstream anyway, so this loses no real lead.
                if is_index_page_not_a_listing(price, title):
                    log_lines.append(
                        f"{source_name}: {detail_url} carries no price — index page, not a "
                        f"listing (title {title!r}) — not emitting it"
                    )
                    skipped_index_pages += 1
                    time.sleep(request_delay_ms / 1000)
                    continue
                address_lines = [line.strip() for line in body.splitlines() if line.strip()]
                address = extract_address(address_lines, {})
                phone = extract_phone(body)
                email = extract_email(body)

                is_takeover = bool(LEASEBREAK_TAKEOVER_RE.search(f"{title} {body}"))

                record = {
                    "id": f"lb-{listing_id}",
                    "url": detail_url,
                    "title": title,
                    "body": body[:2000],
                    "map_address": address,
                    "borough": borough,
                    "neighborhood_hint": borough,
                    "postal_code": None,
                    "price": price,
                    "bedrooms": beds,
                    "bathrooms": None,
                    "sqft": None,
                    "fee_status": "unknown",
                    "contact_name": None,
                    "phone": phone,
                    "email": email,
                    "pet_policy": None,
                    "amenities": [],
                    "image_urls": [],
                    "posted_at": utc_now_iso(),
                    "lat": None,
                    "lon": None,
                    "source_listing_id": listing_id,
                    "lease_takeover": is_takeover,
                    "source_search_mode": "bridge",
                }
                cache[listing_id] = {"fetched_at": utc_now_iso(), "record": record}
                fresh_fetches += 1
                time.sleep(request_delay_ms / 1000)

            if isinstance(record.get("price"), (int, float)) and record["price"] > max_rent:
                continue

            # Also applied to CACHED records, not just freshly parsed ones:
            # the cache already holds the index pages this run would have
            # rejected, and a 12-hour TTL would have kept replaying them.
            if is_index_page_not_a_listing(record.get("price"), record.get("title") or ""):
                skipped_index_pages += 1
                cache.pop(listing_id, None)
                continue

            records_by_id[listing_id] = record
            kept += 1

        query_summaries.append({"query": borough, "status": "ok", "result_count": kept})
        log_lines.append(f"{source_name}: '{borough}' kept {kept} listings")

    if skipped_index_pages:
        log_lines.append(
            f"{source_name}: dropped {skipped_index_pages} index page(s) that carried "
            f"neither a price nor a bed count"
        )

    records = list(records_by_id.values())
    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
        "query_summaries": query_summaries,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
        "skipped_index_pages": skipped_index_pages,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    write_json(cache_path, cache)
    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    })
    log_lines.append(f"{source_name}: wrote {len(records)} records (cache: {cache_hits}, fresh: {fresh_fetches})")


NYBITS_LISTING_RE = re.compile(r'href="(https?://(?:www\.)?nybits\.com/listing/[^"]+)"', re.I)


def discover_nybits_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover listings from NYBits — useful for smaller operators and direct-owner inventory."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    request_delay_ms = int(source.get("request_delay_ms", 2500))
    max_results = int(source.get("max_results_per_query", 10))
    cache_ttl_hours = int(source.get("cache_ttl_hours", 24))
    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 2500)
    cache_path = STATE_ROOT / f"{source_name}_listing_cache.json"
    cache = read_json(cache_path, default={})

    neighborhoods = preferences.get("neighborhoods", [])
    records_by_id: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    fresh_fetches = 0
    query_summaries: list[dict[str, Any]] = []

    for neighborhood in neighborhoods[:6]:
        params = urllib.parse.urlencode({
            "q": neighborhood,
            "max_price": str(max_rent),
            "bedrooms": "0-1",
            "type": "rental",
        })
        search_url = f"https://www.nybits.com/search?{params}"
        try:
            search_html = read_text_url(search_url)
            fresh_fetches += 1
        except Exception as exc:
            query_summaries.append({"query": neighborhood, "status": "error", "error": str(exc), "result_count": 0})
            log_lines.append(f"{source_name}: search for '{neighborhood}' failed: {exc}")
            continue

        time.sleep(request_delay_ms / 1000)
        detail_urls = list(dict.fromkeys(NYBITS_LISTING_RE.findall(search_html)))[:max_results]
        kept = 0

        for detail_url in detail_urls:
            listing_id = detail_url.rstrip("/").split("/")[-1]
            if not listing_id or listing_id in records_by_id:
                continue

            cached_entry = cache.get(listing_id)
            if isinstance(cached_entry, dict) and cache_is_fresh(cached_entry, cache_ttl_hours):
                record = copy.deepcopy(cached_entry.get("record", {}))
                cache_hits += 1
            else:
                try:
                    detail_html = read_text_url(detail_url)
                except Exception:
                    log_lines.append(f"{source_name}: detail fetch failed for {detail_url}")
                    continue

                title_match = re.search(r"<h1[^>]*>(.*?)</h1>", detail_html, re.S)
                title = clean_html_text(title_match.group(1)) if title_match else "NYBits listing"
                body = clean_html_text(detail_html, preserve_newlines=True)[:3000]

                price = extract_price(body, title)
                beds_match = re.search(r"(\d)\s*(?:BR|Bed|bedroom)", f"{title} {body}", re.I)
                beds = int(beds_match.group(1)) if beds_match else None
                if "studio" in f"{title} {body}".lower():
                    beds = 0
                address_lines = [line.strip() for line in body.splitlines() if line.strip()]
                address = extract_address(address_lines, {})
                phone = extract_phone(body)
                email = extract_email(body)

                # NYBits often shows landlord/manager names — extract for record-linking
                manager_match = re.search(r"(?:managed?\s+by|landlord|owner)\s*[:\-]?\s*([A-Za-z][A-Za-z .'\-]{2,40})", body, re.I)
                contact_name = manager_match.group(1).strip() if manager_match else None

                record = {
                    "id": f"nb-{listing_id}",
                    "url": detail_url,
                    "title": title,
                    "body": body[:2000],
                    "map_address": address,
                    "borough": None,
                    "neighborhood_hint": neighborhood,
                    "postal_code": None,
                    "price": price,
                    "bedrooms": beds,
                    "bathrooms": None,
                    "sqft": None,
                    "fee_status": infer_fee_status(title, body),
                    "contact_name": contact_name,
                    "phone": phone,
                    "email": email,
                    "pet_policy": infer_pet_policy(detail_html, body),
                    "amenities": infer_amenities(detail_html, body),
                    "image_urls": [],
                    "posted_at": utc_now_iso(),
                    "lat": None,
                    "lon": None,
                    "source_listing_id": listing_id,
                    "source_search_mode": "permanent",
                }
                cache[listing_id] = {"fetched_at": utc_now_iso(), "record": record}
                fresh_fetches += 1
                time.sleep(request_delay_ms / 1000)

            if isinstance(record.get("price"), (int, float)) and record["price"] > max_rent:
                continue
            records_by_id[listing_id] = record
            kept += 1

        query_summaries.append({"query": neighborhood, "status": "ok", "result_count": kept})
        log_lines.append(f"{source_name}: '{neighborhood}' kept {kept} listings")

    records = list(records_by_id.values())
    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
        "query_summaries": query_summaries,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    write_json(cache_path, cache)
    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    })
    log_lines.append(f"{source_name}: wrote {len(records)} records (cache: {cache_hits}, fresh: {fresh_fetches})")


def discover_housing_connect_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover listings from NYC Housing Connect — official high-trust source."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    cache_ttl_hours = int(source.get("cache_ttl_hours", 48))
    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 2500)
    cache_path = STATE_ROOT / f"{source_name}_listing_cache.json"
    cache = read_json(cache_path, default={})

    # Housing Connect uses a React SPA; we attempt to extract any embedded JSON data
    search_url = str(source.get("search_base_url") or "https://housingconnect.nyc.gov/PublicWeb/search-702")
    records: list[dict[str, Any]] = []
    cache_hits = 0
    fresh_fetches = 0

    try:
        page_html = read_text_url(search_url, timeout=30)
        fresh_fetches += 1
    except Exception as exc:
        manifest["sources"].append({
            "source_name": source_name,
            "status": "error",
            "error": str(exc),
            "record_count": 0,
        })
        log_lines.append(f"{source_name}: search page fetch failed: {exc}")
        return

    # Try to extract embedded JSON state from the SPA
    json_blocks = re.findall(r'<script[^>]*>.*?window\.__\w+__\s*=\s*(\{.*?\})\s*;?\s*</script>', page_html, re.S)
    for block in json_blocks:
        try:
            data = json.loads(block)
            listings = data.get("listings") or data.get("results") or []
            if isinstance(listings, list):
                for item in listings[:int(source.get("max_results_per_query", 8))]:
                    if not isinstance(item, dict):
                        continue
                    listing_id = str(item.get("id") or item.get("projectId") or "")
                    if not listing_id:
                        continue

                    price = None
                    for price_key in ("maxRent", "rent", "price", "maximumRent"):
                        raw_price = item.get(price_key)
                        if raw_price is not None:
                            try:
                                price = int(float(str(raw_price).replace("$", "").replace(",", "")))
                            except ValueError:
                                pass
                            break

                    if price and price > max_rent:
                        continue

                    record = {
                        "id": f"hc-{listing_id}",
                        "url": f"https://housingconnect.nyc.gov/PublicWeb/details/{listing_id}",
                        "title": str(item.get("projectName") or item.get("name") or "Housing Connect listing"),
                        "body": str(item.get("description") or ""),
                        "map_address": str(item.get("address") or item.get("street") or ""),
                        "borough": str(item.get("borough") or ""),
                        "neighborhood_hint": str(item.get("neighborhood") or item.get("borough") or ""),
                        "postal_code": str(item.get("zipCode") or item.get("zip") or ""),
                        "price": price,
                        "bedrooms": item.get("bedrooms") or item.get("minBedrooms"),
                        "bathrooms": None,
                        "sqft": None,
                        "fee_status": "no fee",
                        "contact_name": None,
                        "phone": None,
                        "email": None,
                        "pet_policy": None,
                        "amenities": [],
                        "image_urls": [],
                        "posted_at": str(item.get("applicationDeadline") or utc_now_iso()),
                        "lat": item.get("latitude"),
                        "lon": item.get("longitude"),
                        "source_listing_id": listing_id,
                        "source_search_mode": "permanent",
                        "official_program_source": True,
                        "application_deadline": item.get("applicationDeadline"),
                    }
                    records.append(record)
        except (json.JSONDecodeError, AttributeError):
            continue

    # If no embedded JSON, try to parse visible HTML listings
    if not records:
        listing_blocks = re.findall(r'<div[^>]+class="[^"]*listing[^"]*"[^>]*>(.*?)</div>\s*</div>', page_html, re.S | re.I)
        for block in listing_blocks[:int(source.get("max_results_per_query", 8))]:
            title_match = re.search(r"<h[23][^>]*>(.*?)</h[23]>", block, re.S)
            if not title_match:
                continue
            title = clean_html_text(title_match.group(1))
            body = clean_html_text(block)
            price = extract_price(body)
            address_lines = [line.strip() for line in body.splitlines() if line.strip()]
            address = extract_address(address_lines, {})
            listing_id = f"hc-html-{len(records)}-{RUN_STAMP}"
            record = {
                "id": listing_id,
                "url": search_url,
                "title": title,
                "body": body[:2000],
                "map_address": address,
                "borough": None,
                "neighborhood_hint": None,
                "postal_code": None,
                "price": price,
                "bedrooms": None,
                "bathrooms": None,
                "sqft": None,
                "fee_status": "no fee",
                "contact_name": None,
                "phone": None,
                "email": None,
                "pet_policy": None,
                "amenities": [],
                "image_urls": [],
                "posted_at": utc_now_iso(),
                "lat": None,
                "lon": None,
                "source_listing_id": listing_id,
                "source_search_mode": "permanent",
                "official_program_source": True,
            }
            records.append(record)

    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    write_json(cache_path, cache)
    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    })
    log_lines.append(f"{source_name}: wrote {len(records)} records (SPA extraction)")


def discover_hdc_hpd_rerentals(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover HDC/HPD re-rental listings — official public-program source."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    search_url = str(source.get("search_base_url") or "https://www.nychdc.com/pages/Apartments-Available.html")
    records: list[dict[str, Any]] = []

    try:
        page_html = read_text_url(search_url, timeout=30)
    except Exception as exc:
        manifest["sources"].append({
            "source_name": source_name,
            "status": "error",
            "error": str(exc),
            "record_count": 0,
        })
        log_lines.append(f"{source_name}: page fetch failed: {exc}")
        return

    # HDC page typically has a table or list of available apartments
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S | re.I)
    for row in rows[:int(source.get("max_results_per_query", 10))]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 2:
            continue
        cell_texts = [clean_html_text(c) for c in cells]
        title = cell_texts[0] if cell_texts else "HDC/HPD re-rental"
        body = " | ".join(cell_texts)
        price = extract_price(body)
        address = cell_texts[0] if cell_texts and any(c.isdigit() for c in cell_texts[0]) else None
        listing_id = f"hdc-{len(records)}-{RUN_STAMP}"

        record = {
            "id": listing_id,
            "url": search_url,
            "title": title,
            "body": body[:2000],
            "map_address": address,
            "borough": None,
            "neighborhood_hint": None,
            "postal_code": None,
            "price": price,
            "bedrooms": None,
            "bathrooms": None,
            "sqft": None,
            "fee_status": "no fee",
            "contact_name": None,
            "phone": None,
            "email": None,
            "pet_policy": None,
            "amenities": [],
            "image_urls": [],
            "posted_at": utc_now_iso(),
            "lat": None,
            "lon": None,
            "source_listing_id": listing_id,
            "source_search_mode": "permanent",
            "official_program_source": True,
        }
        records.append(record)

    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
    })
    log_lines.append(f"{source_name}: wrote {len(records)} records")


def discover_nooklyn_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover listings from Nooklyn — Brooklyn-focused."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    request_delay_ms = int(source.get("request_delay_ms", 2500))
    max_results = int(source.get("max_results_per_query", 8))
    cache_ttl_hours = int(source.get("cache_ttl_hours", 24))
    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 2500)
    cache_path = STATE_ROOT / f"{source_name}_listing_cache.json"
    cache = read_json(cache_path, default={})

    brooklyn_neighborhoods = [n for n in preferences.get("neighborhoods", [])
                              if n.lower() in ("williamsburg", "greenpoint", "east williamsburg")]
    if not brooklyn_neighborhoods:
        brooklyn_neighborhoods = ["Williamsburg"]

    records_by_id: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    fresh_fetches = 0
    query_summaries: list[dict[str, Any]] = []

    for neighborhood in brooklyn_neighborhoods:
        slug = neighborhood.lower().replace(" ", "-")
        search_url = f"https://nooklyn.com/listings?neighborhood={slug}&max_price={max_rent}&bedrooms=0,1"
        try:
            search_html = read_text_url(search_url)
            fresh_fetches += 1
        except Exception as exc:
            query_summaries.append({"query": neighborhood, "status": "error", "error": str(exc), "result_count": 0})
            log_lines.append(f"{source_name}: search for '{neighborhood}' failed: {exc}")
            continue

        time.sleep(request_delay_ms / 1000)

        detail_urls = re.findall(r'href="(https?://nooklyn\.com/apartments/[^"]+)"', search_html)
        detail_urls = list(dict.fromkeys(detail_urls))[:max_results]
        kept = 0

        for detail_url in detail_urls:
            listing_id = detail_url.rstrip("/").split("/")[-1]
            if not listing_id or listing_id in records_by_id:
                continue

            cached_entry = cache.get(listing_id)
            if isinstance(cached_entry, dict) and cache_is_fresh(cached_entry, cache_ttl_hours):
                record = copy.deepcopy(cached_entry.get("record", {}))
                cache_hits += 1
            else:
                try:
                    detail_html = read_text_url(detail_url)
                except Exception:
                    continue

                title_match = re.search(r"<h1[^>]*>(.*?)</h1>", detail_html, re.S)
                title = clean_html_text(title_match.group(1)) if title_match else "Nooklyn listing"
                body = clean_html_text(detail_html, preserve_newlines=True)[:3000]
                price = extract_price(body, title)
                beds_match = re.search(r"(\d)\s*(?:BR|Bed|bedroom)", f"{title} {body}", re.I)
                beds = int(beds_match.group(1)) if beds_match else None
                if "studio" in f"{title} {body}".lower():
                    beds = 0
                address_lines = [line.strip() for line in body.splitlines() if line.strip()]
                address = extract_address(address_lines, {})

                record = {
                    "id": f"nk-{listing_id}",
                    "url": detail_url,
                    "title": title,
                    "body": body[:2000],
                    "map_address": address,
                    "borough": "Brooklyn",
                    "neighborhood_hint": neighborhood,
                    "postal_code": None,
                    "price": price,
                    "bedrooms": beds,
                    "bathrooms": None,
                    "sqft": None,
                    "fee_status": infer_fee_status(title, body),
                    "contact_name": None,
                    "phone": extract_phone(body),
                    "email": extract_email(body),
                    "pet_policy": infer_pet_policy(detail_html, body),
                    "amenities": infer_amenities(detail_html, body),
                    "image_urls": [],
                    "posted_at": utc_now_iso(),
                    "lat": None,
                    "lon": None,
                    "source_listing_id": listing_id,
                    "source_search_mode": "permanent",
                }
                cache[listing_id] = {"fetched_at": utc_now_iso(), "record": record}
                fresh_fetches += 1
                time.sleep(request_delay_ms / 1000)

            if isinstance(record.get("price"), (int, float)) and record["price"] > max_rent:
                continue
            records_by_id[listing_id] = record
            kept += 1

        query_summaries.append({"query": neighborhood, "status": "ok", "result_count": kept})
        log_lines.append(f"{source_name}: '{neighborhood}' kept {kept} listings")

    records = list(records_by_id.values())
    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
        "query_summaries": query_summaries,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    write_json(cache_path, cache)
    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
        "cache_hits": cache_hits,
        "fresh_fetches": fresh_fetches,
    })
    log_lines.append(f"{source_name}: wrote {len(records)} records (cache: {cache_hits}, fresh: {fresh_fetches})")


def discover_listings_project(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover listings from Listings Project — curated weekly source."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    # 2026-08: the marketing root has no listing markup at all — the SSR
    # inventory lives at /real-estate/new-york-city (about 12 cards a page,
    # each anchor repeated ~4 times). Cards carry price, an optional sublet
    # date range, and "Neighborhood, Borough | Category" as bare text.
    search_url = str(source.get("search_base_url") or "https://www.listingsproject.com/real-estate/new-york-city")
    max_results = int(source.get("max_results_per_query", 30))
    records: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    uuid_tail = re.compile(r"-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    hood_re = re.compile(r"([A-Za-z][A-Za-z .'\-]{2,40}),\s*(Brooklyn|Manhattan|Queens|Bronx|Staten Island)\s*\|\s*([A-Za-z ]{3,40})")

    for page_no in (1, 2, 3):
        page_url = search_url if page_no == 1 else f"{search_url}?page={page_no}"
        try:
            page_html = read_text_url(page_url, timeout=30)
        except Exception as exc:
            if page_no == 1:
                manifest["sources"].append({
                    "source_name": source_name,
                    "status": "error",
                    "error": str(exc),
                    "record_count": 0,
                })
                log_lines.append(f"{source_name}: page fetch failed: {exc}")
                return
            break

        for m in re.finditer(r'href="(/listings/([^"?#]+))"', page_html):
            href, slug = m.group(1), m.group(2)
            if slug in seen_slugs or len(records) >= max_results:
                continue
            seen_slugs.add(slug)
            chunk = re.sub(r"<[^>]+>", " ", page_html[m.start():m.start() + 1400])
            chunk = html.unescape(re.sub(r"\s+", " ", chunk))

            hood_m = hood_re.search(chunk)
            category = (hood_m.group(3).strip().lower() if hood_m else "")
            # The hunt wants whole rentals: skip sublets (day-priced, date-ranged),
            # rooms, and workspaces — but keep them out loud in the log.
            if "/day" in chunk or "sublet" in category or "workspace" in category or "room" in category:
                continue
            if category and "rent" not in category:
                continue
            # The category line can fall outside the parse window; the slug
            # still names sublets, rooms, swaps, and workspaces reliably.
            if re.search(r"\b(sublets?|workspaces?|swap|rooms?|roommate|office|share|art studios?|desk)\b", slug.replace("-", " ")):
                continue

            title = uuid_tail.sub("", slug)
            title = re.sub(r"-\d[\d\-]*$", "", title).replace("-", " ").strip().capitalize()
            price = extract_price(chunk, title)

            record = {
                "id": f"lp-{slug[:80]}",
                "url": f"https://www.listingsproject.com{href}",
                "title": title or "Listings Project rental",
                "body": chunk[:2000],
                "map_address": None,
                "borough": hood_m.group(2) if hood_m else None,
                "neighborhood_hint": hood_m.group(1).strip() if hood_m else None,
                "postal_code": None,
                "price": price,
                "bedrooms": None,
                "bathrooms": None,
                "sqft": None,
                "fee_status": "no_fee",
                "contact_name": None,
                "phone": None,
                "email": None,
                "pet_policy": None,
                "amenities": [],
                "image_urls": [],
                "posted_at": utc_now_iso(),
                "lat": None,
                "lon": None,
                "source_listing_id": f"lp-{slug[:80]}",
                "source_search_mode": "permanent",
                "curated_source": True,
            }
            records.append(record)

        if len(records) >= max_results:
            break

    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
    })
    log_lines.append(f"{source_name}: wrote {len(records)} records (weekly curated review)")


def discover_spareroom_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover room share listings from SpareRoom — bridge/temporary only."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 2500)
    search_url = str(source.get("search_base_url") or "https://www.spareroom.com/flatshare/new_york")
    records: list[dict[str, Any]] = []

    try:
        page_html = read_text_url(search_url, timeout=30)
    except Exception as exc:
        manifest["sources"].append({
            "source_name": source_name,
            "status": "error",
            "error": str(exc),
            "record_count": 0,
        })
        log_lines.append(f"{source_name}: page fetch failed: {exc}")
        return

    listing_blocks = re.findall(r'<article[^>]*>(.*?)</article>', page_html, re.S | re.I)
    if not listing_blocks:
        listing_blocks = re.findall(r'<li[^>]+class="[^"]*listing[^"]*"[^>]*>(.*?)</li>', page_html, re.S | re.I)

    for block in listing_blocks[:int(source.get("max_results_per_query", 6))]:
        title_match = re.search(r"<h[23][^>]*>(.*?)</h[23]>", block, re.S)
        if not title_match:
            continue
        title = clean_html_text(title_match.group(1))
        body = clean_html_text(block, preserve_newlines=True)
        price = extract_price(body, title)

        if price and price > max_rent:
            continue

        listing_id = f"sr-{len(records)}-{RUN_STAMP}"
        record = {
            "id": listing_id,
            "url": search_url,
            "title": title,
            "body": body[:2000],
            "map_address": None,
            "borough": None,
            "neighborhood_hint": None,
            "postal_code": None,
            "price": price,
            "bedrooms": None,
            "bathrooms": None,
            "sqft": None,
            "fee_status": "unknown",
            "contact_name": None,
            "phone": None,
            "email": None,
            "pet_policy": None,
            "amenities": [],
            "image_urls": [],
            "posted_at": utc_now_iso(),
            "lat": None,
            "lon": None,
            "source_listing_id": listing_id,
            "source_search_mode": "bridge",
            "room_share_source": True,
        }
        records.append(record)

    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
    })
    log_lines.append(f"{source_name}: wrote {len(records)} records (bridge/roommate)")


# ---------------------------------------------------------------------------
def discover_email_alerts(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """StreetEasy/Zillow saved-search alert emails → raw records.

    The sanctioned firehose (scripts/ingest_mail_alerts.py). Without
    configs/mail_ingest.json this is a clean skip, not a failure.
    """
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    from ingest_mail_alerts import pull_alert_records
    pulled, note = pull_alert_records(max_messages=int(source.get("max_results_per_query", 40)))

    if note == "not_configured":
        manifest["sources"].append({"source_name": source_name, "status": "skipped", "record_count": 0, "note": "configs/mail_ingest.json not filled"})
        log_lines.append(f"{source_name}: skipped — mail credentials not configured")
        return

    records: list[dict[str, Any]] = []
    for p in pulled:
        records.append({
            "id": p["id"],
            "url": p["url"],
            "title": p.get("title") or ("Saved-search alert: " + p["url"].split("/")[-1].replace("-", " ")[:80]),
            "body": None,
            "map_address": p.get("address"),
            "borough": p.get("borough"),
            "neighborhood_hint": None,
            "postal_code": None,
            "price": p.get("price"),
            "bedrooms": p.get("beds"),
            "bathrooms": None,
            "sqft": None,
            "fee_status": "unknown",
            "contact_name": None,
            "phone": None,
            "email": None,
            "pet_policy": None,
            "amenities": [],
            "image_urls": [],
            "posted_at": utc_now_iso(),
            "lat": None,
            "lon": None,
            "source_listing_id": p["id"],
            "source_search_mode": "permanent",
            "curated_source": False,
        })

    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    status = "ok" if note == "ok" else "error"
    manifest["sources"].append({
        "source_name": source_name,
        "status": status,
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
        **({"error": note[:200]} if status == "error" else {}),
    })
    log_lines.append(f"{source_name}: {len(records)} alerted listings ({note})")


def _reddit_oauth_entries(subreddits: list[str], max_per: int) -> list[dict[str, Any]] | None:
    """Authenticated JSON entries when configs/reddit.json is filled; else None."""
    import base64
    import urllib.parse
    cfg_path = CONFIG_ROOT / "reddit.json" if "CONFIG_ROOT" in globals() else None
    try:
        cfg = json.loads((Path(__file__).resolve().parent.parent / "configs" / "reddit.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if "PASTE" in json.dumps(cfg) or not cfg.get("client_secret"):
        return None
    try:
        auth = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
        req = urllib.request.Request(
            "https://www.reddit.com/api/v1/access_token",
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            headers={"Authorization": "Basic " + auth, "User-Agent": cfg.get("user_agent", "vera/1.0")},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            token = json.loads(resp.read())["access_token"]
        out: list[dict[str, Any]] = []
        for sub in subreddits:
            req2 = urllib.request.Request(
                f"https://oauth.reddit.com/r/{sub}/new?limit={max_per}",
                headers={"Authorization": "Bearer " + token, "User-Agent": cfg.get("user_agent", "vera/1.0")},
            )
            with urllib.request.urlopen(req2, timeout=20) as resp:
                for child in json.loads(resp.read()).get("data", {}).get("children", []):
                    d = child.get("data", {})
                    out.append({
                        "title": d.get("title") or "",
                        "link": "https://www.reddit.com" + (d.get("permalink") or ""),
                        "post_id": d.get("id"),
                        "published": utc_now_iso(),
                        "content": (d.get("selftext") or "")[:1200],
                    })
        return out
    except Exception:
        return None


def discover_reddit_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover by-owner offers from subreddit Atom feeds.

    Reddit's JSON API 403s unauthenticated callers, but the .rss feeds still
    serve (verified 2026-08-03). Posts are leads, not listings: the record
    links to the thread, carries whatever price/hood the title gives up, and
    is expected to land in manual review. Seeker posts are filtered out.
    """
    import xml.etree.ElementTree as ET

    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    subreddits = source.get("subreddits") or ["NYCapartments"]
    max_results = int(source.get("max_results_per_query", 40))
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    atom = "{http://www.w3.org/2005/Atom}"
    seeker_re = re.compile(r"\b(looking|seeking|iso\b|wanted|advice|question|help|recommendation|recommend|rant|vent|warn|beware|buildings? that|apartments? that|anyone know|does anyone|should i|can i|how do)\b|\?\s*$", re.I)
    offer_re = re.compile(r"\b(studio|1\s?br|1\s?bed|one\s?bed|2\s?br|2\s?bed|apartment|apt\b|unit|sublet|lease)\b", re.I)
    hoods = [str(h) for h in (preferences.get("neighborhoods") or [])]

    errors: list[str] = []

    # Authenticated JSON when configs/reddit.json is filled (Decision 4);
    # anonymous Atom stays as the credential-free fallback. Same filters,
    # same record shape — keep the two branches in lockstep.
    oauth_entries = _reddit_oauth_entries(subreddits, 50)
    if oauth_entries is not None:
        for entry in oauth_entries:
            if len(records) >= max_results:
                break
            title = entry["title"].strip()
            link = entry["link"]
            post_id = entry["post_id"]
            content = re.sub(r"\s+", " ", entry["content"]).strip()
            if not title or not link or not post_id or post_id in seen_ids:
                continue
            if seeker_re.search(title):
                continue
            haystack = f"{title} {content[:600]}"
            if not offer_re.search(haystack):
                continue
            price = extract_price(haystack, title)
            if not price or price < 700 or price > 6500:
                continue
            seen_ids.add(post_id)
            hood_hint = None
            low = haystack.lower()
            for h in hoods:
                if h.lower() in low:
                    hood_hint = h
                    break
            records.append({
                "id": f"rd-{post_id}", "url": link, "title": title[:200], "body": content[:2000],
                "map_address": None, "borough": None, "neighborhood_hint": hood_hint, "postal_code": None,
                "price": price, "bedrooms": None, "bathrooms": None, "sqft": None, "fee_status": "unknown",
                "contact_name": None, "phone": None, "email": None, "pet_policy": None, "amenities": [],
                "image_urls": [], "posted_at": entry["published"], "lat": None, "lon": None,
                "source_listing_id": f"rd-{post_id}", "source_search_mode": "permanent", "curated_source": False,
            })
        subreddits = []  # OAuth handled everything; skip the Atom pass

    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/new.rss?limit=50"
        try:
            feed_xml = read_text_url(url, timeout=30)
            root = ET.fromstring(feed_xml)
        except Exception as exc:
            errors.append(f"r/{sub}: {exc}")
            continue

        for entry in root.findall(f"{atom}entry"):
            if len(records) >= max_results:
                break
            title = (entry.findtext(f"{atom}title") or "").strip()
            link_el = entry.find(f"{atom}link")
            link = link_el.get("href") if link_el is not None else None
            post_id = (entry.findtext(f"{atom}id") or "").split("/")[-1] or None
            published = entry.findtext(f"{atom}published") or utc_now_iso()
            content = html.unescape(re.sub(r"<[^>]+>", " ", entry.findtext(f"{atom}content") or ""))
            content = re.sub(r"\s+", " ", content).strip()

            if not title or not link or not post_id or post_id in seen_ids:
                continue
            if seeker_re.search(title):
                continue
            haystack = f"{title} {content[:600]}"
            if not offer_re.search(haystack):
                continue
            price = extract_price(haystack, title)
            if not price or price < 700 or price > 6500:
                continue
            seen_ids.add(post_id)

            hood_hint = None
            low = haystack.lower()
            for h in hoods:
                if h.lower() in low:
                    hood_hint = h
                    break

            records.append({
                "id": f"rd-{post_id}",
                "url": link,
                "title": title[:200],
                "body": content[:2000],
                "map_address": None,
                "borough": None,
                "neighborhood_hint": hood_hint,
                "postal_code": None,
                "price": price,
                "bedrooms": None,
                "bathrooms": None,
                "sqft": None,
                "fee_status": "unknown",
                "contact_name": None,
                "phone": None,
                "email": None,
                "pet_policy": None,
                "amenities": [],
                "image_urls": [],
                "posted_at": published,
                "lat": None,
                "lon": None,
                "source_listing_id": f"rd-{post_id}",
                "source_search_mode": "permanent",
                "curated_source": False,
            })

    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)
    status = "ok" if records or not errors else "error"
    manifest["sources"].append({
        "source_name": source_name,
        "status": status,
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
        **({"error": "; ".join(errors)[:300]} if errors else {}),
    })
    log_lines.append(f"{source_name}: wrote {len(records)} offer leads from {len(subreddits)} subreddit feed(s)" + (f"; errors: {'; '.join(errors)[:160]}" if errors else ""))


# Source adapter dispatch
# ---------------------------------------------------------------------------

OI_CARD_RE = re.compile(
    r'data-analytics-event="listings_unitcard"\s+data-analytics-props="([^"]+)"\s+href="([^"]+)"(.*?)</a>',
    re.S,
)
OI_TEXT_TAG_RE = re.compile(r"<[^>]+>")
OI_PRICE_RE = re.compile(r"\$([0-9][0-9,]{2,})")
# "3 beds" / "1 bed" / bare "Studio" (openigloo writes studios without a "bed" word).
OI_BEDS_RE = re.compile(r"(?:(\d+(?:\.\d+)?)\s*beds?|\b(studio)\b)", re.I)
OI_BATHS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*baths?", re.I)
OI_IMG_RE = re.compile(r'src="(/_next/image\?url=[^"]+)"')
OI_RATING_RE = re.compile(r"(\d\.\d)\s*\(\s*(\d+)\s*\)")
# Badge chips openigloo prints ahead of the neighborhood name.
OI_BADGES = ("Verified", "Rent-stabilized", "Good cause", "Future", "New")
# addressSlug: <borough>-<neighborhood-words>-<street address>-<zip>-<unit>
OI_SLUG_ZIP_RE = re.compile(r"-(\d{5})(?:-|$)")


def _oi_card_text(fragment: str) -> str:
    return html.unescape(OI_TEXT_TAG_RE.sub(" ", fragment))


def parse_openigloo_card(props_raw: str, href: str, fragment: str, query_label: str) -> dict[str, Any] | None:
    """Build a raw record from one openigloo search-result unit card.

    openigloo server-renders every field VERA needs onto the card itself
    (address, price, beds/baths, neighborhood, photos), so discovery costs
    one request per query — no detail fetch per listing.
    """
    try:
        props = json.loads(html.unescape(props_raw))
    except json.JSONDecodeError:
        return None
    listing_id = str(props.get("unitId") or props.get("id") or "").strip()
    if not listing_id:
        return None

    # Card text reads:
    #   "<badges> <Neighborhood> · <N beds, N baths> [<rating> ( <reviews> )] <address> $<was> $<now>"
    # Two prices means a price drop (original struck through, current second).
    text = _oi_card_text(fragment)
    text = re.sub(r"\s+", " ", text).strip().lstrip("> ").strip()
    prices = [int(p.replace(",", "")) for p in OI_PRICE_RE.findall(text)]
    if not prices:
        return None
    price = prices[-1]
    previous_price = prices[0] if len(prices) > 1 and prices[0] != price else None

    address_slug = str(props.get("addressSlug") or "")
    borough_slug = address_slug.split("-")[0] if address_slug else ""
    zip_match = OI_SLUG_ZIP_RE.search(address_slug)

    badges = [b for b in OI_BADGES if re.search(rf"\b{re.escape(b)}\b", text, re.I)]

    neighborhood = None
    tail = text
    if "·" in text:
        head, tail = text.split("·", 1)
        # Strip any badge words that precede the neighborhood name.
        head_clean = head
        for badge in OI_BADGES:
            head_clean = re.sub(rf"\b{re.escape(badge)}\b", " ", head_clean, flags=re.I)
        neighborhood = re.sub(r"\s+", " ", head_clean).strip(" ,-") or None

    beds_match = OI_BEDS_RE.search(tail)
    beds: float | None = None
    if beds_match:
        beds = 0.0 if beds_match.group(2) else float(beds_match.group(1))
    baths_match = OI_BATHS_RE.search(tail)

    # Building review score, openigloo's signature signal: "3.2 ( 3 )".
    rating = review_count = None
    rating_match = OI_RATING_RE.search(tail)
    if rating_match:
        rating = float(rating_match.group(1))
        review_count = int(rating_match.group(2))

    # Address = what's left after beds/baths and the rating, before the price.
    address = None
    after = tail[rating_match.end():] if rating_match else tail
    if not rating_match:
        bb_end = max(
            beds_match.end() if beds_match else 0,
            baths_match.end() if baths_match else 0,
        )
        after = tail[bb_end:]
    address_match = re.match(r"\s*(.+?)\s*\$", after, re.S)
    if address_match:
        address = re.sub(r"\s+", " ", address_match.group(1)).strip() or None

    images: list[str] = []
    for src in OI_IMG_RE.findall(fragment):
        decoded = html.unescape(src)
        inner = re.search(r"url=([^&]+)", decoded)
        if not inner:
            continue
        full = urllib.parse.unquote(inner.group(1))
        if full not in images:
            images.append(full)
        if len(images) >= 6:
            break

    return {
        "id": listing_id,
        "source_listing_id": listing_id,
        "url": urllib.parse.urljoin("https://www.openigloo.com", href),
        "title": address or f"openigloo listing {listing_id[:8]}",
        "map_address": address,
        "price": price,
        "bedrooms": beds,
        "bathrooms": float(baths_match.group(1)) if baths_match else None,
        "neighborhood_hint": neighborhood or query_label,
        "borough": borough_slug.replace("_", " ").title() if borough_slug else None,
        "postal_code": zip_match.group(1) if zip_match else None,
        "image_urls": images,
        "image_count": len(images),
        "body": " ".join(
            part
            for part in [
                "Listed on openigloo, where tenants rate the building and landlord.",
                f"Building review score {rating}/5 from {review_count} tenant review(s)."
                if rating is not None
                else "No tenant reviews on file for this building yet.",
                f"openigloo badges: {', '.join(badges)}." if badges else "",
                f"Price dropped from ${previous_price:,} to ${price:,}." if previous_price else "",
            ]
            if part
        ),
        "amenities": badges or None,
        "source_enrichment_notes": (
            f"openigloo building rating {rating}/5 ({review_count} reviews)"
            if rating is not None
            else "openigloo listing with no building reviews yet"
        ),
        "rent_stabilized_hint": any(b.lower() == "rent-stabilized" for b in badges) or None,
        "previous_price": previous_price,
        "query_terms": [query_label],
        "posted_at": None,
    }


def build_openigloo_searches(source: dict[str, Any], preferences: dict[str, Any]) -> list[dict[str, str]]:
    """openigloo filter URLs: /listings/borough:<b>|nbr:<slug>|price:-<max>."""
    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 2500)
    searches: list[dict[str, str]] = []
    for term in source.get("query_terms") or []:
        term = str(term).strip()
        if not term:
            continue
        if ":" in term:
            # Pre-built filter expression straight from the catalog.
            filters = term
            label = term
        else:
            filters = f"borough:{term.lower().replace(' ', '-')}"
            label = term
        url = (
            "https://www.openigloo.com/listings/"
            + urllib.parse.quote(f"{filters}|price:-{max_rent}", safe=":|-")
        )
        searches.append({"label": label, "url": url})
    return searches


def discover_openigloo_live(
    source: dict[str, Any],
    preferences: dict[str, Any],
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    """Discover listings from openigloo's server-rendered search results."""
    source_name = source["source_name"]
    output_dir = source_output_dir(source)
    ensure_dir(output_dir)

    request_delay_ms = int(source.get("request_delay_ms", 2000))
    max_results_per_query = int(source.get("max_results_per_query", 20))
    max_rent = int(source.get("max_price") or preferences.get("max_rent") or 2500)
    searches = build_openigloo_searches(source, preferences)

    records_by_id: dict[str, dict[str, Any]] = {}
    query_summaries: list[dict[str, Any]] = []
    fresh_fetches = 0

    for search in searches:
        query_label = search["label"]
        query_url = search["url"]
        try:
            search_html = read_text_url(query_url)
            fresh_fetches += 1
        except Exception as exc:
            query_summaries.append({"query": query_label, "status": "error", "error": str(exc), "result_count": 0})
            log_lines.append(f"{source_name}: query '{query_label}' failed with {exc}")
            continue

        time.sleep(request_delay_ms / 1000)
        kept_for_query = 0
        for props_raw, href, fragment in OI_CARD_RE.findall(search_html):
            if kept_for_query >= max_results_per_query:
                break
            record = parse_openigloo_card(props_raw, href, fragment, query_label)
            if not record:
                continue
            price = record.get("price")
            if isinstance(price, (int, float)) and price > max_rent:
                continue
            existing = records_by_id.get(record["id"])
            if existing:
                terms = existing.setdefault("query_terms", [])
                if query_label not in terms:
                    terms.append(query_label)
                continue
            records_by_id[record["id"]] = record
            kept_for_query += 1

        query_summaries.append({"query": query_label, "status": "ok", "result_count": kept_for_query, "search_url": query_url})
        log_lines.append(f"{source_name}: query '{query_label}' kept {kept_for_query} listings")

    records = list(records_by_id.values())
    snapshot_payload = {
        "source_name": source_name,
        "captured_at": utc_now_iso(),
        "parser_version": PARSER_VERSION,
        "access_mode": source.get("access_mode"),
        "record_count": len(records),
        "records": records,
        "query_summaries": query_summaries,
        "cache_hits": 0,
        "fresh_fetches": fresh_fetches,
    }
    snapshot_path = output_dir / f"{source_name}_snapshot_{RUN_STAMP}.json"
    write_json(snapshot_path, snapshot_payload)

    manifest["sources"].append({
        "source_name": source_name,
        "status": "ok",
        "record_count": len(records),
        "snapshot_path": str(snapshot_path),
        "parser_version": PARSER_VERSION,
        "cache_hits": 0,
        "fresh_fetches": fresh_fetches,
        "search_count": len(searches),
    })
    log_lines.append(
        f"{source_name}: wrote {len(records)} live records to {snapshot_path} "
        f"(searches: {len(searches)}, fresh fetches: {fresh_fetches})"
    )


SOURCE_ADAPTERS: dict[str, Any] = {
    "craigslist": lambda s, p, m, l: discover_craigslist_live(s, p, m, l),
    "openigloo": lambda s, p, m, l: discover_openigloo_live(s, p, m, l),
    "streeteasy": lambda s, p, m, l: discover_streeteasy_live(s, p, m, l),
    "renthop": lambda s, p, m, l: discover_renthop_live(s, p, m, l),
    "leasebreak": lambda s, p, m, l: discover_leasebreak_live(s, p, m, l),
    "nybits": lambda s, p, m, l: discover_nybits_live(s, p, m, l),
    "housing_connect": lambda s, p, m, l: discover_housing_connect_live(s, p, m, l),
    "hdc_hpd_rerentals": lambda s, p, m, l: discover_hdc_hpd_rerentals(s, p, m, l),
    "nooklyn": lambda s, p, m, l: discover_nooklyn_live(s, p, m, l),
    "listings_project": lambda s, p, m, l: discover_listings_project(s, p, m, l),
    "reddit_nycapartments": lambda s, p, m, l: discover_reddit_live(s, p, m, l),
    "email_alerts": lambda s, p, m, l: discover_email_alerts(s, p, m, l),
    "spareroom": lambda s, p, m, l: discover_spareroom_live(s, p, m, l),
}


# Sources that hard-block datacenter IPs (probed from a GitHub runner,
# 2026-08-03: renthop 403, leasebreak 403, housing_connect 503). Under
# VERA_CLOUD=1 these skip honestly instead of burning retries.
#
# streeteasy joined 2026-08-04, and only because the honesty fix made it
# visible: it had been reporting `ok` with zero records every cloud night.
# Once status came from the actual query outcomes it read "all 11 queries
# failed" — so the cloud was firing eleven rejected requests a night at a
# host that has clearly declined. It still runs on the Mac, where it works;
# this set only applies under VERA_CLOUD=1.
CLOUD_BLOCKED_SOURCES = {"renthop", "leasebreak", "housing_connect", "streeteasy"}


def main() -> int:
    parser = argparse.ArgumentParser(description="VERA listing discovery")
    parser.add_argument(
        "--cadence",
        choices=["hourly", "daily", "weekly", "all"],
        default="all",
        help="Only discover sources matching this cadence. 'all' discovers everything enabled.",
    )
    args = parser.parse_args()

    write_stage_start("discover", sources_attempted=0)

    try:
        ensure_dir(LOG_ROOT)
        ensure_dir(STATE_ROOT)
        log_lines: list[str] = []

        preferences = read_json(CONFIG_ROOT / "user_preferences.json", default={})
        catalog = read_json(CONFIG_ROOT / "source_catalog.json", default={"sources": []})

        # Load previous manifest to carry forward non-current-cadence source snapshots
        manifest_path = STATE_ROOT / "current_raw_snapshots.json"
        previous_manifest = read_json(manifest_path, default={"sources": []})

        manifest = {
            "run_stamp": RUN_STAMP,
            "generated_at": utc_now_iso(),
            "cadence": args.cadence,
            "sources": [],
        }

        # Track which sources we're actively discovering this run
        discovered_source_names: set[str] = set()

        for source in catalog.get("sources", []):
            source_name = source["source_name"]
            if not source.get("enabled", False):
                manifest["sources"].append({
                    "source_name": source_name,
                    "status": "skipped",
                    "reason": "disabled",
                })
                log_lines.append(f"{source_name}: skipped because disabled")
                continue
            if os.environ.get("VERA_CLOUD") == "1" and source_name in CLOUD_BLOCKED_SOURCES:
                manifest["sources"].append({
                    "source_name": source_name,
                    "status": "skipped",
                    "reason": "cloud_blocked",
                })
                log_lines.append(f"{source_name}: skipped — hard-blocks datacenter IPs (cloud mode)")
                continue

            # Cadence filtering: skip sources not matching requested cadence
            source_cadence = str(source.get("cadence", "hourly"))
            if args.cadence != "all" and source_cadence != args.cadence:
                log_lines.append(f"{source_name}: skipped (cadence={source_cadence}, requested={args.cadence})")
                continue

            discovered_source_names.add(source_name)
            access_mode = str(source.get("access_mode") or "sample_fixture")

            if access_mode == "sample_fixture":
                discover_sample_fixture(source, manifest, log_lines)
                continue

            if access_mode in ("live_html", "manual_review") and source_name in SOURCE_ADAPTERS:
                try:
                    SOURCE_ADAPTERS[source_name](source, preferences, manifest, log_lines)
                except Exception as exc:
                    manifest["sources"].append({
                        "source_name": source_name,
                        "status": "error",
                        "error": str(exc),
                        "record_count": 0,
                    })
                    log_lines.append(f"{source_name}: adapter error: {exc}")
                continue

            manifest["sources"].append({
                "source_name": source_name,
                "status": "skipped",
                "reason": f"unsupported access mode: {access_mode}",
            })
            log_lines.append(f"{source_name}: skipped because access mode '{access_mode}' is unsupported")

        # Carry forward previous snapshots for sources NOT discovered in this run
        # This allows cadence-filtered runs to preserve data from other cadences
        if args.cadence != "all":
            for prev_source in previous_manifest.get("sources", []):
                prev_name = prev_source.get("source_name")
                if prev_name and prev_name not in discovered_source_names and prev_source.get("status") == "ok":
                    snapshot_path = snapshot_path_for_source(prev_name, prev_source.get("snapshot_path"))
                    if snapshot_path and snapshot_path.exists():
                        prev_source = {**prev_source, "snapshot_path": str(snapshot_path)}
                        manifest["sources"].append(prev_source)
                        log_lines.append(f"{prev_name}: carried forward from previous manifest")

        # Correct asserted success before anything reads it — trends, anomaly
        # detection and the published feed all take status at face value.
        finalize_source_statuses(manifest, log_lines)

        # Enrich all manifest source entries with extraction strategy + anomaly metadata
        for src_entry in manifest.get("sources", []):
            sname = src_entry.get("source_name", "")
            if "strategy_used" not in src_entry and sname in SOURCE_STRATEGIES:
                ok_q = src_entry.get("search_count", 0) if src_entry.get("status") == "ok" else 0
                total_q = src_entry.get("search_count", 1) or 1
                src_entry.update(source_extraction_meta(sname, ok_q, total_q))
            src_entry.setdefault("fetched_at", utc_now_iso())

            # Anomaly detection per source
            if src_entry.get("status") in ("ok", "error"):
                try:
                    anomaly = check_source_anomalies(
                        sname,
                        int(src_entry.get("record_count", 0)),
                    )
                    if anomaly.get("anomaly_flag"):
                        src_entry["anomaly_flag"] = True
                        src_entry["anomaly_reason"] = anomaly.get("reason")
                        log_lines.append(f"ANOMALY [{sname}]: {anomaly.get('reason')}")
                    src_entry["trailing_7d_avg"] = anomaly.get("trailing_7d_avg")
                except Exception:
                    pass

            # Record trend data for reliability scoring
            try:
                record_source_run(
                    source_name=sname,
                    run_id=get_run_id(),
                    status=src_entry.get("status", "unknown"),
                    records_found=int(src_entry.get("record_count", 0)),
                    confidence=src_entry.get("extraction_confidence"),
                    parser_version=src_entry.get("parser_version"),
                )
            except Exception:
                pass

        write_json(manifest_path, manifest)

        log_path = LOG_ROOT / f"discovery_{RUN_STAMP}.log"
        log_header = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        write_text(log_path, "\n".join([f"[{log_header}] {line}" for line in log_lines]) + "\n")

        print(
            json.dumps(
                {
                    "run_stamp": RUN_STAMP,
                    "cadence": args.cadence,
                    "manifest": str(manifest_path),
                    "log": str(log_path),
                },
                indent=2,
            )
        )

        sources_attempted = len(discovered_source_names)
        sources_succeeded = sum(
            1 for s in manifest["sources"]
            if s.get("source_name") in discovered_source_names and s.get("status") == "ok"
        )
        total_records = sum(
            s.get("record_count", 0) for s in manifest["sources"]
            if s.get("source_name") in discovered_source_names
        )
        write_stage_end(
            "discover",
            "success",
            records_out=total_records,
            sources_attempted=sources_attempted,
            sources_succeeded=sources_succeeded,
        )
        return 0

    except Exception as e:
        write_stage_end("discover", "failed", errors=[str(e)])
        raise


if __name__ == "__main__":
    raise SystemExit(main())

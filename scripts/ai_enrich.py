#!/usr/bin/env python3
"""VERA AI Enrichment Layer — OpenAI narrative summaries for scored listings.

This module sits AFTER score_listings.py and BEFORE build_snapshot.py.
It adds human-readable narrative fields to listings that already have
deterministic scores and recommendations.

Architecture:
    - Truth layer (scores, trust, verification) = deterministic pipeline
    - Narrative layer (this file) = AI-written summaries
    - If AI fails or is unavailable, deterministic output is preserved unchanged

Usage:
    python scripts/ai_enrich.py                  # live mode (needs OPENAI_API_KEY)
    python scripts/ai_enrich.py --dry-run        # test mode (no API calls, mock output)
    python scripts/ai_enrich.py --dry-run --verbose  # see prompts and mock responses

Environment:
    OPENAI_API_KEY — required for live mode, ignored in dry-run
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.paths import (
    VERA_ROOT as ROOT,
    SCORED_DIR as SCORED_ROOT,
    CACHE_DIR,
)
from workflow_support import (
    ensure_dir,
    latest_file,
    read_json,
    write_json,
    utc_stamp,
)

# ── Config ────────────────────────────────────────────────────────

MODEL = "gpt-4o-mini"  # fast + cheap for narrative tasks
MAX_TOKENS_PER_CALL = 600
MAX_CONCURRENT_CALLS = 3
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
MAX_RETRY_ATTEMPTS = 3

AI_CACHE_DIR = CACHE_DIR / "ai_enrichments"
ENRICHED_OUTPUT_DIR = SCORED_ROOT  # overwrite scored files in place

DRY_RUN = "--dry-run" in sys.argv
VERBOSE = "--verbose" in sys.argv


# ── OpenAI Client ─────────────────────────────────────────────────

def get_openai_client():
    """Initialize OpenAI client. Returns None if key is missing."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or api_key == "REPLACE_WITH_NEW_KEY":
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except ImportError:
        print("[ai_enrich] openai package not installed. Run: pip install openai")
        return None


def call_openai(client, prompt: str, model: str = MODEL) -> dict[str, Any]:
    """Call OpenAI with retry logic. Returns {ok, text, request_id} or {ok, error}."""
    last_error = None

    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS_PER_CALL,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            text = response.choices[0].message.content
            request_id = getattr(response, "_request_id", None) or response.id

            return {"ok": True, "text": text, "request_id": request_id}

        except Exception as e:
            last_error = e
            status_code = getattr(e, "status_code", None)

            if status_code not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRY_ATTEMPTS:
                return {
                    "ok": False,
                    "error": str(e),
                    "status_code": status_code,
                }

            delay = min(10, 2 ** (attempt - 1)) + random.uniform(0, 0.5)
            time.sleep(delay)

    return {"ok": False, "error": str(last_error)}


# ── Prompt Builder ────────────────────────────────────────────────

def build_enrichment_prompt(listing: dict[str, Any]) -> str:
    """Build a focused prompt for one listing's narrative enrichment."""

    # Extract the fields the model needs to see
    context = {
        "title": listing.get("title"),
        "neighborhood": listing.get("neighborhood"),
        "borough": listing.get("borough"),
        "rent": listing.get("rent"),
        "beds": listing.get("beds"),
        "baths": listing.get("baths"),
        "overall_score": listing.get("overall_score"),
        "recommendation": listing.get("recommendation"),
        "listing_type": listing.get("listing_type"),
        "fee_status": listing.get("fee_status"),
        "likely_landlord_type": listing.get("likely_landlord_type"),
        "by_owner_signal": listing.get("by_owner_signal"),
        "management_company_signal": listing.get("management_company_signal"),
        "verification_status": listing.get("verification_status"),
        "rent_stabilized_signal": listing.get("rent_stabilized_signal"),
        "listing_confidence_band": listing.get("listing_confidence_band"),
        "listing_confidence_score": listing.get("listing_confidence_score"),
        "trust_strengths": listing.get("trust_strengths", []),
        "trust_caveats": listing.get("trust_caveats", []),
        "landlord_reason_summary": listing.get("landlord_reason_summary", []),
        "hpd_risk_score": listing.get("hpd_risk_score"),
        "dob_risk_score": listing.get("dob_risk_score"),
        "component_scores": listing.get("component_scores", {}),
        "full_description": (listing.get("full_description") or "")[:500],
    }

    return f"""You are VERA, an NYC rental analyst writing for someone apartment-hunting.

Given this listing data, write concise, useful narrative fields. Be direct and specific.
Do not hype. Do not hedge excessively. Say what matters.

Listing data:
{json.dumps(context, ensure_ascii=False, default=str)}

Return strict JSON with exactly these keys:
- "why_it_matters": 1-2 sentences explaining why this listing is interesting or not (based on deal score, location, price). Be specific about the neighborhood and price.
- "what_to_watch": 1 sentence about the biggest risk or thing to verify. If trust is high and verified, say so briefly.
- "owner_read": 1 short phrase about the landlord situation (e.g. "Likely owner-direct, small building" or "Broker listing, management company" or "Unclear — verify before calling").
- "next_move": 1 action sentence (e.g. "Call today — good fit, verified listing" or "Verify the address first, then contact" or "Skip — broker ad, not a real listing").
- "contact_brief": A 2-3 line text block someone could paste into a message when reaching out about this apartment. Include the address, rent, and a natural opening line.

Keep all fields SHORT. No filler. No disclaimers. Write like a smart friend texting you about an apartment."""


# ── Cache ─────────────────────────────────────────────────────────

def listing_cache_key(listing: dict[str, Any]) -> str:
    """Hash the fields that affect narrative output."""
    relevant = {
        "title": listing.get("title"),
        "rent": listing.get("rent"),
        "overall_score": listing.get("overall_score"),
        "recommendation": listing.get("recommendation"),
        "listing_confidence_band": listing.get("listing_confidence_band"),
        "likely_landlord_type": listing.get("likely_landlord_type"),
    }
    blob = json.dumps(relevant, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def read_cache(cache_key: str) -> dict[str, Any] | None:
    path = AI_CACHE_DIR / f"{cache_key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def write_cache(cache_key: str, data: dict[str, Any]) -> None:
    ensure_dir(AI_CACHE_DIR)
    path = AI_CACHE_DIR / f"{cache_key}.json"
    path.write_text(json.dumps(data, indent=2))


# ── Dry-run mock ──────────────────────────────────────────────────

def mock_enrichment(listing: dict[str, Any]) -> dict[str, Any]:
    """Generate plausible mock narrative for testing without API calls."""
    rec = listing.get("recommendation", "skip")
    neighborhood = listing.get("neighborhood", "Unknown")
    rent = listing.get("rent")
    rent_str = f"${int(rent):,}" if rent else "unknown rent"
    beds = listing.get("beds")
    bed_str = "studio" if beds == 0 else f"{beds}bd" if beds else "unknown"
    landlord = listing.get("likely_landlord_type", "unclear")
    trust_band = listing.get("listing_confidence_band", "unknown")
    title = listing.get("title", "Untitled")
    score = listing.get("overall_score", 0)

    if rec in ("pursue", "pursue cautiously"):
        why = f"Strong deal for {neighborhood} — {rent_str} {bed_str} scores {score}. Worth a closer look."
        watch = f"Trust is {trust_band}. Verify the listing is still active before calling."
        move = "Call or text today. Listings at this price move fast in this neighborhood."
    elif rec == "manual review":
        why = f"Interesting lead in {neighborhood} at {rent_str}. Deal score is {score} — not amazing but could be decent."
        watch = f"Trust level is {trust_band}. Double-check the address and verify listing freshness."
        move = "Investigate first. Check the address on StreetEasy, then reach out if it checks out."
    else:
        why = f"{rent_str} in {neighborhood} scored {score}. Below the bar for serious consideration."
        watch = f"Multiple issues: {trust_band} trust, questionable listing quality."
        move = "Skip this one. Better options available."

    owner_labels = {
        "independent": "Likely owner-direct, good sign",
        "management_company": "Management company — expect process",
        "broker": "Broker listing — expect a fee conversation",
        "unclear": "Unclear who's behind this — verify before calling",
    }

    return {
        "why_it_matters": why,
        "what_to_watch": watch,
        "owner_read": owner_labels.get(landlord, "Unclear"),
        "next_move": move,
        "contact_brief": f"Hi, I'm interested in the {bed_str} at {title} ({rent_str}). Is it still available? I'd love to schedule a viewing this week.",
        "_source": "dry_run_mock",
    }


# ── Main enrichment logic ─────────────────────────────────────────

def enrich_listing(client, listing: dict[str, Any]) -> dict[str, Any]:
    """Enrich a single listing with AI narrative. Returns the enrichment dict."""

    cache_key = listing_cache_key(listing)

    # Check cache first
    cached = read_cache(cache_key)
    if cached:
        if VERBOSE:
            print(f"  [cache hit] {listing.get('title', '?')[:50]}")
        return cached

    # Dry-run mode
    if DRY_RUN or client is None:
        result = mock_enrichment(listing)
        if VERBOSE:
            print(f"  [dry-run] {listing.get('title', '?')[:50]}")
            print(f"    why_it_matters: {result['why_it_matters']}")
            print(f"    next_move: {result['next_move']}")
        write_cache(cache_key, result)
        return result

    # Live API call
    prompt = build_enrichment_prompt(listing)
    if VERBOSE:
        print(f"  [api call] {listing.get('title', '?')[:50]}")

    response = call_openai(client, prompt)

    if not response["ok"]:
        print(f"  [api error] {response.get('error', 'unknown')}")
        return {"_source": "api_error", "_error": response.get("error")}

    try:
        result = json.loads(response["text"])
        result["_source"] = "openai"
        result["_request_id"] = response.get("request_id")
        result["_model"] = MODEL
        write_cache(cache_key, result)
        return result
    except json.JSONDecodeError:
        print(f"  [json error] Could not parse model response")
        return {"_source": "json_error", "_raw": response.get("text", "")[:200]}


def apply_enrichment(listing: dict[str, Any], enrichment: dict[str, Any]) -> dict[str, Any]:
    """Merge AI enrichment fields into a listing, preserving deterministic fields."""
    updated = dict(listing)

    # Only overwrite narrative fields — never touch scores, trust, recommendations
    if enrichment.get("why_it_matters"):
        updated["why_it_made_the_cut"] = enrichment["why_it_matters"]
    if enrichment.get("what_to_watch"):
        updated["analyst_notes"] = enrichment["what_to_watch"]
    if enrichment.get("next_move"):
        updated["next_move"] = enrichment["next_move"]
    if enrichment.get("owner_read"):
        updated["owner_read"] = enrichment["owner_read"]
    if enrichment.get("contact_brief"):
        updated["contact_brief"] = enrichment["contact_brief"]

    updated["ai_enriched"] = enrichment.get("_source", "unknown")
    return updated


# ── Main ──────────────────────────────────────────────────────────

def main():
    mode = "DRY-RUN" if DRY_RUN else "LIVE"
    print(f"\n[ai_enrich] Starting AI enrichment ({mode} mode)")

    # Find latest scored file
    scored_path = latest_file(SCORED_ROOT, "scored_*.json")
    if not scored_path:
        # Try CSV fallback
        scored_path = latest_file(SCORED_ROOT, "scored_*.csv")
    if not scored_path:
        print("[ai_enrich] No scored listings found. Run score_listings.py first.")
        sys.exit(1)

    print(f"[ai_enrich] Reading: {scored_path.name}")
    listings = read_json(scored_path) if scored_path.suffix == ".json" else []
    if not listings:
        print("[ai_enrich] No listings to enrich.")
        return

    # Initialize client
    client = None if DRY_RUN else get_openai_client()
    if not DRY_RUN and client is None:
        print("[ai_enrich] No OPENAI_API_KEY found. Falling back to dry-run mode.")

    # Enrich each listing
    enriched_count = 0
    error_count = 0

    for listing in listings:
        enrichment = enrich_listing(client, listing)
        if enrichment.get("_source") in ("api_error", "json_error"):
            error_count += 1
        else:
            enriched_count += 1
            listing.update(apply_enrichment(listing, enrichment))

    # Write enriched listings back
    output_path = scored_path.parent / scored_path.name.replace("scored_", "ai_enriched_")
    write_json(output_path, listings)

    print(f"[ai_enrich] Done: {enriched_count} enriched, {error_count} errors")
    print(f"[ai_enrich] Output: {output_path.name}")

    # Also update the original scored file so build_snapshot picks it up
    write_json(scored_path, listings)
    print(f"[ai_enrich] Updated: {scored_path.name}")


if __name__ == "__main__":
    main()

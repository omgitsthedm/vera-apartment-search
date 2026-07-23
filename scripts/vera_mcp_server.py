#!/usr/bin/env python3
"""VERA MCP server — conversational access to the apartment shortlist.

Zero-dependency stdio MCP (newline-delimited JSON-RPC 2.0). Register with:
  claude mcp add --scope user vera -- python3 ~/Code/Personal/vera-apartment-search/scripts/vera_mcp_server.py

Tools: vera_shortlist, vera_listing, vera_changes, vera_status.
Reads the local snapshot only — personal data never leaves the machine.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "latest_snapshot.json"

CARD_FIELDS = [
    "listing_uid", "address_normalized", "neighborhood", "borough", "rent",
    "beds", "baths", "recommendation", "overall_score", "owner_name",
    "owner_type", "owner_portfolio_estimate", "is_coop",
    "private_landlord_likelihood_score", "serious_open_violations",
    "bedbug_reports_3y", "litigation_count_3y", "rent_stabilized_signal",
    "estimated_move_in_cash", "fee_status", "why_this_listing",
    "change_badge", "source_url",
]

TOOLS = [
    {
        "name": "vera_shortlist",
        "description": "Current apartment shortlist (pursue/cautious/manual-review candidates) with ownership, building-record, and scoring signals. Filter by recommendation, max_rent, owner_type (individual|llc|coop_hdfc), or borough.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recommendation": {"type": "string", "description": "pursue | pursue cautiously | manual review"},
                "max_rent": {"type": "number"},
                "owner_type": {"type": "string"},
                "borough": {"type": "string"},
            },
        },
    },
    {
        "name": "vera_listing",
        "description": "Full record for one listing by listing_uid — every scored field, score explanations, verify-before-applying checklist, contact info.",
        "inputSchema": {
            "type": "object",
            "properties": {"listing_uid": {"type": "string"}},
            "required": ["listing_uid"],
        },
    },
    {
        "name": "vera_changes",
        "description": "What changed in the latest run: new listings, price drops, disappeared listings, and summary counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "vera_status",
        "description": "Pipeline health: last run id/time, stage statuses, source health, publish outcome. Use to answer 'is VERA running?'",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def load() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def card(entry: dict) -> dict:
    return {k: entry.get(k) for k in CARD_FIELDS if entry.get(k) is not None}


def tool_call(name: str, args: dict) -> dict:
    snap = load()
    if not snap:
        return {"error": f"No snapshot at {SNAPSHOT} — has the pipeline run?"}
    shortlist = snap.get("shortlist") or []
    if name == "vera_shortlist":
        rows = shortlist
        if args.get("recommendation"):
            rows = [r for r in rows if str(r.get("recommendation", "")).lower().startswith(str(args["recommendation"]).lower()[:6])]
        if args.get("max_rent") is not None:
            rows = [r for r in rows if isinstance(r.get("rent"), (int, float)) and r["rent"] <= args["max_rent"]]
        if args.get("owner_type"):
            rows = [r for r in rows if r.get("owner_type") == args["owner_type"]]
        if args.get("borough"):
            rows = [r for r in rows if str(r.get("borough", "")).lower() == str(args["borough"]).lower()]
        return {"generated_at": snap.get("generated_at"), "count": len(rows), "listings": [card(r) for r in rows]}
    if name == "vera_listing":
        uid = args.get("listing_uid")
        for r in shortlist:
            if r.get("listing_uid") == uid:
                return r
        return {"error": f"listing_uid {uid!r} not on the current shortlist"}
    if name == "vera_changes":
        return {
            "generated_at": snap.get("generated_at"),
            "summary": snap.get("summary"),
            "daily_changes": snap.get("daily_changes"),
        }
    if name == "vera_status":
        return {
            "generated_at": snap.get("generated_at"),
            "run": snap.get("run"),
            "stages": snap.get("stages"),
            "source_health": {
                k: (snap.get("source_health") or {}).get(k)
                for k in ("active", "healthy", "partial", "broken", "stale")
            },
            "publish": snap.get("publish"),
        }
    return {"error": f"unknown tool {name}"}


def reply(msg_id, result=None, error=None) -> None:
    out: dict = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        if method == "initialize":
            reply(msg_id, {
                "protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "vera", "version": "1.0.0"},
            })
        elif method == "tools/list":
            reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params") or {}
            result = tool_call(params.get("name", ""), params.get("arguments") or {})
            reply(msg_id, {"content": [{"type": "text", "text": json.dumps(result, default=str)}]})
        elif method == "ping":
            reply(msg_id, {})
        elif msg_id is not None:
            reply(msg_id, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()

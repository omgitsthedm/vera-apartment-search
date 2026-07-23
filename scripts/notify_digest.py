#!/usr/bin/env python3
"""Send a short post-run digest push notification via ntfy.sh (free).

Reads snapshots/latest_snapshot.json and posts: pursue/cautious counts,
what changed today, and the top lead with its ownership signal. Fires only
when configs/notify.json exists (gitignored — the topic name is the only
credential; anyone who knows it can read digests, so keep it random).

Config: configs/notify.json -> {"ntfy_topic": "vera-hunt-xxxxxxxx"}
Subscribe on the ntfy app (iOS/Android) or https://ntfy.sh/<topic>.
Also posts a local macOS notification as a fallback.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "latest_snapshot.json"
CONFIG = ROOT / "configs" / "notify.json"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def build_message() -> tuple[str, str]:
    snap = read_json(SNAPSHOT)
    summary = snap.get("summary") or {}
    pursue = summary.get("pursue_count", 0)
    cautious = summary.get("cautious_count", 0)
    new_today = summary.get("new_today", 0)
    drops = summary.get("price_drops", 0)

    title = f"VERA: {pursue} pursue, {cautious} cautious"
    lines = [f"{new_today} new today, {drops} price drops."]

    shortlist = snap.get("shortlist") or []
    if shortlist:
        top = shortlist[0]
        addr = top.get("address_normalized") or top.get("address_raw") or "?"
        rent = top.get("rent")
        owner_type = top.get("owner_type") or top.get("likely_landlord_type") or "owner unknown"
        owner_label = {
            "individual": "private landlord",
            "coop_hdfc": "HDFC co-op",
            "llc": "corporate owner",
        }.get(str(owner_type), str(owner_type))
        rent_txt = f" at ${rent:,.0f}" if isinstance(rent, (int, float)) else ""
        lines.append(f"Top: {addr}{rent_txt} ({owner_label}).")
    lines.append("https://nyc-apartment-search-vera.netlify.app")
    return title, "\n".join(lines)


def main() -> int:
    cfg = read_json(CONFIG)
    topic = str(cfg.get("ntfy_topic") or "").strip()
    title, body = build_message()

    # Local notification regardless of ntfy config
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{body.splitlines()[0]}" with title "{title}"'],
            check=False, capture_output=True, timeout=10,
        )
    except Exception:
        pass

    if not topic:
        print("notify_digest: no configs/notify.json topic — local notification only")
        return 0

    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=body.encode(),
        headers={"Title": title, "Priority": "default", "Tags": "house"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"notify_digest: ntfy status {resp.status}")
    except Exception as exc:
        print(f"notify_digest: ntfy send failed ({exc}) — non-fatal")
    return 0


if __name__ == "__main__":
    sys.exit(main())

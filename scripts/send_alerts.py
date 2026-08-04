#!/usr/bin/env python3
"""Email David when a listing fits the full scale.

Reads snapshots/latest_snapshot.json, finds listings that pass every
full-fit gate (recommendation, score, confidence, building risk, rent),
and sends ONE email per new fit via Mail.app (osascript — no credentials,
uses the account already configured on this Mac). Each listing_uid is
alerted at most once, tracked in alerts/alert_state.json.

Config: configs/alerts.json (tracked) — see DEFAULTS below. Disable with
{"enabled": false} or VERA_ALERTS=off. Preview with --dry-run.

Runs non-fatally from the autonomous runners after a successful pipeline.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "latest_snapshot.json"
CONFIG = ROOT / "configs" / "alerts.json"
PREFS = ROOT / "configs" / "user_preferences.json"
STATE_DIR = ROOT / "alerts"
STATE = STATE_DIR / "alert_state.json"
APP_URL = "https://littlefightnyc.com/vera/"

DEFAULTS = {
    "enabled": True,
    "recipient": "info@afterhoursagenda.com",
    "from_address": "info@afterhoursagenda.com",
    "recommendations": ["pursue", "pursue cautiously"],
    "min_overall_score": 60,
    "min_listing_confidence": 60,
    "max_hpd_risk": 65,
    "max_dob_risk": 65,
    "max_per_email": 5,
}

MAIL_SCRIPT = """
on run argv
    set theSubject to item 1 of argv
    set theBody to item 2 of argv
    set theRecipient to item 3 of argv
    set theSender to item 4 of argv
    tell application "Mail"
        set m to make new outgoing message with properties {subject:theSubject, content:theBody, visible:false}
        tell m
            make new to recipient at end of to recipients with properties {address:theRecipient}
        end tell
        if theSender is not "" then set sender of m to theSender
        send m
    end tell
end run
"""


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return fallback


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(read_json(CONFIG, {}))
    return cfg


def full_pool(snap: dict) -> list[dict]:
    pool = []
    seen = set()
    for key in ("shortlist", "reviewed_out"):
        for rec in snap.get(key) or []:
            uid = rec.get("listing_uid")
            if uid and uid not in seen:
                seen.add(uid)
                pool.append(rec)
    return pool


def is_full_fit(rec: dict, cfg: dict, max_rent: float) -> bool:
    if str(rec.get("recommendation") or "").lower() not in cfg["recommendations"]:
        return False
    if (rec.get("overall_score") or 0) < cfg["min_overall_score"]:
        return False
    if (rec.get("listing_confidence_score") or 0) < cfg["min_listing_confidence"]:
        return False
    if (rec.get("hpd_risk_score") or 0) >= cfg["max_hpd_risk"]:
        return False
    if (rec.get("dob_risk_score") or 0) >= cfg["max_dob_risk"]:
        return False
    rent = rec.get("rent")
    if not isinstance(rent, (int, float)) or rent <= 0 or rent > max_rent:
        return False
    return True


def describe(rec: dict) -> str:
    addr = rec.get("address_normalized") or rec.get("address_raw") or "address unknown"
    rent = rec.get("rent")
    rent_txt = f"${rent:,.0f}/mo" if isinstance(rent, (int, float)) else "rent unlisted"
    hood = rec.get("neighborhood") or "?"
    unit = rec.get("unit_type") or "unit ?"
    lines = [f"{addr.title()} — {rent_txt} — {unit}, {hood}"]

    why = []
    score = rec.get("overall_score")
    if isinstance(score, (int, float)):
        why.append(f"score {score:.0f}")
    ind = rec.get("likely_independent_landlord_score")
    if isinstance(ind, (int, float)) and ind >= 60:
        why.append("reads owner-direct")
    hpd = rec.get("hpd_risk_score")
    if isinstance(hpd, (int, float)):
        why.append(f"HPD risk {hpd:.0f}")
    if why:
        lines.append("  Why it fits: " + ", ".join(why) + f" — {rec.get('recommendation')}")

    # The commute, quoted from the timetable rather than invented.
    tr = rec.get("transit") or {}
    if tr.get("station"):
        lines_txt = " ".join(tr.get("lines") or [])
        lines.append(f"  Train: ≈{tr.get('walk_mins')} min walk to {tr['station']}" + (f" ({lines_txt})" if lines_txt else ""))

    cash = rec.get("estimated_move_in_cash")
    if isinstance(cash, (int, float)) and cash > 0:
        lines.append(f"  Cash to keys: ≈${cash:,.0f}")

    # An unlawful demand must never reach you buried under a recommendation.
    # If VERA is putting this listing in front of you, it says so up front.
    for d in (rec.get("illegal_demands") or [])[:3]:
        lines.append(f"  ⚠ UNLAWFUL: {d.get('says')} — {d.get('law')}")
    for c in (rec.get("scam_cues_found") or [])[:2]:
        lines.append(f"  Caution: {c.get('says')}")

    # What this owner does to their other tenants.
    pf = rec.get("landlord_portfolio") or {}
    if pf.get("bldgs"):
        bits = [f"{pf['bldgs']} building" + ("" if pf["bldgs"] == 1 else "s")]
        if pf.get("totalevictions"):
            bits.append(f"{pf['totalevictions']} evictions filed")
        if pf.get("openviolationsperresunit"):
            bits.append(f"{pf['openviolationsperresunit']} open violations per apartment")
        lines.append(f"  Owner's wider record: {pf.get('topcorp') or 'portfolio'} — " + ", ".join(bits))

    for caveat in (rec.get("trust_caveats") or [])[:2]:
        lines.append(f"  Eyes open: {caveat}")
    for step in (rec.get("what_to_verify_before_applying") or [])[:2]:
        lines.append(f"  Verify first: {step}")
    url = rec.get("url") or rec.get("source_url")
    if url:
        lines.append(f"  Listing: {url}")
    lines.append(f"  Full ledger: {APP_URL}#/listing/{rec.get('listing_uid')}")
    return "\n".join(lines)


def compose(fits: list[dict], total_fit: int) -> tuple[str, str]:
    top = fits[0]
    addr = (top.get("address_normalized") or "new lead").title()
    rent = top.get("rent")
    rent_txt = f" ${rent:,.0f}" if isinstance(rent, (int, float)) else ""
    extra = f" (+{len(fits) - 1} more)" if len(fits) > 1 else ""
    subject = f"VERA — full-fit lead:{rent_txt} {addr}{extra}"

    parts = [
        f"{len(fits)} listing{'s' if len(fits) != 1 else ''} just cleared every gate — "
        "right price, right neighborhood, no disqualifying building risk.",
        "",
    ]
    parts.extend(describe(rec) + "\n" for rec in fits)
    if total_fit > len(fits):
        parts.append(f"({total_fit - len(fits)} further fits held back to keep this readable — all live on the board.)")
    parts.append(f"Full picture: {APP_URL}")
    parts.append("")
    parts.append("— VERA · verified evaluation for rental analysis")
    return subject, "\n".join(parts)


def send_mail(subject: str, body: str, recipient: str, sender: str) -> None:
    subprocess.run(
        ["osascript", "-", subject, body, recipient, sender],
        input=MAIL_SCRIPT,
        text=True,
        check=True,
        capture_output=True,
        timeout=60,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print instead of sending; no state written")
    args = parser.parse_args()

    cfg = load_config()
    if not cfg.get("enabled") or os.environ.get("VERA_ALERTS", "").lower() in {"off", "0", "false"}:
        print("[alerts] disabled — nothing sent")
        return 0

    snap = read_json(SNAPSHOT, {})
    if not snap:
        print("[alerts] no snapshot — nothing to do")
        return 0

    prefs = read_json(PREFS, {})
    max_rent = prefs.get("max_rent") or 3000

    state = read_json(STATE, {})
    fits = [r for r in full_pool(snap) if is_full_fit(r, cfg, max_rent)]
    fresh = [r for r in fits if r.get("listing_uid") not in state]
    if not fresh:
        print(f"[alerts] {len(fits)} full-fit, 0 new — no email")
        return 0

    fresh.sort(key=lambda r: r.get("overall_score") or 0, reverse=True)
    batch = fresh[: cfg["max_per_email"]]
    subject, body = compose(batch, total_fit=len(fresh))

    if args.dry_run:
        print(f"[alerts] DRY RUN — would email {cfg['recipient']}")
        print(f"Subject: {subject}\n\n{body}")
        return 0

    send_mail(subject, body, cfg["recipient"], cfg.get("from_address") or "")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for rec in batch:
        state[rec["listing_uid"]] = {
            "alerted_at": now,
            "rent": rec.get("rent"),
            "overall_score": rec.get("overall_score"),
            "address": rec.get("address_normalized"),
        }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True))
    print(f"[alerts] emailed {len(batch)} full-fit lead(s) to {cfg['recipient']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

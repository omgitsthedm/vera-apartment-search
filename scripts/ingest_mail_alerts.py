#!/usr/bin/env python3
"""The sanctioned firehose: read StreetEasy/Zillow saved-search alert emails.

David subscribes to the portals' own alert emails; VERA reads that inbox
over IMAP and turns each alerted listing into a raw discovery record. No
scraping, nothing to block, works from any IP — the ingestion path the
2026 tooling research called the single best ToS-safe source.

Activates itself: with no configs/mail_ingest.json (gitignored) it
reports a clean skip and costs nothing. Fill the file and the next sweep
drinks from the firehose.
"""
from __future__ import annotations

import email
import email.header
import imaplib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "mail_ingest.json"

SE_URL = re.compile(r"https://streeteasy\.com/(?:rental|building)/[A-Za-z0-9\-_/#\.]+")
ZI_URL = re.compile(r"https://www\.zillow\.com/homedetails/[A-Za-z0-9\-_/\.]+")
# Rents as the portals actually write them: "$2,200", "$2,200/mo",
# "$2200". The previous pattern required 3-4 digits before any comma, so it
# matched "$2200" and missed "$2,200" — which is the form both StreetEasy and
# Zillow use. Every email-ingested listing would have arrived priceless and
# then been dropped by the rent filter as "rent missing".
PRICE = re.compile(r"\$\s?(\d{1,2},\d{3}|\d{3,5})(?!\d)")


# An alert email carries a link and a price but no street address, and
# without an address nothing can reach the city's records — the listing would
# arrive as an unverifiable stub. Both portals encode the address in the URL:
#   streeteasy.com/building/459-keap-st-brooklyn/garden
#   zillow.com/homedetails/114-N-7th-St-1L-Brooklyn-NY-11249/9988776_zpid/
SE_SLUG = re.compile(r"streeteasy\.com/building/([a-z0-9\-]+?)-(brooklyn|manhattan|queens|bronx|staten-island)(?:/([a-z0-9\-]+))?", re.I)
ZI_SLUG = re.compile(r"zillow\.com/homedetails/([A-Za-z0-9\-]+?)-(?:New-York|Brooklyn|Bronx|Queens|Staten-Island)-NY-\d{5}/", re.I)
BOROUGHS = {"brooklyn": "Brooklyn", "manhattan": "Manhattan", "queens": "Queens",
            "bronx": "Bronx", "staten-island": "Staten Island"}


def _tidy(street: str) -> str:
    """Title-case a slug without mangling ordinals: 7th, not 7Th."""
    out = []
    for word in street.split():
        if re.fullmatch(r"\d+(st|nd|rd|th)", word, re.I):
            out.append(word.lower())
        elif re.fullmatch(r"[nsew]", word, re.I):
            out.append(word.upper())
        else:
            out.append(word.capitalize())
    text = " ".join(out)
    return re.sub(r"\s+(Apt|Unit|#)$", "", text, flags=re.I).strip()


def address_from_url(url: str) -> tuple[str | None, str | None, str | None]:
    """(address, borough, unit) recovered from a listing URL, or Nones."""
    m = SE_SLUG.search(url)
    if m:
        street = m.group(1).replace("-", " ").strip()
        return _tidy(street), BOROUGHS.get(m.group(2).lower()), (m.group(3) or None)
    m = ZI_SLUG.search(url)
    if m:
        parts = m.group(1).split("-")
        # trailing token is often the unit (…-114-N-7th-St-1L)
        unit = None
        if len(parts) > 2 and re.fullmatch(r"[0-9]{1,3}[A-Za-z]?|[A-Za-z][0-9]{0,3}", parts[-1] or ""):
            unit = parts.pop()
        boro = None
        for b in ("Brooklyn", "New-York", "Bronx", "Queens", "Staten-Island"):
            if b.lower() in url.lower():
                boro = "Manhattan" if b == "New-York" else b.replace("-", " ")
                break
        return _tidy(" ".join(parts)), boro, unit
    return None, None, None


def _decode(part) -> str:
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, "ignore")
    except Exception:
        return ""


def _bodies(msg) -> str:
    if msg.is_multipart():
        return " ".join(_decode(p) for p in msg.walk() if p.get_content_type() in ("text/html", "text/plain"))
    return _decode(msg)


def pull_alert_records(max_messages: int = 40) -> tuple[list[dict[str, Any]], str]:
    """Return (records, status_note). Config-absent is a clean, silent skip."""
    try:
        cfg = json.loads(CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        return [], "not_configured"
    if "PASTE" in json.dumps(cfg) or not cfg.get("app_password"):
        return [], "not_configured"

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        box = imaplib.IMAP4_SSL(cfg.get("imap_host", "imap.gmail.com"))
        box.login(cfg["email"], cfg["app_password"])
        box.select(cfg.get("folder", "INBOX"), readonly=True)
        senders = cfg.get("senders") or ["notifications@streeteasy.com", "convo@zillow.com"]
        ids: list[bytes] = []
        for snd in senders:
            ok, data = box.search(None, "FROM", f'"{snd}"', "SINCE", _imap_since())
            if ok == "OK" and data and data[0]:
                ids.extend(data[0].split())
        for mid in ids[-max_messages:]:
            ok, data = box.fetch(mid, "(RFC822)")
            if ok != "OK" or not data or not data[0]:
                continue
            msg = email.message_from_bytes(data[0][1])
            body = _bodies(msg)
            for rx, src in ((SE_URL, "streeteasy_alert"), (ZI_URL, "zillow_alert")):
                for url in rx.findall(body):
                    url = url.rstrip(".#")
                    if url in seen:
                        continue
                    seen.add(url)
                    window = body[max(0, body.find(url) - 400): body.find(url) + 200]
                    pm = PRICE.search(window)
                    addr, boro, unit = address_from_url(url)
                    records.append({
                        "id": "ma-" + re.sub(r"[^a-z0-9]+", "-", url.split("//")[1].lower())[:70],
                        "url": url,
                        "address": addr,
                        "borough": boro,
                        "unit": unit,
                        "title": (f"{addr} {unit}".strip() if addr else None),
                        "body": None,
                        "price": int(pm.group(1).replace(",", "")) if pm else None,
                        "source_hint": src,
                    })
        box.logout()
    except Exception as exc:
        return records, f"error: {exc}"
    return records, "ok"


def _imap_since() -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%d-%b-%Y")


if __name__ == "__main__":
    recs, note = pull_alert_records()
    print(json.dumps({"status": note, "records": len(recs)}))

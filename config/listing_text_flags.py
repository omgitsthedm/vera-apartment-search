"""Read the listing's own words against New York law and the scam playbook.

Two different things get found here, and VERA must never confuse them:

  ILLEGAL DEMAND — the post asks for something New York law forbids.
  This is not a guess about intent. A listing demanding two months'
  security is demanding something HSTPA made unlawful in 2019, whether
  the landlord knows it or not. Each hit names the statute so the reader
  can check it, and the honest read is "this demand is unlawful", not
  "this person is a criminal".

  SCAM CUE — language that correlates with fraud (wire the deposit, keys
  in the mail, I'm abroad). Correlation only. Surfaced as a caution with
  its reasoning, never as an accusation.

Everything here is deterministic regex over text the listing published.
No inference about people, no scoring of landlords — that lives in the
public-record layer where it belongs.
"""
from __future__ import annotations

import re
from typing import Any

# --- Demands New York law forbids -------------------------------------
# Each: (id, pattern, human sentence, statute)
ILLEGAL_PATTERNS: list[tuple[str, re.Pattern, str, str]] = [
    (
        "deposit_over_one_month",
        re.compile(
            r"(two|2|three|3)\s*months?[’'s]*\s*(security|deposit)"
            r"|security\s*(deposit\s*)?(of\s*)?(two|2|three|3)\s*months?"
            r"|first[,\s]+last[,\s]+(and\s+)?(one\s+month\s+)?security",
            re.I,
        ),
        "asks for more than one month's security",
        "HSTPA 2019 caps security at one month's rent",
    ),
    (
        "application_fee_over_cap",
        re.compile(r"\$\s*(2[5-9]|[3-9]\d|\d{3,})\s*(non[-\s]?refundable\s*)?(application|app|credit\s*check|screening)\s*fee"
                   r"|(application|screening|credit\s*check)\s*fee[:\s]*\$\s*(2[5-9]|[3-9]\d|\d{3,})", re.I),
        "advertises an application fee above the legal cap",
        "HSTPA 2019 caps application/screening fees at $20",
    ),
    (
        "holding_deposit",
        re.compile(r"(holding|good[-\s]?faith)\s*(deposit|fee)|deposit\s*to\s*hold\s*(the\s*)?(apartment|unit|place)"
                   r"|hold\s*(the\s*)?(apartment|unit)\s*with\s*a?\s*deposit", re.I),
        "asks for a deposit to hold the apartment before a lease",
        "Holding/good-faith deposits are not lawful in New York",
    ),
    (
        "key_money",
        re.compile(r"key\s*money|super[’'s]*\s*(tip|fee)|tip\s*(for|to)\s*the\s*super|finder[’'s]*\s*fee\s*to\s*(the\s*)?super", re.I),
        "asks for key money or a payment to the super",
        "Key money is illegal in New York",
    ),
    (
        "tenant_pays_landlords_broker",
        re.compile(r"(tenant|renter)\s*pays?\s*(the\s*)?broker|broker[’'s]*\s*fee\s*paid\s*by\s*(the\s*)?(tenant|renter)"
                   r"|(one\s*month|15%|12%|10%)\s*broker\s*fee\s*(due|paid)\s*(by|from)\s*(the\s*)?tenant", re.I),
        "bills the tenant for a broker the landlord engaged",
        "FARE Act (NYC LL119/2024, in force 11 Jun 2025): whoever hires the broker pays",
    ),
]

# --- Fraud-correlated language (caution, never accusation) -------------
SCAM_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("wire_payment", re.compile(r"wire\s*transfer|western\s*union|money\s*gram|moneygram", re.I),
     "asks to be paid by wire — untraceable and unrecoverable"),
    ("app_payment", re.compile(r"\b(zelle|venmo|cash\s*app|cashapp|apple\s*pay)\b.{0,40}(deposit|first|rent|hold)"
                               r"|(deposit|rent|hold).{0,40}\b(zelle|venmo|cash\s*app|cashapp)\b", re.I),
     "asks for money through a peer-to-peer app, which has no buyer protection"),
    ("crypto_payment", re.compile(r"\b(bitcoin|btc|crypto|usdt|ethereum)\b.{0,30}(deposit|rent|payment)", re.I),
     "asks for cryptocurrency"),
    ("keys_mailed", re.compile(r"(keys?|lease)\s*(will\s*be\s*)?(mail|ship|fedex|courier)(ed)?"
                               r"|mail\s*(you\s*)?the\s*keys?", re.I),
     "offers to mail the keys — you would pay before ever standing in the apartment"),
    ("owner_absent", re.compile(r"currently\s*(abroad|overseas|out\s*of\s*(the\s*)?country|on\s*a?\s*mission)"
                                r"|i\s*am\s*(abroad|overseas|out\s*of\s*town)|relocated\s*(abroad|overseas)", re.I),
     "says the owner is away and cannot show it in person"),
    ("no_viewing", re.compile(r"(no|without)\s*(in[-\s]?person\s*)?(viewing|showing|visit)s?\s*(available|possible|until)"
                              r"|sight\s*unseen|virtual\s*tour\s*only", re.I),
     "will not let you see it in person before committing"),
    ("deposit_before_lease", re.compile(r"(deposit|payment|money)\s*(first|up\s*front|before)\s*(then|to|for)?\s*"
                                        r"(i\s*will\s*)?(send|show|give|release)\s*(the\s*)?(keys?|address|lease|unit)", re.I),
     "wants money before you see the apartment or sign anything"),
    ("urgency_pressure", re.compile(r"(must|need\s*to)\s*(rent|move|decide)\s*(today|now|immediately|within\s*24)"
                                    r"|first\s*come\s*first\s*serve.{0,30}deposit", re.I),
     "pressures an immediate decision, which is how deposits get taken"),
]


def scan_listing_text(listing: dict[str, Any]) -> dict[str, Any]:
    """Return {illegal_demands: [...], scam_cues: [...]} for one listing."""
    text = " ".join(
        str(listing.get(k) or "")
        for k in ("title", "description", "body", "full_description")
    )
    if not text.strip():
        return {}

    illegal = []
    for key, pattern, sentence, statute in ILLEGAL_PATTERNS:
        m = pattern.search(text)
        if m:
            illegal.append({
                "id": key,
                "says": sentence,
                "law": statute,
                "quote": " ".join(m.group(0).split())[:90],
            })

    cues = []
    for key, pattern, sentence in SCAM_PATTERNS:
        m = pattern.search(text)
        if m:
            cues.append({
                "id": key,
                "says": sentence,
                "quote": " ".join(m.group(0).split())[:90],
            })

    out: dict[str, Any] = {}
    if illegal:
        out["illegal_demands"] = illegal[:4]
    if cues:
        out["scam_cues_found"] = cues[:5]
    return out

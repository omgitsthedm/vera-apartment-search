#!/usr/bin/env python3
"""Perceptual photo hashing — the stolen-photo detector, v2.

The hotlink check catches a reused URL; this catches the reuploaded copy.
Nightly, for each listing's lead photo not yet hashed: download (bounded),
compute an 8×8 average hash, and flag any pair of DIFFERENT addresses
whose hashes sit within hamming distance 4 — same photo, different
apartment, the classic cloned-listing fingerprint. Flags land in
state/photo_clone_flags.json; build_snapshot folds them into
photo_clone_suspect. Non-fatal everywhere; skips silently without PIL.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "latest_snapshot.json"
HASHES = ROOT / "state" / "photo_hashes.json"
FLAGS = ROOT / "state" / "photo_clone_flags.json"
PER_RUN = 80
TIMEOUT = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"}


def read(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return fallback


def ahash(img_bytes: bytes) -> str | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("L").resize((8, 8))
        px = list(img.getdata())
        mean = sum(px) / 64
        bits = 0
        for i, p in enumerate(px):
            if p >= mean:
                bits |= 1 << i
        return f"{bits:016x}"
    except Exception:
        return None


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def addr_key(rec: dict) -> str:
    return " ".join(str(rec.get("address_normalized") or "").strip().lower().split())


def owner_key(rec: dict) -> str:
    """A stable identity for whoever is behind the listing, or "".

    The clone rule is "same photo, different address", and on its own that
    accuses a landlord who reuses one marketing photo across their own
    buildings — which is ordinary and not fraud. The first night portfolio
    data reached the cloud (2026-08-04) both flagged listings were
    322 E 81 St and 321 E 75 St, filed under Round Hill Management and
    Frank & Walter Eberhart L.P. #1 — and JustFix puts both under
    Eberhart Brothers, LLC at 312 East 82nd Street, 46 buildings. The same
    owner, two of their own walk-ups, one photo.

    That flag costs a listing 20 points of confidence. Both scored 59.6 and
    59.9 against a 60.0 bar.

    Business address first: corporate names differ across a portfolio far
    more often than the address they all file from.
    """
    p = rec.get("landlord_portfolio") or {}
    for field in ("topbusinessaddr", "topcorp"):
        v = " ".join(str(p.get(field) or "").strip().lower().split())
        if v:
            return v
    return " ".join(str(rec.get("owner_name") or "").strip().lower().split())


def main() -> int:
    snap = read(SNAPSHOT, {})
    pool, seen = [], set()
    for key in ("shortlist", "reviewed_out"):
        for rec in snap.get(key) or []:
            uid = rec.get("listing_uid")
            if uid and uid not in seen:
                seen.add(uid)
                pool.append(rec)

    store = read(HASHES, {})
    fetched = 0
    for rec in pool:
        if fetched >= PER_RUN:
            break
        urls = [u for u in (rec.get("image_urls") or []) if isinstance(u, str) and u.startswith("https://")]
        if not urls:
            continue
        url = urls[0]
        ukey = hashlib.sha1(url.encode()).hexdigest()[:16]
        if ukey in store:
            entry = store[ukey]
            entry["uid"] = rec["listing_uid"]
            entry["addr"] = addr_key(rec) or entry.get("addr", "")
            # Refreshed, not just set on first write: every hash cached
            # before the owner check existed carries none, and portfolio
            # data arrives a cycle after the photo does. Without this the
            # guard would never fire for an already-hashed photo.
            entry["owner"] = owner_key(rec) or entry.get("owner", "")
            continue
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                blob = resp.read(2_500_000)
            fetched += 1
        except Exception:
            store[ukey] = {"ahash": None, "uid": rec["listing_uid"], "addr": addr_key(rec), "owner": owner_key(rec)}
            continue
        store[ukey] = {"ahash": ahash(blob), "uid": rec["listing_uid"], "addr": addr_key(rec), "owner": owner_key(rec)}

    entries = [(k, v) for k, v in store.items() if v.get("ahash")]
    flags: dict[str, str] = {}
    same_owner = 0
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = entries[i][1], entries[j][1]
            if not a.get("addr") or not b.get("addr") or a["addr"] == b["addr"]:
                continue
            if hamming(a["ahash"], b["ahash"]) > 4:
                continue
            # Same photo across two buildings the SAME owner holds is a
            # landlord reusing their own marketing shot, not a cloned
            # listing — and the flag costs 20 points of confidence.
            #
            # Only suppressed when BOTH sides have a known owner and they
            # match. If either is unknown the flag stands: the photo really
            # is being reused across addresses, and silence would be the
            # more dangerous error of the two.
            oa, ob = a.get("owner") or "", b.get("owner") or ""
            if oa and ob and oa == ob:
                same_owner += 1
                continue
            flags[a["uid"]] = b["uid"]
            flags[b["uid"]] = a["uid"]

    HASHES.parent.mkdir(parents=True, exist_ok=True)
    HASHES.write_text(json.dumps(store, separators=(",", ":")))
    FLAGS.write_text(json.dumps(flags, separators=(",", ":")))
    print(f"[photo-hash] {len(store)} hashed (+{fetched} new), {len(flags)} clone flags across addresses"
          f"{f', {same_owner} same-owner reuse not flagged' if same_owner else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
            continue
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                blob = resp.read(2_500_000)
            fetched += 1
        except Exception:
            store[ukey] = {"ahash": None, "uid": rec["listing_uid"], "addr": addr_key(rec)}
            continue
        store[ukey] = {"ahash": ahash(blob), "uid": rec["listing_uid"], "addr": addr_key(rec)}

    entries = [(k, v) for k, v in store.items() if v.get("ahash")]
    flags: dict[str, str] = {}
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            a, b = entries[i][1], entries[j][1]
            if not a.get("addr") or not b.get("addr") or a["addr"] == b["addr"]:
                continue
            if hamming(a["ahash"], b["ahash"]) <= 4:
                flags[a["uid"]] = b["uid"]
                flags[b["uid"]] = a["uid"]

    HASHES.parent.mkdir(parents=True, exist_ok=True)
    HASHES.write_text(json.dumps(store, separators=(",", ":")))
    FLAGS.write_text(json.dumps(flags, separators=(",", ":")))
    print(f"[photo-hash] {len(store)} hashed (+{fetched} new), {len(flags)} clone flags across addresses")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""AI-generated listing-photo detection ("housefishing") via Hugging Face.

Mamdani's July 2026 Rental Ripoff Report proposed mandatory AI-photo
disclosure; VERA does not wait for the rule. A local HF image classifier
scores each lead photo once; scores ≥ 0.85 flag ai_photo_suspect with the
probability attached — ALWAYS presented as probabilistic, never proof,
and deliberately NOT wired into confidence deductions (only the four
approved weights touch the score).

Runs where transformers exists (the cloud job installs it; the Mac skips
silently unless David installs it). Bounded 40 photos/run, cached by uid.
"""
from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "latest_snapshot.json"
FLAGS = ROOT / "state" / "ai_photo_flags.json"
MODEL = "umm-maybe/AI-image-detector"
PER_RUN = 40
THRESHOLD = 0.85
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"}


def read(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return fallback


def main() -> int:
    try:
        from transformers import pipeline  # noqa: WPS433
        from PIL import Image
    except ImportError:
        print("[ai-photo] transformers not installed — skipped (cloud job carries it)")
        return 0

    snap = read(SNAPSHOT, {})
    pool, seen = [], set()
    for key in ("shortlist", "reviewed_out"):
        for rec in snap.get(key) or []:
            uid = rec.get("listing_uid")
            if uid and uid not in seen:
                seen.add(uid)
                pool.append(rec)

    flags = read(FLAGS, {})
    clf = pipeline("image-classification", model=MODEL)
    scored = 0
    for rec in pool:
        if scored >= PER_RUN:
            break
        uid = rec["listing_uid"]
        if uid in flags:
            continue
        urls = [u for u in (rec.get("image_urls") or []) if isinstance(u, str) and u.startswith("https://")]
        if not urls:
            continue
        try:
            req = urllib.request.Request(urls[0], headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                img = Image.open(io.BytesIO(resp.read(2_500_000))).convert("RGB")
            out = clf(img)
            prob = 0.0
            for row in out:
                if "artificial" in str(row.get("label", "")).lower() or str(row.get("label", "")).lower() == "ai":
                    prob = float(row.get("score") or 0)
            flags[uid] = {"prob_ai": round(prob, 3), "model": MODEL}
            scored += 1
        except Exception:
            flags[uid] = {"prob_ai": None, "model": MODEL}
            continue

    FLAGS.parent.mkdir(parents=True, exist_ok=True)
    FLAGS.write_text(json.dumps(flags, separators=(",", ":")))
    hot = sum(1 for v in flags.values() if (v.get("prob_ai") or 0) >= THRESHOLD)
    print(f"[ai-photo] {len(flags)} scored (+{scored} new), {hot} above the {THRESHOLD} line")
    return 0


if __name__ == "__main__":
    sys.exit(main())

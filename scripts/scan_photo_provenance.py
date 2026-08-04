#!/usr/bin/env python3
"""Photo provenance — what the image file says about itself.

Two honest tiers, and this script only ships the certain one:

  FACT      the file carries a generator marker (C2PA Content Credentials,
            an XMP digital-source-type of trainedAlgorithmicMedia, or an
            EXIF Software tag naming a generator). That is the image
            declaring itself synthetic. No inference, no guessing.

  ABSENCE   no camera EXIF at all. Common in AI output — and equally
            common after any portal re-encodes an upload, so on its own
            it means almost nothing. Recorded as context, never a verdict.

A probabilistic classifier is deliberately NOT here: the only
ONNX-ready public detector is cc-by-nc-3.0 (non-commercial — unusable
in a public product), and the apache-2.0 alternative needs a ~2.5GB
torch stack for a signal that would be excluded from scoring anyway.
See docs/proposals/ai-photo-detection.md.

Writes state/photo_provenance.json: {listing_uid: {...}}.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "snapshots" / "latest_snapshot.json"
OUT = ROOT / "state" / "photo_provenance.json"
PER_RUN = 60
TIMEOUT = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"}

# Generator names that appear in EXIF Software / XMP CreatorTool.
GEN_RE = re.compile(
    rb"(stable\s*diffusion|midjourney|dall[\s\-]?e|firefly|imagen|flux\.1|"
    rb"leonardo\.ai|nightcafe|dreamstudio|automatic1111|comfyui|invokeai|"
    rb"novelai|craiyon|bing image creator|designer\.microsoft|sora)",
    re.I,
)
# C2PA / CAI manifest markers embedded in JPEG/PNG containers.
C2PA_RE = re.compile(rb"(c2pa|jumbf|contentauth|urn:uuid:c2pa)", re.I)
# XMP digital source type — the ISO term for synthetic media.
XMP_SYNTH_RE = re.compile(rb"(trainedAlgorithmicMedia|compositeSynthetic|algorithmicMedia)", re.I)


def read(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return fallback


def inspect(blob: bytes) -> dict:
    """Return provenance facts about one image's bytes."""
    head = blob[:262144]  # metadata lives near the front
    out: dict[str, object] = {}

    gen = GEN_RE.search(head)
    if gen:
        out["generator_marker"] = gen.group(1).decode("utf-8", "ignore").strip()
    if XMP_SYNTH_RE.search(head):
        out["xmp_synthetic"] = True
    if C2PA_RE.search(head):
        out["c2pa_present"] = True

    camera = None
    try:
        from PIL import Image, ExifTags
        img = Image.open(io.BytesIO(blob))
        exif = img.getexif() or {}
        tags = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
        make, model = tags.get("Make"), tags.get("Model")
        if make or model:
            camera = " ".join(str(x).strip() for x in (make, model) if x)
        soft = str(tags.get("Software") or "")
        if soft and GEN_RE.search(soft.encode()):
            out["generator_marker"] = soft.strip()
        out["pixels"] = f"{img.width}x{img.height}"
    except Exception:
        pass

    if camera:
        out["camera"] = camera
    else:
        out["no_camera_exif"] = True

    # The only claim strong enough to show as fact.
    out["declares_ai"] = bool(out.get("generator_marker") or out.get("xmp_synthetic"))
    return out


def main() -> int:
    snap = read(SNAPSHOT, {})
    pool, seen = [], set()
    for key in ("shortlist", "reviewed_out"):
        for rec in snap.get(key) or []:
            uid = rec.get("listing_uid")
            if uid and uid not in seen:
                seen.add(uid)
                pool.append(rec)

    store = read(OUT, {})
    fetched = 0
    declared = 0
    for rec in pool:
        uid = rec.get("listing_uid")
        urls = [u for u in (rec.get("image_urls") or []) if isinstance(u, str) and u.startswith("https://")]
        if not uid or not urls:
            continue
        key = hashlib.sha1(urls[0].encode()).hexdigest()[:16]
        prev = store.get(uid)
        if prev and prev.get("_k") == key:
            if prev.get("declares_ai"):
                declared += 1
            continue
        if fetched >= PER_RUN:
            continue
        try:
            req = urllib.request.Request(urls[0], headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                blob = resp.read(3_000_000)
            fetched += 1
        except Exception:
            continue
        info = inspect(blob)
        info["_k"] = key
        store[uid] = info
        if info.get("declares_ai"):
            declared += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(store, separators=(",", ":")))
    cams = sum(1 for v in store.values() if v.get("camera"))
    print(f"[provenance] {len(store)} inspected (+{fetched} new) · {declared} declare AI generation · {cams} carry camera EXIF")
    return 0


if __name__ == "__main__":
    sys.exit(main())

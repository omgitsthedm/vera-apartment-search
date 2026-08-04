#!/usr/bin/env python3
"""Build the public feed from a snapshot, with no Netlify token involved.

WHY
---
The cloud sweep has been running the full pipeline daily and finding real
listings — 231 on 2026-08-04, including 179 from Craigslist, which the Mac
cannot reach as reliably. Every one of them died in a GitHub artifact that
expires in seven days and that no human or browser can read. The live feed
only refreshed when David's Mac happened to run.

Publishing to Netlify needs a token David has not created. Rather than wait
on that, this writes the same sanitized feed to a plain directory, which the
workflow force-pushes to an orphan `feed` branch of this PUBLIC repo.
raw.githubusercontent.com then serves it with `access-control-allow-origin: *`
and a 5-minute cache — so the browser can read it directly, with no secret
anywhere in the chain, and the Mac can be off.

An orphan branch (not main) keeps a 1.5MB daily JSON out of the repo's real
history: each publish replaces the single commit rather than stacking on it.

SAFETY
------
The payload goes through the same lens as the Netlify feed — literally the
same module — and then through audit_public_payload(), which walks the
finished structure looking for personal fields and un-neutralized watchlist
wording. A non-empty audit is a hard failure: nothing is written, and the
workflow step fails loudly. A feed that does not publish is a bad day; a
feed that publishes someone's phone number is not recoverable.

Usage: python3 scripts/publish_cloud_feed.py [--out public_feed]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from public_lens import (  # noqa: E402
    audit_public_payload,
    build_hunt_payload,
    build_public_extras,
    build_public_payload,
    maintain_archive,
)

SNAPSHOTS = ROOT / "snapshots"
LATEST = SNAPSHOTS / "latest_snapshot.json"
LKG = SNAPSHOTS / "last_known_good_snapshot.json"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def load_snapshot() -> tuple[dict[str, Any], str]:
    """Prefer a successful latest run; fall back to last-known-good.

    Mirrors the dashboard's rule. A degraded run must not blank the feed —
    stale-but-true beats empty, and the app shows the run's own timestamp so
    a visitor can see for themselves how fresh it is.
    """
    latest = read_json(LATEST, default={}) or {}
    if latest.get("snapshot", {}).get("status") == "success":
        return latest, "latest"
    lkg = read_json(LKG, default={}) or {}
    if lkg:
        return lkg, "last_known_good"
    if latest:
        return latest, "latest_degraded"
    raise FileNotFoundError("No VERA snapshot available to publish")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="public_feed",
                    help="directory to write the feed into (default: public_feed)")
    args = ap.parse_args()

    out = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    snapshot, source = load_snapshot()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {**snapshot, "generated_at": generated_at}

    # Every cloud publish carried run_id: null, because state/latest_run.json
    # is written by the Mac's autonomous runners and run_daily.sh — which is
    # what the cloud runs — never writes it. So the System page's Run panel
    # named nothing, and no published feed could be traced to the run that
    # produced it. In Actions the run genuinely does have an identity.
    run_id = os.environ.get("GITHUB_RUN_ID")
    if run_id:
        run = dict(payload.get("run") or {})
        if not run.get("run_id"):
            run["run_id"] = f"cloud-{run_id}"
            run.setdefault("cadence", "nightly")
            repo = os.environ.get("GITHUB_REPOSITORY")
            if repo:
                run["log_url"] = f"https://github.com/{repo}/actions/runs/{run_id}"
        payload["run"] = run

    hunt = build_hunt_payload(payload)
    extras = build_public_extras(payload, snapshot_root=SNAPSHOTS)
    public = build_public_payload(hunt, extras=extras)
    public["origin"] = "cloud"          # the app labels where a feed came from

    problems = audit_public_payload(public)
    if problems:
        print("REFUSING TO PUBLISH — the privacy audit found:", file=sys.stderr)
        for p in problems[:20]:
            print(f"  - {p}", file=sys.stderr)
        if len(problems) > 20:
            print(f"  ... and {len(problems) - 20} more", file=sys.stderr)
        return 1

    (out / "public.json").write_text(json.dumps(public) + "\n")
    archive_stat = maintain_archive(public, out)

    pool = public.get("pool") or []
    sources: dict[str, int] = {}
    for listing in pool:
        if isinstance(listing, dict):
            name = listing.get("source_name") or "unknown"
            sources[name] = sources.get(name, 0) + 1

    meta = {
        "generated_at": generated_at,
        "origin": "cloud",
        "snapshot_source": source,
        "run_id": (public.get("run") or {}).get("run_id"),
        "pool": len(pool),
        "shortlist": len(public.get("shortlist") or []),
        "sources": dict(sorted(sources.items(), key=lambda kv: -kv[1])),
        "bytes": (out / "public.json").stat().st_size,
        "archive": archive_stat,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))

    if not pool:
        # Not a failure: an honest empty run is a real outcome and the app
        # says so. But it should never pass silently in the log.
        print("[WARN] published an EMPTY pool — check source health", file=sys.stderr)

    # Whole-market aggregates and commute times are separate layers, and the
    # first cloud publish silently shipped without either. Missing them is
    # not fatal — the feed is still true — but it must be visible in the log
    # rather than discovered later as a blank Market page.
    for layer, present in (("market_context", public.get("market_context")),
                           ("transit_tables", public.get("transit_tables"))):
        if not present:
            print(f"[WARN] {layer} missing — that page will be empty", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

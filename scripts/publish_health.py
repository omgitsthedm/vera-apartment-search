#!/usr/bin/env python3
"""VERA Dashboard Publish Health Check & Verification.

Provides pre-publish validation, post-publish live-site verification,
stale-site detection, publish metadata management, and operator reporting.

Usage:
    python3 publish_health.py --phase pre-publish
    python3 publish_health.py --phase post-publish --expected-hash <hash>
    python3 publish_health.py --phase report
    python3 publish_health.py --phase stale-check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.paths import (VERA_ROOT as ROOT, DASHBOARD_ROOT, DASHBOARD_DATA_DIR as SITE_DATA_ROOT,
    LEGACY_STATE_DIR as STATE_ROOT, LOG_DIR as LOG_ROOT, REPORT_DIR as REPORT_ROOT)

# The feed site deploy_netlify.sh actually targets. (The old value pointed
# at nyc-apartment-search-vera.netlify.app — a retired site — which made
# every post-publish verification fail against stale content.)
LIVE_SITE_BASE = "https://vera-pipeline.netlify.app"
# dashboard.json is private now; the deployed contract is public.json.
LIVE_DASHBOARD_URL = f"{LIVE_SITE_BASE}/data/public.json"
LIVE_HASH_URL = f"{LIVE_SITE_BASE}/data/content_hash.txt"

PUBLISH_STATE_PATH = ROOT / ".publish_state.json"
LAST_DEPLOYED_HASH_PATH = ROOT / ".last_deployed_hash"
CONTENT_HASH_PATH = SITE_DATA_ROOT / "content_hash.txt"
DASHBOARD_JSON_PATH = SITE_DATA_ROOT.parent.parent / "private" / "data" / "dashboard.json"

# Stale threshold: if local is newer than live by more than this many seconds,
# flag it. 300s = 5 minutes — generous for Netlify CDN propagation.
STALE_THRESHOLD_SECONDS = 300


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json_safe(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json_safe(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_text_safe(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def fetch_url_text(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL and return text content, or None on failure."""
    try:
        request = urllib.request.Request(url, headers={
            "User-Agent": "VERA-PublishHealthCheck/1.0",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "ignore")
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def compute_dashboard_hash(dashboard_path: Path) -> str | None:
    """Compute stable content hash from dashboard.json, matching sync logic."""
    if not dashboard_path.exists():
        return None
    try:
        payload = json.loads(dashboard_path.read_text())
        stable = {k: v for k, v in payload.items() if k not in ("generated_at", "publish", "stages", "run", "source_health")}
        vera_section = stable.get("vera", {})
        stable["vera"] = {
            k: v for k, v in vera_section.items()
            if k not in ("last_run_started_at", "last_run_finished_at")
        }
        return hashlib.sha256(
            json.dumps(stable, sort_keys=True).encode()
        ).hexdigest()[:16]
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Pre-publish health checks
# ---------------------------------------------------------------------------

def pre_publish_check() -> dict[str, Any]:
    """Validate that local pipeline output is ready for publishing."""
    checks: list[dict[str, Any]] = []
    all_passed = True

    # 1. Latest scored inventory exists
    scored_state = read_json_safe(STATE_ROOT / "current_scored.json", {})
    scored_path = scored_state.get("scored_json_path")
    scored_candidate = Path(scored_path) if scored_path else None
    if scored_candidate and not scored_candidate.exists():
        fallback = ROOT / "scored" / scored_candidate.name
        scored_candidate = fallback if fallback.exists() else None
    if scored_candidate and scored_candidate.exists():
        checks.append({"check": "scored_inventory_exists", "passed": True,
                        "detail": str(scored_candidate)})
    else:
        checks.append({"check": "scored_inventory_exists", "passed": False,
                        "detail": "No scored inventory found"})
        all_passed = False

    # 2. Enriched data exists
    enriched_state = read_json_safe(STATE_ROOT / "current_enriched.json", {})
    enriched_path = enriched_state.get("enriched_path")
    enriched_candidate = Path(enriched_path) if enriched_path else None
    if enriched_candidate and not enriched_candidate.exists():
        fallback = ROOT / "enriched" / enriched_candidate.name
        enriched_candidate = fallback if fallback.exists() else None
    if enriched_candidate and enriched_candidate.exists():
        checks.append({"check": "enriched_data_exists", "passed": True,
                        "detail": str(enriched_candidate)})
    else:
        checks.append({"check": "enriched_data_exists", "passed": False,
                        "detail": "No enriched data found"})
        all_passed = False

    # 3. Dashboard root exists
    if DASHBOARD_ROOT.exists():
        checks.append({"check": "dashboard_root_exists", "passed": True,
                        "detail": str(DASHBOARD_ROOT)})
    else:
        checks.append({"check": "dashboard_root_exists", "passed": False,
                        "detail": f"Dashboard root missing: {DASHBOARD_ROOT}"})
        all_passed = False

    # 4. Sync script exists
    sync_script = DASHBOARD_ROOT / "scripts" / "sync_vera_dashboard.py"
    if sync_script.exists():
        checks.append({"check": "sync_script_exists", "passed": True,
                        "detail": str(sync_script)})
    else:
        checks.append({"check": "sync_script_exists", "passed": False,
                        "detail": f"Sync script missing: {sync_script}"})
        all_passed = False

    # 5. No critical pipeline failure — check that scored state has a recent stamp
    run_stamp = scored_state.get("run_stamp", "")
    if run_stamp:
        checks.append({"check": "pipeline_run_stamp_present", "passed": True,
                        "detail": f"run_stamp={run_stamp}"})
    else:
        checks.append({"check": "pipeline_run_stamp_present", "passed": False,
                        "detail": "No run stamp in scored state"})
        all_passed = False

    # 6. Raw manifest exists with at least one OK source
    raw_manifest = read_json_safe(STATE_ROOT / "current_raw_snapshots.json", {})
    ok_sources = [s for s in raw_manifest.get("sources", [])
                  if s.get("status") == "ok"]
    if ok_sources:
        checks.append({"check": "discovery_sources_ok", "passed": True,
                        "detail": f"{len(ok_sources)} sources with status=ok"})
    else:
        checks.append({"check": "discovery_sources_ok", "passed": False,
                        "detail": "No sources with status=ok in raw manifest"})
        all_passed = False

    result = {
        "phase": "pre-publish",
        "timestamp": utc_now_iso(),
        "all_passed": all_passed,
        "checks": checks,
    }

    # Write pre-publish log
    log_path = LOG_ROOT / "publish_health_pre.json"
    write_json_safe(log_path, result)

    return result


# ---------------------------------------------------------------------------
# Post-publish verification
# ---------------------------------------------------------------------------

def post_publish_verify(expected_hash: str | None = None) -> dict[str, Any]:
    """Verify the live site reflects the just-published snapshot."""
    verifications: list[dict[str, Any]] = []
    all_verified = True

    # Determine expected hash
    if not expected_hash:
        expected_hash = read_text_safe(CONTENT_HASH_PATH)
    if not expected_hash:
        expected_hash = compute_dashboard_hash(DASHBOARD_JSON_PATH)

    # 1. Fetch live content_hash.txt
    live_hash = fetch_url_text(LIVE_HASH_URL)
    if live_hash is not None:
        live_hash = live_hash.strip()
        hash_match = (live_hash == expected_hash)
        verifications.append({
            "check": "live_hash_matches",
            "passed": hash_match,
            "expected": expected_hash,
            "live": live_hash,
        })
        if not hash_match:
            all_verified = False
    else:
        verifications.append({
            "check": "live_hash_matches",
            "passed": False,
            "detail": "Could not fetch live content_hash.txt",
        })
        all_verified = False

    # 2. Fetch live dashboard.json and verify structure
    live_dashboard_text = fetch_url_text(LIVE_DASHBOARD_URL)
    if live_dashboard_text is not None:
        try:
            live_dashboard = json.loads(live_dashboard_text)

            # Check generated_at exists
            live_generated = live_dashboard.get("generated_at", "")
            verifications.append({
                "check": "live_dashboard_parseable",
                "passed": True,
                "live_generated_at": live_generated,
            })

            # Compare source counts
            local_dashboard = read_json_safe(DASHBOARD_JSON_PATH, {})
            local_sources = len(local_dashboard.get("sources", []))
            live_sources = len(live_dashboard.get("sources", []))
            source_match = (local_sources == live_sources)
            verifications.append({
                "check": "source_count_matches",
                "passed": source_match,
                "local_count": local_sources,
                "live_count": live_sources,
            })
            if not source_match:
                all_verified = False

            # Compare shortlist count
            local_shortlist = len(local_dashboard.get("shortlist", []))
            live_shortlist = len(live_dashboard.get("shortlist", []))
            shortlist_match = (local_shortlist == live_shortlist)
            verifications.append({
                "check": "shortlist_count_matches",
                "passed": shortlist_match,
                "local_count": local_shortlist,
                "live_count": live_shortlist,
            })
            if not shortlist_match:
                all_verified = False

            # Compare summary counts
            local_summary = local_dashboard.get("summary", {})
            live_summary = live_dashboard.get("summary", {})
            summary_match = (
                local_summary.get("pursue_count") == live_summary.get("pursue_count")
                and local_summary.get("cautious_count") == live_summary.get("cautious_count")
                and local_summary.get("skip_count") == live_summary.get("skip_count")
            )
            verifications.append({
                "check": "summary_counts_match",
                "passed": summary_match,
                "local": {k: local_summary.get(k) for k in ("pursue_count", "cautious_count", "skip_count")},
                "live": {k: live_summary.get(k) for k in ("pursue_count", "cautious_count", "skip_count")},
            })
            if not summary_match:
                all_verified = False

        except json.JSONDecodeError:
            verifications.append({
                "check": "live_dashboard_parseable",
                "passed": False,
                "detail": "Live dashboard.json is not valid JSON",
            })
            all_verified = False
    else:
        verifications.append({
            "check": "live_dashboard_parseable",
            "passed": False,
            "detail": "Could not fetch live dashboard.json",
        })
        all_verified = False

    result = {
        "phase": "post-publish",
        "timestamp": utc_now_iso(),
        "all_verified": all_verified,
        "expected_hash": expected_hash,
        "verifications": verifications,
    }

    # Write post-publish log
    log_path = LOG_ROOT / "publish_health_post.json"
    write_json_safe(log_path, result)

    return result


# ---------------------------------------------------------------------------
# Publish metadata management
# ---------------------------------------------------------------------------

def load_publish_state() -> dict[str, Any]:
    return read_json_safe(PUBLISH_STATE_PATH, {
        "last_deployed_hash": None,
        "last_deployed_at": None,
        "last_deploy_result": None,
        "last_verified_at": None,
        "last_verified_hash": None,
        "last_skip_reason": None,
        "deploy_history": [],
    })


def save_publish_state(state: dict[str, Any]) -> None:
    write_json_safe(PUBLISH_STATE_PATH, state)


def record_deploy_event(
    state: dict[str, Any],
    action: str,
    content_hash: str,
    result: str,
    reason: str = "",
    verified: bool | None = None,
    local_run_stamp: str = "",
) -> dict[str, Any]:
    """Record a deploy/skip/fail event in publish state."""
    event = {
        "timestamp": utc_now_iso(),
        "action": action,
        "content_hash": content_hash,
        "result": result,
        "reason": reason,
        "verified": verified,
        "local_run_stamp": local_run_stamp,
    }

    if action == "deployed" and result == "success":
        state["last_deployed_hash"] = content_hash
        state["last_deployed_at"] = event["timestamp"]
        state["last_deploy_result"] = "success"
        if verified is True:
            state["last_verified_at"] = event["timestamp"]
            state["last_verified_hash"] = content_hash
    elif action == "deployed" and result == "verification_failed":
        state["last_deployed_hash"] = content_hash
        state["last_deployed_at"] = event["timestamp"]
        state["last_deploy_result"] = "verification_failed"
    elif action == "skipped":
        state["last_skip_reason"] = reason
    elif action == "failed":
        state["last_deploy_result"] = f"failed: {reason}"

    history = state.setdefault("deploy_history", [])
    history.append(event)
    # Keep last 20 events
    state["deploy_history"] = history[-20:]

    return state


# ---------------------------------------------------------------------------
# Stale site detection
# ---------------------------------------------------------------------------

def stale_site_check() -> dict[str, Any]:
    """Detect if the live site is stale relative to local state."""
    issues: list[str] = []
    is_stale = False

    state = load_publish_state()
    local_hash = read_text_safe(CONTENT_HASH_PATH)
    deployed_hash = state.get("last_deployed_hash") or read_text_safe(LAST_DEPLOYED_HASH_PATH)

    # Fetch live hash
    live_hash = fetch_url_text(LIVE_HASH_URL)
    live_hash = live_hash.strip() if live_hash else None

    # Check 1: deployed hash vs live hash
    if deployed_hash and live_hash and deployed_hash != live_hash:
        issues.append(
            f"Last deployed hash ({deployed_hash}) differs from live hash ({live_hash}). "
            "Netlify may have rolled back or deploy did not propagate."
        )
        is_stale = True

    # Check 2: local hash vs live hash (meaningful local change not reflected)
    if local_hash and live_hash and local_hash != live_hash:
        # Only flag if we think we deployed it
        if state.get("last_deploy_result") == "success" and state.get("last_deployed_hash") == local_hash:
            issues.append(
                f"Local hash ({local_hash}) was deployed but live hash ({live_hash}) differs. "
                "Deploy may have failed silently."
            )
            is_stale = True

    # Check 3: local hash differs from deployed hash (local ran but no deploy happened)
    if local_hash and deployed_hash and local_hash != deployed_hash:
        last_action = (state.get("deploy_history") or [{}])[-1] if state.get("deploy_history") else {}
        if last_action.get("action") == "skipped":
            # This is intentional — no stale flag needed
            pass
        elif last_action.get("action") not in ("deployed",):
            issues.append(
                f"Local content changed ({local_hash}) but no deploy was recorded. "
                "A deploy may be needed."
            )

    # Check 4: live dashboard timestamp freshness
    live_dashboard_text = fetch_url_text(LIVE_DASHBOARD_URL)
    if live_dashboard_text:
        try:
            live_data = json.loads(live_dashboard_text)
            live_vera = live_data.get("vera", {})
            live_finished = live_vera.get("last_run_finished_at")
            if live_finished:
                # Just report the timestamp — don't hard-fail on timing
                issues_detail = f"Live site last_run_finished_at: {live_finished}"
            else:
                issues_detail = "Live site has no last_run_finished_at timestamp"
        except json.JSONDecodeError:
            issues.append("Live dashboard.json is not valid JSON")
            is_stale = True

    result = {
        "phase": "stale-check",
        "timestamp": utc_now_iso(),
        "is_stale": is_stale,
        "local_hash": local_hash,
        "deployed_hash": deployed_hash,
        "live_hash": live_hash,
        "issues": issues,
    }

    log_path = LOG_ROOT / "publish_health_stale.json"
    write_json_safe(log_path, result)

    return result


# ---------------------------------------------------------------------------
# Publish health report
# ---------------------------------------------------------------------------

def generate_report() -> dict[str, Any]:
    """Generate the operator-facing publish health report."""
    state = load_publish_state()
    local_hash = read_text_safe(CONTENT_HASH_PATH)
    deployed_hash = state.get("last_deployed_hash") or read_text_safe(LAST_DEPLOYED_HASH_PATH)

    # Pipeline status
    scored_state = read_json_safe(STATE_ROOT / "current_scored.json", {})
    enriched_state = read_json_safe(STATE_ROOT / "current_enriched.json", {})

    pipeline_ok = bool(scored_state.get("scored_json_path") and enriched_state.get("enriched_path"))

    # Dashboard sync status
    dashboard_exists = DASHBOARD_JSON_PATH.exists()
    dashboard_hash = compute_dashboard_hash(DASHBOARD_JSON_PATH) if dashboard_exists else None

    # Deploy decision
    last_event = (state.get("deploy_history") or [{}])[-1] if state.get("deploy_history") else {}
    deploy_decision = last_event.get("action", "unknown")
    deploy_result = last_event.get("result", "unknown")

    # Live verification
    live_hash = fetch_url_text(LIVE_HASH_URL)
    live_hash = live_hash.strip() if live_hash else None
    live_verified = (live_hash == local_hash) if live_hash and local_hash else None

    # Stale warning
    stale_warning = None
    if live_hash and local_hash and live_hash != local_hash:
        if deployed_hash == local_hash:
            stale_warning = "STALE: Local content was deployed but live site shows different hash"
        elif deployed_hash != local_hash:
            stale_warning = "PENDING: Local content changed but has not been deployed yet"

    report = {
        "phase": "report",
        "timestamp": utc_now_iso(),
        "local_pipeline_status": "ok" if pipeline_ok else "failed",
        "local_pipeline_run_stamp": scored_state.get("run_stamp"),
        "dashboard_sync_status": "ok" if dashboard_exists else "missing",
        "dashboard_hash_computed": dashboard_hash,
        "deploy_decision": deploy_decision,
        "deploy_result": deploy_result,
        "expected_content_hash": local_hash,
        "last_deployed_hash": deployed_hash,
        "last_verified_hash": state.get("last_verified_hash"),
        "live_hash": live_hash,
        "live_verification": (
            "VERIFIED" if live_verified is True
            else "MISMATCH" if live_verified is False
            else "UNKNOWN"
        ),
        "stale_warning": stale_warning,
        "last_deployed_at": state.get("last_deployed_at"),
        "last_verified_at": state.get("last_verified_at"),
        "operator_summary": _build_operator_summary(
            pipeline_ok, dashboard_exists, deploy_decision, deploy_result,
            live_verified, stale_warning, local_hash, deployed_hash, live_hash,
        ),
    }

    # Write report
    report_dir = REPORT_ROOT / "publish_health"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / f"publish_health_{stamp}.json"
    write_json_safe(report_path, report)

    # Also write latest pointer
    write_json_safe(report_dir / "latest_publish_health.json", report)

    return report


def _build_operator_summary(
    pipeline_ok: bool,
    dashboard_exists: bool,
    deploy_decision: str,
    deploy_result: str,
    live_verified: bool | None,
    stale_warning: str | None,
    local_hash: str,
    deployed_hash: str | None,
    live_hash: str | None,
) -> str:
    """Build a concise one-line operator summary."""
    parts: list[str] = []

    if not pipeline_ok:
        return "PIPELINE FAILED — no publish attempted"
    parts.append("pipeline=ok")

    if not dashboard_exists:
        return "PIPELINE OK — dashboard sync missing"
    parts.append("sync=ok")

    if deploy_decision == "deployed" and deploy_result == "success":
        parts.append("deploy=success")
    elif deploy_decision == "deployed" and deploy_result == "verification_failed":
        parts.append("deploy=VERIFICATION_FAILED")
    elif deploy_decision == "skipped":
        parts.append("deploy=skipped(no-change)")
    elif deploy_decision == "failed":
        parts.append(f"deploy=FAILED({deploy_result})")
    else:
        parts.append(f"deploy={deploy_decision}")

    if live_verified is True:
        parts.append("live=VERIFIED")
    elif live_verified is False:
        parts.append("live=MISMATCH")
    else:
        parts.append("live=unverified")

    if stale_warning:
        parts.append(f"WARNING: {stale_warning}")

    return " // ".join(parts)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="VERA Dashboard Publish Health Check")
    parser.add_argument(
        "--phase",
        choices=["pre-publish", "post-publish", "report", "stale-check"],
        required=True,
        help="Which health check phase to run.",
    )
    parser.add_argument(
        "--expected-hash",
        default=None,
        help="Expected content hash for post-publish verification.",
    )
    args = parser.parse_args()

    if args.phase == "pre-publish":
        result = pre_publish_check()
        print(json.dumps(result, indent=2))
        return 0 if result["all_passed"] else 1

    if args.phase == "post-publish":
        result = post_publish_verify(expected_hash=args.expected_hash)
        print(json.dumps(result, indent=2))
        return 0 if result["all_verified"] else 1

    if args.phase == "stale-check":
        result = stale_site_check()
        print(json.dumps(result, indent=2))
        return 0 if not result["is_stale"] else 1

    if args.phase == "report":
        result = generate_report()
        print(json.dumps(result, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())

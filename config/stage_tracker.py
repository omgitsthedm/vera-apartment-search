"""Stage-based pipeline state tracking for VERA.

Each pipeline stage writes its status to state/stage_<name>.json.
The autonomous runner writes state/latest_run.json with a shared run_id.
Publish gating checks that discover succeeded in the same run_id.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.paths import STATE_DIR, LOG_DIR

STAGES = ("discover", "normalize", "dedupe", "enrich", "score", "publish")
VALID_STATUSES = ("pending", "running", "success", "partial", "failed", "skipped", "blocked")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def get_run_id() -> str:
    """Return the current run_id from VERA_RUN_ID env var, or generate one."""
    return os.environ.get("VERA_RUN_ID", f"manual_{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")


def stage_state_path(stage: str) -> Path:
    return STATE_DIR / f"stage_{stage}.json"


def write_stage_start(stage: str, run_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Record that a stage has started."""
    run_id = run_id or get_run_id()
    state = {
        "stage": stage,
        "run_id": run_id,
        "started_at": _now_iso(),
        "finished_at": None,
        "status": "running",
        "records_in": 0,
        "records_out": 0,
        "errors": [],
        "warnings": [],
        **extra,
    }
    _write_json(stage_state_path(stage), state)
    return state


def write_stage_end(
    stage: str,
    status: str,
    run_id: str | None = None,
    records_in: int = 0,
    records_out: int = 0,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Record that a stage has finished."""
    run_id = run_id or get_run_id()
    existing = _read_json(stage_state_path(stage), default={})
    state = {
        **existing,
        "stage": stage,
        "run_id": run_id,
        "finished_at": _now_iso(),
        "status": status,
        "records_in": records_in,
        "records_out": records_out,
        "errors": errors or [],
        "warnings": warnings or [],
        **extra,
    }
    _write_json(stage_state_path(stage), state)
    return state


def read_stage_state(stage: str) -> dict[str, Any]:
    """Read the current state file for a stage."""
    return _read_json(stage_state_path(stage), default={})


def read_all_stage_states() -> dict[str, dict[str, Any]]:
    """Read all stage state files into a dict keyed by stage name."""
    return {stage: read_stage_state(stage) for stage in STAGES}


def read_latest_run() -> dict[str, Any]:
    """Read the latest_run.json state."""
    return _read_json(STATE_DIR / "latest_run.json", default={})


def check_publish_eligible(run_id: str | None = None) -> tuple[bool, str]:
    """Check if publish is eligible based on discover stage success in current run.

    Returns (eligible, reason).
    """
    run_id = run_id or get_run_id()
    discover_state = read_stage_state("discover")

    if not discover_state:
        return False, "no discover state found"

    if discover_state.get("run_id") != run_id:
        return False, f"discover ran in different run ({discover_state.get('run_id')}) vs current ({run_id})"

    if discover_state.get("status") not in ("success", "partial"):
        return False, f"discover status is '{discover_state.get('status')}', not success/partial"

    return True, "discover succeeded in current run"


def build_source_health_summary(source_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build source health summary from discover stage results."""
    active = len(source_results)
    healthy = sum(1 for s in source_results if s.get("status") == "healthy")
    partial = sum(1 for s in source_results if s.get("status") == "partial")
    degraded = sum(1 for s in source_results if s.get("status") == "degraded")
    broken = sum(1 for s in source_results if s.get("status") in ("broken", "failed"))

    return {
        "active": active,
        "healthy": healthy,
        "partial": partial,
        "degraded": degraded,
        "broken": broken,
    }


# -- Run trend history -----------------------------------------------------

RUN_TREND_FILE = STATE_DIR / "run_trends.json"
MAX_RUN_TRENDS = 7


def record_run_trend(
    run_id: str,
    records_discovered: int,
    records_published: int,
    healthy_sources: int,
    active_sources: int,
    avg_reliability: float,
    pipeline_status: str,
) -> None:
    """Append a summary entry for this run to run_trends.json."""
    trends = _read_json(RUN_TREND_FILE, default=[])
    trends.append({
        "run_id": run_id,
        "timestamp": _now_iso(),
        "records_discovered": records_discovered,
        "records_published": records_published,
        "healthy_sources": healthy_sources,
        "active_sources": active_sources,
        "avg_reliability": round(avg_reliability, 1),
        "pipeline_status": pipeline_status,
    })
    _write_json(RUN_TREND_FILE, trends[-MAX_RUN_TRENDS:])


def read_run_trends() -> list[dict[str, Any]]:
    """Return the last N run trend entries."""
    return _read_json(RUN_TREND_FILE, default=[])

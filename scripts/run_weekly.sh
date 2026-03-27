#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
RUN_ID="${VERA_RUN_ID:-weekly_${STAMP}}"
LOG_PATH="$ROOT/logs/run_weekly_${STAMP}.log"

export VERA_ROOT="$ROOT"
export VERA_RUN_ID="$RUN_ID"

mkdir -p "$ROOT/logs"

{
  echo "=== VERA weekly pipeline starting ==="
  echo "TIMESTAMP: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "RUN_ID:    $RUN_ID"
  echo "ROOT:      $ROOT"
  echo "USER:      $(whoami)"
  echo "PWD:       $(pwd)"
  echo "PYTHON:    $(which python3 2>/dev/null || echo 'NOT FOUND')"
  echo "PATH:      $PATH"
  echo "========================================="

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: health_check"
  "$ROOT/scripts/health_check.sh"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: discover (cadence=weekly)"
  python3 "$ROOT/scripts/discover_listings.py" --cadence weekly

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: normalize"
  python3 "$ROOT/scripts/normalize_listings.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: dedupe"
  python3 "$ROOT/scripts/dedupe_listings.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: refresh_public_records"
  python3 "$ROOT/scripts/refresh_public_records.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: enrich"
  python3 "$ROOT/scripts/enrich_listings.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: score (scope=weekly)"
  python3 "$ROOT/scripts/score_listings.py" --scope weekly

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: build_snapshot"
  python3 "$ROOT/scripts/build_snapshot.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] VERA weekly pipeline complete"
} 2>&1 | tee "$LOG_PATH"

echo "Weekly run log written to: $LOG_PATH"

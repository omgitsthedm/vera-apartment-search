#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
RUN_ID="${VERA_RUN_ID:-daily_${STAMP}}"
LOG_PATH="$ROOT/logs/run_daily_${STAMP}.log"

export VERA_ROOT="$ROOT"
export VERA_RUN_ID="$RUN_ID"

mkdir -p "$ROOT/logs"

{
  echo "=== VERA daily pipeline starting ==="
  python3 "$ROOT/tests/test_scoring.py" >/dev/null 2>&1 && echo "scoring tests: PASS" || echo "[WARN] scoring tests FAILED — see python3 tests/test_scoring.py"
  python3 "$ROOT/tests/test_mail_ingest.py" >/dev/null 2>&1 && echo "mail-ingest tests: PASS" || echo "[WARN] mail-ingest tests FAILED — see python3 tests/test_mail_ingest.py"
  python3 "$ROOT/tests/test_public_lens.py" >/dev/null 2>&1 && echo "public-lens tests: PASS" || echo "[WARN] public-lens tests FAILED — see python3 tests/test_public_lens.py"
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

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: discover (cadence=daily)"
  python3 "$ROOT/scripts/discover_listings.py" --cadence daily

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: normalize"
  python3 "$ROOT/scripts/normalize_listings.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: dedupe"
  python3 "$ROOT/scripts/dedupe_listings.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: refresh_public_records"
  python3 "$ROOT/scripts/refresh_public_records.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: enrich"
  python3 "$ROOT/scripts/enrich_listings.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: score (scope=daily)"
  python3 "$ROOT/scripts/score_listings.py" --scope daily

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: ai_enrich"
  python3 "$ROOT/scripts/ai_enrich.py" || echo "[WARN] ai_enrich failed — continuing with deterministic output"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: track_changes"
  python3 "$ROOT/scripts/track_changes.py" || echo "[WARN] track_changes failed — continuing without change badges"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] stage: build_snapshot"
  python3 "$ROOT/scripts/build_snapshot.py"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] VERA daily pipeline complete"
} 2>&1 | tee "$LOG_PATH"

echo "Daily run log written to: $LOG_PATH"

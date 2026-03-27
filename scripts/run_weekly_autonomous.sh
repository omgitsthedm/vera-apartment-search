#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
RUN_ID="weekly_${STAMP}"
LOG_PATH="$ROOT/logs/run_weekly_autonomous_${STAMP}.log"
STATE_DIR="$ROOT/state"

export VERA_ROOT="$ROOT"
export VERA_RUN_ID="$RUN_ID"
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# Fix macOS Python SSL: default cert bundle is missing, point to certifi
SSL_CERT_FILE="$(/usr/local/bin/python3 -c 'import certifi; print(certifi.where())' 2>/dev/null)" || true
if [[ -n "$SSL_CERT_FILE" && -f "$SSL_CERT_FILE" ]]; then
  export SSL_CERT_FILE
fi

mkdir -p "$ROOT/logs" "$STATE_DIR"

{
  echo "=== VERA autonomous weekly cycle ==="
  echo "TIMESTAMP: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "RUN_ID:    $RUN_ID"
  echo "ROOT:      $ROOT"
  echo "SCRIPT:    $0"
  echo "USER:      $(whoami)"
  echo "PWD:       $(pwd)"
  echo "PYTHON:    $(which python3 2>/dev/null || echo 'NOT FOUND')"
  echo "PATH:      $PATH"
  echo "========================================="

  python3 -c "
import json
from datetime import datetime, timezone
state = {
    'run_id': '$RUN_ID',
    'cadence': 'weekly',
    'started_at': datetime.now(timezone.utc).isoformat(),
    'status': 'running',
    'pipeline_status': 'pending',
    'publish_status': 'pending'
}
with open('$STATE_DIR/latest_run.json', 'w') as f:
    json.dump(state, f, indent=2)
" 2>/dev/null || echo "[WARN] Could not write initial run state"

  PIPELINE_OK=true
  PIPELINE_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if "$ROOT/scripts/run_weekly.sh"; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] pipeline step: SUCCESS"
  else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] pipeline step: FAILED (exit code: $?)"
    PIPELINE_OK=false
  fi
  PIPELINE_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  PUBLISH_OK=true
  PUBLISH_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  PUBLISH_BLOCKED_REASON=""
  if [ "$PIPELINE_OK" = "true" ]; then
    if "$ROOT/scripts/publish_dashboard.sh"; then
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] publish step: COMPLETED"
    else
      echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] publish step: FAILED"
      PUBLISH_OK=false
    fi
  else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] publish step: BLOCKED (pipeline failed)"
    PUBLISH_OK=false
    PUBLISH_BLOCKED_REASON="discover/pipeline stage failed in current run"
  fi
  PUBLISH_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if [ "$PIPELINE_OK" = "true" ] && [ "$PUBLISH_OK" = "true" ]; then
    OUTCOME="success"
  elif [ "$PIPELINE_OK" = "true" ] && [ "$PUBLISH_OK" = "false" ]; then
    OUTCOME="pipeline_ok_publish_failed"
  else
    OUTCOME="pipeline_failed"
  fi

  python3 -c "
import json
from datetime import datetime, timezone
state = {
    'run_id': '$RUN_ID',
    'cadence': 'weekly',
    'started_at': '$STAMP',
    'finished_at': datetime.now(timezone.utc).isoformat(),
    'status': '$OUTCOME',
    'pipeline_status': 'success' if '$PIPELINE_OK' == 'true' else 'failed',
    'pipeline_started_at': '$PIPELINE_START',
    'pipeline_finished_at': '$PIPELINE_END',
    'publish_status': 'success' if '$PUBLISH_OK' == 'true' else 'failed',
    'publish_started_at': '$PUBLISH_START',
    'publish_finished_at': '$PUBLISH_END',
    'publish_blocked_reason': '$PUBLISH_BLOCKED_REASON' or None
}
with open('$STATE_DIR/latest_run.json', 'w') as f:
    json.dump(state, f, indent=2)
" 2>/dev/null || echo "[WARN] Could not write final run state"

  echo ""
  echo "================================================================"
  echo "VERA WEEKLY CYCLE OUTCOME: ${OUTCOME^^}"
  echo "RUN_ID: $RUN_ID"
  echo "================================================================"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] VERA autonomous weekly cycle complete"
} 2>&1 | tee "$LOG_PATH"

echo "Autonomous weekly log written to: $LOG_PATH"

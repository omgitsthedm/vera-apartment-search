#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
RUN_ID="hourly_${STAMP}"
LOG_PATH="$ROOT/logs/run_hourly_autonomous_${STAMP}.log"
STATE_DIR="$ROOT/state"

export VERA_ROOT="$ROOT"
export VERA_RUN_ID="$RUN_ID"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# Source local env (API keys, overrides) — launchd doesn't inherit shell env
if [[ -f "$ROOT/.env" ]]; then
  set -a
  source "$ROOT/.env"
  set +a
fi

# Deterministic/free mode: ai_enrich falls back to dry-run without this key.
unset OPENAI_API_KEY

# Fix macOS Python SSL: default cert bundle is missing, point to certifi
SSL_CERT_FILE="$(/usr/local/bin/python3 -c 'import certifi; print(certifi.where())' 2>/dev/null)" || true
if [[ -n "$SSL_CERT_FILE" && -f "$SSL_CERT_FILE" ]]; then
  export SSL_CERT_FILE
fi

mkdir -p "$ROOT/logs" "$STATE_DIR"

{
  echo "=== VERA autonomous hourly cycle ==="
  echo "TIMESTAMP: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "RUN_ID:    $RUN_ID"
  echo "ROOT:      $ROOT"
  echo "SCRIPT:    $0"
  echo "USER:      $(whoami)"
  echo "PWD:       $(pwd)"
  echo "PYTHON:    $(which python3 2>/dev/null || echo 'NOT FOUND')"
  echo "PATH:      $PATH"
  echo "========================================="

  # Write run start state
  python3 -c "
import json
from datetime import datetime, timezone
state = {
    'run_id': '$RUN_ID',
    'cadence': 'hourly',
    'started_at': datetime.now(timezone.utc).isoformat(),
    'status': 'running',
    'pipeline_status': 'pending',
    'publish_status': 'external'
}
with open('$STATE_DIR/latest_run.json', 'w') as f:
    json.dump(state, f, indent=2)
" 2>/dev/null || echo "[WARN] Could not write initial run state"

  # Step 1: Run the core pipeline
  PIPELINE_OK=true
  PIPELINE_START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if "$ROOT/scripts/run_hourly.sh"; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] pipeline step: SUCCESS"
  else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] pipeline step: FAILED (exit code: $?)"
    PIPELINE_OK=false
  fi
  PIPELINE_END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  # Public publishing is owned by the scheduled GitHub Actions cloud sweep.
  # Local runners never sync or deploy the retired standalone dashboard.
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] publish step: EXTERNAL (cloud feed)"

  # Step 2: Determine local pipeline outcome.
  if [ "$PIPELINE_OK" = "true" ]; then OUTCOME="success"; else OUTCOME="pipeline_failed"; fi

  # Step 3: Write final run state
  python3 -c "
import json
from datetime import datetime, timezone
state = {
    'run_id': '$RUN_ID',
    'cadence': 'hourly',
    'started_at': '$STAMP',
    'finished_at': datetime.now(timezone.utc).isoformat(),
    'status': '$OUTCOME',
    'pipeline_status': 'success' if '$PIPELINE_OK' == 'true' else 'failed',
    'pipeline_started_at': '$PIPELINE_START',
    'pipeline_finished_at': '$PIPELINE_END',
    'publish_status': 'external',
    'publish_started_at': None,
    'publish_finished_at': None,
    'publish_blocked_reason': None
}
with open('$STATE_DIR/latest_run.json', 'w') as f:
    json.dump(state, f, indent=2)
" 2>/dev/null || echo "[WARN] Could not write final run state"

  echo ""
  echo "================================================================"
  echo "VERA HOURLY CYCLE OUTCOME: $(printf %s "$OUTCOME" | tr "[:lower:]" "[:upper:]")"
  echo "RUN_ID: $RUN_ID"
  echo "================================================================"

  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] VERA autonomous hourly cycle complete"
} 2>&1 | tee "$LOG_PATH"

echo "Autonomous hourly log written to: $LOG_PATH"

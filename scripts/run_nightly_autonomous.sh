#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
RUN_ID="nightly_${STAMP}"
LOG_PATH="$ROOT/logs/run_nightly_autonomous_${STAMP}.log"
STATE_DIR="$ROOT/state"
GUARD_DIR="$STATE_DIR/schedule_guards"
GUARD_FILE="$GUARD_DIR/nightly.json"

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
SSL_CERT_FILE="$(python3 -c 'import certifi; print(certifi.where())' 2>/dev/null)" || true
if [[ -n "$SSL_CERT_FILE" && -f "$SSL_CERT_FILE" ]]; then
  export SSL_CERT_FILE
fi

mkdir -p "$ROOT/logs" "$STATE_DIR" "$GUARD_DIR"

# Once-per-ET-date guard: launchd re-fires missed jobs on wake, and a manual
# run may already have claimed tonight — never run the nightly cycle twice
# for the same ET calendar date.
ET_DATE="$(TZ=America/New_York date +%Y-%m-%d)"
if [[ -f "$GUARD_FILE" ]] && python3 - "$GUARD_FILE" "$ET_DATE" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        guard = json.load(f)
except Exception:
    sys.exit(1)
sys.exit(0 if guard.get("last_et_date") == sys.argv[2] else 1)
PY
then
  echo "Nightly cycle already claimed for ET date ${ET_DATE}; skipping." | tee -a "$LOG_PATH"
  exit 0
fi
python3 - "$GUARD_FILE" "$ET_DATE" <<'PY'
import json, sys
from datetime import datetime, timezone
with open(sys.argv[1], "w") as f:
    json.dump({
        "cadence": "nightly",
        "last_et_date": sys.argv[2],
        "timezone": "America/New_York",
        "claimed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, f, indent=2)
PY

{
  echo "=== VERA autonomous nightly cycle ==="
  echo "TIMESTAMP: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "RUN_ID:    $RUN_ID"
  echo "ROOT:      $ROOT"
  echo "SCRIPT:    $0"
  echo "USER:      $(whoami)"
  echo "PYTHON:    $(which python3 2>/dev/null || echo 'NOT FOUND')"
  echo "========================================="

  python3 -c "
import json
from datetime import datetime, timezone
state = {
    'run_id': '$RUN_ID',
    'cadence': 'nightly',
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
  if "$ROOT/scripts/run_daily.sh"; then
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
    'cadence': 'nightly',
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
  echo "VERA NIGHTLY CYCLE OUTCOME: ${OUTCOME^^}"
  echo "RUN_ID: $RUN_ID"
  echo "================================================================"
} 2>&1 | tee -a "$LOG_PATH"

echo "Autonomous nightly log written to: $LOG_PATH"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DASHBOARD_ROOT="/Users/davidmarsh/Code/Personal/nyc-apartment-search-dashboard"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
PUBLISH_LOG="$ROOT/logs/publish_${STAMP}.log"

mkdir -p "$ROOT/logs"

{
echo "[vera-publish] [$STAMP] publish cycle starting"
echo "[vera-publish] RUN_ID: ${VERA_RUN_ID:-unset}"

# -----------------------------------------------------------------------
# STEP 0: Publish gating — require discover success in current run
# -----------------------------------------------------------------------
GATE_RESULT=$(python3 -c "
import sys
sys.path.insert(0, '$ROOT')
from config.stage_tracker import check_publish_eligible
eligible, reason = check_publish_eligible()
print(f'{eligible}|{reason}')
" 2>/dev/null) || GATE_RESULT="True|gate check unavailable (fallback)"

GATE_ELIGIBLE="$(echo "$GATE_RESULT" | cut -d'|' -f1)"
GATE_REASON="$(echo "$GATE_RESULT" | cut -d'|' -f2-)"

if [ "$GATE_ELIGIBLE" = "False" ]; then
  echo "[vera-publish] PUBLISH GATED — $GATE_REASON"
  echo "[vera-publish] publish requires discover to have succeeded in the current run_id"

  # Record blocked state in both publish_health and stage tracker
  python3 -c "
import json, sys
sys.path.insert(0, '$ROOT')
sys.path.insert(0, '$ROOT/scripts')
from config.stage_tracker import write_stage_end
from publish_health import load_publish_state, record_deploy_event, save_publish_state
state = load_publish_state()
state = record_deploy_event(state, 'failed', '', 'publish-gated', reason='$GATE_REASON')
save_publish_state(state)
write_stage_end('publish', 'blocked', blocked_reason='$GATE_REASON')
" 2>/dev/null || true

  echo "[vera-publish] publish cycle aborted (gated)"
  exit 0
fi
echo "[vera-publish] publish gate passed: $GATE_REASON"

# Record publish stage start
python3 -c "
import sys
sys.path.insert(0, '$ROOT')
from config.stage_tracker import write_stage_start
write_stage_start('publish')
" 2>/dev/null || true

# -----------------------------------------------------------------------
# STEP 1: Pre-publish health check
# -----------------------------------------------------------------------
echo "[vera-publish] running pre-publish health check..."
PRE_RESULT=$(python3 "$ROOT/scripts/publish_health.py" --phase pre-publish 2>&1) || true

if echo "$PRE_RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); sys.exit(0 if r.get('all_passed') else 1)" 2>/dev/null; then
  echo "[vera-publish] pre-publish checks PASSED"
else
  echo "[vera-publish] PRE-PUBLISH CHECKS FAILED — aborting publish"
  echo "$PRE_RESULT"
  echo "[vera-publish] keeping last good published state intact"

  # Record failure in publish state and stage tracker
  python3 -c "
import json, sys
sys.path.insert(0, '$ROOT')
sys.path.insert(0, '$ROOT/scripts')
from config.stage_tracker import write_stage_end
from publish_health import load_publish_state, record_deploy_event, save_publish_state
state = load_publish_state()
state = record_deploy_event(state, 'failed', '', 'pre-publish-failed', reason='pre-publish checks failed')
save_publish_state(state)
write_stage_end('publish', 'error', error_reason='pre-publish checks failed')
" 2>/dev/null || true

  echo "[vera-publish] publish cycle aborted (pre-publish failure)"
  exit 0
fi

# -----------------------------------------------------------------------
# STEP 2: Dashboard sync
# -----------------------------------------------------------------------
if [ ! -d "$DASHBOARD_ROOT" ]; then
  echo "[vera-publish] dashboard root not found at $DASHBOARD_ROOT — aborting"
  exit 0
fi

echo "[vera-publish] building publish snapshot..."
python3 "$ROOT/scripts/build_snapshot.py"

echo "[vera-publish] syncing dashboard snapshot from latest VERA outputs..."
SYNC_OUTPUT=$(python3 "$DASHBOARD_ROOT/scripts/sync_vera_dashboard.py" 2>&1) || {
  echo "[vera-publish] DASHBOARD SYNC FAILED"
  echo "$SYNC_OUTPUT"

  python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from publish_health import load_publish_state, record_deploy_event, save_publish_state
state = load_publish_state()
state = record_deploy_event(state, 'failed', '', 'sync-failed', reason='sync_vera_dashboard.py failed')
save_publish_state(state)
" 2>/dev/null || true

  echo "[vera-publish] publish cycle aborted (sync failure)"
  exit 0
}
echo "$SYNC_OUTPUT"

# -----------------------------------------------------------------------
# STEP 3: Compare hashes for meaningful-change detection
# -----------------------------------------------------------------------
HASH_FILE="$DASHBOARD_ROOT/site/data/content_hash.txt"
DEPLOYED_HASH_FILE="$ROOT/.last_deployed_hash"

if [ ! -f "$HASH_FILE" ]; then
  echo "[vera-publish] no content hash found; will deploy"
  NEEDS_DEPLOY=true
elif [ ! -f "$DEPLOYED_HASH_FILE" ]; then
  echo "[vera-publish] no previous deploy hash on record; will deploy"
  NEEDS_DEPLOY=true
else
  CURRENT_HASH="$(cat "$HASH_FILE" | tr -d '[:space:]')"
  LAST_HASH="$(cat "$DEPLOYED_HASH_FILE" | tr -d '[:space:]')"
  if [ "$CURRENT_HASH" = "$LAST_HASH" ]; then
    echo "[vera-publish] content unchanged since last deploy (hash: $CURRENT_HASH); skipping production deploy"
    NEEDS_DEPLOY=false

    # Record intentional skip in publish state
    python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from publish_health import load_publish_state, record_deploy_event, save_publish_state
state = load_publish_state()
state = record_deploy_event(state, 'skipped', '$CURRENT_HASH', 'no-change', reason='content hash unchanged: $CURRENT_HASH')
save_publish_state(state)
" 2>/dev/null || true

  else
    echo "[vera-publish] content changed (was: $LAST_HASH, now: $CURRENT_HASH); will deploy"
    NEEDS_DEPLOY=true
  fi
fi

# -----------------------------------------------------------------------
# STEP 4: Deploy if needed
# -----------------------------------------------------------------------
DEPLOY_SUCCESS=false
CONTENT_HASH="$(cat "$HASH_FILE" 2>/dev/null | tr -d '[:space:]' || echo 'unknown')"

if [ "$NEEDS_DEPLOY" = "true" ]; then
  if command -v netlify >/dev/null 2>&1; then
    echo "[vera-publish] deploying refreshed snapshot to Netlify..."
    if "$DASHBOARD_ROOT/scripts/deploy_netlify.sh"; then
      cp "$HASH_FILE" "$DEPLOYED_HASH_FILE"
      echo "[vera-publish] deploy complete; hash recorded: $CONTENT_HASH"
      DEPLOY_SUCCESS=true
    else
      echo "[vera-publish] NETLIFY DEPLOY FAILED"

      python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from publish_health import load_publish_state, record_deploy_event, save_publish_state
state = load_publish_state()
state = record_deploy_event(state, 'failed', '$CONTENT_HASH', 'deploy-command-failed', reason='netlify deploy CLI returned non-zero')
save_publish_state(state)
" 2>/dev/null || true
    fi
  else
    echo "[vera-publish] netlify CLI not available; leaving dashboard refreshed locally only."

    python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from publish_health import load_publish_state, record_deploy_event, save_publish_state
state = load_publish_state()
state = record_deploy_event(state, 'failed', '$CONTENT_HASH', 'no-netlify-cli', reason='netlify CLI not available')
save_publish_state(state)
" 2>/dev/null || true
  fi
fi

# -----------------------------------------------------------------------
# STEP 5: Post-publish verification (only after successful deploy)
# -----------------------------------------------------------------------
if [ "$DEPLOY_SUCCESS" = "true" ]; then
  echo "[vera-publish] running post-publish live-site verification..."
  # Brief pause for Netlify CDN propagation
  sleep 5

  POST_RESULT=$(python3 "$ROOT/scripts/publish_health.py" --phase post-publish --expected-hash "$CONTENT_HASH" 2>&1) || true
  echo "$POST_RESULT"

  if echo "$POST_RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); sys.exit(0 if r.get('all_verified') else 1)" 2>/dev/null; then
    echo "[vera-publish] LIVE SITE VERIFIED — content matches published snapshot"

    # Record verified deploy
    python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from publish_health import load_publish_state, record_deploy_event, save_publish_state
state = load_publish_state()
state = record_deploy_event(state, 'deployed', '$CONTENT_HASH', 'success', verified=True)
save_publish_state(state)
" 2>/dev/null || true

    PUBLISH_OUTCOME="deployed_and_verified"
  else
    echo "[vera-publish] WARNING: LIVE SITE VERIFICATION FAILED — content may not match"

    python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from publish_health import load_publish_state, record_deploy_event, save_publish_state
state = load_publish_state()
state = record_deploy_event(state, 'deployed', '$CONTENT_HASH', 'verification_failed', verified=False)
save_publish_state(state)
" 2>/dev/null || true

    PUBLISH_OUTCOME="deployed_verification_failed"
  fi
elif [ "$NEEDS_DEPLOY" = "false" ]; then
  PUBLISH_OUTCOME="skipped_no_change"
else
  PUBLISH_OUTCOME="deploy_failed"
fi

# -----------------------------------------------------------------------
# STEP 5.5: Record publish stage end
# -----------------------------------------------------------------------
PUBLISH_STAGE_STATUS="error"
if [ "$PUBLISH_OUTCOME" = "deployed_and_verified" ]; then
  PUBLISH_STAGE_STATUS="success"
elif [ "$PUBLISH_OUTCOME" = "skipped_no_change" ]; then
  PUBLISH_STAGE_STATUS="success"
elif [ "$PUBLISH_OUTCOME" = "deployed_verification_failed" ]; then
  PUBLISH_STAGE_STATUS="partial"
fi

python3 -c "
import sys
sys.path.insert(0, '$ROOT')
from config.stage_tracker import write_stage_end
write_stage_end('publish', '$PUBLISH_STAGE_STATUS', publish_outcome='$PUBLISH_OUTCOME')
" 2>/dev/null || true

# -----------------------------------------------------------------------
# STEP 6: Generate publish health report
# -----------------------------------------------------------------------
echo "[vera-publish] generating publish health report..."
REPORT_RESULT=$(python3 "$ROOT/scripts/publish_health.py" --phase report 2>&1) || true
echo "$REPORT_RESULT"

echo ""
echo "================================================================"
echo "VERA PUBLISH OUTCOME: $PUBLISH_OUTCOME"
echo "================================================================"
echo "[vera-publish] publish cycle complete"

} 2>&1 | tee "$PUBLISH_LOG"

echo "Publish log written to: $PUBLISH_LOG"

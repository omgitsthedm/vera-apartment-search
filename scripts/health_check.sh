#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT/logs"
LOG_PATH="$LOG_DIR/health_check_${STAMP}.log"

mkdir -p "$LOG_DIR"

failures=()
passes=()

check_path() {
  local path="$1"
  local label="$2"
  if [ -e "$path" ]; then
    passes+=("$label")
  else
    failures+=("$label missing: $path")
  fi
}

check_writable_dir() {
  local path="$1"
  local label="$2"
  # Runtime dirs are gitignored, so cleanups can delete them; recreate
  # before checking instead of failing the whole pipeline on a missing dir.
  mkdir -p "$path" 2>/dev/null || true
  if [ -d "$path" ] && [ -w "$path" ]; then
    passes+=("$label writable")
  else
    failures+=("$label not writable: $path")
  fi
}

check_path "$ROOT" "project root"
check_path "$ROOT/logs" "logs dir"
check_path "$ROOT/configs/user_preferences.json" "user preferences"
check_path "$ROOT/configs/source_registry.md" "source registry"
check_path "$ROOT/configs/scoring_rules.md" "scoring rules"
check_path "$ROOT/configs/health_check_procedure.md" "health procedure"
check_path "$ROOT/scripts/discover_listings.py" "discover script"
check_path "$ROOT/scripts/normalize_listings.py" "normalize script"
check_path "$ROOT/scripts/dedupe_listings.py" "dedupe script"
check_path "$ROOT/scripts/refresh_public_records.py" "public-record refresh script"
check_path "$ROOT/scripts/enrich_listings.py" "enrich script"
check_path "$ROOT/scripts/score_listings.py" "score script"
check_path "$ROOT/scripts/run_daily.sh" "daily runner"
check_path "$ROOT/scripts/run_weekly.sh" "weekly runner"
check_path "$ROOT/scripts/publish_dashboard.sh" "dashboard publish runner"
check_path "$ROOT/scripts/run_daily_autonomous.sh" "autonomous daily runner"
check_path "$ROOT/scripts/run_weekly_autonomous.sh" "autonomous weekly runner"
check_path "$ROOT/scripts/install_launch_agents.sh" "launch-agent install script"
check_path "$ROOT/scripts/remove_launch_agents.sh" "launch-agent remove script"
check_path "$ROOT/configs/launchd/com.vera.apartment-search.daily.plist" "daily launch-agent template"
check_path "$ROOT/configs/launchd/com.vera.apartment-search.weekly.plist" "weekly launch-agent template"
check_writable_dir "$ROOT/raw" "raw dir"
check_writable_dir "$ROOT/normalized" "normalized dir"
check_writable_dir "$ROOT/deduped" "deduped dir"
check_writable_dir "$ROOT/enriched" "enriched dir"
check_writable_dir "$ROOT/scored" "scored dir"
check_writable_dir "$ROOT/reports" "reports dir"
check_writable_dir "$ROOT/exports" "exports dir"

# Ollama is optional: the pipeline is deterministic (ai_enrich dry-runs
# without a key) and no stage shells out to a local LLM.
if command -v ollama >/dev/null 2>&1; then
  passes+=("ollama available (optional)")
else
  passes+=("ollama absent (optional — deterministic mode)")
fi

if command -v netlify >/dev/null 2>&1; then
  passes+=("netlify available")
else
  failures+=("netlify missing from PATH")
fi

{
  echo "Health check for $ROOT"
  echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "Passes:"
  for pass in "${passes[@]}"; do
    echo "- $pass"
  done
  echo
  echo "Failures:"
  if [ "${#failures[@]}" -eq 0 ]; then
    echo "- none"
  else
    for failure in "${failures[@]}"; do
      echo "- $failure"
    done
  fi
} | tee "$LOG_PATH"

if [ "${#failures[@]}" -gt 0 ]; then
  exit 1
fi

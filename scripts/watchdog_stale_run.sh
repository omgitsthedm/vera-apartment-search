#!/usr/bin/env bash
# Stale-run watchdog: if VERA hasn't completed a pipeline run in >30h,
# surface a macOS notification instead of dying silently. Fired daily by
# launchd (com.vera.apartment-search.watchdog). Free, local, no network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT="$ROOT/snapshots/latest_snapshot.json"
THRESHOLD_H=30

if [[ ! -f "$SNAPSHOT" ]]; then
  MSG="VERA has no snapshot at all — pipeline has never completed here."
else
  AGE_H=$(( ( $(date +%s) - $(stat -f %m "$SNAPSHOT") ) / 3600 ))
  if (( AGE_H <= THRESHOLD_H )); then
    exit 0
  fi
  MSG="VERA's last snapshot is ${AGE_H}h old (threshold ${THRESHOLD_H}h). Check logs in $ROOT/logs."
fi

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) STALE: $MSG" >> "$ROOT/logs/watchdog.log"
osascript -e "display notification \"$MSG\" with title \"VERA watchdog\" sound name \"Basso\"" || true

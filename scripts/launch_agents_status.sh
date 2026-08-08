#!/usr/bin/env bash
set -euo pipefail

UID_VALUE="$(id -u)"
LABELS=(
  "com.vera.apartment-search.daily"
  "com.vera.apartment-search.nightly"
  "com.vera.apartment-search.watchdog"
  "com.vera.apartment-search.weekly"
)

for label in "${LABELS[@]}"; do
  echo "== $label =="
  if launchctl print "gui/${UID_VALUE}/${label}" >/dev/null 2>&1; then
    launchctl print "gui/${UID_VALUE}/${label}" | grep -E 'state =|path =|program =|last exit code =|runs =|minimum runtime =|pid =|scheduled' || true
  else
    echo "not loaded"
  fi
  echo
done

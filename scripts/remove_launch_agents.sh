#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="$HOME/Library/LaunchAgents"
UID_VALUE="$(id -u)"
LABELS=(
  "com.vera.apartment-search.hourly"
  "com.vera.apartment-search.weekly"
  "com.vera.apartment-search.daily"
)

for label in "${LABELS[@]}"; do
  target_path="$TARGET_DIR/${label}.plist"
  launchctl bootout "gui/${UID_VALUE}" "$target_path" >/dev/null 2>&1 || true
  rm -f "$target_path"
done

echo "Removed all VERA launch agents from $TARGET_DIR"

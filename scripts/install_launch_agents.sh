#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHD_ROOT="$ROOT/configs/launchd"
TARGET_DIR="$HOME/Library/LaunchAgents"
UID_VALUE="$(id -u)"
LABELS=(
  "com.vera.apartment-search.hourly"
  "com.vera.apartment-search.weekly"
)

mkdir -p "$TARGET_DIR" "$ROOT/logs"

# Remove old daily agent if present
OLD_DAILY="com.vera.apartment-search.daily"
OLD_PATH="$TARGET_DIR/${OLD_DAILY}.plist"
launchctl bootout "gui/${UID_VALUE}" "$OLD_PATH" >/dev/null 2>&1 || true
rm -f "$OLD_PATH"

for label in "${LABELS[@]}"; do
  source_path="$LAUNCHD_ROOT/${label}.plist"
  target_path="$TARGET_DIR/${label}.plist"

  if [ ! -f "$source_path" ]; then
    echo "Missing launch agent template: $source_path" >&2
    exit 1
  fi

  launchctl bootout "gui/${UID_VALUE}" "$target_path" >/dev/null 2>&1 || true
  cp "$source_path" "$target_path"
  launchctl bootstrap "gui/${UID_VALUE}" "$target_path"
done

echo "Installed VERA launch agents into $TARGET_DIR (hourly + weekly)"
launchctl list | grep 'com.vera.apartment-search' || true

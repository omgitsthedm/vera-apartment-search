#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' \
  '[vera-schedule] RETIRED: unattended schedule installation is disabled.' \
  '[vera-schedule] The loaded daily, nightly, watchdog, and weekly agents already use the canonical Code checkout.' \
  '[vera-schedule] Review configs/launchd-v2 and obtain explicit schedule-change authorization before replacing them.' \
  '[vera-schedule] No LaunchAgent was changed.' >&2
exit 1

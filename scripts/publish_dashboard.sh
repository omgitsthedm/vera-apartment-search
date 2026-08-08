#!/usr/bin/env bash
set -euo pipefail

printf '%s\n' \
  '[vera-publish] RETIRED: local dashboard publishing is disabled.' \
  '[vera-publish] The sanitized public feed is published by GitHub Actions and served at littlefightnyc.com/vera/.' \
  '[vera-publish] Do not restore a Netlify CLI deploy or sync the historical dashboard checkout.' >&2
exit 1

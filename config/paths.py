"""Canonical path configuration for VERA.

Every script should import paths from here instead of computing them locally.
Override VERA_ROOT via environment variable for testing or alternate installs.
"""
from __future__ import annotations

import os
from pathlib import Path

VERA_ROOT = Path(
    os.environ.get(
        "VERA_ROOT",
        str(Path(__file__).resolve().parents[1]),
    )
).resolve()

# Pipeline data directories
RAW_DIR = VERA_ROOT / "raw"
NORMALIZED_DIR = VERA_ROOT / "normalized"
DEDUPED_DIR = VERA_ROOT / "deduped"
ENRICHED_DIR = VERA_ROOT / "enriched"
SCORED_DIR = VERA_ROOT / "scored"

# Output directories
REPORT_DIR = VERA_ROOT / "reports"
EXPORT_DIR = VERA_ROOT / "exports"
SNAPSHOT_DIR = VERA_ROOT / "snapshots"
SNAPSHOT_METADATA_DIR = SNAPSHOT_DIR / "metadata"

# Config and cache
CONFIG_DIR = VERA_ROOT / "configs"
CACHE_DIR = VERA_ROOT / "cache"
STATE_DIR = VERA_ROOT / "state"
REFERENCE_DIR = CACHE_DIR / "reference_data"
LEGACY_STATE_DIR = CACHE_DIR / "state"
WATCHLIST_DIR = VERA_ROOT / "watchlists"

# Logging
LOG_DIR = VERA_ROOT / "logs"

# Dashboard (external project)
DASHBOARD_ROOT = Path(
    os.environ.get(
        "VERA_DASHBOARD_ROOT",
        "/Users/davidmarsh/Documents/Playground/projects/nyc-apartment-search-dashboard",
    )
)
DASHBOARD_SITE_DIR = DASHBOARD_ROOT / "site"
DASHBOARD_DATA_DIR = DASHBOARD_SITE_DIR / "data"

# Key state files
PUBLISH_STATE_FILE = VERA_ROOT / ".publish_state.json"
LAST_DEPLOYED_HASH_FILE = VERA_ROOT / ".last_deployed_hash"
LATEST_RUN_FILE = STATE_DIR / "latest_run.json"

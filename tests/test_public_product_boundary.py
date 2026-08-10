#!/usr/bin/env python3
"""Static deployment-boundary regression test.

Run with `python3 tests/test_public_product_boundary.py`.

VERA's engine may publish a sanitized upstream feed, but active local
runners and config must never regain a second website or dashboard deploy
path. The public browser surface belongs exclusively to Little Fight NYC.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RETIRED_PATHS = {
    ROOT / "scripts" / "run_hourly.sh",
    ROOT / "scripts" / "run_hourly_autonomous.sh",
    ROOT / "scripts" / "publish_dashboard.sh",
    ROOT / "scripts" / "publish_health.py",
    ROOT / "scripts" / "install_launch_agents.sh",
    ROOT / "docs" / "STATE-2026-08-03.md",
    ROOT / "docs" / "STATE-2026-08-04.md",
    ROOT / "docs" / "launch" / "GO-LIVE-CHECKLIST.md",
    ROOT / "docs" / "launch" / "POSTS.md",
    ROOT / "docs" / "launch" / "README-public.md",
    ROOT / "docs" / "plans" / "2026-03-17-multi-source-expansion-design.md",
    ROOT / "docs" / "proposals" / "feed-payload-weight.md",
}


def active_files() -> list[Path]:
    candidates = [
        *ROOT.glob("scripts/*.py"),
        *ROOT.glob("scripts/*.sh"),
        *ROOT.glob("config/**/*.py"),
        *ROOT.glob("configs/*.md"),
        *ROOT.glob("configs/launchd/**/*.plist"),
        *ROOT.glob("configs/launchd-v2/*.plist"),
        *ROOT.glob(".github/workflows/*.yml"),
        *ROOT.glob(".github/workflows/*.yaml"),
    ]
    return sorted(candidates)


FORBIDDEN = {
    "retired dashboard publisher": re.compile(r"publish_dashboard\.sh", re.I),
    "hosting CLI deploy": re.compile(r"\bnetlify\b[^\n]{0,40}\bdeploy\b", re.I),
    "retired VERA host": re.compile(r"vera-pipeline", re.I),
    "retired VERA site ID": re.compile(
        r"fcd6f741-d479-44f4-8ee1-51da2b321227", re.I
    ),
    "dashboard checkout constant": re.compile(r"DASHBOARD_ROOT"),
    "retired Desktop/OpenClaw checkout": re.compile(
        r"/Users/davidmarsh/Desktop/Personal/OpenClaw_Local/vera-apartment-search"
    ),
}

SCHEDULE_LABELS = (
    "com.vera.apartment-search.daily",
    "com.vera.apartment-search.nightly",
    "com.vera.apartment-search.watchdog",
    "com.vera.apartment-search.weekly",
)

SCHEDULE_ENTRYPOINTS = {
    "com.vera.apartment-search.daily": "scripts/run_daily_autonomous.sh",
    "com.vera.apartment-search.nightly": "scripts/run_nightly_autonomous.sh",
    "com.vera.apartment-search.watchdog": "scripts/watchdog_stale_run.sh",
    "com.vera.apartment-search.weekly": "scripts/run_weekly_autonomous.sh",
}


def main() -> int:
    failures: list[str] = []
    files = active_files()

    for path in sorted(RETIRED_PATHS):
        if path.exists():
            failures.append(
                f"{path.relative_to(ROOT)}: retired path must remain absent"
            )

    for path in files:
        text = path.read_text(errors="replace")
        for label, pattern in FORBIDDEN.items():
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                failures.append(f"{path.relative_to(ROOT)}:{line}: {label}")

    wrappers = [
        ROOT / "scripts" / f"run_{cadence}_autonomous.sh"
        for cadence in ("daily", "nightly", "weekly")
    ]
    for path in wrappers:
        text = path.read_text()
        if "publish_status': 'external'" not in text:
            failures.append(
                f"{path.relative_to(ROOT)}: missing external publication state"
            )

    for helper_name in ("launch_agents_status.sh", "remove_launch_agents.sh"):
        helper = ROOT / "scripts" / helper_name
        helper_text = helper.read_text()
        for label in SCHEDULE_LABELS:
            if label not in helper_text:
                failures.append(f"scripts/{helper_name}: missing {label}")
        if "com.vera.apartment-search.hourly" in helper_text:
            failures.append(f"scripts/{helper_name}: still enumerates retired hourly agent")

    legacy_templates = list((ROOT / "configs" / "launchd").glob("*.plist"))
    if legacy_templates:
        names = ", ".join(path.name for path in sorted(legacy_templates))
        failures.append(f"configs/launchd: stale templates restored: {names}")

    template_names = {
        path.stem for path in (ROOT / "configs" / "launchd-v2").glob("*.plist")
    }
    if template_names != set(SCHEDULE_LABELS):
        failures.append(
            "configs/launchd-v2: template set does not match the loaded agent set"
        )
    canonical_engine = "/Users/davidmarsh/Code/Personal/vera-apartment-search"
    for label, relative_entrypoint in SCHEDULE_ENTRYPOINTS.items():
        template = ROOT / "configs" / "launchd-v2" / f"{label}.plist"
        expected_entrypoint = f"{canonical_engine}/{relative_entrypoint}"
        if template.exists() and expected_entrypoint not in template.read_text():
            failures.append(
                f"{template.relative_to(ROOT)}: expected {expected_entrypoint}"
            )

    health_text = (ROOT / "scripts" / "health_check.sh").read_text()
    if "scripts/install_launch_agents.sh" in health_text:
        failures.append("scripts/health_check.sh: still requires the retired installer")
    for label in SCHEDULE_LABELS:
        expected = f"configs/launchd-v2/{label}.plist"
        if expected not in health_text:
            failures.append(f"scripts/health_check.sh: missing {expected}")

    handoff = ROOT / "VERA-HANDOFF.md"
    if not handoff.exists():
        failures.append("VERA-HANDOFF.md: canonical cross-repository handoff is missing")
    else:
        handoff_text = handoff.read_text()
        required_handoff_markers = (
            "https://littlefightnyc.com/vera/",
            "/Users/davidmarsh/Code/Personal/vera-apartment-search",
            "/Users/davidmarsh/Code/LiFi NYC/Little Fight NYC Business/Website/littlefightnyc-website",
            "scripts/public_lens.py",
            "0907d8fe-7018-48db-a6be-1f906e4b2619",
        )
        for marker in required_handoff_markers:
            if marker not in handoff_text:
                failures.append(f"VERA-HANDOFF.md: missing canonical marker {marker}")

    if failures:
        print("VERA public-product boundary FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(
        "VERA public-product boundary passed: "
        f"{len(files)} active runner/config files checked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

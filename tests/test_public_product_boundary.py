#!/usr/bin/env python3
"""Static deployment-boundary regression test.

Run with `python3 tests/test_public_product_boundary.py`.

VERA's private engine may publish a sanitized upstream feed, but active local
runners and config must never regain a second website or dashboard deploy
path. The public browser surface belongs exclusively to Little Fight NYC.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RETIRED_ENTRYPOINTS = {
    ROOT / "scripts" / "publish_dashboard.sh",
    ROOT / "scripts" / "publish_health.py",
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
    return sorted(path for path in candidates if path not in RETIRED_ENTRYPOINTS)


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


def main() -> int:
    failures: list[str] = []
    files = active_files()

    for path in files:
        text = path.read_text(errors="replace")
        for label, pattern in FORBIDDEN.items():
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                failures.append(f"{path.relative_to(ROOT)}:{line}: {label}")

    wrappers = [
        ROOT / "scripts" / f"run_{cadence}_autonomous.sh"
        for cadence in ("hourly", "daily", "nightly", "weekly")
    ]
    for path in wrappers:
        text = path.read_text()
        if "publish_status': 'external'" not in text:
            failures.append(
                f"{path.relative_to(ROOT)}: missing external publication state"
            )

    installer = ROOT / "scripts" / "install_launch_agents.sh"
    installer_text = installer.read_text()
    if "RETIRED:" not in installer_text or not re.search(
        r"^exit 1$", installer_text, re.M
    ):
        failures.append(
            "scripts/install_launch_agents.sh: installer is not hard-disabled"
        )
    if re.search(r"\blaunchctl\b", installer_text):
        failures.append(
            "scripts/install_launch_agents.sh: retired installer still calls launchctl"
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

    health_text = (ROOT / "scripts" / "health_check.sh").read_text()
    if "scripts/install_launch_agents.sh" in health_text:
        failures.append("scripts/health_check.sh: still requires the retired installer")
    for label in SCHEDULE_LABELS:
        expected = f"configs/launchd-v2/{label}.plist"
        if expected not in health_text:
            failures.append(f"scripts/health_check.sh: missing {expected}")

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

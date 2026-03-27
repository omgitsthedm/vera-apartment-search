#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow_support import (
    address_similarity,
    building_address,
    canonical_text,
    ensure_dir,
    latest_file,
    read_json,
    render_markdown_table,
    stable_hash,
    state_path_or_latest,
    utc_stamp,
    write_csv,
    write_json,
    write_text,
)

from config.paths import VERA_ROOT as ROOT, DEDUPED_DIR as DEDUPED_ROOT, LOG_DIR as LOG_ROOT, NORMALIZED_DIR as NORMALIZED_ROOT, LEGACY_STATE_DIR as STATE_ROOT
from config.stage_tracker import write_stage_start, write_stage_end

RUN_STAMP = utc_stamp()


def load_normalized_rows() -> list[dict[str, Any]]:
    state = read_json(STATE_ROOT / "current_normalized.json", default={})
    path = state_path_or_latest(state.get("normalized_path"), NORMALIZED_ROOT, "normalized_listings_*.json")
    if not path:
        raise FileNotFoundError("No normalized dataset found")
    return read_json(path, default=[])


def float_matches(left: Any, right: Any, tolerance: float = 0.1) -> bool:
    if left in (None, "") or right in (None, ""):
        return True
    try:
        return abs(float(left) - float(right)) <= tolerance
    except (TypeError, ValueError):
        return False


def price_gap(left: Any, right: Any) -> float | None:
    if left in (None, "") or right in (None, ""):
        return None
    try:
        return abs(float(left) - float(right))
    except (TypeError, ValueError):
        return None


def listing_text(listing: dict[str, Any]) -> str:
    return canonical_text(
        " ".join(
            [
                str(listing.get("title") or ""),
                str(listing.get("full_description") or ""),
                str(listing.get("address_normalized") or ""),
                str(listing.get("contact_phone") or ""),
                str(listing.get("contact_email") or ""),
            ]
        )
    )


def duplicate_reason(left: dict[str, Any], right: dict[str, Any]) -> str | None:
    left_address = canonical_text(left.get("address_normalized"))
    right_address = canonical_text(right.get("address_normalized"))
    left_building = building_address(left.get("address_normalized"))
    right_building = building_address(right.get("address_normalized"))
    same_layout = float_matches(left.get("beds"), right.get("beds")) and float_matches(left.get("baths"), right.get("baths"))
    gap = price_gap(left.get("rent"), right.get("rent"))
    is_cross_source = left.get("source_name") != right.get("source_name")

    if left.get("contact_phone") and left.get("contact_phone") == right.get("contact_phone") and same_layout and (gap is None or gap <= 150):
        return "same_contact_phone"
    if left.get("contact_email") and left.get("contact_email") == right.get("contact_email") and same_layout and (gap is None or gap <= 150):
        return "same_contact_email"
    if left_address and left_address == right_address and same_layout and (gap is None or gap <= 150):
        return "same_address_signature"
    if left_building and left_building == right_building and same_layout and (gap is None or gap <= 125):
        return "same_building_same_layout"
    if address_similarity(left_address, right_address) >= 0.94 and same_layout and (gap is None or gap <= 175):
        return "near_address_match"
    if left_building and left_building == right_building:
        text_ratio = address_similarity(listing_text(left), listing_text(right))
        if text_ratio >= 0.82 and (gap is None or gap <= 150):
            return "same_building_text_similarity"
    # Cross-source: relax thresholds when listings come from different sources
    if is_cross_source and left_building and left_building == right_building and same_layout and (gap is None or gap <= 200):
        return "cross_source_same_building"
    if is_cross_source and address_similarity(left_address, right_address) >= 0.88 and same_layout and (gap is None or gap <= 200):
        return "cross_source_near_address"
    return None


def completeness_score(listing: dict[str, Any]) -> tuple[int, int, int]:
    completeness = sum(
        listing.get(field) not in (None, "", [])
        for field in [
            "address_normalized",
            "neighborhood",
            "borough",
            "zip",
            "rent",
            "beds",
            "baths",
            "contact_name",
            "contact_phone",
            "contact_email",
        ]
    )
    contact_score = int(bool(listing.get("contact_phone"))) + int(bool(listing.get("contact_email")))
    return completeness, contact_score, int(listing.get("image_count") or 0)


def merge_cluster_fields(members: list[dict[str, Any]]) -> dict[str, Any]:
    canonical = dict(sorted(members, key=completeness_score, reverse=True)[0])
    canonical["source_names"] = sorted({item["source_name"] for item in members})
    canonical["source_urls"] = [item["source_url"] for item in members if item.get("source_url")]
    canonical["cluster_member_ids"] = [item["listing_uid"] for item in members]
    canonical["duplicate_count"] = len(members)
    canonical["amenities"] = sorted({amenity for item in members for amenity in item.get("amenities", [])})
    for field in [
        "contact_phone",
        "contact_email",
        "contact_name",
        "address_raw",
        "address_normalized",
        "zip",
        "neighborhood",
        "borough",
        "pet_policy",
    ]:
        if canonical.get(field) in (None, "", []):
            for member in members:
                if member.get(field) not in (None, "", []):
                    canonical[field] = member[field]
                    break
    return canonical


def main() -> int:
    write_stage_start("dedupe")
    try:
        ensure_dir(DEDUPED_ROOT)
        ensure_dir(LOG_ROOT)
        ensure_dir(STATE_ROOT)

        normalized_rows = load_normalized_rows()
        if not normalized_rows:
            raise SystemExit("No normalized rows available")

        parent = list(range(len(normalized_rows)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left_index: int, right_index: int) -> None:
            left_root = find(left_index)
            right_root = find(right_index)
            if left_root != right_root:
                parent[right_root] = left_root

        matches: list[tuple[int, int, str]] = []
        for left_index in range(len(normalized_rows)):
            for right_index in range(left_index + 1, len(normalized_rows)):
                reason = duplicate_reason(normalized_rows[left_index], normalized_rows[right_index])
                if reason:
                    union(left_index, right_index)
                    matches.append((left_index, right_index, reason))

        grouped: dict[int, list[dict[str, Any]]] = {}
        group_reasons: dict[int, set[str]] = {}
        for index, listing in enumerate(normalized_rows):
            root = find(index)
            grouped.setdefault(root, []).append(dict(listing))
        for left_index, _, reason in matches:
            root = find(left_index)
            group_reasons.setdefault(root, set()).add(reason)

        deduped_rows: list[dict[str, Any]] = []
        audit_rows: list[dict[str, Any]] = []
        markdown_rows: list[list[Any]] = []

        for root, members in grouped.items():
            canonical = merge_cluster_fields(members)
            cluster_id = f"cluster-{stable_hash(*(sorted(item['listing_uid'] for item in members)))}"
            canonical["duplicate_cluster_id"] = cluster_id
            canonical["duplicate_match_evidence"] = sorted(group_reasons.get(root) or {"unique_record"})
            deduped_rows.append(canonical)

            audit_rows.append(
                {
                    "duplicate_cluster_id": cluster_id,
                    "member_count": len(members),
                    "source_names": ", ".join(canonical["source_names"]),
                    "member_ids": ", ".join(canonical["cluster_member_ids"]),
                    "match_evidence": ", ".join(canonical["duplicate_match_evidence"]),
                    "canonical_title": canonical.get("title"),
                    "address_normalized": canonical.get("address_normalized"),
                    "rent": canonical.get("rent"),
                }
            )
            markdown_rows.append(
                [
                    cluster_id,
                    len(members),
                    ", ".join(canonical["source_names"]),
                    canonical.get("address_normalized") or "n/a",
                    ", ".join(canonical["duplicate_match_evidence"]),
                ]
            )

        deduped_rows.sort(key=lambda item: ((item.get("rent") or 999999), item.get("neighborhood") or ""))
        audit_rows.sort(key=lambda item: item["member_count"], reverse=True)

        deduped_path = DEDUPED_ROOT / f"deduped_listings_{RUN_STAMP}.json"
        cluster_csv_path = DEDUPED_ROOT / f"duplicate_clusters_{RUN_STAMP}.csv"
        cluster_report_path = DEDUPED_ROOT / f"duplicate_cluster_report_{RUN_STAMP}.md"
        log_path = LOG_ROOT / f"duplicate_audit_{RUN_STAMP}.log"

        write_json(deduped_path, deduped_rows)
        write_csv(cluster_csv_path, audit_rows)
        write_text(
            cluster_report_path,
            "\n".join(
                [
                    "# Duplicate Cluster Report",
                    "",
                    render_markdown_table(
                        ["Cluster", "Members", "Sources", "Address", "Evidence"],
                        markdown_rows or [["None", 0, "", "", ""]],
                    ),
                    "",
                ]
            ),
        )
        write_text(
            log_path,
            "\n".join(
                [
                    f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] deduped {len(normalized_rows)} normalized rows into {len(deduped_rows)} clusters",
                    *[
                        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] {row['duplicate_cluster_id']} -> {row['member_count']} members ({row['match_evidence']})"
                        for row in audit_rows
                    ],
                ]
            )
            + "\n",
        )
        write_json(
            STATE_ROOT / "current_deduped.json",
            {
                "run_stamp": RUN_STAMP,
                "deduped_path": str(deduped_path),
                "cluster_csv_path": str(cluster_csv_path),
                "cluster_report_path": str(cluster_report_path),
                "deduped_count": len(deduped_rows),
            },
        )

        print(
            json.dumps(
                {
                    "run_stamp": RUN_STAMP,
                    "normalized_count": len(normalized_rows),
                    "deduped_count": len(deduped_rows),
                    "deduped_path": str(deduped_path),
                    "cluster_csv_path": str(cluster_csv_path),
                    "cluster_report_path": str(cluster_report_path),
                    "log": str(log_path),
                },
                indent=2,
            )
        )
        write_stage_end("dedupe", "success", records_in=len(normalized_rows), records_out=len(deduped_rows))
        return 0
    except Exception as e:
        write_stage_end("dedupe", "failed", errors=[str(e)])
        raise


if __name__ == "__main__":
    raise SystemExit(main())

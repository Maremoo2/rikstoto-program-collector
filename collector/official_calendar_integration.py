"""C1 original Collector ZIP + newly retained official-source page comparison.

Builds the day/day+1/day+2 end-to-end OFFLINE path by composing existing
archive_integrity_audit and independent_day_window. Missing or unverifiable
source days stay explicitly BLOCKED and no coverage percent is invented.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

from .archive_integrity_audit import audit_archive_zip
from .independent_day_window import audit_window, read_official_bundle, window_dates

SCHEMA = "collector_cdev01_official_original_three_day_pipeline_v1"
MAX_CAPTURE_BYTES = 200_000_000


def compare_original_three_day_sources(
    start_day: str,
    original_archives: dict[str, Path],
    official_bundles: dict[str, Path],
) -> dict[str, Any]:
    """Require true ZIP source receipts before calendar matching, not file names."""
    days = window_dates(start_day)
    expected = set(days)
    if not set(original_archives).issubset(expected):
        raise ValueError("Original archive supplied outside requested day+2 window")
    if not set(official_bundles).issubset(expected):
        raise ValueError("Official source bundle outside requested day+2 window")
    manifests, sources = {}, {}
    evidence = []
    for day in days:
        row: dict[str, Any] = {
            "date_oslo": day,
            "archive_input_supplied": day in original_archives,
            "official_bundle_supplied": day in official_bundles,
            "original_archive_sha256": None,
            "original_archive_receipt_errors": [],
            "official_source_sha_copies_verified": 0,
            "official_source_errors": [],
            "original_source_publication_time_attested": False,
            "c1_denominator_independently_verified": False,
            "c6_pit_certified": False,
        }
        archive_path = original_archives.get(day)
        if archive_path is not None:
            original = Path(archive_path)
            try:
                if original.stat().st_size > MAX_CAPTURE_BYTES:
                    row["original_archive_receipt_errors"].append(
                        "ORIGINAL_ARCHIVE_SIZE_LIMIT")
                else:
                    audit = audit_archive_zip(original)
                    row["original_archive_receipt_errors"] = audit["errors"]
                    if not audit["errors"] and audit.get("date_oslo") == day:
                        row["original_archive_sha256"] = hashlib.sha256(
                            original.read_bytes()).hexdigest()
                        with zipfile.ZipFile(original) as zipfile_read:
                            manifest_files = [
                                name for name in zipfile_read.namelist()
                                if name.endswith("/manifest.json")
                            ]
                            if len(manifest_files) != 1:
                                row["original_archive_receipt_errors"].append(
                                    "ORIGINAL_MANIFEST_NOT_UNIQUE")
                            else:
                                manifests[day] = json.loads(
                                    zipfile_read.read(manifest_files[0]))
                    elif not audit["errors"]:
                        row["original_archive_receipt_errors"].append(
                            "ORIGINAL_ARCHIVE_DAY_DISAGREES")
            except (OSError, zipfile.BadZipFile, ValueError) as exc:
                row["original_archive_receipt_errors"].append(
                    "ORIGINAL_ARCHIVE_UNREADABLE:" + type(exc).__name__)
        official_path = official_bundles.get(day)
        if official_path is not None:
            source = read_official_bundle(Path(official_path), day=day)
            row["official_source_sha_copies_verified"] = source[
                "source_receipts_verified"]
            row["official_source_errors"] = source["errors"]
            sources[day] = source
        evidence.append(row)
    comparison = audit_window(start_day, manifests, sources)
    return {
        "schema": SCHEMA, "status": "BLOCKED_INDEPENDENT_C1_DENOMINATOR",
        "window_dates": days,
        "original_source_days_with_valid_receipts": len(manifests),
        "official_source_days_with_two_hashed_copies": sum(
            row["official_source_sha_copies_verified"] == 2
            and row["official_source_errors"] == [] for row in evidence),
        "source_evidence_by_day": evidence,
        "calendar_candidate_comparison": comparison,
        "independent_meeting_denominator_verified": False,
        "independent_race_denominator_verified": False,
        "calendar_coverage_percentage": None,
        "c1_14_day_coverage_eligible": False,
        "source_first_publication_time_attested": False,
        "c6_tminus4_pit_certified": False,
        "hq_accepted": False,
        "bet_authorized": False,
        "production_changed": False,
    }


def _day_paths(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        key, marker, file = value.partition("=")
        if not marker or key in result or not file:
            raise ValueError("Each input must be unique DATE=/absolute/file")
        result[key] = Path(file)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-day", required=True)
    parser.add_argument("--original-archive", action="append", default=[])
    parser.add_argument("--official-bundle", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        originals = _day_paths(args.original_archive)
        officials = _day_paths(args.official_bundle)
        report = compare_original_three_day_sources(
            args.start_day, originals, officials)
        rendered = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2)
        if args.output is None:
            print(rendered)
        else:
            if args.output.resolve() in {
                *(path.resolve() for path in originals.values()),
                *(path.resolve() for path in officials.values()),
            }:
                parser.error("Output cannot overwrite any original source")
            with args.output.open("x", encoding="utf-8") as target:
                target.write(rendered + "\n")
    except (ValueError, OSError) as exc:
        parser.error(type(exc).__name__ + ":" + str(exc)[:150])
    # Comparison is intentionally not a passing C1 acceptance command.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

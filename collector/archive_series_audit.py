"""Fail-closed, read-only longitudinal audit of original collector day ZIPs.

Checks independent raw-byte receipt integrity *within captures*, never proves
independent complete-day coverage, first provider publication, T-4/PIT, or bets.
An operational green job without genuine source artifacts is NOT a passed day.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from .archive_integrity_audit import audit_archive_zip

SCHEMA = "COLLECTOR_ORIGINAL_SOURCE_SERIES_AUDIT_V1"
MINIMUM_CONSECUTIVE_DAYS = 14


def audit_series(archives: list[Path | str], *, start_date: str,
                 end_date: str, minimum_days: int = MINIMUM_CONSECUTIVE_DAYS) -> dict:
    """Inspect immutable original archives for a fixed inclusive calendar window."""
    begin, finish = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if finish < begin or begin.isoformat() != start_date or finish.isoformat() != end_date:
        raise ValueError("Exact increasing YYYY-MM-DD period required")
    if type(minimum_days) is not int or minimum_days < 1:
        raise ValueError("Invalid minimum_days")
    days = [
        (begin + timedelta(days=i)).isoformat()
        for i in range((finish - begin).days + 1)
    ]
    if len(days) > 366:
        raise ValueError("Maximum period is 366 days")
    expected = set(days)
    observed: dict[str, dict] = {}
    audit_errors: list[str] = []
    for index, path in enumerate(archives):
        candidate = Path(path)
        evidence = audit_archive_zip(candidate)
        reported_date = evidence.get("date_oslo")
        # Immutable source paths/hashes: do not use a mutable filename or
        # claimed successful workflow status as a substitute for source bytes.
        try:
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError:
            digest = None
        if evidence["errors"] or not isinstance(reported_date, str):
            audit_errors.append(f"INVALID_OR_UNREADABLE_SOURCE_ARTIFACT:{index}")
            continue
        if reported_date not in expected:
            audit_errors.append(f"OUTSIDE_PREDECLARED_WINDOW:{reported_date}")
            continue
        if reported_date in observed:
            audit_errors.append(f"DUPLICATE_SOURCE_DAY:{reported_date}")
            continue
        responses = (evidence["pdf_raw_sha_verified"]
                     + evidence["json_raw_sha_verified"])
        raw_ok = bool(evidence["raw_provenance_complete"] and responses > 0)
        observed[reported_date] = {
            "zip_sha256": digest,
            "manifest": evidence["manifest"],
            "original_json_verified": evidence["json_raw_sha_verified"],
            "original_pdf_verified": evidence["pdf_raw_sha_verified"],
            "unrecoverable_legacy_json": evidence["json_raw_unavailable_legacy"],
            "raw_provenance_complete": raw_ok,
            "collector_status": evidence.get("collector_status"),
            "calendar_status": evidence.get("calendar_status"),
            "source_day_coverage_certified": False,
            "pit_certified": False,
        }

    missing = sorted(expected - set(observed))
    raw_ready = sum(v["raw_provenance_complete"] for v in observed.values())
    if audit_errors:
        status = "INVALID_ARCHIVE_SERIES"
    elif len(days) < minimum_days:
        status = "INSUFFICIENT_PREDECLARED_WINDOW"
    elif missing:
        status = "MISSING_SOURCE_DAYS"
    elif raw_ready != len(days):
        status = "RAW_SOURCE_EVIDENCE_INCOMPLETE"
    else:
        status = "RAW_RECEIPTS_WINDOW_PASS_NO_DAY_OR_PIT_CERTIFICATION"

    return {
        "schema": SCHEMA, "status": status,
        "start_date": start_date, "end_date": end_date,
        "minimum_consecutive_days": minimum_days,
        "predeclared_days": len(days),
        "source_archives_supplied": len(archives),
        "unique_source_days": len(observed),
        "missing_source_days": missing,
        "days_with_verified_successful_raw_receipts": raw_ready,
        "days_with_unverifiable_or_missing_receipts": len(observed) - raw_ready,
        "archive_errors": sorted(audit_errors),
        "by_day": dict(sorted(observed.items())),
        "source_scope": "SUCCESSFUL_CAPTURED_HTTP_BODIES_ONLY",
        "independent_whole_day_denominator_proven": False,
        "prospective_pit_certified": False,
        "model_training_or_bet_authority": False,
        "operational_14_day_completion_certified": False,
        "notes": [
            "Even 14 complete raw capture archives are not an independent schedule denominator.",
            "Original capture timestamps do not attest first provider publication times.",
            "Missing or duplicate days remain visible rather than being counted as no-race days.",
            "Historical wrapper-only JSON does not become recovered raw HTTP bytes.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--minimum-days", type=int, default=14)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args(argv)
    report = audit_series(
        args.archives, start_date=args.start_date,
        end_date=args.end_date, minimum_days=args.minimum_days
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == (
        "RAW_RECEIPTS_WINDOW_PASS_NO_DAY_OR_PIT_CERTIFICATION"
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())

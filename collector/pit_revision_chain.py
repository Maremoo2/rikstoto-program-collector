"""Compare time-ordered original race PDF source captures for one Oslo day.

Reuses the existing one-archive receipt audit. The result is historical
source revision evidence, not point-in-time certification.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .pit_source_snapshot import _utc_receipt, audit_original_pdf_capture_tminus4

SCHEMA = "collector_cdev06_source_revision_sequence_v1"
MAX_ARCHIVES = 30


def compare_source_captures(paths: list[Path], *, day: str) -> dict:
    result = {
        "schema": SCHEMA, "date_oslo": day,
        "status": "BLOCKED_INSUFFICIENT_SOURCE_CAPTURES",
        "archives_requested": len(paths), "valid_archives": 0,
        "races_observed": 0, "races_in_every_capture": 0,
        "source_pdf_revisions_observed": 0,
        "start_clock_changes_observed": 0,
        "races_with_capture_near_pdf_tminus4": 0,
        "races_bracketing_pdf_tminus4": 0,
        "errors": [], "captures": [], "race_timelines": [],
        "independent_start_time_verified": False,
        "first_publication_time_attested": False,
        "independent_complete_race_day_verified": False,
        "tminus4_pit_certified": False,
        "bet_authorized": False, "hq_accepted": False,
        "source_archives_modified": False,
    }
    if not 1 <= len(paths) <= MAX_ARCHIVES:
        result["errors"].append("INVALID_CAPTURE_COUNT")
        return result
    seen = set()
    race_sources = defaultdict(list)
    keysets = []
    for number, path in enumerate(paths):
        source = audit_original_pdf_capture_tminus4(Path(path))
        result["captures"].append({
            "source_run_id": source.get("source_run_id"),
            "original_archive_sha256": source.get("original_archive_sha256"),
            "source_status": source["status"],
            "source_day": source.get("source_day"),
        })
        identity = (source.get("source_run_id"),
                    source.get("original_archive_sha256"))
        if (source["status"] != "SOURCE_CAPTURE_TIMING_DIAGNOSTIC_ONLY"
                or source.get("source_day") != day or None in identity):
            result["errors"].append("INVALID_ORIGINAL_CAPTURE:" + str(number))
            continue
        if identity[0] in {entry[0] for entry in seen} or identity[1] in {
                entry[1] for entry in seen}:
            result["errors"].append("DUPLICATE_CAPTURE_IDENTITY:" + str(number))
            continue
        seen.add(identity)
        result["valid_archives"] += 1
        keys = set()
        for row in source["races"]:
            key = (row.get("meeting_id"), row.get("race_number"))
            stamp = _utc_receipt(row.get("pdf_receipt_observed_at_utc"))
            if (not isinstance(key[0], str) or type(key[1]) is not int
                    or stamp is None or key in keys):
                result["errors"].append("INVALID_RACE_IDENTITY_OR_CLOCK:" + str(number))
                continue
            keys.add(key)
            race_sources[key].append((stamp, row))
        keysets.append(keys)
    if result["errors"]:
        result["status"] = "BLOCKED_INVALID_SOURCE_SEQUENCE"
        return result
    result["races_observed"] = len(race_sources)
    if keysets:
        result["races_in_every_capture"] = len(set.intersection(*keysets))
    for (meeting, number), entries in sorted(race_sources.items()):
        ordered = sorted(entries, key=lambda pair: pair[0])
        times = [stamp for stamp, _ in ordered]
        hashes = {row.get("source_pdf_sha256") for _, row in ordered}
        deadlines = {row.get("pdf_tminus4_utc_unverified") for _, row in ordered}
        revised = len(hashes) > 1
        clock_changed = len(deadlines) > 1
        if revised:
            result["source_pdf_revisions_observed"] += 1
        if clock_changed:
            result["start_clock_changes_observed"] += 1
        deadline = None
        if (not clock_changed and None not in deadlines
                and len(times) == len(set(times))):
            try:
                deadline = datetime.fromisoformat(next(iter(deadlines)))
            except (ValueError, TypeError):
                pass
        near = deadline is not None and any(
            deadline - timedelta(minutes=1) <= t <= deadline + timedelta(minutes=1)
            for t in times)
        bracketed = deadline is not None and (
            any(t <= deadline for t in times)
            and any(t > deadline for t in times))
        if near:
            result["races_with_capture_near_pdf_tminus4"] += 1
        if bracketed:
            result["races_bracketing_pdf_tminus4"] += 1
        result["race_timelines"].append({
            "meeting_id": meeting, "race_number": number,
            "source_capture_count": len(entries),
            "source_pdf_revision_observed": revised,
            "pdf_start_clock_changed": clock_changed,
            "source_observed_at_utc": [t.isoformat() for t in times],
            "near_unverified_tminus4": bool(near),
            "observations_bracket_unverified_tminus4": bool(bracketed),
            "tminus4_pit_certified": False,
        })
    if len(seen) < 2:
        result["status"] = "BLOCKED_INSUFFICIENT_SOURCE_CAPTURES"
    elif any(len(v) != len(seen) for v in race_sources.values()):
        result["status"] = "BLOCKED_INCOMPLETE_CAPTURE_SEQUENCE"
    elif not race_sources:
        result["status"] = "BLOCKED_NO_RACE_SOURCE"
    else:
        result["status"] = "SOURCE_REVISION_SEQUENCE_DIAGNOSTIC_ONLY"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = compare_source_captures(args.archive, day=args.day)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is None:
        print(rendered)
    else:
        if args.output.resolve() in {p.resolve() for p in args.archive}:
            parser.error("Cannot overwrite an original source archive")
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
    return 0 if report["status"] == "SOURCE_REVISION_SEQUENCE_DIAGNOSTIC_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())

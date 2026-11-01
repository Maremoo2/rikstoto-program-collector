"""C-DEV-06 read-only T−4 source-capture timing diagnostic from original PDFs.

A PDF retrieval-completion timestamp is NOT a provider first-publication
timestamp. A parsed PDF race clock is NOT independently confirmed start time.
This diagnostic never certifies PIT, C1, WIN or betting eligibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .archive_integrity_audit import audit_archive_zip
from .history_shadow import replay_original_archive
from .no_se_calendar import audit_no_se_trot_discovery
from .pdf_program import parse_extended_pdf
from .source_integrity import time_blocker

SCHEMA = "COLLECTOR_CDEV06_ORIGINAL_PDF_TMINUS4_SOURCE_DIAGNOSTIC_V1"
OFFICIAL_PDF_BASE = "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/"
OSLO = ZoneInfo("Europe/Oslo")
DAY_RE = re.compile(r"20\d{2}-\d{2}-\d{2}\Z")
RUN_RE = re.compile(r"\d{8}T\d{12}Z\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
CLOCK = re.compile(r"(?:[01]?\d|2[0-3]):[0-5]\d\Z")
MAX_ARCHIVE_BYTES = 200_000_000


def _utc_receipt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        candidate = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if candidate.tzinfo is None or candidate.utcoffset() != timedelta(0):
        return None
    return candidate.astimezone(UTC)


def _pdf_clock_utc(day: str, clock: object) -> tuple[datetime | None, str | None]:
    """Disallow DST fold/nonexistence, midnight placeholders and invalid times."""
    problem = time_blocker(clock)
    if problem is not None:
        return None, problem
    if not isinstance(clock, str) or not CLOCK.fullmatch(clock):
        return None, "START_TIME_INVALID"
    try:
        hh, mm = (int(part) for part in clock.split(":"))
        local_naive = datetime.combine(date.fromisoformat(day), time(hh, mm))
    except (ValueError, TypeError):
        return None, "START_TIME_INVALID"
    candidates = []
    for fold in (0, 1):
        localized = local_naive.replace(tzinfo=OSLO, fold=fold)
        utc = localized.astimezone(UTC)
        if utc.astimezone(OSLO).replace(tzinfo=None) == local_naive:
            candidates.append(utc)
    unique = set(candidates)
    if len(unique) != 1:
        return None, ("AMBIGUOUS_DST_RACE_CLOCK" if unique
                      else "NONEXISTENT_DST_RACE_CLOCK")
    return unique.pop(), None


def _archive_root(archive: zipfile.ZipFile, day: str, run: str) -> str | None:
    manifests = [name for name in archive.namelist()
                 if name.endswith("/manifest.json")]
    if len(manifests) != 1:
        return None
    prefix = manifests[0][:-len("manifest.json")]
    if prefix.endswith(f"/{day}/{run}/"):
        return prefix
    return None


def audit_original_pdf_capture_tminus4(archive_path: Path) -> dict:
    """Verify PDF-source observation times against PDF-derived race clocks.

    Uses frozen original bytes; reports candidate race timing only. No
    publication attestation, actual post-change start time, complete
    field/meeting denominator or PIT authorization can be inferred.
    """
    output = {
        "schema": SCHEMA,
        "status": "BLOCKED_ORIGINAL_SOURCE_TIMING",
        "original_archive_sha256": None,
        "source_archive_integrity_errors": [],
        "source_day": None,
        "source_run_id": None,
        "source_candidate_meetings": 0,
        "source_candidate_races": 0,
        "candidate_pdf_receipts_sha_verified": 0,
        "pdf_text_projection_reproduced": 0,
        "observed_pdf_capture_before_unverified_clock_tminus4": 0,
        "observed_pdf_capture_after_unverified_clock_tminus4": 0,
        "race_clock_or_identity_unverified": 0,
        "excluded_composite_products": [],
        "meeting_issues": [],
        "races": [],
        "source_first_publication_time_attested": False,
        "independent_race_start_time_verified": False,
        "independent_full_day_no_se_denominator_verified": False,
        "prospective_tminus4_snapshot_attested": False,
        "c6_pit_certified": False,
        "live_win_market_verified": False,
        "bet_authorized": False,
        "hq_accepted": False,
        "production_mutation": False,
    }
    integrity = audit_archive_zip(archive_path)
    output["source_archive_integrity_errors"] = list(integrity.get("errors", []))
    if integrity["errors"]:
        return output
    try:
        if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
            output["source_archive_integrity_errors"].append("ARCHIVE_SIZE_LIMIT")
            return output
        output["original_archive_sha256"] = hashlib.sha256(
            archive_path.read_bytes()
        ).hexdigest()
        with zipfile.ZipFile(archive_path) as archive:
            day, run = integrity["date_oslo"], integrity["run_id"]
            output["source_day"], output["source_run_id"] = day, run
            if (not DAY_RE.fullmatch(day) or date.fromisoformat(day).isoformat() != day
                    or not RUN_RE.fullmatch(run)):
                output["source_archive_integrity_errors"].append("INVALID_ARCHIVE_DAY_RUN")
                return output
            root = _archive_root(archive, day, run)
            if root is None:
                output["source_archive_integrity_errors"].append("ARCHIVE_MANIFEST_ROOT_MISMATCH")
                return output
            manifest = json.loads(archive.read(root + "manifest.json"))
            typed = audit_no_se_trot_discovery(manifest)
            meetings = typed["no_se_trot_physical_candidate_ids"]
            output["source_candidate_meetings"] = len(meetings)
            output["excluded_composite_products"] = typed["composite_product_ids_excluded"]
            output["source_discovery_blockers"] = typed["blockers"]
            output["source_candidate_races"] = typed["no_se_trot_observed_pdf_race_count"]
            output["source_collector_candidates_not_collected"] = typed[
                "candidate_ids_not_collected"
            ]
            if not meetings:
                output["meeting_issues"].append("NO_TYPED_PHYSICAL_NO_SE_TROT_CANDIDATES")
            recorded = {
                row["meeting_id"]: row for row in manifest.get("meetings", [])
                if isinstance(row, dict) and isinstance(row.get("meeting_id"), str)
            }
            for mid in meetings:
                if mid not in recorded or recorded[mid].get(
                        "is_multi_track_product") is not False:
                    output["meeting_issues"].append(mid + ":MISSING_PHYSICAL_MEETING_RECORD")
                    continue
                pdf_path = root + "meetings/" + mid + "/full_program.pdf"
                text_path = pdf_path[:-4] + ".txt"
                sources = [
                    rec for rec in manifest["requests"]
                    if isinstance(rec, dict)
                    and rec.get("status") == "PDF_OK"
                    and rec.get("url") == OFFICIAL_PDF_BASE + mid
                    and isinstance(rec.get("path"), str)
                    and rec["path"].endswith("/meetings/" + mid + "/full_program.pdf")
                ]
                if len(sources) != 1:
                    output["meeting_issues"].append(mid + ":PDF_RECEIPT_NOT_UNIQUE")
                    continue
                receipt = sources[0]
                src_sha = receipt.get("sha256")
                observed = _utc_receipt(receipt.get("at_utc"))
                if (not isinstance(src_sha, str) or not HEX.fullmatch(src_sha)
                        or observed is None or pdf_path not in archive.namelist()
                        or text_path not in archive.namelist()):
                    output["meeting_issues"].append(mid + ":ORIGINAL_PDF_RECEIPT_OR_TIME_UNVERIFIED")
                    continue
                if hashlib.sha256(archive.read(pdf_path)).hexdigest() != src_sha:
                    output["meeting_issues"].append(mid + ":ORIGINAL_PDF_SHA_DISAGREES")
                    continue
                output["candidate_pdf_receipts_sha_verified"] += 1
                # Reuse existing C-DEV-04 original PDF→TXT re-extraction.
                try:
                    parity = replay_original_archive(
                        archive_path, meeting_id=mid, date_oslo=day,
                        expected_pdf_sha256=src_sha)
                except (ValueError, OSError, KeyError, TypeError, UnicodeError) as exc:
                    output["meeting_issues"].append(
                        mid + ":PDF_TEXT_PROJECTION_UNVERIFIED:" + type(exc).__name__)
                    continue
                if parity["pdf_text_projection_reproduced_from_original_pdf"] is not True:
                    output["meeting_issues"].append(mid + ":PDF_TEXT_PROJECTION_NOT_REPRODUCED")
                    continue
                output["pdf_text_projection_reproduced"] += 1
                parsed = parse_extended_pdf(
                    archive.read(text_path).decode("utf-8"),
                    meeting_id=mid, date=day, url=OFFICIAL_PDF_BASE + mid,
                    captured_at=receipt["at_utc"],
                )
                numbers = [d["race"].get("race_number") for d in parsed["races"]]
                repeated = {n for n in numbers if numbers.count(n) > 1}
                for document in parsed["races"]:
                    item = document["race"]
                    number = item.get("race_number")
                    race = {
                        "meeting_id": mid,
                        "race_number": number,
                        "pdf_race_number_source": item.get("race_number_source"),
                        "pdf_start_clock_local_unverified": item.get(
                            "scheduled_time_local"
                        ),
                        "pdf_receipt_observed_at_utc": observed.isoformat(),
                        "source_pdf_sha256": src_sha,
                        "status": "RACE_SOURCE_CLOCK_OR_IDENTITY_UNVERIFIED",
                        "independent_start_time_verified": False,
                        "source_publication_time_attested": False,
                        "pit_certified": False,
                    }
                    if (type(number) is not int or not 1 <= number <= 30
                            or number in repeated
                            or item.get("race_number_source") not in (
                                "pdf_heading", "pdf_heading_number"
                            )):
                        race["blocker"] = "PHYSICAL_RACE_NUMBER_UNVERIFIED"
                    else:
                        start, blocker = _pdf_clock_utc(
                            day, item.get("scheduled_time_local"))
                        if blocker:
                            race["blocker"] = blocker
                        else:
                            deadline = start - timedelta(minutes=4)
                            race["pdf_tminus4_utc_unverified"] = deadline.isoformat()
                            # This assesses past PDF retrieval relative to
                            # a *parsed* start clock, not an actual as-of PIT.
                            if observed <= deadline:
                                race["status"] = "PDF_CAPTURE_EARLIER_THAN_UNVERIFIED_TMINUS4"
                                output[
                                    "observed_pdf_capture_before_unverified_clock_tminus4"
                                ] += 1
                            else:
                                race["status"] = "PDF_CAPTURE_AFTER_UNVERIFIED_TMINUS4"
                                output[
                                    "observed_pdf_capture_after_unverified_clock_tminus4"
                                ] += 1
                    if race["status"] == "RACE_SOURCE_CLOCK_OR_IDENTITY_UNVERIFIED":
                        output["race_clock_or_identity_unverified"] += 1
                    output["races"].append(race)

            output["parsed_pdf_races_in_typed_meetings"] = len(output["races"])
            output["observed_candidate_race_denominator_is_independent"] = False
            output["history_pdf_source_pit_eligible_races"] = 0
            output["status"] = (
                "SOURCE_CAPTURE_TIMING_DIAGNOSTIC_ONLY"
                if output["races"] and not output["meeting_issues"]
                else "BLOCKED_ORIGINAL_SOURCE_TIMING"
            )
            return output
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        output["source_archive_integrity_errors"].append(
            "UNREADABLE_SOURCE_ARTIFACT:" + type(exc).__name__)
        return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = audit_original_pdf_capture_tminus4(args.archive)
    rendered = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False)
    if args.output:
        if args.output.resolve() == args.archive.resolve():
            parser.error("Refuse original archive replacement")
        with args.output.open("x", encoding="utf-8") as destination:
            destination.write(rendered + "\n")
    else:
        summary = {k: v for k, v in report.items() if k != "races"}
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False, indent=2))
    # Source-only diagnostic return 0 means no missing source, not PIT success.
    return 0 if report["status"] == "SOURCE_CAPTURE_TIMING_DIAGNOSTIC_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only C-DEV-04 24-PDF text-projection replay (NOT history gold).

Compose existing Collector 24-PDF original source audit with existing
history_shadow.replay_original_archive. Do not reimplement PDF parsing,
the original SHA/receipt checks, Betting DATA-004E gold, or C6 PIT.
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from .history_shadow import replay_original_archive
from .holdout_pdf_source_replay import (
    MAX_INDEX_BYTES, audit_frozen_holdout_sources, git_blob_sha1,
)

SCHEMA = "COLLECTOR_CDEV04_FROZEN_24_PDF_TEXT_PARITY_V1"
EXPECTED_FROZEN_PROGRAMS = 24
EXPECTED_FROZEN_ARCHIVES = 7

# Stable diagnostics only; never include private horse rows or stack traces.
_REPLAY_EXCEPTIONS = (
    ValueError, TypeError, KeyError, OSError, UnicodeError,
    zipfile.BadZipFile,
)
_ERROR_MESSAGES = {
    "ARCHIVED_PDF_TEXT_PROJECTION_MISMATCH",
    "Missing paired PDF text member",
    "Missing or ambiguous source archive manifest",
    "Original archive manifest day/run mismatch",
    "Missing, duplicate or foreign-capture PDF member",
    "Original PDF SHA mismatch",
    "Original PDF has no extractable pages",
    "Original PDF exceeds read-only size limit",
    "Derived PDF text exceeds read-only limit",
    "Invalid source identity, date or source SHA",
    "Derived PDF text SHA mismatch",
}


def _failure_code(error: Exception) -> str:
    text = str(error)
    if text in _ERROR_MESSAGES:
        return text.upper().replace(" ", "_").replace(",", "")
    return "ORIGINAL_TEXT_REPLAY_EXCEPTION_" + type(error).__name__


def audit_frozen_text_projection(
    source_index: Any,
    archive_paths: dict[int, Path],
    *,
    index_git_blob_sha1: str,
    observed_index_git_blob_sha1: str,
    expected_programs: int = EXPECTED_FROZEN_PROGRAMS,
    expected_archives: int = EXPECTED_FROZEN_ARCHIVES,
) -> dict[str, Any]:
    """Evidence for archived pypdf text parity, never independent field gold.

    Only a byte-exact frozen external source index + complete original
    PDF source audit permits the historical TXT/PDF replay. Every
    exception is a visible per-meeting veto, never a skipped denominator.
    """
    origin = audit_frozen_holdout_sources(
        source_index,
        archive_paths,
        expected_programs=expected_programs,
        expected_archives=expected_archives,
        index_git_blob_sha1=index_git_blob_sha1,
        observed_index_git_blob_sha1=observed_index_git_blob_sha1,
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "BLOCKED_FROZEN_SOURCE_CORPUS",
        "source_only_original_pdf_corpus_verified": (
            origin.get("source_only_original_programs_complete") is True
            and origin.get("source_index_identity_verified") is True
        ),
        "frozen_source_index_git_blob_sha1": index_git_blob_sha1,
        "expected_pdf_programs": expected_programs,
        "expected_original_archives": expected_archives,
        "pdf_source_sha_verified": origin["pdf_hashes_verified"],
        "pdf_source_pages_verified": origin["pdf_page_counts_verified"],
        "pdf_source_official_receipts_verified": origin["pdf_request_receipts_correlated"],
        "typed_physical_pdf_programs": origin["typed_physical_meeting_pdf_programs"],
        "typed_composite_pdf_programs": origin["typed_composite_product_pdf_programs"],
        "meeting_type_unknown_pdf_programs": origin["meeting_type_unverified_pdf_programs"],
        "legacy_json_receipts_without_original_bytes": sum(
            item["legacy_json_receipts_without_raw_bytes"]
            for item in origin["archive_diagnostics"]
        ),
        "pdf_text_projection_verified": 0,
        "pdf_text_projection_blocked": 0,
        "pdf_text_projection_missing": 0,
        "history_candidate_rows_from_reproduced_text": 0,
        "projection_error_counts": {},
        "program_diagnostics": [],
        "errors": list(origin["errors"]),
        # These fields are permanent exclusions, not conditional scores.
        "independent_pdf_page_visual_review": False,
        "independent_horse_history_row_identity_verified": False,
        "data004e_390_gold_pairs_accepted": 0,
        "data004e_390_gold_pairs_expected": 390,
        "data004e_gold_verified": False,
        "independent_no_se_full_day_denominator_verified": False,
        "c1_14day_coverage_verified": False,
        "source_first_publication_time_attested": False,
        "c6_t_minus_4_pit_certified": False,
        "live_market_verified": False,
        "bet_authorized": False,
        "production_parser_changed": False,
        "hq_accepted": False,
    }
    if not report["source_only_original_pdf_corpus_verified"]:
        report["status"] = "BLOCKED_FROZEN_SOURCE_CORPUS"
        report["errors"].append("ORIGINAL_24_PDF_SOURCE_AUDIT_UNVERIFIED")
        report["errors"] = sorted(set(report["errors"]))
        return report

    if not isinstance(source_index, dict) or not isinstance(
            source_index.get("programs"), list):
        # Should not occur after base auditor success.
        report["errors"].append("SOURCE_INDEX_UNRECOGNIZED_AFTER_AUDIT")
        return report

    failures = Counter()
    for record in sorted(source_index["programs"], key=lambda r: r["meeting"]):
        meeting = record["meeting"]
        artifact_id = record["artifact_id"]
        diag = {
            "meeting": meeting,
            "artifact_id": artifact_id,
            "status": "PDF_TEXT_PROJECTION_BLOCKED",
            "original_pdf_sha256": record["pdf_sha256"],
            "original_pdf_pages_expected": record["pages"],
            "pdf_text_projection_reproduced_from_original_pdf": False,
            "independent_visual_row_gold": False,
            "c6_pit_certified": False,
        }
        try:
            source = replay_original_archive(
                Path(archive_paths[artifact_id]),
                meeting_id=meeting,
                date_oslo=meeting.rsplit("_", 1)[-1],
                expected_pdf_sha256=record["pdf_sha256"],
            )
            if (source.get("pdf_text_projection_reproduced_from_original_pdf") is not True
                    or source.get("source_bytes_sha256_verified") is not True
                    or source.get("independent_original_page_visual_review") is not False
                    or source.get("data004e_holdout_390_accepted") != 0
                    or source.get("pit_certified") is not False):
                raise ValueError("INVALID_PROJECTION_PROOF_CONTRACT")
            if source["pdf_extraction_page_count"] != record["pages"]:
                raise ValueError("PROJECTION_PAGE_COUNT_CHANGED")
            if source["source_pdf_sha256"] != record["pdf_sha256"]:
                raise ValueError("PROJECTION_PDF_SHA_CHANGED")
            diag.update({
                "status": "REPRODUCED_PDF_TEXT_SOURCE_ONLY",
                "pdf_text_projection_reproduced_from_original_pdf": True,
                "pypdf_extractor_version": source["pdf_text_projection_extractor"],
                "derived_text_sha256": source["pdf_text_sha256"],
                "reextracted_text_sha256": source["pdf_text_reextracted_sha256"],
                "reextracted_pdf_pages": source["pdf_extraction_page_count"],
                "unverified_history_candidate_rows": source["history_source_rows_indexed"],
            })
            report["pdf_text_projection_verified"] += 1
            report["history_candidate_rows_from_reproduced_text"] += source[
                "history_source_rows_indexed"
            ]
        except _REPLAY_EXCEPTIONS as err:
            code = _failure_code(err)
            diag["blocker"] = code
            failures[code] += 1
            report["errors"].append(meeting + ":" + code)
            report["pdf_text_projection_blocked"] += 1
            if code == "MISSING_PAIRED_PDF_TEXT_MEMBER":
                report["pdf_text_projection_missing"] += 1
        report["program_diagnostics"].append(diag)

    report["projection_error_counts"] = dict(sorted(failures.items()))
    if (not report["errors"]
            and report["pdf_text_projection_verified"] == expected_programs
            and len(report["program_diagnostics"]) == expected_programs):
        report["status"] = "COMPLETE_ORIGINAL_PDF_TEXT_PROJECTION_SOURCE_ONLY"
    else:
        report["status"] = "PARTIAL_OR_BLOCKED_PDF_TEXT_PROJECTION"
    report["errors"] = sorted(set(report["errors"]))
    report["notes"] = [
        "Reproduced PDF text means identical extraction bytes, not correct horse/history ownership.",
        "Original PDF visual page/column confirmation remains independent and absent.",
        "Betting DATA-004E independent human 390-cell holdout gold remains 0/390.",
        "No C1 full-day denominator, C6 source publication clock or PIT evidence.",
        "Original PDF bytes and frozen Betting source metadata were not modified.",
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--expected-index-blob-sha1", required=True)
    parser.add_argument(
        "--archive", action="append", default=[],
        help="ARTIFACT_ID=/private/immutable-original.zip"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--diagnostic-only", action="store_true",
        help="Allow an incomplete replay to produce an explicit BLOCKED report; never certify it."
    )
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_index_blob_sha1):
        parser.error("Expected frozen source Git blob must be an exact lowercase SHA-1")
    if args.source_index.stat().st_size > MAX_INDEX_BYTES:
        parser.error("Frozen source index too large")
    try:
        raw_index = args.source_index.read_bytes()
        source_index = json.loads(raw_index)
        paths: dict[int, Path] = {}
        for item in args.archive:
            aid, sep, filename = item.partition("=")
            if (not sep or not aid.isascii() or not aid.isdecimal()
                    or int(aid) in paths):
                parser.error("Archive must be unique ARTIFACT_ID=FILE")
            paths[int(aid)] = Path(filename)
        result = audit_frozen_text_projection(
            source_index, paths,
            index_git_blob_sha1=args.expected_index_blob_sha1,
            observed_index_git_blob_sha1=git_blob_sha1(raw_index),
        )
    except (ValueError, OSError, TypeError) as err:
        parser.error("Source input invalid: " + type(err).__name__)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        if args.output.resolve() in {
            args.source_index.resolve(),
            *(path.resolve() for path in paths.values())
        }:
            parser.error("Cannot overwrite immutable original source inputs")
        with args.output.open("x", encoding="utf-8") as output:
            output.write(rendered + "\n")
    else:
        print(rendered)
    if result["status"] == "COMPLETE_ORIGINAL_PDF_TEXT_PROJECTION_SOURCE_ONLY":
        return 0
    # Nonzero by default; a research-only runner may opt to archive an
    # explicit negative report, not to claim C3/C4/C6 success.
    return 0 if args.diagnostic_only else 2


if __name__ == "__main__":
    raise SystemExit(main())

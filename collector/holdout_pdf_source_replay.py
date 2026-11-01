"""C-DEV-04 offline original-PDF source replay across a frozen external index.

Collector verifies its own original archive provenance, bytes and PDF pages.
Betting DATA-004E independently owns blind review, holdout labels and gold.
No network, production writes, gold inference, PIT or betting logic here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from pypdf import PdfReader

from .archive_integrity_audit import audit_archive_zip

SCHEMA = "DATA004_HOLDOUT_PDF_SOURCE_EVIDENCE_V1"
REPORT_SCHEMA = "COLLECTOR_CDEV04_24_PDF_SOURCE_REPLAY_V1"
MEETING = re.compile(r"[A-Z0-9]{1,14}_[A-Z]{2,4}_(20\d{2}-\d{2}-\d{2})\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RUN_ID = re.compile(r"\d{8}T\d{12}Z\Z")
MAX_PDF_BYTES = 64_000_000
MAX_INDEX_BYTES = 2_000_000


def git_blob_sha1(body: bytes) -> str:
    """Git object hash of source JSON, not approval or reviewer evidence."""
    return hashlib.sha1(
        b"blob " + str(len(body)).encode("ascii") + b"\0" + body
    ).hexdigest()


def _program_metadata(index: Any, expected_programs: int,
                      expected_archives: int) -> tuple[list[dict], list[str]]:
    errors = []
    if (not isinstance(index, dict) or index.get("schema_version") != SCHEMA
            or type(index.get("distinct_pdf_programs")) is not int
            or index["distinct_pdf_programs"] != expected_programs
            or type(index.get("source_archives")) is not int
            or index["source_archives"] != expected_archives
            or type(index.get("pre_registered_samples")) is not int
            or index["pre_registered_samples"] != 30
            or index.get("historical_row_identity_verified") is not False
            or index.get("independent_gold_fields_verified") is not False):
        return [], ["FROZEN_SOURCE_INDEX_SCHEMA_OR_UNVERIFIED_GOLD_STATUS_INVALID"]
    programs = index.get("programs")
    if not isinstance(programs, list) or len(programs) != expected_programs:
        return [], ["SOURCE_INDEX_PROGRAM_COUNT_MISMATCH"]
    meetings, artifacts = set(), set()
    for entry in programs:
        if not isinstance(entry, dict):
            errors.append("MALFORMED_SOURCE_PROGRAM")
            continue
        mid = entry.get("meeting")
        match = MEETING.fullmatch(mid) if isinstance(mid, str) else None
        sha = entry.get("pdf_sha256")
        artifact = entry.get("artifact_id")
        pages = entry.get("pages")
        if (not match or not isinstance(sha, str) or not SHA256.fullmatch(sha)
                or type(artifact) is not int or artifact < 1
                or type(pages) is not int or not 1 <= pages <= 1000):
            errors.append("SOURCE_PROGRAM_ID_SHA_PAGES_OR_ARTIFACT_INVALID")
            continue
        if mid in meetings:
            errors.append("DUPLICATE_PHYSICAL_PROGRAM_SOURCE_MEETING")
        meetings.add(mid)
        artifacts.add(artifact)
        if entry.get("archive_entry_found") is not True or entry.get(
                "pdf_opened_with_fitz") is not True:
            errors.append("FROZEN_PROGRAM_SOURCE_ATTESTATION_MISSING")
    if len(artifacts) != expected_archives:
        errors.append("SOURCE_INDEX_DISTINCT_ARCHIVE_COUNT_MISMATCH")
    return programs, sorted(set(errors))


def _source_zip(
    archive_file: Path,
) -> tuple[zipfile.ZipFile | None, dict[str, Any], list[str]]:
    """Return an opened archive and existing Collector audit, fail closed.

    Caller closes the ZIP. Existing audit_archive_zip owns the receipt
    checks; this module does not invent another raw JSON/PDF validator.
    """
    audit = audit_archive_zip(archive_file)
    issues = list(audit.get("errors") or [])
    if issues:
        return None, audit, ["COLLECTOR_ARCHIVE_INTEGRITY_ERROR:" + item for item in issues]
    try:
        archive = zipfile.ZipFile(archive_file)
    except (OSError, zipfile.BadZipFile):
        return None, audit, ["UNOPENABLE_SOURCE_ZIP"]
    return archive, audit, []


def _one_pdf(archive: zipfile.ZipFile, meeting: str, pdf_sha: str,
             pages: int) -> dict[str, Any]:
    """Bind one physical PDF to the manifest's exact day/run directory."""
    result = {
        "meeting": meeting, "expected_pdf_sha256": pdf_sha,
        "expected_pages": pages, "original_pdf_sha256_verified": False,
        "page_count_verified": False, "pdf_request_receipt_correlated": False,
        "source_run_identity_verified": False,
        "derived_text_member_present": False,
        "independent_horse_history_owner_verified": False,
        "independent_gold_fields_accepted": 0,
        "pdf_text_reextraction_verified": False,
        "pit_certified": False, "errors": [],
    }
    names = archive.namelist()
    # The underlying shared archive audit already rejects duplicate/unsafe
    # entries; strict identity is repeated for this individual source PDF.
    manifests = [item for item in names if item.endswith("/manifest.json")]
    if len(manifests) != 1:
        result["errors"].append("NOT_EXACTLY_ONE_MANIFEST")
        return result
    manifest_path = manifests[0]
    try:
        manifest = json.loads(archive.read(manifest_path))
    except (ValueError, TypeError):
        result["errors"].append("MANIFEST_NOT_JSON")
        return result
    day = meeting.rsplit("_", 1)[-1]
    prefix = manifest_path.removesuffix("manifest.json")
    run = manifest.get("run_id")
    if (not isinstance(run, str) or not RUN_ID.fullmatch(run)
            or manifest.get("date_oslo") != day
            or not prefix.endswith(f"/{day}/{run}/")):
        result["errors"].append("PROGRAM_MANIFEST_DAY_RUN_MISMATCH")
        return result
    expected_path = prefix + "meetings/" + meeting + "/full_program.pdf"
    candidates = [item for item in names
                  if item.endswith("/meetings/" + meeting + "/full_program.pdf")]
    if len(candidates) != 1 or candidates[0] != expected_path:
        result["errors"].append("PDF_MISSING_DUPLICATE_OR_FOREIGN_RUN")
        return result
    result["source_run_identity_verified"] = True
    if archive.getinfo(expected_path).file_size > MAX_PDF_BYTES:
        result["errors"].append("PDF_EXCEEDS_READONLY_BYTE_LIMIT")
        return result
    raw_pdf = archive.read(expected_path)
    observed_sha = hashlib.sha256(raw_pdf).hexdigest()
    result["actual_pdf_sha256"] = observed_sha
    if observed_sha != pdf_sha:
        result["errors"].append("ORIGINAL_PDF_SHA256_MISMATCH")
        return result
    result["original_pdf_sha256_verified"] = True
    result["derived_text_member_present"] = (
        expected_path[:-4] + ".txt" in names
    )
    # Cross-check the official request receipt, not merely a matching
    # filename in a caller-controlled ZIP.
    requests = manifest.get("requests")
    found_receipts = [
        r for r in requests if isinstance(r, dict)
        and r.get("status") == "PDF_OK"
        and isinstance(r.get("path"), str)
        and r["path"].endswith("/meetings/" + meeting + "/full_program.pdf")
    ] if isinstance(requests, list) else []
    if len(found_receipts) != 1 or (
        found_receipts[0].get("sha256") != pdf_sha
        or found_receipts[0].get("url")
        != "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/" + meeting
    ):
        result["errors"].append("SOURCE_PDF_HTTP_RECEIPT_NOT_CORRELATED")
    else:
        result["pdf_request_receipt_correlated"] = True
        result["observed_request_at_utc_unattested_publication"] = (
            found_receipts[0].get("at_utc")
        )
    try:
        reader = PdfReader(__import__("io").BytesIO(raw_pdf))
        result["actual_pages"] = len(reader.pages)
        if len(reader.pages) != pages:
            result["errors"].append("ORIGINAL_PDF_PAGE_COUNT_MISMATCH")
        else:
            result["page_count_verified"] = True
    except Exception as error:
        result["errors"].append("ORIGINAL_PDF_OPEN_FAILURE:" + type(error).__name__)
    return result


def audit_frozen_holdout_sources(
    source_index: Any, archive_paths: dict[int, Path], *,
    expected_programs: int = 24, expected_archives: int = 7,
    index_git_blob_sha1: str | None = None,
    observed_index_git_blob_sha1: str | None = None,
) -> dict[str, Any]:
    """Read-only source-provenance check; never mutate source or score a label."""
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "BLOCKED_SOURCE_PROGRAM_COHORT",
        "expected_programs": expected_programs,
        "expected_original_archives": expected_archives,
        "frozen_betting_source_index_git_blob_sha1": index_git_blob_sha1,
        "observed_source_index_git_blob_sha1": observed_index_git_blob_sha1,
        "source_index_identity_verified": False,
        "programs": [],
        "archive_diagnostics": [],
        "errors": [],
        "pdf_hashes_verified": 0,
        "pdf_page_counts_verified": 0,
        "pdf_request_receipts_correlated": 0,
        "captured_programs_with_derived_text": 0,
        "sample_rows_independently_gold_verified": 0,
        "data004e_holdout_gold_pairs_accepted": 0,
        "data004e_holdout_gold_pairs_total": 390,
        "independent_complete_day_denominator_verified": False,
        "c1_14day_coverage_eligible": False,
        "c4_gold_accepted": False,
        "source_first_publication_timestamp_attested": False,
        "c6_t_minus_4_pit_certified": False,
        "bet_authorized": False,
        "production_parser_changed": False,
    }
    if (index_git_blob_sha1 is not None
            and (not re.fullmatch(r"[0-9a-f]{40}", index_git_blob_sha1)
                 or observed_index_git_blob_sha1 != index_git_blob_sha1)):
        report["errors"].append("FROZEN_BETTING_SOURCE_INDEX_BLOB_SHA_MISMATCH")
        return report
    report["source_index_identity_verified"] = (
        index_git_blob_sha1 is not None
        and observed_index_git_blob_sha1 == index_git_blob_sha1
    )
    programs, errors = _program_metadata(source_index, expected_programs,
                                          expected_archives)
    if errors:
        report["errors"] = errors
        return report
    wanted_ids = {entry["artifact_id"] for entry in programs}
    if set(archive_paths) != wanted_ids:
        report["errors"].append("REQUIRED_ORIGINAL_ARTIFACT_ID_SET_MISMATCH")
        return report
    grouped: dict[int, list[dict]] = {}
    for p in programs:
        grouped.setdefault(p["artifact_id"], []).append(p)
    for aid in sorted(wanted_ids):
        path = archive_paths[aid]
        if not path.is_file():
            report["errors"].append(f"MISSING_ORIGINAL_ARCHIVE:{aid}")
            continue
        archive, integrity, archive_errors = _source_zip(path)
        report["archive_diagnostics"].append({
            "artifact_id": aid,
            "collector_integrity_status": integrity["status"],
            "original_pdf_receipts_sha_verified_by_collector": integrity[
                "pdf_raw_sha_verified"],
            "original_json_raw_receipts_sha_verified_by_collector": integrity[
                "json_raw_sha_verified"],
            "legacy_json_receipts_without_raw_bytes": integrity[
                "json_raw_unavailable_legacy"],
            "full_day_denominator_verified": False, "pit_certified": False,
            "errors": archive_errors,
        })
        if archive_errors or archive is None:
            report["errors"].extend(f"ARCHIVE_{aid}:{e}" for e in archive_errors)
            continue
        with archive:
            for source in grouped[aid]:
                one = _one_pdf(
                    archive, source["meeting"], source["pdf_sha256"],
                    source["pages"])
                one["artifact_id"] = aid
                report["programs"].append(one)
                if one["original_pdf_sha256_verified"]:
                    report["pdf_hashes_verified"] += 1
                if one["page_count_verified"]:
                    report["pdf_page_counts_verified"] += 1
                if one["pdf_request_receipt_correlated"]:
                    report["pdf_request_receipts_correlated"] += 1
                if one["derived_text_member_present"]:
                    report["captured_programs_with_derived_text"] += 1
                if one["errors"]:
                    report["errors"].extend(
                        f"{source['meeting']}:{issue}" for issue in one["errors"])
    report["source_only_original_programs_complete"] = (
        not report["errors"]
        and report["pdf_hashes_verified"] == expected_programs
        and report["pdf_page_counts_verified"] == expected_programs
        and report["pdf_request_receipts_correlated"] == expected_programs
        and len(report["programs"]) == expected_programs
    )
    if report["source_only_original_programs_complete"]:
        report["status"] = "ORIGINAL_PDF_COHORT_SOURCE_ONLY_VERIFIED"
    report["errors"] = sorted(set(report["errors"]))
    report["notes"] = [
        "24 source PDF byte/page/receipt successes do not verify 30 horse-history rows.",
        "Betting DATA-004E owns the 390-cell independent human gold review.",
        "Original source request timestamps are not source publication time or T-4 PIT.",
        "No predictive, economic, betting or full-day coverage authorization.",
        "PDF text projection equivalence must be checked separately on PR #51.",
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--expected-index-blob-sha1", required=True)
    parser.add_argument("--archive", action="append", default=[],
                        help="ARTIFACT_ID=/private/original.zip")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.source_index.stat().st_size > MAX_INDEX_BYTES:
            parser.error("Original frozen source index too large")
        index_bytes = args.source_index.read_bytes()
        index = json.loads(index_bytes)
        originals = {}
        for item in args.archive:
            aid, sep, filename = item.partition("=")
            if not sep or not aid.isascii() or not aid.isdecimal() or int(aid) in originals:
                parser.error("Each --archive must have a unique ARTIFACT_ID=FILE")
            originals[int(aid)] = Path(filename)
        result = audit_frozen_holdout_sources(
            index, originals,
            index_git_blob_sha1=args.expected_index_blob_sha1,
            observed_index_git_blob_sha1=git_blob_sha1(index_bytes),
        )
    except (ValueError, OSError, TypeError) as err:
        parser.error("Source input invalid: " + type(err).__name__)
    rendered = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
    if args.output:
        # Exclusive new output; never overwrite archived originals.
        if args.output.resolve() in {
            args.source_index.resolve(),
            *(path.resolve() for path in originals.values())
        }:
            parser.error("Cannot overwrite any original source input")
        with args.output.open("x", encoding="utf-8") as output:
            output.write(rendered + "\n")
    else:
        print(rendered)
    return 0 if result.get("source_only_original_programs_complete") else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Synthetic source ZIP evidence; never independent historical gold."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas

from collector.holdout_pdf_source_replay import (
    REPORT_SCHEMA, SCHEMA, audit_frozen_holdout_sources, git_blob_sha1,
)

MEETING = "OR_NR_2026-10-18"
DAY = "2026-10-18"
RUN = "20261018T120412486322Z"
ARTIFACT = 12135567920
PDF_PATH = f"output/daily/{DAY}/{RUN}/meetings/{MEETING}/full_program.pdf"
PDF_URL = "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/" + MEETING


def _pdf():
    buf = io.BytesIO()
    c = Canvas(buf)
    c.drawString(30, 750, "Source-only one page, no labels or gold")
    c.showPage()
    c.save()
    return buf.getvalue()


RAW_PDF = _pdf()
PDF_SHA = hashlib.sha256(RAW_PDF).hexdigest()


def _source_index(*, pdf_sha=PDF_SHA, pages=1, included=True):
    return {
        "schema_version": SCHEMA,
        "distinct_pdf_programs": 1,
        "source_archives": 1,
        "pre_registered_samples": 30,
        "historical_row_identity_verified": False,
        "independent_gold_fields_verified": False,
        "programs": [{
            "meeting": MEETING, "pdf_sha256": pdf_sha, "pages": pages,
            "artifact_id": ARTIFACT, "archive_entry_found": included,
            "pdf_opened_with_fitz": True,
        }],
    }


def _archive(tmp_path, *, original=RAW_PDF, change_manifest=None,
             path=PDF_PATH, request_sha=PDF_SHA,
             add_json_legacy=False, duplicate=False, meeting_type=False):
    root = tmp_path / "captured.zip"
    requests = [{
        "url": PDF_URL, "status": "PDF_OK", "path": path,
        "sha256": request_sha, "at_utc": DAY + "T10:00:00Z",
    }]
    if add_json_legacy:
        requests.append({
            "url": "https://www.rikstoto.no/api/racedays",
            "status": "JSON_OK",
            "path": f"output/daily/{DAY}/{RUN}/discovery_racedays.json",
            "sha256": "0" * 64,
        })
    manifest = {
        "date_oslo": DAY, "run_id": RUN, "requests": requests,
        "meetings": [{"meeting_id": MEETING,
                      "is_multi_track_product": meeting_type}],
        "counts": {},
    }
    if change_manifest:
        manifest.update(change_manifest)
    with zipfile.ZipFile(root, "w") as archive:
        archive.writestr(
            f"output/daily/{DAY}/{RUN}/manifest.json", json.dumps(manifest))
        archive.writestr(path, original)
        if duplicate:
            archive.writestr(path, original)
        if add_json_legacy:
            archive.writestr(
                f"output/daily/{DAY}/{RUN}/discovery_racedays.json",
                json.dumps({"response": {"success": True}}))
    return root


def _audit(index, path, *, expected_sha=None):
    return audit_frozen_holdout_sources(
        index, {ARTIFACT: Path(path)},
        expected_programs=1, expected_archives=1,
        index_git_blob_sha1=expected_sha,
        observed_index_git_blob_sha1=expected_sha,
    )


def test_actual_pdf_byte_sha_page_and_collector_receipt_only(tmp_path):
    report = _audit(_source_index(), _archive(tmp_path))
    assert report["schema"] == REPORT_SCHEMA
    assert report["status"] == "ORIGINAL_PDF_COHORT_SOURCE_ONLY_VERIFIED"
    assert report["source_only_original_programs_complete"] is True
    assert report["pdf_hashes_verified"] == 1
    assert report["pdf_page_counts_verified"] == 1
    assert report["pdf_request_receipts_correlated"] == 1
    assert report["typed_physical_meeting_pdf_programs"] == 1
    assert report["typed_composite_product_pdf_programs"] == 0
    assert report["meeting_type_unverified_pdf_programs"] == 0
    assert report["archive_diagnostics"][0]["original_pdf_receipts_sha_verified_by_collector"] == 1
    assert report["data004e_holdout_gold_pairs_accepted"] == 0
    assert report["data004e_holdout_gold_pairs_total"] == 390
    assert report["c4_gold_accepted"] is False
    assert report["independent_complete_day_denominator_verified"] is False
    assert report["c6_t_minus_4_pit_certified"] is False
    assert report["bet_authorized"] is False
    assert report["programs"][0]["pdf_text_reextraction_verified"] is False


def test_manifest_date_run_disagreement_blocks_even_valid_pdf_bytes(tmp_path):
    report = _audit(_source_index(), _archive(
        tmp_path, change_manifest={"date_oslo": "2026-10-19"}))
    assert report["status"] == "BLOCKED_SOURCE_PROGRAM_COHORT"
    assert report["source_only_original_programs_complete"] is False
    assert any("MANIFEST_IDENTITY_MISMATCH" in err for err in report["errors"])


def test_forged_source_index_pdf_sha_is_rejected(tmp_path):
    report = _audit(_source_index(pdf_sha="0" * 64), _archive(tmp_path))
    assert report["pdf_hashes_verified"] == 0
    assert any("ORIGINAL_PDF_SHA256_MISMATCH" in err for err in report["errors"])


def test_missing_original_artifact_cannot_be_implicit_no_race(tmp_path):
    report = _audit(_source_index(), tmp_path / "missing.zip")
    assert report["status"] == "BLOCKED_SOURCE_PROGRAM_COHORT"
    assert report["pdf_hashes_verified"] == 0
    assert "MISSING_ORIGINAL_ARCHIVE:" + str(ARTIFACT) in report["errors"]


def test_page_count_mismatch_is_visible_not_historic_gold(tmp_path):
    report = _audit(_source_index(pages=2), _archive(tmp_path))
    assert report["pdf_hashes_verified"] == 1
    assert report["pdf_page_counts_verified"] == 0
    assert any("ORIGINAL_PDF_PAGE_COUNT_MISMATCH" in err
               for err in report["errors"])
    assert report["data004e_holdout_gold_pairs_accepted"] == 0


def test_duplicate_original_zip_member_is_blocked(tmp_path):
    report = _audit(_source_index(), _archive(tmp_path, duplicate=True))
    assert any("DUPLICATE_ZIP_PATH" in err for err in report["errors"])
    assert report["status"] == "BLOCKED_SOURCE_PROGRAM_COHORT"


def test_unexpected_foreign_run_path_is_blocked(tmp_path):
    foreign = f"output/daily/{DAY}/20261018T120412486323Z/meetings/{MEETING}/full_program.pdf"
    report = _audit(_source_index(), _archive(tmp_path, path=foreign))
    assert any(
        "PDF_MISSING_DUPLICATE_OR_FOREIGN_RUN" in err
        or "COLLECTOR_ARCHIVE_INTEGRITY_ERROR:PDF_ARCHIVE_PATH_MISSING" in err
        for err in report["errors"]
    ), report["errors"]
    assert report["source_only_original_programs_complete"] is False


def test_legacy_json_without_raw_bytes_is_reported_not_recertified(tmp_path):
    report = _audit(_source_index(), _archive(tmp_path, add_json_legacy=True))
    assert report["status"] == "ORIGINAL_PDF_COHORT_SOURCE_ONLY_VERIFIED"
    archived = report["archive_diagnostics"][0]
    assert archived["legacy_json_receipts_without_raw_bytes"] == 1
    assert archived["full_day_denominator_verified"] is False
    assert archived["pit_certified"] is False


def test_source_index_sha_identity_required_for_cli_style_pin(tmp_path):
    content = json.dumps(_source_index()).encode()
    expected = git_blob_sha1(content)
    assert len(expected) == 40
    report = audit_frozen_holdout_sources(
        _source_index(), {ARTIFACT: _archive(tmp_path)},
        expected_programs=1, expected_archives=1,
        index_git_blob_sha1=expected, observed_index_git_blob_sha1="f" * 40)
    assert "FROZEN_BETTING_SOURCE_INDEX_BLOB_SHA_MISMATCH" in report["errors"]
    assert report["source_index_identity_verified"] is False
    assert report["data004e_holdout_gold_pairs_accepted"] == 0


def test_malformed_index_claiming_gold_or_duplicate_program_blocked(tmp_path):
    source = _source_index()
    source["independent_gold_fields_verified"] = True
    report = _audit(source, _archive(tmp_path))
    assert "FROZEN_SOURCE_INDEX_SCHEMA_OR_UNVERIFIED_GOLD_STATUS_INVALID" in report["errors"]
    source = _source_index()
    source["programs"] *= 2
    report = _audit(source, tmp_path / "missing.zip")
    assert "SOURCE_INDEX_PROGRAM_COUNT_MISMATCH" in report["errors"]


def test_source_receipt_disagreement_does_not_become_original_proof(tmp_path):
    report = _audit(_source_index(), _archive(tmp_path, request_sha="f" * 64))
    assert report["status"] == "BLOCKED_SOURCE_PROGRAM_COHORT"
    assert report["pdf_request_receipts_correlated"] == 0
    assert any("PDF_SOURCE_SHA_MISMATCH" in err for err in report["errors"])


def test_expected_archive_artifact_set_is_exact(tmp_path):
    index = _source_index()
    report = audit_frozen_holdout_sources(
        index, {111111: _archive(tmp_path)},
        expected_programs=1, expected_archives=1)
    assert "REQUIRED_ORIGINAL_ARTIFACT_ID_SET_MISMATCH" in report["errors"]


def test_no_gold_or_pit_even_with_matching_observation_timestamp(tmp_path):
    report = _audit(_source_index(), _archive(tmp_path))
    assert report["programs"][0]["observed_request_at_utc_unattested_publication"]
    assert report["source_first_publication_timestamp_attested"] is False
    assert report["sample_rows_independently_gold_verified"] == 0
    assert report["c1_14day_coverage_eligible"] is False
    assert report["production_parser_changed"] is False


def test_composite_type_cannot_be_inferred_from_meeting_id_prefix(tmp_path):
    # OR looks like a physical meeting, but the original manifest alone
    # is authoritative for source-declared composite/physical separation.
    result = _audit(_source_index(), _archive(tmp_path, meeting_type=True))
    assert result["status"] == "ORIGINAL_PDF_COHORT_SOURCE_ONLY_VERIFIED"
    assert result["typed_composite_product_pdf_programs"] == 1
    assert result["typed_physical_meeting_pdf_programs"] == 0
    assert result["independent_complete_day_denominator_verified"] is False


def test_untyped_meeting_is_not_silently_accepted_as_physical(tmp_path):
    result = _audit(_source_index(), _archive(tmp_path, meeting_type=None))
    assert result["pdf_hashes_verified"] == 1
    assert result["meeting_type_unverified_pdf_programs"] == 1
    assert result["typed_physical_meeting_pdf_programs"] == 0
    assert result["c1_14day_coverage_eligible"] is False

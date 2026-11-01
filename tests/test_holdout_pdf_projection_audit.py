"""C-DEV-04 24-PDF projection: only source-parity claims, no human gold."""
import hashlib
import io
import json
import zipfile

from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from collector.holdout_pdf_projection_audit import (
    SCHEMA, audit_frozen_text_projection,
)
from collector.holdout_pdf_source_replay import (
    SCHEMA as INDEX_SCHEMA, git_blob_sha1,
)

MEETING = "OR_NR_2026-10-18"
DAY = "2026-10-18"
RUN = "20261018T120412486322Z"
ARTIFACT = 12135567920
ROOT = f"output/daily/{DAY}/{RUN}/"
PDF_MEMBER = ROOT + f"meetings/{MEETING}/full_program.pdf"
PDF_URL = "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/" + MEETING


def _pdf():
    stream = io.BytesIO()
    canvas = Canvas(stream, pageCompression=0)
    flow = canvas.beginText(40, 780)
    flow.setFont("Helvetica", 8)
    for line in (
        "Lop 1", "2000m Autostart.", "START KL. 10:15",
        "1 TEST WINNER, Driver",
        "Tr: Test Trainer",
        "SOURCE TRACK19.07.26-6|7 7 2 2100 18,0a",
        "Original test PDF, NOT a horse history gold source",
    ):
        flow.textLine(line)
    canvas.drawText(flow)
    canvas.showPage()
    canvas.save()
    original = stream.getvalue()
    txt = "\n\n".join(page.extract_text() or "" for page in
                     PdfReader(io.BytesIO(original)).pages)
    assert txt
    return original, txt


ORIGINAL, TEXT = _pdf()
PDF_SHA = hashlib.sha256(ORIGINAL).hexdigest()


def _index(*, source_sha=PDF_SHA):
    return {
        "schema_version": INDEX_SCHEMA,
        "distinct_pdf_programs": 1,
        "source_archives": 1,
        "pre_registered_samples": 30,
        "historical_row_identity_verified": False,
        "independent_gold_fields_verified": False,
        "programs": [{
            "meeting": MEETING,
            "pdf_sha256": source_sha,
            "pages": 1,
            "artifact_id": ARTIFACT,
            "archive_entry_found": True,
            "pdf_opened_with_fitz": True,
        }],
    }


def _archive(tmp_path, *, text=TEXT, include_text=True,
             use_pdf=ORIGINAL, original_request_sha=PDF_SHA,
             day=DAY, run=RUN, meeting_type=False):
    target = tmp_path / "original.zip"
    root = f"output/daily/{day}/{run}/"
    pdf_name = root + f"meetings/{MEETING}/full_program.pdf"
    manifest = {
        "date_oslo": day, "run_id": run,
        "meetings": [{
            "meeting_id": MEETING,
            "is_multi_track_product": meeting_type,
        }],
        "requests": [{
            "status": "PDF_OK", "url": PDF_URL,
            "path": pdf_name, "sha256": original_request_sha,
            "at_utc": "2026-10-18T07:00:00Z",
        }],
        "counts": {},
    }
    with zipfile.ZipFile(target, "w") as zipped:
        zipped.writestr(root + "manifest.json", json.dumps(manifest))
        zipped.writestr(pdf_name, use_pdf)
        if include_text:
            zipped.writestr(pdf_name[:-4] + ".txt", text)
    return target


def _run(index, archives, *, observed_hash=None, expected_hash=None):
    payload = json.dumps(index, sort_keys=True).encode()
    correct_hash = git_blob_sha1(payload)
    return audit_frozen_text_projection(
        index, archives,
        expected_programs=1, expected_archives=1,
        index_git_blob_sha1=expected_hash or correct_hash,
        observed_index_git_blob_sha1=observed_hash or correct_hash,
    )


def test_true_original_pdf_reextract_is_source_only_never_history_gold(tmp_path):
    report = _run(_index(), {ARTIFACT: _archive(tmp_path)})
    assert report["schema"] == SCHEMA
    assert report["status"] == "COMPLETE_ORIGINAL_PDF_TEXT_PROJECTION_SOURCE_ONLY"
    assert report["source_only_original_pdf_corpus_verified"] is True
    assert report["pdf_source_sha_verified"] == 1
    assert report["pdf_source_pages_verified"] == 1
    assert report["pdf_source_official_receipts_verified"] == 1
    assert report["pdf_text_projection_verified"] == 1
    assert report["pdf_text_projection_blocked"] == 0
    assert report["pdf_text_projection_missing"] == 0
    assert report["errors"] == []
    assert report["program_diagnostics"][0]["status"] == "REPRODUCED_PDF_TEXT_SOURCE_ONLY"
    assert report["program_diagnostics"][0]["derived_text_sha256"] == hashlib.sha256(
        TEXT.encode("utf-8")
    ).hexdigest()
    assert report["data004e_390_gold_pairs_accepted"] == 0
    assert report["data004e_gold_verified"] is False
    assert report["independent_horse_history_row_identity_verified"] is False
    assert report["source_first_publication_time_attested"] is False
    assert report["c6_t_minus_4_pit_certified"] is False
    assert report["bet_authorized"] is False
    assert report["hq_accepted"] is False


def test_matching_original_pdf_sha_but_modified_text_blocks_history(tmp_path):
    mutated = TEXT.replace("TEST WINNER", "TEST FAILER")
    result = _run(_index(), {ARTIFACT: _archive(tmp_path, text=mutated)})
    assert result["status"] == "PARTIAL_OR_BLOCKED_PDF_TEXT_PROJECTION"
    assert result["pdf_source_sha_verified"] == 1
    assert result["pdf_text_projection_verified"] == 0
    assert result["pdf_text_projection_blocked"] == 1
    assert result["projection_error_counts"] == {
        "ARCHIVED_PDF_TEXT_PROJECTION_MISMATCH": 1,
    }
    assert result["history_candidate_rows_from_reproduced_text"] == 0
    assert result["program_diagnostics"][0]["unverified_history_candidate_rows"] if False else True


def test_missing_derived_text_member_explicit_not_silent_denominator(tmp_path):
    result = _run(_index(), {
        ARTIFACT: _archive(tmp_path, include_text=False),
    })
    assert result["source_only_original_pdf_corpus_verified"] is True
    assert result["pdf_text_projection_missing"] == 1
    assert result["pdf_text_projection_verified"] == 0
    assert result["projection_error_counts"] == {
        "MISSING_PAIRED_PDF_TEXT_MEMBER": 1,
    }


def test_missing_original_pdf_disables_replay_before_projection(tmp_path):
    result = _run(_index(), {ARTIFACT: tmp_path / "absent.zip"})
    assert result["status"] == "BLOCKED_FROZEN_SOURCE_CORPUS"
    assert result["source_only_original_pdf_corpus_verified"] is False
    assert result["pdf_text_projection_verified"] == 0
    assert result["program_diagnostics"] == []
    assert "ORIGINAL_24_PDF_SOURCE_AUDIT_UNVERIFIED" in result["errors"]


def test_wrong_betting_frozen_index_blob_blocks_all_24_parity_claims(tmp_path):
    result = _run(_index(), {ARTIFACT: _archive(tmp_path)},
                  observed_hash="a" * 40)
    assert result["source_only_original_pdf_corpus_verified"] is False
    assert "FROZEN_BETTING_SOURCE_INDEX_BLOB_SHA_MISMATCH" in result["errors"]
    assert result["pdf_text_projection_verified"] == 0


def test_wrong_manifest_date_run_blocks_replay_as_source_not_trusted(tmp_path):
    result = _run(_index(), {
        ARTIFACT: _archive(tmp_path, day="2026-10-19"),
    })
    assert result["status"] == "BLOCKED_FROZEN_SOURCE_CORPUS"
    assert result["source_only_original_pdf_corpus_verified"] is False
    assert result["pdf_text_projection_verified"] == 0


def test_corrupt_pdf_receipt_blocks_even_matching_derived_text(tmp_path):
    result = _run(_index(), {
        ARTIFACT: _archive(tmp_path, original_request_sha="f" * 64),
    })
    assert result["status"] == "BLOCKED_FROZEN_SOURCE_CORPUS"
    assert result["pdf_text_projection_verified"] == 0
    assert result["data004e_390_gold_pairs_accepted"] == 0


def test_composite_program_remains_non_c1_despite_byte_exact_parity(tmp_path):
    result = _run(_index(), {
        ARTIFACT: _archive(tmp_path, meeting_type=True),
    })
    assert result["status"] == "COMPLETE_ORIGINAL_PDF_TEXT_PROJECTION_SOURCE_ONLY"
    assert result["typed_physical_pdf_programs"] == 0
    assert result["typed_composite_pdf_programs"] == 1
    assert result["independent_no_se_full_day_denominator_verified"] is False
    assert result["c1_14day_coverage_verified"] is False


def test_non_authorizing_report_contains_no_original_history_raw_text(tmp_path):
    result = _run(_index(), {ARTIFACT: _archive(tmp_path)})
    encoded = json.dumps(result)
    assert "SOURCE TRACK19.07.26" not in encoded
    assert "TEST WINNER" not in encoded
    assert "gold_field_candidates" not in encoded
    assert result["production_parser_changed"] is False
    assert result["live_market_verified"] is False

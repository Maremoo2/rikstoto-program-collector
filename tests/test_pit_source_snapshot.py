"""C6 original PDF receipt time vs parsed start: never actual PIT."""
import hashlib
import io
import json
import zipfile

import pytest
from reportlab.pdfgen.canvas import Canvas

from collector.pit_source_snapshot import (
    SCHEMA, _pdf_clock_utc, _utc_receipt, audit_original_pdf_capture_tminus4,
)

DAY = "2026-11-01"
RUN = "20261101T061900000000Z"
MO = "MO_NR_" + DAY
X1 = "X1_NR_" + DAY
ROOT = f"output/daily/{DAY}/{RUN}/"
SOURCE_URL = "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/"
RAW_EXCERPT = (
    "Lop 1\n"
    "2000 m Autostart\n"
    "Lop 1\n"
    "START KL. 12:00\n"
    "1 TEST HORSE, Test Driver\n"
    "Tr: Test Trainer\n"
    "SOURCE TRACK19.07.26-6|7 7 2 2100 18,0a\n"
    "Momarken 01.11.2026 Utvidet - rikstoto.no Side: 1 av 1\n"
)


def _pdf():
    stream = io.BytesIO()
    pdf = Canvas(stream, pageCompression=0)
    block = pdf.beginText(40, 760)
    block.setFont("Helvetica", 8)
    for line in RAW_EXCERPT.splitlines():
        block.textLine(line)
    pdf.drawText(block)
    pdf.showPage()
    pdf.save()
    return stream.getvalue()


PDF = _pdf()
SHA = hashlib.sha256(PDF).hexdigest()


def _write_archive(tmp_path, *, at="2026-11-01T06:20:00+00:00",
                   pdf_data=PDF, pdf_sha=SHA, text=None,
                   missing_text=False, source_day=DAY, composite=False,
                   pdf_number_source_ok=True):
    archive_path = tmp_path / "source.zip"
    dirname = f"output/daily/{source_day}/{RUN}/"
    pdf_path = dirname + f"meetings/{MO}/full_program.pdf"
    from pypdf import PdfReader
    expected = "\n\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_data)).pages
    )
    if not pdf_number_source_ok:
        # Edited TXT won't match source PDF: tests must never silently pass.
        expected = expected.replace("Lop 1", "Unknown", 1)
    if text is not None:
        expected = text
    no_typed = {"meeting_id": MO, "country": "NO", "sport_type": "T",
                "is_multi_track": False, "track": "Momarken"}
    x_typed = {"meeting_id": X1, "country": "SE", "sport_type": "T",
               "is_multi_track": True, "track": "Composite"}
    manifest = {
        "date_oslo": source_day, "run_id": RUN,
        "calendar_source_diagnostic": {"status": "EMPTY_RESULT_ARRAY"},
        "automatically_discovered_meetings": [MO, X1],
        "manually_seeded_meetings": [],
        "homepage_spa_racedays": {
            "api_path": "/api/racedays",
            "meetings": {MO: no_typed, X1: x_typed},
        },
        "public_racedays_api": {MO: no_typed, X1: x_typed},
        "calendar_racedays": {},
        "meetings": [{
            "meeting_id": MO, "is_multi_track_product": composite,
            "program_pdf": "PDF_TEXT_OK",
            "pdf_race_numbers": [1],
            "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT"},
        }, {
            "meeting_id": X1, "is_multi_track_product": True,
            "program_pdf": "PDF_TEXT_OK",
        }],
        "requests": [{
            "url": SOURCE_URL + MO,
            "status": "PDF_OK", "path": pdf_path,
            "sha256": pdf_sha, "at_utc": at,
        }],
        "counts": {},
    }
    with zipfile.ZipFile(archive_path, "w") as z:
        z.writestr(dirname + "manifest.json", json.dumps(manifest))
        z.writestr(pdf_path, pdf_data)
        if not missing_text:
            z.writestr(pdf_path[:-4] + ".txt", expected.encode("utf-8"))
    return archive_path


def test_original_pdf_replay_never_promotes_early_capture_to_actual_pit(tmp_path):
    source = _write_archive(tmp_path)
    result = audit_original_pdf_capture_tminus4(source)
    assert result["schema"] == SCHEMA
    assert result["status"] == "SOURCE_CAPTURE_TIMING_DIAGNOSTIC_ONLY"
    assert result["source_candidate_meetings"] == 1
    assert result["excluded_composite_products"] == [X1]
    assert result["candidate_pdf_receipts_sha_verified"] == 1
    assert result["pdf_text_projection_reproduced"] == 1
    assert len(result["races"]) == 1
    one = result["races"][0]
    assert one["race_number"] == 1
    assert one["pdf_race_number_source"] == "pdf_heading_number"
    assert one["status"] == "PDF_CAPTURE_EARLIER_THAN_UNVERIFIED_TMINUS4"
    assert result["observed_pdf_capture_before_unverified_clock_tminus4"] == 1
    assert one["pit_certified"] is False
    assert result["source_first_publication_time_attested"] is False
    assert result["independent_race_start_time_verified"] is False
    assert result["independent_full_day_no_se_denominator_verified"] is False
    assert result["prospective_tminus4_snapshot_attested"] is False
    assert result["c6_pit_certified"] is False
    assert result["bet_authorized"] is False
    assert result["hq_accepted"] is False
    assert result["production_mutation"] is False


def test_late_observation_is_a_source_clock_warning_not_a_backdated_receipt(tmp_path):
    result = audit_original_pdf_capture_tminus4(
        _write_archive(tmp_path, at="2026-11-01T11:00:00Z"))
    assert result["observed_pdf_capture_after_unverified_clock_tminus4"] == 1
    assert result["observed_pdf_capture_before_unverified_clock_tminus4"] == 0
    assert result["races"][0]["status"] == "PDF_CAPTURE_AFTER_UNVERIFIED_TMINUS4"
    assert result["c6_pit_certified"] is False


@pytest.mark.parametrize("at", [
    "2026-11-01T06:20:00", None, "2026-11-01T07:20:00+01:00",
    "2026-13-01T06:20:00Z",
])
def test_bad_original_receipt_observation_clock_blocks_meeting(tmp_path, at):
    result = audit_original_pdf_capture_tminus4(_write_archive(tmp_path, at=at))
    assert result["status"] == "BLOCKED_ORIGINAL_SOURCE_TIMING"
    assert result["candidate_pdf_receipts_sha_verified"] == 0
    assert any("ORIGINAL_PDF_RECEIPT_OR_TIME_UNVERIFIED" in error
               for error in result["meeting_issues"])
    assert result["c6_pit_certified"] is False


def test_text_tampering_with_valid_original_pdf_sha_blocks(tmp_path):
    result = audit_original_pdf_capture_tminus4(
        _write_archive(tmp_path, text="tampered valid-looking horse rows"))
    assert result["status"] == "BLOCKED_ORIGINAL_SOURCE_TIMING"
    assert result["candidate_pdf_receipts_sha_verified"] == 1
    assert result["pdf_text_projection_reproduced"] == 0
    assert any("PDF_TEXT_PROJECTION_UNVERIFIED" in error
               for error in result["meeting_issues"])
    assert result["observed_pdf_capture_before_unverified_clock_tminus4"] == 0


def test_original_pdf_sha_wrong_blocks_without_t_minus_4_claim(tmp_path):
    result = audit_original_pdf_capture_tminus4(
        _write_archive(tmp_path, pdf_sha="0" * 64))
    assert result["status"] == "BLOCKED_ORIGINAL_SOURCE_TIMING"
    assert result["source_archive_integrity_errors"] != []
    assert result["source_candidate_meetings"] == 0
    assert result["c6_pit_certified"] is False


def test_missing_derived_text_blocks_and_preserves_archive(tmp_path):
    path = _write_archive(tmp_path, missing_text=True)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = audit_original_pdf_capture_tminus4(path)
    assert result["status"] == "BLOCKED_ORIGINAL_SOURCE_TIMING"
    assert result["pdf_text_projection_reproduced"] == 0
    assert result["c6_pit_certified"] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_composite_never_becomes_pit_race_or_independent_calendar(tmp_path):
    result = audit_original_pdf_capture_tminus4(
        _write_archive(tmp_path, composite=True))
    assert result["source_candidate_meetings"] == 1
    assert result["status"] == "BLOCKED_ORIGINAL_SOURCE_TIMING"
    assert result["c6_pit_certified"] is False
    assert result["independent_full_day_no_se_denominator_verified"] is False


@pytest.mark.parametrize("day,clock,error", [
    ("2026-11-01", "00:00", "START_TIME_UNVERIFIED_MIDNIGHT"),
    ("2026-11-01", "99:00", "START_TIME_INVALID"),
    ("2026-10-25", "02:30", "AMBIGUOUS_DST_RACE_CLOCK"),
    ("2026-03-29", "02:30", "NONEXISTENT_DST_RACE_CLOCK"),
])
def test_unverified_or_dst_race_clock_cannot_be_backdated(day, clock, error):
    stamp, blocker = _pdf_clock_utc(day, clock)
    assert stamp is None
    assert blocker == error


def test_source_receipts_must_have_explicit_utc_offsets():
    assert _utc_receipt("2026-11-01T06:20:00Z") is not None
    assert _utc_receipt("2026-11-01T06:20:00+00:00") is not None
    assert _utc_receipt("2026-11-01T07:20:00+01:00") is None
    assert _utc_receipt("2026-11-01T06:20:00") is None


def test_missing_original_zip_cannot_be_a_zero_races_success(tmp_path):
    r = audit_original_pdf_capture_tminus4(tmp_path / "no-such-source.zip")
    assert r["status"] == "BLOCKED_ORIGINAL_SOURCE_TIMING"
    assert r["source_candidate_races"] == 0
    assert r["c6_pit_certified"] is False

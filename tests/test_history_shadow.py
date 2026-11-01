"""C-DEV-04 strict shadow-only source history diagnostics, no 390-cell gold."""
import hashlib
import io
import json
import zipfile

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from collector.history_shadow import (
    HISTORY_GOLD_FIELDS, SCHEMA, build_history_shadow,
    replay_original_archive,
)

DAY = "2026-10-27"
MEETING = "F2_NR_" + DAY
ARCHIVE_SHA = "a" * 64
EXCERPT = """Løp 1
2000m Autostart.
START KL. 11:05
1 REMCO VL, Onderwater Kevin
Tr: J. Bergmann
OPPOLI SARAD9519.07.26-6|7 7 2 2100 18,0a 36.8
OPPOLI SARAD9509.08.26-4|2 2 2 2100 17,3a 8.9
2 NADYHA, Will Ben
Tr: M. Schonlau
SCHONLAU MARCGEL99.99.26-5|1 1 1 2000 16,9a
Gelsenkirchen 27.10.2026 Utvidet - rikstoto.no Side: 1 av 1
"""


def _make_original_pdf_fixture():
    """Synthetic but genuine PDF with deterministic extractable UTF-8 text."""
    stream = io.BytesIO()
    writer = Canvas(stream, pageCompression=0)
    writer.setTitle("CDEV04 synthetic original source integrity fixture")
    flow = writer.beginText(40, 780)
    flow.setFont("Helvetica", 8)
    for line in EXCERPT.splitlines():
        flow.textLine(line)
    writer.drawText(flow)
    writer.showPage()
    writer.save()
    content = stream.getvalue()
    assert "\n\n".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages
    ) == EXCERPT
    return content


PDF = _make_original_pdf_fixture()
PDF_SHA = hashlib.sha256(PDF).hexdigest()


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _shadow(raw=EXCERPT):
    return build_history_shadow(
        raw, meeting_id=MEETING, racing_date=DAY,
        source_archive_sha256=ARCHIVE_SHA, source_pdf_sha256=PDF_SHA,
        pdf_text_sha256=_hash(raw),
    )


def _archive(tmp_path, raw=EXCERPT, *, two_pdfs=False, no_text=False):
    path = tmp_path / "original.zip"
    pdf_member = f"output/daily/{DAY}/run/meetings/{MEETING}/full_program.pdf"
    with zipfile.ZipFile(path, "w") as out:
        out.writestr(f"output/daily/{DAY}/run/manifest.json",
                     json.dumps({"date_oslo": DAY, "run_id": "run"}))
        out.writestr(pdf_member, PDF)
        if two_pdfs:
            out.writestr(f"{DAY}/run/meetings/{MEETING}/full_program.pdf", PDF)
        if not no_text:
            out.writestr(pdf_member[:-4] + ".txt", raw.encode("utf-8"))
    return path


def test_source_history_candidates_reuse_original_parser_and_preserve_raw():
    report = _shadow()
    assert report["schema"] == SCHEMA
    assert report["pdf_race_sections"] == 1
    assert report["history_source_rows_indexed"] == 3
    assert report["source_row_diagnostics"] == {
        "SOURCE_ROW_CANDIDATE_NOT_GOLD": 2,
        "INVALID_HISTORY_DATE_ABSTAIN": 1,
    }
    first, second, invalid = report["history_rows"]
    assert first["source"]["horse_name"] == "REMCO VL"
    assert first["source"]["horse_program_number"] == 1
    assert first["source"]["history_ordinal_within_horse"] == 1
    assert first["source"]["raw_text"].startswith("OPPOLI SARAD95")
    assert first["source_tokens_not_gold"]["post_after_pipe"] == 7
    assert first["source_tokens_not_gold"]["distance_tokens_after_pipe"] == [2100]
    assert first["gold_field_candidates"]["date"] == {
        "status": "SOURCE_EXTRACTED_UNVERIFIED", "value": "2026-07-19",
    }
    assert first["gold_field_candidates"]["race_number"] == {
        "status": "SOURCE_EXTRACTED_UNVERIFIED", "value": 6,
    }
    assert invalid["status"] == "INVALID_HISTORY_DATE_ABSTAIN"
    assert invalid["gold_field_candidates"]["date"]["value"] is None
    assert second["source"]["horse_name"] == "REMCO VL"
    assert invalid["source"]["horse_name"] == "NADYHA"


def test_exact_13_fields_are_research_only_and_gallop_dq_never_inferred_false():
    report = _shadow()
    assert HISTORY_GOLD_FIELDS == (
        "date", "track", "race_number", "distance", "start_method",
        "result_category", "placing", "km_time", "driver", "shoes",
        "wagon", "gallop", "dq",
    )
    for row in report["history_rows"]:
        fields = row["gold_field_candidates"]
        assert set(fields) == set(HISTORY_GOLD_FIELDS)
        assert all(record["status"] != "VERIFIED_GOLD" for record in fields.values())
        for col in ("gallop", "dq", "placing", "km_time", "shoes", "wagon"):
            assert fields[col] == {
                "status": "ABSTAIN_INDEPENDENT_GOLD_PENDING", "value": None,
            }
        assert row["source_publication_time_attested"] is False
        assert row["pit_certified"] is False
    assert report["data004e_holdout_390_accepted"] == 0
    assert report["data004e_holdout_verified"] is False
    assert report["independent_gold_field_pairs_accepted"] == 0
    assert report["production_parser_approved"] is False
    assert report["production_parser_changed"] is False
    assert report["bet_authorized"] is False


def test_original_pdf_sha_and_raw_text_in_zip_are_checked_before_parse(tmp_path):
    p = _archive(tmp_path)
    report = replay_original_archive(
        p, meeting_id=MEETING, date_oslo=DAY, expected_pdf_sha256=PDF_SHA,
    )
    assert report["source_bytes_sha256_verified"] is True
    assert report["source_archive_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert report["history_source_rows_indexed"] == 3
    assert report["source_members"]["original_pdf"].endswith(
        f"/meetings/{MEETING}/full_program.pdf")
    assert report["source_scope"].startswith("IMMUTABLE_ARCHIVED_PDF_BYTES")
    assert report["pdf_text_projection_reproduced_from_original_pdf"] is True
    assert report["pdf_extraction_page_count"] == 1
    assert report["pdf_text_reextracted_sha256"] == _hash(EXCERPT)
    assert report["pdf_text_projection_extractor"].startswith("pypdf ")
    assert report["independent_original_page_visual_review"] is False
    assert all(not row["source_text_projection_is_official_pdf_attested"]
               for row in report["history_rows"])


@pytest.mark.parametrize("bad_sha", ["0" * 64, "invalid", ""])
def test_wrong_expected_pdf_sha_is_rejected(tmp_path, bad_sha):
    with pytest.raises(ValueError):
        replay_original_archive(
            _archive(tmp_path), meeting_id=MEETING,
            date_oslo=DAY, expected_pdf_sha256=bad_sha,
        )


def test_missing_original_pdf_text_companion_is_blocked(tmp_path):
    with pytest.raises(ValueError, match="Missing paired PDF text"):
        replay_original_archive(
            _archive(tmp_path, no_text=True),
            meeting_id=MEETING, date_oslo=DAY, expected_pdf_sha256=PDF_SHA,
        )


def test_duplicate_archive_original_pdf_is_blocked(tmp_path):
    with pytest.raises(ValueError, match="duplicate or foreign-capture PDF"):
        replay_original_archive(
            _archive(tmp_path, two_pdfs=True),
            meeting_id=MEETING, date_oslo=DAY, expected_pdf_sha256=PDF_SHA,
        )


def test_wrong_date_meeting_or_text_sha_is_not_accepted():
    with pytest.raises(ValueError):
        build_history_shadow(
            EXCERPT, meeting_id=MEETING, racing_date="2026-10-28",
            source_archive_sha256=ARCHIVE_SHA,
            source_pdf_sha256=PDF_SHA, pdf_text_sha256=_hash(EXCERPT),
        )
    with pytest.raises(ValueError, match="Derived PDF text SHA"):
        build_history_shadow(
            EXCERPT, meeting_id=MEETING, racing_date=DAY,
            source_archive_sha256=ARCHIVE_SHA,
            source_pdf_sha256=PDF_SHA, pdf_text_sha256="b" * 64,
        )


def test_future_dated_history_is_abstained_not_backdated():
    text = EXCERPT.replace("19.07.26-6|", "19.11.26-6|")
    report = _shadow(text)
    assert report["history_rows"][0]["status"] == "HISTORY_DATE_AFTER_RACEDAY_ABSTAIN"
    assert report["history_rows"][0]["gold_field_candidates"]["date"]["value"] == "2026-11-19"
    assert report["pit_certified"] is False


def test_rows_with_no_valid_history_are_not_invented():
    text = EXCERPT.replace("19.07.26-6|", "NO VALID DATE|")
    text = text.replace("09.08.26-4|", "NO VALID DATE|")
    text = text.replace("99.99.26-5|", "NO VALID DATE|")
    report = _shadow(text)
    assert report["pdf_horse_headers"] == 2
    assert report["history_source_rows_indexed"] == 0


def test_histories_do_not_become_user_visible_bets_or_prospective_pit():
    result = _shadow()
    assert result["parse_status"] == "REVIEW_REQUIRED"
    assert result["source_publication_time_attested"] is False
    assert result["pit_certified"] is False
    assert result["production_parser_changed"] is False
    assert result["bet_authorized"] is False


def test_manifest_wrong_date_or_capture_root_rejects_hashed_pdf(tmp_path):
    path = _archive(tmp_path)
    with zipfile.ZipFile(path) as z:
        items = {name: z.read(name) for name in z.namelist()}
    manifest = f"output/daily/{DAY}/run/manifest.json"
    payload = json.loads(items[manifest])
    payload["date_oslo"] = "2026-10-28"
    items[manifest] = json.dumps(payload).encode("utf-8")
    with zipfile.ZipFile(path, "w") as z:
        for name, body in items.items():
            z.writestr(name, body)
    with pytest.raises(ValueError, match="manifest day/run mismatch"):
        replay_original_archive(
            path, meeting_id=MEETING, date_oslo=DAY,
            expected_pdf_sha256=PDF_SHA,
        )


def test_cross_capture_pdf_cannot_borrow_valid_sha(tmp_path):
    path = _archive(tmp_path)
    with zipfile.ZipFile(path) as z:
        items = {name: z.read(name) for name in z.namelist()}
    pdf_member = f"output/daily/{DAY}/run/meetings/{MEETING}/full_program.pdf"
    original = items.pop(pdf_member)
    items[f"output/daily/{DAY}/other-run/meetings/{MEETING}/full_program.pdf"] = original
    with zipfile.ZipFile(path, "w") as z:
        for name, body in items.items():
            z.writestr(name, body)
    with pytest.raises(ValueError, match="foreign-capture PDF"):
        replay_original_archive(
            path, meeting_id=MEETING, date_oslo=DAY,
            expected_pdf_sha256=PDF_SHA,
        )


def test_missing_archived_manifest_cannot_attest_pdf(tmp_path):
    path = _archive(tmp_path)
    with zipfile.ZipFile(path) as z:
        items = {name: z.read(name) for name in z.namelist()
                 if not name.endswith("/manifest.json")}
    with zipfile.ZipFile(path, "w") as z:
        for name, body in items.items():
            z.writestr(name, body)
    with pytest.raises(ValueError, match="source archive manifest"):
        replay_original_archive(
            path, meeting_id=MEETING, date_oslo=DAY,
            expected_pdf_sha256=PDF_SHA,
        )


def test_tampered_derived_text_with_original_pdf_unchanged_is_blocked(tmp_path):
    # PDF SHA is still the pinned valid original; only TXT content was changed.
    path = _archive(tmp_path, raw=EXCERPT.replace("REMCO VL", "REMCO XX"))
    with pytest.raises(ValueError, match="ARCHIVED_PDF_TEXT_PROJECTION_MISMATCH"):
        replay_original_archive(
            path, meeting_id=MEETING, date_oslo=DAY, expected_pdf_sha256=PDF_SHA,
        )


def test_archived_txt_reordered_history_without_pdf_change_is_blocked(tmp_path):
    # Substituting a valid-looking history line is not a source projection.
    mutated = EXCERPT.replace("19.07.26-6|", "19.08.26-6|")
    path = _archive(tmp_path, raw=mutated)
    with pytest.raises(ValueError, match="ARCHIVED_PDF_TEXT_PROJECTION_MISMATCH"):
        replay_original_archive(
            path, meeting_id=MEETING, date_oslo=DAY, expected_pdf_sha256=PDF_SHA,
        )


def test_reproduction_does_not_upgrade_history_to_gold_or_pit(tmp_path):
    report = replay_original_archive(
        _archive(tmp_path), meeting_id=MEETING, date_oslo=DAY,
        expected_pdf_sha256=PDF_SHA,
    )
    assert report["pdf_text_projection_reproduced_from_original_pdf"] is True
    assert report["data004e_holdout_390_accepted"] == 0
    assert report["independent_gold_field_pairs_accepted"] == 0
    assert report["data004e_holdout_verified"] is False
    assert report["source_publication_time_attested"] is False
    assert report["pit_certified"] is False
    assert report["bet_authorized"] is False

"""Diagnostic quality counters only, never independent full-day/PIT proof."""
from collector.source_quality import summarize_source_quality


def _race(meeting="BJ_NR_2026-10-31", number=2, clock="17:50",
          provenance="pdf_heading", horses=2):
    return {"race": {"meeting_id": meeting, "race_number": number,
                     "race_number_source": provenance,
                     "scheduled_time_local": clock},
            "entrants": [{} for _ in range(horses)]}


def _manifest():
    return {
        "calendar_source_diagnostic": {"status": "EMPTY_RESULT_ARRAY"},
        "meetings": [
            {"meeting_id": "BJ_NR_2026-10-31",
             "is_multi_track_product": False,
             "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT"}},
            {"meeting_id": "X1_NR_2026-10-31",
             "is_multi_track_product": True},
        ],
        "requests": [
            {"status": "PDF_OK"},
            {"status": "JSON_OK"},
            {"status": "JSON_OK", "raw_path": "starts.raw.json",
             "raw_readback_verified": True},
            {"status": "JSON_OK", "raw_path": "wrong.raw.json",
             "raw_readback_verified": False},
        ],
    }


def test_separate_physical_candidates_from_composite_and_pit():
    m = _manifest()
    races = [_race(number=1, clock="00:00"),
             _race(number=2, clock="25:90", provenance="pdf_order_inferred"),
             _race(number=2),
             _race(meeting="X1_NR_2026-10-31"),
             _race(meeting="MISSING_NR_2026-10-31")]
    result = summarize_source_quality(m, races)
    assert result["physical_meetings_observed"] == 1
    assert result["composite_meeting_refs"] == 1
    assert result["physical_race_candidate_rows"] == 3
    assert result["distinct_physical_race_keys"] == 2
    assert result["duplicate_physical_race_keys"] == 1
    assert result["unmapped_or_composite_race_rows"] == 2
    assert result["physical_race_clock_unverified_midnight"] == 1
    assert result["physical_race_clock_missing_or_invalid"] == 1
    assert result["physical_race_number_inferred"] == 1
    assert result["physical_horse_rows"] == 6
    assert result["physical_races_with_reconciled_meeting_snapshot"] == 3
    assert result["calendar_diagnostic_status"] == "EMPTY_RESULT_ARRAY"
    assert result["full_day_denominator_independently_verified"] is False
    assert result["source_publication_time_attested"] is False
    assert result["pit_certified"] is False


def test_json_raw_proof_counts_separate_pre_fix_and_corrupt_readback():
    r = summarize_source_quality(_manifest(), [])
    assert r["json_raw_receipts_verified"] == 1
    assert r["json_raw_receipts_legacy_unverifiable"] == 1
    assert r["json_raw_receipts_missing_verification"] == 1
    assert r["pdf_source_receipts"] == 1


def test_empty_or_incomplete_manifest_never_invents_coverage():
    r = summarize_source_quality({"meetings": [], "requests": []}, [])
    assert r["physical_meetings_observed"] == 0
    assert r["distinct_physical_race_keys"] == 0
    assert r["pit_certified"] is False
    assert r["calendar_diagnostic_status"] == "UNKNOWN"


def test_unknown_meeting_type_and_unknown_source_flags_are_not_physical():
    manifest = {"meetings": [{"meeting_id": "A_NR_2026-10-31"}],
                "requests": []}
    result = summarize_source_quality(manifest, [_race("A_NR_2026-10-31")])
    assert result["meeting_type_unknown"] == 1
    assert result["unmapped_or_composite_race_rows"] == 1
    assert result["physical_race_candidate_rows"] == 0
    assert result["source_scope"] == "CAPTURED_PHYSICAL_CANDIDATES_ONLY"


def test_missing_or_invalid_clock_and_unknown_pdf_number_are_counted():
    r = summarize_source_quality(_manifest(), [
        _race(number=1, clock=None, provenance=None),
        _race(number=2, clock="invalid", provenance="untrusted")])
    assert r["physical_race_clock_missing_or_invalid"] == 2
    assert r["physical_race_number_unknown"] == 2
    assert r["physical_race_number_inferred"] == 0


def test_bad_race_meeting_id_and_null_audit_never_crash_or_approve():
    manifest = _manifest()
    manifest["meetings"][0]["startlist_pdf_audit"] = None
    bad_race = _race()
    bad_race["race"]["meeting_id"] = ["BJ_NR_2026-10-31"]
    result = summarize_source_quality(manifest, [bad_race, _race()])
    assert result["unmapped_or_composite_race_rows"] == 1
    assert result["physical_race_candidate_rows"] == 1
    assert result["physical_races_with_reconciled_meeting_snapshot"] == 0
    assert result["pit_certified"] is False

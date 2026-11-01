"""C6 multi-capture timing: source revisions are NOT approved PIT."""
from pathlib import Path

from collector.pit_revision_chain import (
    SCHEMA, compare_source_captures,
)

DAY = "2026-11-01"
T4 = "2026-11-01T18:00:00+00:00"


def _capture(run, archive_hash, time, pdf_hash, *, key=1, clock=T4,
             status="SOURCE_CAPTURE_TIMING_DIAGNOSTIC_ONLY", day=DAY):
    return {
        "status": status, "source_day": day,
        "source_run_id": run, "original_archive_sha256": archive_hash,
        "races": [{
            "meeting_id": "MO_NR_" + DAY, "race_number": key,
            "pdf_receipt_observed_at_utc": time,
            "pdf_tminus4_utc_unverified": clock,
            "source_pdf_sha256": pdf_hash,
        }],
        "c6_pit_certified": False,
    }


def _run(monkeypatch, records):
    def probe(path):
        return records[path.name]
    monkeypatch.setattr(
        "collector.pit_revision_chain.audit_original_pdf_capture_tminus4",
        probe,
    )
    return compare_source_captures(
        [Path(x) for x in records], day=DAY)


def test_two_original_captures_reveal_pdf_revision_near_t4_but_never_pit(monkeypatch):
    report = _run(monkeypatch, {
        "first": _capture("r1", "sha-a", "2026-11-01T17:55:00+00:00", "pdf1"),
        "second": _capture("r2", "sha-b", "2026-11-01T17:59:30+00:00", "pdf2"),
        "third": _capture("r3", "sha-c", "2026-11-01T18:00:30+00:00", "pdf2"),
    })
    assert report["schema"] == SCHEMA
    assert report["status"] == "SOURCE_REVISION_SEQUENCE_DIAGNOSTIC_ONLY"
    assert report["valid_archives"] == 3
    assert report["races_observed"] == 1
    assert report["races_in_every_capture"] == 1
    assert report["source_pdf_revisions_observed"] == 1
    assert report["races_with_capture_near_pdf_tminus4"] == 1
    assert report["races_bracketing_pdf_tminus4"] == 1
    assert report["race_timelines"][0]["source_capture_count"] == 3
    assert report["independent_start_time_verified"] is False
    assert report["first_publication_time_attested"] is False
    assert report["tminus4_pit_certified"] is False
    assert report["bet_authorized"] is False
    assert report["hq_accepted"] is False


def test_one_old_morning_capture_cannot_establish_t4_source_history(monkeypatch):
    report = _run(monkeypatch, {
        "morning": _capture("r1", "sha-a", "2026-11-01T06:19:00+00:00", "pdf1"),
    })
    assert report["status"] == "BLOCKED_INSUFFICIENT_SOURCE_CAPTURES"
    assert report["races_with_capture_near_pdf_tminus4"] == 0
    assert report["tminus4_pit_certified"] is False


def test_same_original_zip_repeated_with_different_input_path_is_blocked(monkeypatch):
    report = _run(monkeypatch, {
        "first": _capture("r1", "sha-a", "2026-11-01T06:19:00+00:00", "pdf1"),
        "second": _capture("r1", "sha-a", "2026-11-01T06:19:00+00:00", "pdf1"),
    })
    assert report["status"] == "BLOCKED_INVALID_SOURCE_SEQUENCE"
    assert "DUPLICATE_CAPTURE_IDENTITY:1" in report["errors"]


def test_changed_original_pdf_start_clock_prevents_t4_bracket_claim(monkeypatch):
    report = _run(monkeypatch, {
        "first": _capture("r1", "sha-a", "2026-11-01T17:59:00+00:00", "pdf1"),
        "second": _capture("r2", "sha-b", "2026-11-01T18:00:30+00:00",
                           "pdf2", clock="2026-11-01T18:20:00+00:00"),
    })
    assert report["start_clock_changes_observed"] == 1
    assert report["races_bracketing_pdf_tminus4"] == 0
    assert report["races_with_capture_near_pdf_tminus4"] == 0
    assert report["tminus4_pit_certified"] is False


def test_missing_race_from_later_capture_blocks_complete_source_sequence(monkeypatch):
    report = _run(monkeypatch, {
        "first": _capture("r1", "sha-a", "2026-11-01T17:59:00+00:00", "pdf1"),
        "second": _capture("r2", "sha-b", "2026-11-01T18:00:30+00:00", "pdf2",
                           key=2),
    })
    assert report["status"] == "BLOCKED_INCOMPLETE_CAPTURE_SEQUENCE"
    assert report["races_in_every_capture"] == 0
    assert report["races_observed"] == 2
    assert report["tminus4_pit_certified"] is False


def test_foreign_day_and_unverified_capture_are_not_valid_source_lineage(monkeypatch):
    report = _run(monkeypatch, {
        "first": _capture("r1", "sha-a", "2026-11-01T06:19:00+00:00",
                          "pdf1", day="2026-11-02"),
        "second": _capture("r2", "sha-b", "2026-11-01T07:19:00+00:00",
                           "pdf2", status="BLOCKED_ORIGINAL_SOURCE_TIMING"),
    })
    assert report["status"] == "BLOCKED_INVALID_SOURCE_SEQUENCE"
    assert len(report["errors"]) == 2
    assert report["valid_archives"] == 0


def test_non_utc_observation_and_duplicate_race_key_fail_closed(monkeypatch):
    report = _run(monkeypatch, {
        "first": _capture("r1", "sha-a", "2026-11-01T18:00:00", "pdf1"),
    })
    assert report["status"] == "BLOCKED_INVALID_SOURCE_SEQUENCE"
    assert "INVALID_RACE_IDENTITY_OR_CLOCK:0" in report["errors"]


def test_requested_empty_series_is_blocked_without_fake_no_races():
    report = compare_source_captures([], day=DAY)
    assert report["status"] == "BLOCKED_INSUFFICIENT_SOURCE_CAPTURES"
    assert report["errors"] == ["INVALID_CAPTURE_COUNT"]
    assert report["tminus4_pit_certified"] is False

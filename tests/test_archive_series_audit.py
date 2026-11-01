"""Offline negative tests for original collector longitudinal archive receipts."""
import hashlib
import json
import zipfile
from datetime import date, timedelta

import pytest

from collector.archive_series_audit import audit_series


def _archive(tmp_path, day, *, legacy=False, tamper=False):
    run = day.replace("-", "") + "T060000000000Z"
    prefix = f"output/daily/{day}/{run}/"
    target = tmp_path / (day + ".zip")
    raw = b'{"result":[],"success":true}'
    wrapper = json.dumps({
        "source_url": "https://www.rikstoto.no/api/racedays",
        "fetched_utc": day + "T06:00:00+00:00",
        "response": json.loads(raw),
    }).encode()
    pdf = b"%PDF-1.4\noriginal source"
    requests = [
        {"status": "JSON_OK", "sha256": hashlib.sha256(raw).hexdigest(),
         "path": prefix + "calendar.json"},
        {"status": "PDF_OK", "sha256": hashlib.sha256(pdf).hexdigest(),
         "path": prefix + "meetings/TEST/full_program.pdf"},
    ]
    if not legacy:
        requests[0].update({
            "raw_path": prefix + "calendar.raw.json",
            "wrapper_sha256": hashlib.sha256(wrapper).hexdigest(),
            "raw_readback_verified": True,
        })
    manifest = {
        "date_oslo": day, "run_id": run, "requests": requests,
        "meetings": [{"meeting_id": "TEST", "is_multi_track_product": False}],
        "counts": {"unique_track_races": 1, "unique_track_horses": 2},
        "status": "CAPTURED_UNVERIFIED", "completeness_verified": False,
    }
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(prefix + "manifest.json", json.dumps(manifest))
        archive.writestr(prefix + "calendar.json", wrapper)
        archive.writestr(prefix + "meetings/TEST/full_program.pdf",
                         pdf if not tamper else b"wrong pdf")
        if not legacy:
            archive.writestr(prefix + "calendar.raw.json", raw)
    return target


def _days(start, n):
    first = date.fromisoformat(start)
    return [(first + timedelta(days=i)).isoformat() for i in range(n)]


def test_fourteen_consecutive_original_source_days_are_raw_only(tmp_path):
    days = _days("2026-11-01", 14)
    archives = [_archive(tmp_path, day) for day in days]
    report = audit_series(archives, start_date=days[0], end_date=days[-1])
    assert report["status"] == "RAW_RECEIPTS_WINDOW_PASS_NO_DAY_OR_PIT_CERTIFICATION"
    assert report["unique_source_days"] == 14
    assert report["days_with_verified_successful_raw_receipts"] == 14
    assert report["missing_source_days"] == []
    assert report["independent_whole_day_denominator_proven"] is False
    assert report["prospective_pit_certified"] is False
    assert report["operational_14_day_completion_certified"] is False
    assert report["model_training_or_bet_authority"] is False


def test_four_observed_days_with_two_gaps_do_not_make_a_six_day_series(tmp_path):
    days = _days("2026-10-27", 6)
    observed = [days[i] for i in (0, 2, 4, 5)]
    report = audit_series([_archive(tmp_path, day) for day in observed],
                          start_date=days[0], end_date=days[-1])
    assert report["status"] == "INSUFFICIENT_PREDECLARED_WINDOW"
    assert report["unique_source_days"] == 4
    assert report["missing_source_days"] == [days[1], days[3]]


def test_fourteen_day_gap_is_not_silent_noop(tmp_path):
    days = _days("2026-11-01", 14)
    report = audit_series([_archive(tmp_path, day) for day in days[:-1]],
                          start_date=days[0], end_date=days[-1])
    assert report["status"] == "MISSING_SOURCE_DAYS"
    assert report["missing_source_days"] == [days[-1]]


def test_legacy_and_undamaged_bytes_never_merge_into_full_raw_pass(tmp_path):
    days = _days("2026-11-01", 14)
    archives = [_archive(tmp_path, day, legacy=(i == 3))
                for i, day in enumerate(days)]
    report = audit_series(archives, start_date=days[0], end_date=days[-1])
    assert report["status"] == "RAW_SOURCE_EVIDENCE_INCOMPLETE"
    assert report["days_with_verified_successful_raw_receipts"] == 13
    assert report["by_day"][days[3]]["unrecoverable_legacy_json"] == 1


def test_corrupt_original_pdf_blocks_entire_series(tmp_path):
    days = _days("2026-11-01", 14)
    archives = [_archive(tmp_path, day, tamper=(i == 0))
                for i, day in enumerate(days)]
    report = audit_series(archives, start_date=days[0], end_date=days[-1])
    assert report["status"] == "INVALID_ARCHIVE_SERIES"
    assert "INVALID_OR_UNREADABLE_SOURCE_ARTIFACT:0" in report["archive_errors"]


def test_duplicate_day_and_unrelated_day_fail_closed(tmp_path):
    days = _days("2026-11-01", 14)
    archives = [_archive(tmp_path, day) for day in days]
    r = audit_series(archives + [archives[0]],
                     start_date=days[0], end_date=days[-1])
    assert r["status"] == "INVALID_ARCHIVE_SERIES"
    assert "DUPLICATE_SOURCE_DAY:" + days[0] in r["archive_errors"]
    outside = _archive(tmp_path, "2026-10-30")
    r = audit_series([outside] + archives,
                     start_date=days[0], end_date=days[-1])
    assert r["status"] == "INVALID_ARCHIVE_SERIES"
    assert "OUTSIDE_PREDECLARED_WINDOW:2026-10-30" in r["archive_errors"]


@pytest.mark.parametrize("start,end,minimum", [
    ("2026-11-02", "2026-11-01", 14),
    ("2026-11-01", "2026-11-01", 0),
    ("2026-11-01", "2026-11-01", True),
    ("2026-11-01", "2026-11-01", -1),
    ("2026-11-01", "2026-11-01", 1.5),
])
def test_invalid_window_is_rejected(start, end, minimum):
    with pytest.raises(ValueError):
        audit_series([], start_date=start, end_date=end, minimum_days=minimum)

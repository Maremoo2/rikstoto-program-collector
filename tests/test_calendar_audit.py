"""Regression tests grounded in observed calendar response structure."""
import pytest

from collector.calendar_audit import calendar_window, calendar_racedays, diagnose_calendar_response


def test_upper_bound_exclusive_for_single_day():
    assert calendar_window("2026-10-18") == ("2026-10-18", "2026-10-19")
    assert calendar_window("2026-12-31") == ("2026-12-31", "2027-01-01")


def test_calendar_reads_only_target_day_and_actual_keys():
    response = {"result": [
        {"raceDayKey": "OR_NR_2026-10-18", "raceDayName": "Varig Orkla",
         "countryIsoCode": "NO", "sportType": "T", "isMultiTrack": False,
         "races": [{"raceNumber": 1}, {"raceNumber": 2}, {"raceNumber": 2}]},
        {"raceDayKey": "X1_NR_2026-10-18", "raceDayName": "Orkla/Årjäng",
         "isMultiTrack": True, "races": [{"raceNumber": 1}, {"raceNumber": 2}]},
        {"raceDayKey": "MO_NR_2026-10-17", "races": [{"raceNumber": 1}]},
        {"raceDayKey": "bad-domain-2026-10-18", "races": [{"raceNumber": 1}]},
    ]}
    result = calendar_racedays(response, "2026-10-18")
    assert sorted(result) == ["OR_NR_2026-10-18", "X1_NR_2026-10-18"]
    assert result["OR_NR_2026-10-18"]["race_numbers"] == [1, 2]
    assert result["OR_NR_2026-10-18"]["track"] == "Varig Orkla"
    assert result["X1_NR_2026-10-18"]["is_multi_track"] is True


def test_unknown_calendar_schema_never_claims_empty_day():
    assert calendar_racedays({"result": {"foo": "bar"}}, "2026-10-18") == {}
    assert calendar_racedays({"success": False}, "2026-10-18") == {}


@pytest.mark.parametrize("response,expected_status,rows,target,invalid", [
    (None, "SOURCE_UNAVAILABLE", 0, 0, 0),
    ({"success": False, "result": []}, "SOURCE_REPORTED_FAILURE", 0, 0, 0),
    ({"success": True, "result": {"not": "a list"}}, "SCHEMA_UNRECOGNIZED", 0, 0, 0),
    ({"success": True, "result": []}, "EMPTY_RESULT_ARRAY", 0, 0, 0),
    ({"success": True, "result": [
        {"raceDayKey": "BT_NR_2026-10-28"}]}, "NO_TARGET_DAY_ENTRIES", 1, 0, 0),
    ({"success": True, "result": [
        {"raceDayKey": "BT_NR_2026-10-29"}]}, "TARGET_DAY_ENTRIES_PRESENT", 1, 1, 0),
    ({"success": True, "result": [
        {"notRaceDayKey": "BT_NR_2026-10-29"}]}, "ROW_SCHEMA_UNRECOGNIZED", 1, 0, 1),
    ({"success": True, "result": [
        {"raceDayKey": "BT_NR_2026-10-29"},
        {"notRaceDayKey": "?"}]}, "ROW_SCHEMA_UNRECOGNIZED", 2, 1, 1),
])
def test_diagnose_calendar_response_fail_closed(
        response, expected_status, rows, target, invalid):
    diagnosis = diagnose_calendar_response(response, "2026-10-29")
    assert diagnosis["status"] == expected_status
    assert diagnosis["rows_seen"] == rows
    assert diagnosis["target_day_rows"] == target
    assert diagnosis["invalid_rows"] == invalid
    assert diagnosis["date_coverage_verified"] is False


def test_empty_date_api_does_not_erase_independent_discovery():
    # Archived 2026-10-29 date API returned success=true, result=[] while
    # the normal racedays API and homepage observed target-day meetings.
    date_api = {"result": [], "success": True, "errorCode": None, "message": None}
    normal_api = {"result": [{"raceDayKey": "BT_NR_2026-10-29",
                               "races": [{"raceNumber": 1}]}], "success": True}
    assert diagnose_calendar_response(date_api, "2026-10-29")["status"] == "EMPTY_RESULT_ARRAY"
    assert calendar_racedays(date_api, "2026-10-29") == {}
    assert calendar_racedays(normal_api, "2026-10-29")["BT_NR_2026-10-29"]["race_numbers"] == [1]
    assert diagnose_calendar_response(normal_api, "2026-10-29")["date_coverage_verified"] is False


def test_source_reported_failure_never_yields_authoritative_calendar_entries():
    response = {"success": False, "result": [
        {"raceDayKey": "BT_NR_2026-10-29", "races": [{"raceNumber": 1}]}]}
    assert calendar_racedays(response, "2026-10-29") == {}


def test_duplicate_official_raceday_key_is_ambiguous_not_last_wins():
    source = {"success": True, "result": [
        {"raceDayKey": "BT_NR_2026-10-29", "raceDayName": "Bjerke",
         "races": [{"raceNumber": 1}]},
        {"raceDayKey": "BT_NR_2026-10-29", "raceDayName": "Another venue",
         "races": [{"raceNumber": 1}, {"raceNumber": 2}]},
        {"raceDayKey": "OR_NR_2026-10-29", "raceDayName": "Varig Orkla",
         "races": [{"raceNumber": 1}]},
    ]}
    entries = calendar_racedays(source, "2026-10-29")
    assert "BT_NR_2026-10-29" not in entries
    assert entries["OR_NR_2026-10-29"]["race_numbers"] == [1]
    diagnostic = diagnose_calendar_response(source, "2026-10-29")
    assert diagnostic["status"] == "DUPLICATE_TARGET_DAY_KEYS"
    assert diagnostic["duplicate_target_keys"] == 1
    assert diagnostic["date_coverage_verified"] is False


def test_identical_duplicate_official_key_still_not_a_second_race():
    row = {"raceDayKey": "BT_NR_2026-10-29", "races": [{"raceNumber": 1}]}
    response = {"success": True, "result": [row, dict(row)]}
    assert calendar_racedays(response, "2026-10-29") == {}
    assert diagnose_calendar_response(response, "2026-10-29")["duplicate_target_keys"] == 1


def test_duplicate_different_day_does_not_block_target_day():
    response = {"result": [
        {"raceDayKey": "BT_NR_2026-10-28", "races": []},
        {"raceDayKey": "BT_NR_2026-10-28", "races": []},
        {"raceDayKey": "BT_NR_2026-10-29", "races": [{"raceNumber": 1}]},
    ]}
    assert len(calendar_racedays(response, "2026-10-29")) == 1
    assert diagnose_calendar_response(response, "2026-10-29")["duplicate_target_keys"] == 0

"""Regression tests grounded in observed calendar response structure."""
import pytest

from collector.calendar_audit import calendar_window, calendar_racedays


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

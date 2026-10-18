"""Pure offline regression coverage for the scheduled day collector."""
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from collector.daily import meeting_ids, race_numbers, scratch_signals, oslo_date


def test_extract_only_actual_ids_on_selected_date():
    sample = {"racedays": [
        {"id": "OR_NR_2026-10-18", "date": "2026-10-18"},
        {"id": "SO_SE_2026-10-18", "date": "2026-10-18"},
        {"id": "BK_NR_2026-10-17", "date": "2026-10-17"},
    ]}
    assert meeting_ids(sample, "2026-10-18") == [
        "OR_NR_2026-10-18", "SO_SE_2026-10-18"]


def test_ignores_date_strings_without_meeting_identifiers():
    assert meeting_ids({"dates": ["2026-10-18", "2026-10-19"]}, "2026-10-18") == []


def test_numbers_only_explicit_race_number_fields():
    data = {"races": [{"raceNumber": 6, "horses": [{"horseNumber": 11}]},
                      {"raceNo": "7", "horses": [{"number": 5}]},
                      {"raceNumber": 40}]}
    assert race_numbers(data) == [6, 7]


def test_positive_scratch_with_named_horse_and_race():
    data = {"races": [
        {"raceNumber": 6, "starts": [
            {"startNumber": 2, "horseName": "Lesja Loke", "isScratched": True},
            {"startNumber": 3, "horseName": "Test Horse", "isScratched": False}]}]}
    result = scratch_signals(data)
    assert result["explicit_status_fields_seen"] == 2
    assert result["positive_scratches"] == [{
        "race_number": 6, "horse_number": 2, "horse_name": "Lesja Loke",
        "source_path": "$.races[0].starts[0]", "evidence": {"isScratched": True}}]


def test_absent_scratch_schema_is_unknown_not_zero_certainty():
    result = scratch_signals({"races": [{"raceNumber": 1, "starts": [
        {"horseNumber": 1, "horseName": "A"}]}]})
    assert result["positive_scratches"] == []
    assert result["explicit_status_fields_seen"] == 0
    assert "UNKNOWN" in result["interpretation"]


def test_declared_scratches_list():
    result = scratch_signals({"races": [{"raceNumber": 2, "scratches": [
        {"horseNumber": 8, "horseName": "Some Horse"}]}]})
    assert result["positive_scratches"][0]["horse_number"] == 8


def test_norwegian_date_timezone_from_utc():
    winter = datetime(2026, 1, 17, 23, 40, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 17, 22, 40, tzinfo=timezone.utc)
    oslo = ZoneInfo("Europe/Oslo")
    assert winter.astimezone(oslo).date().isoformat() == "2026-01-18"
    assert summer.astimezone(oslo).date().isoformat() == "2026-07-18"

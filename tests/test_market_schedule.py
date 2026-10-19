from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from collector.market_schedule import plan_market_checks

OSLO = ZoneInfo("Europe/Oslo")


def meeting():
    return [{"meeting_id": "S2_NR_2026-10-19",
             "races": [{"race_number": 8, "start_utc": "2026-10-19T18:56:00Z"},
                       {"race_number": 9, "start_utc": "2026-10-19T19:15:00Z"}]}]


def test_meeting_30_minutes_before_first_race():
    now = datetime(2026, 10, 19, 20, 20, tzinfo=OSLO)
    result = plan_market_checks(meeting(), now=now)
    assert [(e["check"], e["race_number"]) for e in result["events"]] == [("MEETING_T_MINUS_30", None)]
    assert not result["odds_captured"] and not result["bet_authorized"]


def test_per_race_checks():
    now = datetime(2026, 10, 19, 20, 45, tzinfo=OSLO)
    result = plan_market_checks(meeting(), now=now)
    assert ("RACE_T_MINUS_10", 8) in [(e["check"], e["race_number"]) for e in result["events"]]
    now = datetime(2026, 10, 19, 20, 51, tzinfo=OSLO)
    result = plan_market_checks(meeting(), now=now)
    assert ("RACE_T_MINUS_3", 8) in [(e["check"], e["race_number"]) for e in result["events"]]


def test_no_retroactive_prestart_checks():
    now = datetime(2026, 10, 19, 21, 30, tzinfo=OSLO)
    assert plan_market_checks(meeting(), now=now)["events"] == []


def test_missing_race_times_fail_closed():
    result = plan_market_checks([{"meeting_id": "X", "races": [{"race_number": 1}]}],
                                now=datetime(2026, 10, 19, 19, 0, tzinfo=OSLO))
    assert not result["events"]
    assert "X:INVALID_RACE_TIME_OR_NUMBER" in result["warnings"]


def test_dst_offset_aware():
    m = [{"meeting_id": "TEST", "races": [{"race_number": 1, "start_utc": "2026-10-25T11:00:00Z"}]}]
    now = datetime(2026, 10, 25, 11, 21, tzinfo=OSLO)
    result = plan_market_checks(m, now=now)
    assert result["events"][0]["target_oslo"] == "2026-10-25T11:30:00+01:00"


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        plan_market_checks(meeting(), now=datetime(2026, 10, 19, 20, 0))

from datetime import datetime, timezone, timedelta
from collector.market_schedule import plan_awatch_market_checks

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
START = (NOW + timedelta(minutes=13)).isoformat()

def race(n, score=70, gates=True, status="A-WATCH"):
    return {"race_number": n, "start_utc": START, "prewatch_score": score,
            "prewatch_gates_passed": gates, "prewatch_status": status}

def test_only_qualified_awatch_is_scheduled():
    out = plan_awatch_market_checks([{"meeting_id": "MEET",
        "races": [race(1), race(2, 69), race(3, 90, False),
                  race(4, 90, True, "WATCH")]}], now=NOW)
    assert out["selected_race_count"] == 1
    assert len(out["rejected"]) == 3
    assert out["prewatch_requires_win_odds"] is False
    assert out["bet_authorized"] is False
    assert all(e["race_number"] in (1, None) for e in out["events"])

def test_missing_qualification_never_schedules():
    out = plan_awatch_market_checks([{"meeting_id": "MEET",
        "races": [{"race_number": 1, "start_utc": START}]}], now=NOW)
    assert out["events"] == []
    assert out["selected_race_count"] == 0

def test_boolean_score_does_not_qualify():
    out = plan_awatch_market_checks([{"meeting_id": "MEET",
        "races": [race(1, True)]}], now=NOW)
    assert out["events"] == []

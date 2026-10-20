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


def test_win_collector_selects_only_qualified_and_no_request_for_rejected():
    from collector.awatch_win_collector import eligible_race_urls
    meetings = [{"meeting_id": "S2_NR_2026-10-20",
                 "races": [race(1, 70), race(2, 69), race(3, 90, False),
                           race(4, 90, True, "WATCH")]}]
    plan, urls = eligible_race_urls(meetings, now=NOW)
    assert list(urls) == [("S2_NR_2026-10-20", 1)]
    assert plan["bet_authorized"] is False


def test_win_collector_never_probes_without_awatch():
    import asyncio
    from unittest.mock import patch
    from collector.awatch_win_collector import collect
    with patch("collector.awatch_win_collector.probe") as fake:
        result = asyncio.run(collect([{"meeting_id": "M",
            "races": [race(1, 69)]}], now=NOW))
        fake.assert_not_called()
    assert result["probed_race_count"] == 0
    assert result["bet_authorized"] is False


def test_win_collector_qualified_probes_but_never_authorizes():
    import asyncio
    from unittest.mock import AsyncMock, patch
    from collector.awatch_win_collector import collect
    with patch("collector.awatch_win_collector.probe",
               new_callable=AsyncMock) as fake:
        fake.return_value = {"status": "DIAGNOSTIC_CAPTURED", "bet_authorized": False}
        result = asyncio.run(collect([{"meeting_id": "S2_NR_2026-10-20",
            "races": [race(7, 75)]}], now=NOW))
        fake.assert_awaited_once()
    assert result["probed_race_count"] == 1
    assert result["bet_authorized"] is False


def test_win_collector_missing_score_never_probes():
    import asyncio
    from unittest.mock import patch
    from collector.awatch_win_collector import collect
    with patch("collector.awatch_win_collector.probe") as fake:
        result = asyncio.run(collect([{"meeting_id": "M",
            "races": [{"race_number": 1, "start_utc": START,
                       "prewatch_status": "A-WATCH",
                       "prewatch_gates_passed": True}]}], now=NOW))
        fake.assert_not_called()
    assert result["probed_race_count"] == 0


def test_win_collector_past_race_never_probes():
    import asyncio
    from unittest.mock import patch
    from collector.awatch_win_collector import collect
    old = race(1, 90)
    old["start_utc"] = (NOW - timedelta(minutes=20)).isoformat()
    with patch("collector.awatch_win_collector.probe") as fake:
        result = asyncio.run(collect([{"meeting_id": "M",
            "races": [old]}], now=NOW))
        fake.assert_not_called()
    assert result["probed_race_count"] == 0


def test_end_to_end_phase_b_selection_mixed_races():
    import asyncio
    from unittest.mock import AsyncMock, patch
    from collector.awatch_win_collector import collect
    sample = [{"meeting_id": "S2_NR_2026-10-20",
               "races": [race(1, 70), race(2, 69), race(3, 95, False),
                         race(4, 88, True, "PASS")]}]
    with patch("collector.awatch_win_collector.probe",
               new_callable=AsyncMock) as fake:
        fake.return_value = {"status": "BLOCKED", "reason": "STALE_MARKET_ODDS"}
        output = asyncio.run(collect(sample, now=NOW))
        fake.assert_awaited_once()
        assert "race=1" in fake.await_args.args[0]
    assert output["probed_race_count"] == 1
    assert output["schedule"]["selected_race_count"] == 1
    assert len(output["schedule"]["rejected"]) == 3
    assert output["races"][0]["diagnostic"]["status"] == "BLOCKED"
    assert output["bet_authorized"] is False
    assert output["automated_betting"] is False

"""Tests based on 2026-10-18 public Rikstoto SPA raceDays layout."""
import json

from collector.homepage_schedule import homepage_racedays, schedule_comparison


def homepage(data, *, api_path="/api/racedays"):
    return ("<html><script>window.__spaRehydration = " +
            json.dumps({"raceDays": {"url": api_path, "data": data,
                                     "expiration": "2026-10-18T13:00:00+02:00"}}) +
            ";\n</script></html>")


def test_hydration_discovers_all_actual_meeting_keys():
    rows = [{"raceDayKey": "OR_NR_2026-10-18", "raceDayName": "Varig Orkla",
             "isMultiTrack": False,
             "races": [{"raceNumber": 1}, {"raceNumber": 2}]},
            {"raceDayKey": "X1_NR_2026-10-18", "raceDayName": "Orkla/Årjäng",
             "isMultiTrack": True, "races": [{"raceNumber": 1}]},
            {"raceDayKey": "S1_NR_2026-10-19", "raceDayName": "Other day",
             "isMultiTrack": False, "races": [{"raceNumber": 1}]}]
    result = homepage_racedays(homepage(rows), "2026-10-18")
    assert result["status"] == "DATE_MATCHES_PRESENT"
    assert set(result["meetings"]) == {"OR_NR_2026-10-18", "X1_NR_2026-10-18"}
    assert result["meetings"]["X1_NR_2026-10-18"]["is_multi_track"] is True
    assert result["api_path"] == "/api/racedays"
    assert result["race_counts_are_complete"] is False


def test_first_party_endpoint_must_match_observed_whitelist():
    data = [{"raceDayKey": "OR_NR_2026-10-18", "races": [{"raceNumber": 1}]}]
    result = homepage_racedays(homepage(data, api_path="//other.example/api/racedays"),
                               "2026-10-18")
    assert result["api_path"] is None


def test_invalid_json_fails_closed():
    assert homepage_racedays("<script>window.__spaRehydration = {invalid;</script>",
                             "2026-10-18")["status"] == "INVALID_REHYDRATION_JSON"


def test_missing_marker_has_no_discovered_entries():
    result = homepage_racedays("<html>no embedded schedule</html>", "2026-10-18")
    assert not result["meetings"]
    assert result["status"] == "NOT_PRESENT"


def test_cross_source_comparison_never_falsely_certifies_all_tracks():
    home = {"meetings": {"OR_NR_2026-10-18": {}, "S1_NR_2026-10-18": {}}}
    ids = set(home["meetings"])
    result = schedule_comparison(ids, home, {x: {} for x in ids}, {})
    assert result["status"] == "CROSS_SOURCE_AGREEMENT"
    assert result["completeness_certified"] is False
    missing = schedule_comparison({"OR_NR_2026-10-18"}, home, {}, {})
    assert missing["missing_from_collector"] == ["S1_NR_2026-10-18"]
    assert missing["status"] == "MISSING_OR_DISAGREEMENT"

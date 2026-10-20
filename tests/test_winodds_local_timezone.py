from collector.winodds_adapter import parse_public_winodds


def test_explicit_oslo_time_and_no_bet():
    payload = {"success": True, "result": {"7": [
        {"startNumber": 1, "odds": 4.0, "lastUpdated": "2026-10-20T10:00:00"}]}}
    common = dict(meeting_id="TEST", race_number=7,
                  captured_utc="2026-10-20T08:01:00Z",
                  expected_runners={1: "Horse"}, scratches_verified=True)
    assert "INVALID_MARKET_TIMESTAMP" in parse_public_winodds(payload, **common)["errors"]
    result = parse_public_winodds(payload, source_timezone="Europe/Oslo", **common)
    assert result["status"] == "STRUCTURE_VALID_UNVERIFIED"
    assert result["bet_authorized"] is False


def test_stale_local_time_still_blocks():
    payload = {"success": True, "result": {"7": [
        {"startNumber": 1, "odds": 4.0, "lastUpdated": "2026-10-20T09:00:00"}]}}
    result = parse_public_winodds(payload, meeting_id="TEST", race_number=7,
        captured_utc="2026-10-20T08:01:00Z", expected_runners={1: "Horse"},
        scratches_verified=True, source_timezone="Europe/Oslo")
    assert "STALE_MARKET_ODDS" in result["errors"]

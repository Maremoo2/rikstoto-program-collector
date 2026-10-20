from collector.winodds_adapter import parse_public_winodds


def example():
    return {"success": True, "result": {"2": [
        {"startNumber": 4, "odds": 3.5, "lastUpdated": "2026-10-20T08:00:00Z"},
        {"startNumber": 7, "odds": 5.2, "lastUpdated": "2026-10-20T08:00:00Z"}]}}


def parse(response=None, **overrides):
    params = {"meeting_id": "S2_NR_2026-10-20", "race_number": 2,
              "captured_utc": "2026-10-20T08:01:00Z",
              "expected_runners": {4: "Alpha", 7: "Bravo"},
              "scratches_verified": True}
    params.update(overrides)
    return parse_public_winodds(example() if response is None else response, **params)


def test_complete_structure_remains_unverified():
    out = parse()
    assert out["status"] == "STRUCTURE_VALID_UNVERIFIED"
    assert out["is_live"] is False and out["bet_authorized"] is False
    assert len(out["snapshot"]["runners"]) == 2


def test_missing_runner_blocked():
    assert "RUNNER_SET_MISMATCH" in parse(expected_runners={4: "Alpha", 7: "Bravo", 8: "Charlie"})["errors"]


def test_scratches_not_verified_blocked():
    assert "SCRATCHES_NOT_VERIFIED" in parse(scratches_verified=False)["errors"]


def test_bad_odds_blocked():
    raw = example()
    raw["result"]["2"][0]["odds"] = 0
    assert "INVALID_SOURCE_ODDS" in parse(raw)["errors"]


def test_bad_timestamp_blocked():
    raw = example()
    raw["result"]["2"][0]["lastUpdated"] = "not a timestamp"
    assert "INVALID_MARKET_TIMESTAMP" in parse(raw)["errors"]


def test_wrong_market_or_missing_race_blocked():
    assert parse({"success": True, "result": {"1": []}})["status"] == "BLOCKED"
    assert parse({"success": False, "result": example()["result"]})["status"] == "BLOCKED"


def test_extra_runner_blocked():
    raw = example()
    raw["result"]["2"].append({"startNumber": 9, "odds": 10.0,
                               "lastUpdated": "2026-10-20T08:00:00Z"})
    assert "UNKNOWN_OR_SCRATCHED_RUNNER" in parse(raw)["errors"]


def test_duplicate_blocked():
    raw = example()
    raw["result"]["2"].append(dict(raw["result"]["2"][0]))
    assert "INVALID_OR_DUPLICATE_NUMBER" in parse(raw)["errors"]

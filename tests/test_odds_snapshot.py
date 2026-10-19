from collector.odds_snapshot import SCHEMA, validate_win_snapshot


def sample():
    return {"schema": SCHEMA, "market": "WIN",
            "meeting_id": "S2_NR_2026-10-19", "race_number": 8,
            "captured_utc": "2026-10-19T12:00:00Z",
            "scratches_verified": True,
            "runners": [{"number": 7, "name": "Raidhour Newport", "win_odds": 6.52}]}


def test_valid_snapshot_still_not_live_or_bet():
    result = validate_win_snapshot(sample(), {7: "Raidhour Newport"})
    assert result["status"] == "SNAPSHOT_VALID"
    assert result["is_live"] is False
    assert result["bet_authorized"] is False


def test_missing_runner_fails_closed():
    result = validate_win_snapshot(sample(), {7: "Raidhour Newport", 9: "Miranda Unica"})
    assert "RUNNER_SET_MISMATCH" in result["errors"]


def test_wrong_name_fails_closed():
    result = validate_win_snapshot(sample(), {7: "Another Horse"})
    assert "RUNNER_NAME_MISMATCH" in result["errors"]


def test_missing_scratch_verification_fails_closed():
    obj = sample()
    obj["scratches_verified"] = False
    assert "SCRATCHES_NOT_VERIFIED" in validate_win_snapshot(obj, {7: "Raidhour Newport"})["errors"]


def test_missing_price_fails_closed():
    obj = sample()
    obj["runners"][0]["win_odds"] = None
    assert "INVALID_WIN_ODDS" in validate_win_snapshot(obj, {7: "Raidhour Newport"})["errors"]


def test_duplicate_runner_fails_closed():
    obj = sample()
    obj["runners"].append(dict(obj["runners"][0]))
    assert "INVALID_OR_DUPLICATE_NUMBER" in validate_win_snapshot(obj, {7: "Raidhour Newport"})["errors"]

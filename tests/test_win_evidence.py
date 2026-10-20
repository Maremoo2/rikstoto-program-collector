from collector.win_evidence import assess_win_evidence, fresh


NOW = "2026-10-20T10:00:00Z"


def sample():
    odds = {"status": "STRUCTURE_VALID_UNVERIFIED", "errors": [],
            "snapshot": {"market": "WIN", "runners": [{"number": 1, "win_odds": 3.2}]},
            "market_last_updated": [NOW]}
    starts = [{"startNumber": 1, "horseName": "Example", "isScratched": False}]
    pool = {"market": "WIN", "scope": "SINGLE_MARKET", "turnover": 1200,
            "currency": "SEK", "source": "public-operator", "captured_utc": NOW}
    return odds, starts, pool


def audit(odds=None, starts=None, pool=None, start_time=NOW):
    a, b, c = sample()
    return assess_win_evidence(a if odds is None else odds,
                               b if starts is None else starts, start_time,
                               c if pool is None else pool, NOW)


def test_all_evidence_never_authorizes_bet():
    result = audit()
    assert result["status"] == "EVIDENCE_COMPLETE_UNVERIFIED_FOR_BET"
    assert result["bet_authorized"] is False
    assert not result["errors"]


def test_combined_market_turnover_rejected():
    _, _, p = sample()
    p["scope"] = "COMBINED_MARKETS"
    result = audit(pool=p)
    assert "SEPARATE_WIN_POOL_NOT_VERIFIED" in result["errors"]
    assert result["bet_authorized"] is False


def test_missing_pool_rejected():
    result = audit(pool={})
    assert result["win_pool"] == "BLOCKED"


def test_stale_odds_rejected():
    a, _, _ = sample()
    a["market_last_updated"] = ["2026-10-20T09:50:00Z"]
    assert audit(odds=a)["odds"] == "BLOCKED"


def test_stale_starts_rejected():
    assert audit(start_time="2026-10-20T09:50:00Z")["scratches"] == "BLOCKED"


def test_unknown_scratch_flag_rejected():
    _, b, _ = sample()
    b[0]["isScratched"] = None
    assert audit(starts=b)["scratches"] == "BLOCKED"


def test_duplicate_start_numbers_rejected():
    _, b, _ = sample()
    b.append(dict(b[0]))
    assert audit(starts=b)["scratches"] == "BLOCKED"


def test_invalid_pool_numbers_rejected():
    _, _, p = sample()
    for bad in [float("nan"), float("inf"), -1, True, "1200"]:
        p["turnover"] = bad
        assert audit(pool=p)["win_pool"] == "BLOCKED"


def test_invalid_timestamps_fail_closed():
    assert not fresh("not-a-date", NOW)
    assert not fresh(NOW, "not-a-date")
    assert not fresh("2026-10-20T10:00:00", NOW)


def test_all_missing_evidence_reports_three_blockers():
    result = assess_win_evidence(None, None, None, None, NOW)
    assert len(result["errors"]) == 3
    assert result["bet_authorized"] is False

"""Adversarial source-only Phase B contract (all race/odds/pool data synthetic).

A passing example is *never* an actual BET, source validation or p(win).
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from collector.phase_b_contract import (
    SCHEMA,
    audit_synthetic_phase_b_source,
)

FIXTURE = Path(__file__).parent / "fixtures/phase_b_source_synthetic_v1.json"


@pytest.fixture()
def case() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_synthetic_happy_path_exercises_full_source_chain_but_cannot_bet(case):
    report = audit_synthetic_phase_b_source(case)
    assert report["schema"] == "phase_b_source_chain_offline_audit_v1"
    assert report["status"] == "SYNTHETIC_SOURCE_CONTRACT_COMPLETE_NOT_BET"
    assert report["phase_a_selected_in_synthetic_planner"] is True
    assert report["t_minus_3_due_in_synthetic_planner"] is True
    assert report["source_url_would_be_requested"].endswith("race=2&p=2:0")
    assert report["official_active_runner_count_fixture"] == 2
    assert report["official_scratch_count_fixture"] == 1
    assert report["win_adapter_status"] == "STRUCTURE_VALID_UNVERIFIED"
    assert report["technical_source_contract_passed_synthetic"] is True
    assert report["failed_contract_checks"] == []
    assert report["bet_authorized"] is False
    assert report["automated_betting"] is False
    assert report["BET_BLOCKED"] is True
    for key in (
        "real_A_WATCH_frozen_evidence_verified",
        "actual_source_provenance_verified",
        "real_live_WIN_pool_verified",
        "calibrated_probability_evidence_verified",
        "minimum_price_and_EV_verified",
        "full_phase_b_operationally_verified",
    ):
        assert report[key] is False


@pytest.mark.parametrize(("score", "gates", "status"), [
    (69, True, "A-WATCH"),
    (70, False, "A-WATCH"),
    (70, True, "WATCH"),
    (100.01, True, "A-WATCH"),
    (True, True, "A-WATCH"),
    (None, True, "A-WATCH"),
])
def test_phase_a_rejection_never_promotes_or_validates_win(case, score, gates, status):
    case["prewatch"].update(
        prewatch_score=score, prewatch_gates_passed=gates,
        prewatch_status=status,
    )
    report = audit_synthetic_phase_b_source(case)
    assert "NOT_QUALIFIED_FROZEN_A_WATCH" in report["failed_contract_checks"]
    assert report["win_adapter_status"] == "NOT_RUN_UNQUALIFIED_OR_UNVERIFIED_ROSTER"
    assert report["technical_source_contract_passed_synthetic"] is False
    assert report["bet_authorized"] is False


def test_phase_a_eligible_but_no_T_minus_3_due_event_is_not_ready(case):
    case["now_utc"] = "2026-10-20T11:54:00Z"
    case["win_odds"]["captured_utc"] = "2026-10-20T11:54:00Z"
    case["rendered_win_screen"]["captured_utc"] = "2026-10-20T11:54:00Z"
    report = audit_synthetic_phase_b_source(case)
    assert report["phase_a_selected_in_synthetic_planner"] is True
    assert report["t_minus_3_due_in_synthetic_planner"] is False
    assert "NO_DUE_T_MINUS_3_COLLECTION" in report["failed_contract_checks"]
    assert not report["technical_source_contract_passed_synthetic"]


def test_wrong_race_identity_is_not_accepted_as_same_market(case):
    case["win_odds"]["race_number"] = 3
    case["standalone_win_pool"]["race_number"] = 3
    report = audit_synthetic_phase_b_source(case)
    assert "WIN_ODDS_RACE_IDENTITY_MISMATCH" in report["failed_contract_checks"]
    assert "STANDALONE_WIN_POOL_RACE_IDENTITY_MISMATCH" in report["failed_contract_checks"]
    assert not report["bet_authorized"]


def test_scratches_need_explicit_official_booleans(case):
    case["official_startlist"]["runners"][2]["is_scratched"] = None
    report = audit_synthetic_phase_b_source(case)
    assert "UNVERIFIED_OR_INCOMPLETE_OFFICIAL_ROSTER" in report["failed_contract_checks"]
    assert report["win_adapter_status"] == "NOT_RUN_UNQUALIFIED_OR_UNVERIFIED_ROSTER"


def test_missing_verified_scratch_state_blocks_source(case):
    case["official_startlist"]["scratch_flags_verified"] = False
    report = audit_synthetic_phase_b_source(case)
    assert "UNVERIFIED_OR_INCOMPLETE_OFFICIAL_ROSTER" in report["failed_contract_checks"]


def test_duplicate_runner_in_official_roster_blocks(case):
    case["official_startlist"]["runners"][1]["number"] = 4
    report = audit_synthetic_phase_b_source(case)
    assert "UNVERIFIED_OR_INCOMPLETE_OFFICIAL_ROSTER" in report["failed_contract_checks"]


def test_missing_active_win_quote_never_becomes_full_field(case):
    case["win_odds"]["response"]["result"]["2"].pop()
    report = audit_synthetic_phase_b_source(case)
    assert "WIN_ADAPTER_RUNNER_SET_MISMATCH" in report["failed_contract_checks"]
    assert report["win_adapter_status"] == "BLOCKED"


def test_extra_scratched_runner_win_quote_not_accepted(case):
    case["win_odds"]["response"]["result"]["2"].append({
        "startNumber": 8, "odds": 12.5,
        "lastUpdated": "2026-10-20T11:59:45Z",
    })
    report = audit_synthetic_phase_b_source(case)
    assert "WIN_ADAPTER_UNKNOWN_OR_SCRATCHED_RUNNER" in report["failed_contract_checks"]


def test_late_quote_is_not_fresh_win(case):
    case["win_odds"]["response"]["result"]["2"][0]["lastUpdated"] = (
        "2026-10-20T11:55:00Z"
    )
    report = audit_synthetic_phase_b_source(case)
    assert "WIN_ADAPTER_STALE_MARKET_ODDS" in report["failed_contract_checks"]
    assert "WIN_PER_RUNNER_QUOTE_NOT_FRESH_PRESTART" in report["failed_contract_checks"]


def test_market_quote_postdates_own_capture_even_within_adapter_grace(case):
    case["win_odds"]["response"]["result"]["2"][0]["lastUpdated"] = (
        "2026-10-20T12:00:05Z"
    )
    report = audit_synthetic_phase_b_source(case)
    assert "WIN_QUOTE_ASOF_AFTER_CAPTURE" in report["failed_contract_checks"]
    assert not report["technical_source_contract_passed_synthetic"]


def test_same_screen_runner_set_but_wrong_price_blocks_parity(case):
    case["rendered_win_screen"]["runners"][0]["win_odds"] = 5.5
    report = audit_synthetic_phase_b_source(case)
    assert "WIN_API_SCREEN_PARITY_MISMATCH" in report["failed_contract_checks"]


def test_api_screen_timestamp_separation_blocks_parity(case):
    case["rendered_win_screen"]["captured_utc"] = "2026-10-20T11:58:15Z"
    report = audit_synthetic_phase_b_source(case)
    assert "WIN_API_SCREEN_TIMESTAMPS_NOT_COMPARABLE" in report["failed_contract_checks"]


def test_v75_or_v85_pool_is_never_standalone_win_liquidity(case):
    case["standalone_win_pool"]["market_type"] = "V75"
    report = audit_synthetic_phase_b_source(case)
    assert "V_SERIES_OR_OTHER_POOL_IS_NOT_WIN" in report["failed_contract_checks"]


def test_pool_amount_missing_is_not_inferred_from_V_pool(case):
    case["standalone_win_pool"]["amount"] = None
    report = audit_synthetic_phase_b_source(case)
    assert "STANDALONE_WIN_POOL_AMOUNT_UNKNOWN" in report["failed_contract_checks"]


def test_old_pool_asof_and_future_pool_asof_fail_closed(case):
    case["standalone_win_pool"]["asof_utc"] = "2026-10-19T11:59:45Z"
    report = audit_synthetic_phase_b_source(case)
    assert "WIN_POOL_ASOF_NOT_FRESH_PRESTART" in report["failed_contract_checks"]
    case["standalone_win_pool"]["asof_utc"] = "2026-10-20T12:01:00Z"
    report = audit_synthetic_phase_b_source(case)
    assert "WIN_POOL_CAPTURE_NOT_COMPARABLE" in report["failed_contract_checks"]


def test_poststart_observation_cannot_retroactively_qualify(case):
    case["now_utc"] = "2026-10-20T12:04:00Z"
    case["win_odds"]["captured_utc"] = "2026-10-20T12:04:00Z"
    report = audit_synthetic_phase_b_source(case)
    assert "INVALID_OR_POSTSTART_CLOCK" in report["failed_contract_checks"]
    assert report["bet_authorized"] is False


def test_naive_clock_and_wrong_dated_meeting_are_blocked(case):
    case["now_utc"] = "2026-10-20T12:00:00"
    case["meeting_id"] = "S2_NR_2026-10-21"
    report = audit_synthetic_phase_b_source(case)
    assert "INVALID_OR_POSTSTART_CLOCK" in report["failed_contract_checks"]
    assert "MEETING_DATE_MISMATCH" in report["failed_contract_checks"]


@pytest.mark.parametrize("field", ["p_win", "fair_odds", "stake_nok", "bet_authorized"])
def test_collector_cannot_be_synthetic_strategy_decision_engine(case, field):
    case[field] = 1.0
    report = audit_synthetic_phase_b_source(case)
    assert "STRATEGY_OR_BET_FIELDS_FORBIDDEN_IN_SOURCE_FIXTURE" in (
        report["failed_contract_checks"]
    )
    assert report["bet_authorized"] is False


def test_non_synthetic_input_is_rejected_before_any_source_evaluation(case):
    case["synthetic_fixture"] = False
    with pytest.raises(ValueError, match="explicitly synthetic"):
        audit_synthetic_phase_b_source(case)


def test_report_deterministic_and_does_not_mutate_source_case(case):
    frozen = copy.deepcopy(case)
    report1 = audit_synthetic_phase_b_source(case)
    report2 = audit_synthetic_phase_b_source(case)
    assert case == frozen
    assert report1 == report2
    assert len(report1["fixture_input_sha256"]) == 64


def test_offline_cli_writes_only_new_diagnostic_file(tmp_path):
    destination = tmp_path / "audit.json"
    command = [
        sys.executable, "-m", "collector.phase_b_contract",
        "--input", str(FIXTURE), "--output", str(destination),
    ]
    response = subprocess.run(command, capture_output=True, text=True, check=False)
    assert response.returncode == 0, response.stderr
    result = json.loads(destination.read_text(encoding="utf-8"))
    assert result["technical_source_contract_passed_synthetic"] is True
    assert result["bet_authorized"] is False
    assert result["full_phase_b_operationally_verified"] is False
    again = subprocess.run(command, capture_output=True, text=True, check=False)
    assert again.returncode != 0  # no silent overwrite of diagnostic evidence

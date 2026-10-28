"""Terminal receipts for the existing selective Phase B source probe.

No real betting, network, fake source verification or inferred market pool.
All scenario data are synthetic and the source probe is stubbed in memory.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from collector.awatch_win_collector import collect
from collector.phase_b_receipts import receipt_from_selective_collection

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
START = NOW + timedelta(minutes=3)
MEETING = "S2_NR_2026-10-20"


def _race(number=2, score=70, gates=True, status="A-WATCH", start=START):
    return {
        "race_number": number,
        "start_utc": start.isoformat(),
        "prewatch_score": score,
        "prewatch_gates_passed": gates,
        "prewatch_status": status,
    }


def _captured(url: str):
    return {
        "schema": "prewatch_win_source_probe_v1",
        "url": url,
        "captured_utc": NOW.isoformat(),
        "requested_race_number": 2,
        "source_capture_counts": {"winodds": 1, "official_starts": 1},
        "status": "DIAGNOSTIC_CAPTURED",
        "reason": "WIN_AUDIT_STRUCTURE_VALID_UNVERIFIED;SCREEN_MATCH",
        "win_market_verified": False,
        "bet_authorized": False,
        "win_startlist_audit": {
            "status": "STRUCTURE_VALID_UNVERIFIED",
            "errors": [],
            "runner_count": 2,
            "market_last_updated": [
                (NOW - timedelta(seconds=10)).isoformat(),
                (NOW - timedelta(seconds=20)).isoformat(),
            ],
        },
        "screen_parity": {
            "status": "MATCH",
            "api_field_complete": True,
            "matched_count": 2,
            "expected_count": 2,
        },
    }


async def _run(races, response=None, now=NOW):
    with patch("collector.awatch_win_collector.probe",
               new_callable=AsyncMock) as stub:
        stub.side_effect = (
            lambda url: _captured(url) if response is None else copy.deepcopy(response)
        )
        output = await collect(
            [{"meeting_id": MEETING, "races": races}],
            now=now, lookahead_minutes=1,
        )
        requests = stub.await_count
    return output, requests


def test_real_collector_no_qualified_a_watch_creates_explicit_terminal_noop():
    report, requests = asyncio.run(_run([_race(score=69)]))
    receipt = report["receipt"]
    assert requests == 0
    assert receipt["status"] == "NO_QUALIFIED_A_WATCH"
    assert receipt["selected_by_manual_prewatch_input"] == 0
    assert receipt["due_unique_races"] == 0
    assert receipt["probes_attempted"] == 0
    assert receipt["due_terminal_counts"] == {}
    assert receipt["BET_BLOCKED"] is True


def test_qualified_but_not_yet_due_is_not_success():
    report, requests = asyncio.run(
        _run([_race()], now=NOW - timedelta(minutes=6))
    )
    receipt = report["receipt"]
    assert requests == 0
    assert receipt["status"] == "QUALIFIED_A_WATCH_NOT_DUE"
    assert receipt["selected_by_manual_prewatch_input"] == 1
    assert receipt["due_unique_races"] == 0
    assert not receipt["complete_operational_phase_b"]


def test_full_synthetic_capture_is_source_candidate_only_never_a_bet():
    result, requests = asyncio.run(_run([_race()]))
    receipt = result["receipt"]
    assert requests == 1
    assert receipt["status"] == "SOURCE_CANDIDATES_UNVERIFIED_NOT_BET"
    assert receipt["due_terminal_counts"] == {
        "SOURCE_CANDIDATE_ONLY_UNVERIFIED": 1,
    }
    assert receipt["probes_attempted"] == 1
    assert receipt["due_races"][0]["scheduled_start_utc_derived_from_due_event"] == (
        START.isoformat()
    )
    assert receipt["due_races"][0]["blockers"] == []
    for key in (
        "manual_prewatch_score_independently_verified",
        "full_active_field_live_source_provenance_verified",
        "standalone_win_pool_source_verified",
        "calibrated_full_field_probability_verified",
        "complete_operational_phase_b", "bet_authorized",
    ):
        assert receipt[key] is False
    assert receipt["BET_BLOCKED"] is True
    assert result["bet_authorized"] is False


def test_generic_diagnostic_captured_without_full_evidence_is_not_source_candidate():
    incomplete = {"status": "DIAGNOSTIC_CAPTURED", "bet_authorized": False,
                  "win_market_verified": False}
    result, requests = asyncio.run(_run([_race()], response=incomplete))
    assert requests == 1
    receipt = result["receipt"]
    assert receipt["status"] == "DUE_SOURCE_INCOMPLETE_OR_BLOCKED"
    reasons = receipt["due_races"][0]["blockers"]
    assert "FULL_ACTIVE_FIELD_WIN_AUDIT_NOT_VALIDATED" in reasons
    assert "SCREEN_API_ALL_RUNNERS_PARITY_NOT_VERIFIED" in reasons
    assert "WIN_AND_OFFICIAL_STARTLIST_NOT_BOTH_OBSERVED" in reasons


def test_blocked_probe_does_not_count_as_full_market_capture():
    result, requests = asyncio.run(_run(
        [_race()], response={
            "status": "BLOCKED", "reason": "ROBOTS_UNVERIFIED_OR_DISALLOWED",
            "bet_authorized": False, "win_market_verified": False,
        }
    ))
    assert requests == 1
    assert result["receipt"]["status"] == "DUE_SOURCE_INCOMPLETE_OR_BLOCKED"
    assert "NO_CAPTURED_DIAGNOSTIC" in (
        result["receipt"]["due_races"][0]["blockers"]
    )


@pytest.mark.parametrize(("mutation", "code"), [
    (lambda x: x.update(requested_race_number=3), "SOURCE_RACE_NUMBER_NOT_MATCHED"),
    (lambda x: x.update(url="https://example.invalid/Spill/other"),
     "SOURCE_PAGE_URL_NOT_MATCHED"),
    (lambda x: x.update(captured_utc=(START + timedelta(seconds=1)).isoformat()),
     "CAPTURE_TIMESTAMP_NOT_VERIFIED_PRESTART"),
    (lambda x: x["win_startlist_audit"]["market_last_updated"].pop(),
     "PER_RUNNER_MARKET_TIMESTAMPS_INCOMPLETE"),
    (lambda x: x["win_startlist_audit"]["market_last_updated"].__setitem__(
        0, (NOW - timedelta(minutes=8)).isoformat()
    ), "PER_RUNNER_MARKET_TIMESTAMP_INVALID_OR_STALE"),
    (lambda x: x["screen_parity"].update(api_field_complete=False),
     "SCREEN_API_ALL_RUNNERS_PARITY_NOT_VERIFIED"),
    (lambda x: x["win_startlist_audit"].update(errors=["RUNNER_SET_MISMATCH"]),
     "FULL_ACTIVE_FIELD_WIN_AUDIT_NOT_VALIDATED"),
    (lambda x: x.update(win_market_verified=True),
     "DIAGNOSTIC_IMPROPER_LIVE_VERIFICATION"),
    (lambda x: x.update(bet_authorized=True),
     "DIAGNOSTIC_IMPROPER_BET_AUTHORIZATION"),
])
def test_malformed_or_claimed_live_probe_never_becomes_candidate(mutation, code):
    # The stub's URL is already the source URL authorized by the planner.
    from collector.awatch_win_collector import eligible_race_urls

    _, sources = eligible_race_urls(
        [{"meeting_id": MEETING, "races": [_race()]}], now=NOW, lookahead_minutes=1
    )
    response = _captured(next(iter(sources.values())))
    mutation(response)
    result, _ = asyncio.run(_run([_race()], response=response))
    assert result["receipt"]["status"] == "DUE_SOURCE_INCOMPLETE_OR_BLOCKED"
    assert code in result["receipt"]["due_races"][0]["blockers"]
    assert result["receipt"]["BET_BLOCKED"]


def test_duplicate_probe_entries_and_non_due_probe_fail_closed():
    report, _ = asyncio.run(_run([_race()]))
    duplicate = copy.deepcopy(report)
    duplicate["races"].append(copy.deepcopy(duplicate["races"][0]))
    with pytest.raises(ValueError, match="Repeated probe"):
        receipt_from_selective_collection(duplicate)
    extra = copy.deepcopy(report)
    extra["races"][0]["race_number"] = 99
    with pytest.raises(ValueError, match="does not match a due"):
        receipt_from_selective_collection(extra)


def test_due_but_source_unmapped_remains_explicit_blocked_noop():
    from collector.market_schedule import plan_awatch_market_checks

    schedule = plan_awatch_market_checks(
        [{"meeting_id": MEETING, "races": [_race()]}],
        now=NOW, lookahead_minutes=1,
    )
    envelope = {
        "phase": "B_MARKET_ONLY", "schedule": schedule,
        "races": [], "bet_authorized": False,
    }
    receipt = receipt_from_selective_collection(envelope)
    assert receipt["status"] == "DUE_BUT_NO_SOURCE_PROBE"
    assert receipt["due_terminal_counts"] == {"DUE_WITHOUT_PROBE": 1}
    assert receipt["due_races"][0]["blockers"] == ["DUE_PROBE_NOT_ATTEMPTED"]


def test_hash_reproducible_and_original_results_not_mutated():
    report, _ = asyncio.run(_run([_race()]))
    frozen = copy.deepcopy(report)
    first = receipt_from_selective_collection(report)
    second = receipt_from_selective_collection(report)
    assert first == second
    assert report == frozen
    assert len(first["diagnostic_envelope_sha256"]) == 64

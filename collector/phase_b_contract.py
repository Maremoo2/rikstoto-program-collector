"""Offline Phase B *source* contract probe; no real sources or betting.

This module deliberately reuses the existing frozen A-WATCH request planner,
public WIN odds adapter and roster validator. It NEVER collects a live page,
authorizes a model, creates p(win), changes Pre-Watch or places a wager.

The CLI requires an explicitly synthetic fixture so success can never be
misread as a completed operational Phase B or a genuine BET.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .awatch_win_collector import eligible_race_urls
from .startlist_audit import normalized_horse_name
from .winodds_adapter import parse_public_winodds

SCHEMA = "phase_b_offline_source_contract_fixture_v1"
FORBIDDEN_STRATEGY_FIELDS = frozenset({
    "p_win", "fair_odds", "locked_min_odds", "expected_value", "edge_roi",
    "stake_nok", "bet_type", "bet_authorized", "place_bet",
})
MAX_AGE_SECONDS = 180
MAX_SCREEN_SEPARATION_SECONDS = 90


def _instant(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)
    except ValueError:
        return None


def _same_race(item: Any, meeting_id: str, race_number: int) -> bool:
    return (
        isinstance(item, dict)
        and item.get("meeting_id") == meeting_id
        and type(item.get("race_number")) is int
        and item["race_number"] == race_number
    )


def _close_before_start(
    captured: datetime | None, now: datetime | None, start: datetime | None
) -> bool:
    return (
        captured is not None and now is not None and start is not None
        and captured < start and 0 <= (now - captured).total_seconds() <= MAX_AGE_SECONDS
    )


def _record_date_matches_id(meeting_id: str, start: datetime | None) -> bool:
    # Legacy IDs without ISO dates are left to the existing URL validator.
    match = re.search(r"_(\d{4}-\d{2}-\d{2})\Z", meeting_id)
    if match is None:
        return True
    return start is not None and start.date().isoformat() == match.group(1)


def audit_synthetic_phase_b_source(payload: dict[str, Any]) -> dict[str, Any]:
    """Exercise Phase A selection -> source roster -> WIN -> screen -> pool.

    `technical_source_contract_passed` means self-consistent *synthetic*
    inputs only. It is NEVER proof of a real source, model probability,
    executable price or live BET authorization.
    """
    if (not isinstance(payload, dict)
            or payload.get("schema") != SCHEMA
            or payload.get("synthetic_fixture") is not True):
        raise ValueError("Only an explicitly synthetic Phase B fixture is permitted")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    errors: set[str] = set()
    if FORBIDDEN_STRATEGY_FIELDS.intersection(payload):
        errors.add("STRATEGY_OR_BET_FIELDS_FORBIDDEN_IN_SOURCE_FIXTURE")
    now = _instant(payload.get("now_utc"))
    start = _instant(payload.get("scheduled_start_utc"))
    if now is None or start is None or not now < start:
        errors.add("INVALID_OR_POSTSTART_CLOCK")

    meeting_id = payload.get("meeting_id")
    number = payload.get("race_number")
    if not isinstance(meeting_id, str) or type(number) is not int or number <= 0:
        errors.add("INVALID_RACE_IDENTITY")
        meeting_id, number = "", -1
    if not _record_date_matches_id(meeting_id, start):
        errors.add("MEETING_DATE_MISMATCH")

    prewatch = payload.get("prewatch")
    phase_a_selected = False
    due_t_minus_3 = False
    planned_url = None
    if isinstance(prewatch, dict) and now is not None and start is not None:
        if (type(prewatch.get("race_number")) is int
                and prewatch["race_number"] == number
                and _instant(prewatch.get("start_utc")) == start):
            schedule, urls = eligible_race_urls(
                [{"meeting_id": meeting_id, "races": [prewatch]}],
                now=now, lookahead_minutes=1,
            )
            phase_a_selected = (
                schedule["selected_race_count"] == 1
                and (meeting_id, number) in urls
            )
            due_t_minus_3 = any(
                event.get("race_number") == number
                and event.get("check") == "RACE_T_MINUS_3"
                for event in schedule["events"]
            )
            planned_url = urls.get((meeting_id, number))
    if not phase_a_selected:
        errors.add("NOT_QUALIFIED_FROZEN_A_WATCH")
    if phase_a_selected and not due_t_minus_3:
        errors.add("NO_DUE_T_MINUS_3_COLLECTION")
    # Even a perfectly simulated source cannot fix a missing official
    # frozen A-WATCH proof; this checks only the syntax/gate plan.
    official = payload.get("official_startlist")
    expected: dict[int, str] = {}
    scratched = set()
    roster_ok = (
        _same_race(official, meeting_id, number)
        and official.get("scratch_flags_verified") is True
        and isinstance(official.get("runners"), list)
        and bool(official["runners"])
    )
    if roster_ok:
        for runner in official["runners"]:
            if (not isinstance(runner, dict)
                    or type(runner.get("number")) is not int
                    or runner["number"] <= 0
                    or not isinstance(runner.get("name"), str)
                    or not runner["name"].strip()
                    or type(runner.get("is_scratched")) is not bool
                    or runner["number"] in expected or runner["number"] in scratched):
                roster_ok = False
                break
            if runner["is_scratched"]:
                scratched.add(runner["number"])
            else:
                expected[runner["number"]] = runner["name"]
        if not expected:
            roster_ok = False
    if not roster_ok:
        errors.add("UNVERIFIED_OR_INCOMPLETE_OFFICIAL_ROSTER")
    roster_at = _instant(official.get("captured_utc")) if isinstance(official, dict) else None
    if not _close_before_start(roster_at, now, start):
        errors.add("ROSTER_ASOF_NOT_FRESH_PRESTART")

    odds = payload.get("win_odds")
    quote_at = _instant(odds.get("captured_utc")) if isinstance(odds, dict) else None
    if not _same_race(odds, meeting_id, number):
        errors.add("WIN_ODDS_RACE_IDENTITY_MISMATCH")
    if not _close_before_start(quote_at, now, start):
        errors.add("WIN_ODDS_CAPTURE_NOT_FRESH_PRESTART")
    adapter_status = "NOT_RUN_UNQUALIFIED_OR_UNVERIFIED_ROSTER"
    adapter_errors: list[str] = []
    adapter_runners: list[dict[str, Any]] = []
    if phase_a_selected and due_t_minus_3 and roster_ok and isinstance(odds, dict):
        response = odds.get("response")
        if isinstance(response, dict) and quote_at is not None:
            audit = parse_public_winodds(
                response, meeting_id=meeting_id, race_number=number,
                captured_utc=quote_at.isoformat(), expected_runners=expected,
                scratches_verified=True, max_market_age_seconds=MAX_AGE_SECONDS,
            )
            adapter_status = audit["status"]
            adapter_errors = list(audit.get("errors", []))
            adapter_runners = audit.get("snapshot", {}).get("runners", [])
            if adapter_status != "STRUCTURE_VALID_UNVERIFIED":
                errors.add("WIN_ADAPTER_DID_NOT_VALIDATE_FULL_FIELD")
            for stamp in audit.get("market_last_updated", []):
                stamp_at = _instant(stamp)
                if not _close_before_start(stamp_at, now, start):
                    errors.add("WIN_PER_RUNNER_QUOTE_NOT_FRESH_PRESTART")
                if stamp_at is None or quote_at is None or stamp_at > quote_at:
                    errors.add("WIN_QUOTE_ASOF_AFTER_CAPTURE")
        else:
            errors.add("MISSING_RAW_WIN_SOURCE_RESPONSE")
    if adapter_errors:
        errors.update(f"WIN_ADAPTER_{reason}" for reason in adapter_errors)

    screen = payload.get("rendered_win_screen")
    screen_at = _instant(screen.get("captured_utc")) if isinstance(screen, dict) else None
    if not _same_race(screen, meeting_id, number):
        errors.add("RENDERED_WIN_RACE_IDENTITY_MISMATCH")
    if not _close_before_start(screen_at, now, start):
        errors.add("RENDERED_WIN_SCREEN_NOT_FRESH_PRESTART")
    if (screen_at is None or quote_at is None
            or abs((screen_at - quote_at).total_seconds()) > MAX_SCREEN_SEPARATION_SECONDS):
        errors.add("WIN_API_SCREEN_TIMESTAMPS_NOT_COMPARABLE")
    screen_rows = screen.get("runners") if isinstance(screen, dict) else None
    screen_by_number: dict[int, dict[str, Any]] = {}
    if not isinstance(screen_rows, list):
        errors.add("SCREEN_WIN_RUNNERS_MISSING")
    else:
        for row in screen_rows:
            if (not isinstance(row, dict)
                    or type(row.get("number")) is not int
                    or row["number"] <= 0
                    or row["number"] in screen_by_number):
                errors.add("SCREEN_WIN_DUPLICATE_OR_INVALID_NUMBER")
                continue
            screen_by_number[row["number"]] = row
        if set(screen_by_number) != set(expected):
            errors.add("SCREEN_WIN_ACTIVE_ROSTER_MISMATCH")
        prices = {x.get("number"): x.get("win_odds") for x in adapter_runners}
        if not adapter_runners or set(prices) != set(expected):
            errors.add("WIN_API_SCREEN_PARITY_UNVERIFIED")
        else:
            for n, name in expected.items():
                display = screen_by_number.get(n, {})
                value = display.get("win_odds")
                reference = prices[n]
                if (not isinstance(display.get("name"), str)
                        or normalized_horse_name(display["name"])
                        != normalized_horse_name(name)
                        or type(value) not in (int, float)
                        or not math.isfinite(value)
                        or type(reference) not in (int, float)
                        or not math.isfinite(reference)
                        or abs(value - reference) > 0.011):
                    errors.add("WIN_API_SCREEN_PARITY_MISMATCH")

    pool = payload.get("standalone_win_pool")
    if not _same_race(pool, meeting_id, number):
        errors.add("STANDALONE_WIN_POOL_RACE_IDENTITY_MISMATCH")
    if not isinstance(pool, dict) or pool.get("market_type") != "WIN":
        errors.add("V_SERIES_OR_OTHER_POOL_IS_NOT_WIN")
    amount = pool.get("amount") if isinstance(pool, dict) else None
    if type(amount) not in (int, float) or not math.isfinite(amount) or amount <= 0:
        errors.add("STANDALONE_WIN_POOL_AMOUNT_UNKNOWN")
    pool_at = _instant(pool.get("asof_utc")) if isinstance(pool, dict) else None
    pool_capture = _instant(pool.get("captured_utc")) if isinstance(pool, dict) else None
    if not _close_before_start(pool_at, now, start):
        errors.add("WIN_POOL_ASOF_NOT_FRESH_PRESTART")
    if (not _close_before_start(pool_capture, now, start)
            or pool_at is None or pool_capture is None or pool_at > pool_capture):
        errors.add("WIN_POOL_CAPTURE_NOT_COMPARABLE")
    if not isinstance(pool, dict) or pool.get("currency") not in {"NOK", "SEK", "EUR"}:
        errors.add("WIN_POOL_CURRENCY_UNVERIFIED")

    return {
        "schema": "phase_b_source_chain_offline_audit_v1",
        "fixture_input_sha256": digest,
        "fixture_only": True,
        "status": (
            "SYNTHETIC_SOURCE_CONTRACT_COMPLETE_NOT_BET"
            if not errors else "SYNTHETIC_SOURCE_CONTRACT_BLOCKED"
        ),
        "phase_a_selected_in_synthetic_planner": phase_a_selected,
        "t_minus_3_due_in_synthetic_planner": due_t_minus_3,
        "source_url_would_be_requested": planned_url,
        "official_active_runner_count_fixture": len(expected),
        "official_scratch_count_fixture": len(scratched),
        "win_adapter_status": adapter_status,
        "win_adapter_errors": adapter_errors,
        "technical_source_contract_passed_synthetic": not errors,
        "failed_contract_checks": sorted(errors),
        "real_A_WATCH_frozen_evidence_verified": False,
        "actual_source_provenance_verified": False,
        "real_live_WIN_pool_verified": False,
        "calibrated_probability_evidence_verified": False,
        "minimum_price_and_EV_verified": False,
        "full_phase_b_operationally_verified": False,
        "bet_authorized": False,
        "automated_betting": False,
        "BET_BLOCKED": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    report = audit_synthetic_phase_b_source(data)
    with args.output.open("x", encoding="utf-8") as destination:
        destination.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Strict adapter for observed public Rikstoto WIN odds response structure.

No network calls, no betting, no inferred runner names or scratch status.
Observed response: {"result": {"1": [{"startNumber": int, "odds": float,
"lastUpdated": str}, ...]}}. Capture time is separate from market update time.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from math import isfinite
from typing import Any

from .odds_snapshot import SCHEMA, validate_win_snapshot


def parse_public_winodds(response: dict[str, Any], *, meeting_id: str,
                         race_number: int, captured_utc: str,
                         expected_runners: dict[int, str],
                         scratches_verified: bool = False,
                         max_market_age_seconds: int = 180) -> dict[str, Any]:
    """Return fail-closed audit envelope; do not infer LIVE or BET status."""
    errors: list[str] = []
    if not isinstance(response, dict) or response.get("success") is not True:
        return {"status": "BLOCKED", "errors": ["SOURCE_RESPONSE_UNVERIFIED"],
                "is_live": False, "bet_authorized": False}
    races = response.get("result")
    if not isinstance(races, dict) or type(race_number) is not int:
        return {"status": "BLOCKED", "errors": ["INVALID_RACE_MAP"],
                "is_live": False, "bet_authorized": False}
    raw = races.get(str(race_number))
    if not isinstance(raw, list) or not raw:
        return {"status": "BLOCKED", "errors": ["MISSING_RACE_ODDS"],
                "is_live": False, "bet_authorized": False}
    rows = []
    market_times = []
    parsed_market_times = []
    try:
        capture_dt = datetime.fromisoformat(captured_utc.replace("Z", "+00:00"))
        if capture_dt.tzinfo is None or capture_dt.utcoffset() != timedelta(0):
            raise ValueError("capture not UTC")
    except (ValueError, TypeError, AttributeError):
        capture_dt = None
        errors.append("INVALID_CAPTURE_TIMESTAMP")
    if type(max_market_age_seconds) is not int or max_market_age_seconds <= 0:
        errors.append("INVALID_MAX_MARKET_AGE")
    for item in raw:
        if not isinstance(item, dict):
            errors.append("INVALID_SOURCE_ROW")
            continue
        number, odd, stamp = item.get("startNumber"), item.get("odds"), item.get("lastUpdated")
        if type(number) is not int or number <= 0:
            errors.append("INVALID_SOURCE_NUMBER")
            continue
        if type(odd) not in (float, int) or not isfinite(odd) or odd <= 1:
            errors.append("INVALID_SOURCE_ODDS")
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("naive timestamp")
            market_times.append(dt.isoformat())
            parsed_market_times.append(dt)
            if capture_dt is not None:
                age = (capture_dt - dt).total_seconds()
                if age < -30:
                    errors.append("MARKET_TIMESTAMP_IN_FUTURE")
                elif age > max_market_age_seconds:
                    errors.append("STALE_MARKET_ODDS")
        except (ValueError, TypeError, AttributeError):
            errors.append("INVALID_MARKET_TIMESTAMP")
        if number not in expected_runners:
            errors.append("UNKNOWN_OR_SCRATCHED_RUNNER")
        rows.append({"number": number, "name": expected_runners.get(number, ""),
                     "win_odds": odd})
    if len(set(parsed_market_times)) > 1:
        errors.append("MIXED_MARKET_UPDATE_TIMES")
    snapshot = {"schema": SCHEMA, "market": "WIN", "meeting_id": meeting_id,
                "race_number": race_number, "captured_utc": captured_utc,
                "scratches_verified": scratches_verified, "runners": rows}
    audit = validate_win_snapshot(snapshot, expected_runners)
    errors.extend(audit["errors"])
    return {"status": "BLOCKED" if errors else "STRUCTURE_VALID_UNVERIFIED",
            "errors": sorted(set(errors)), "snapshot": snapshot,
            "market_last_updated": market_times,
            "is_live": False, "bet_authorized": False}

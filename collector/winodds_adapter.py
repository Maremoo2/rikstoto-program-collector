"""Strict adapter for observed public Rikstoto WIN odds response structure.

No network calls, no betting, no inferred runner names or scratch status.
Observed response: {"result": {"1": [{"startNumber": int, "odds": float,
"lastUpdated": str}, ...]}}. Capture time is separate from market update time.
"""
from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from .odds_snapshot import SCHEMA, validate_win_snapshot


def parse_public_winodds(response: dict[str, Any], *, meeting_id: str,
                         race_number: int, captured_utc: str,
                         expected_runners: dict[int, str],
                         scratches_verified: bool = False) -> dict[str, Any]:
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
        except (ValueError, TypeError, AttributeError):
            errors.append("INVALID_MARKET_TIMESTAMP")
        if number not in expected_runners:
            errors.append("UNKNOWN_OR_SCRATCHED_RUNNER")
        rows.append({"number": number, "name": expected_runners.get(number, ""),
                     "win_odds": odd})
    snapshot = {"schema": SCHEMA, "market": "WIN", "meeting_id": meeting_id,
                "race_number": race_number, "captured_utc": captured_utc,
                "scratches_verified": scratches_verified, "runners": rows}
    audit = validate_win_snapshot(snapshot, expected_runners)
    errors.extend(audit["errors"])
    return {"status": "BLOCKED" if errors else "STRUCTURE_VALID_UNVERIFIED",
            "errors": sorted(set(errors)), "snapshot": snapshot,
            "market_last_updated": market_times,
            "is_live": False, "bet_authorized": False}

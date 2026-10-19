"""Strict, source-neutral WIN odds snapshot validation (no live-source claim).

This module does NOT scrape a site, place bets, or turn odds into p(win).
A capture adapter must supply actual timestamp, meeting, race and rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

SCHEMA = "prewatch_win_odds_v1"


def validate_win_snapshot(payload: dict[str, Any], expected_runners: dict[int, str]) -> dict[str, Any]:
    """Fail closed unless every active runner has exactly one usable WIN quote."""
    from .startlist_audit import normalized_horse_name

    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"status": "BLOCKED", "errors": ["INVALID_PAYLOAD"]}
    if payload.get("schema") != SCHEMA:
        errors.append("SCHEMA_MISMATCH")
    if payload.get("market") != "WIN":
        errors.append("NOT_WIN_MARKET")
    if not isinstance(payload.get("meeting_id"), str) or not payload["meeting_id"]:
        errors.append("MISSING_MEETING_ID")
    if type(payload.get("race_number")) is not int or payload["race_number"] < 1:
        errors.append("INVALID_RACE_NUMBER")
    stamp = payload.get("captured_utc")
    try:
        captured = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if captured.utcoffset() != timezone.utc.utcoffset(captured):
            errors.append("NOT_UTC")
    except (TypeError, ValueError, AttributeError):
        errors.append("INVALID_CAPTURE_TIME")
    rows = payload.get("runners")
    if not isinstance(rows, list):
        rows = []
        errors.append("INVALID_RUNNERS")
    found: dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            errors.append("INVALID_ROW")
            continue
        n, name, odd = row.get("number"), row.get("name"), row.get("win_odds")
        if type(n) is not int or n <= 0 or n in found:
            errors.append("INVALID_OR_DUPLICATE_NUMBER")
            continue
        if not isinstance(name, str) or not name.strip():
            errors.append("INVALID_NAME")
            continue
        found[n] = name
        if type(odd) not in (int, float) or not isfinite(odd) or odd <= 1:
            errors.append("INVALID_WIN_ODDS")
    if set(found) != set(expected_runners):
        errors.append("RUNNER_SET_MISMATCH")
    for n in set(found) & set(expected_runners):
        if normalized_horse_name(found[n]) != normalized_horse_name(expected_runners[n]):
            errors.append("RUNNER_NAME_MISMATCH")
            break
    if payload.get("scratches_verified") is not True:
        errors.append("SCRATCHES_NOT_VERIFIED")
    return {"status": "SNAPSHOT_VALID" if not errors else "BLOCKED",
            "errors": sorted(set(errors)), "runner_count": len(found),
            "schema": SCHEMA, "is_live": False, "bet_authorized": False}

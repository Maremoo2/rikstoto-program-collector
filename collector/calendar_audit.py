"""Date-scoped schedule audit based only on observed Rikstoto calendar fields.

The public /api/racedays/dates/{from}/{to} endpoint returned 11-17 Oct
when asked for 11-18 Oct in a live 18 Oct 2026 capture: upper bound
is apparently exclusive. Use [date, date+1) for a one-day request.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

DAY_KEY = re.compile(r"[A-Z0-9]{1,14}_[A-Z]{2,4}_20\d{2}-\d{2}-\d{2}", re.I)


def calendar_window(day: str) -> tuple[str, str]:
    parsed = date.fromisoformat(day)
    if parsed.isoformat() != day:
        raise ValueError("Date must be YYYY-MM-DD")
    return day, (parsed + timedelta(days=1)).isoformat()


def calendar_racedays(response: object, day: str) -> dict[str, dict]:
    """Read authoritative raceDayKey, raceNumber, date, track and multiTrack.

    Unrecognized API shapes yield {}, never a claim that no races exist.
    """
    if not isinstance(response, dict) or response.get("success") is False:
        return {}
    rows = response.get("result")
    if not isinstance(rows, list):
        return {}
    found = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get("raceDayKey")
        if not isinstance(key, str) or not DAY_KEY.fullmatch(key):
            continue
        if not key.endswith("_" + day):
            continue
        races = row.get("races") or []
        numbers = sorted({item["raceNumber"] for item in races
                          if isinstance(item, dict)
                          and type(item.get("raceNumber")) is int
                          and 1 <= item["raceNumber"] <= 30})
        found[key] = {
            "meeting_id": key, "track": row.get("raceDayName"),
            "country": row.get("countryIsoCode"),
            "sport_type": row.get("sportType"),
            "is_multi_track": bool(row.get("isMultiTrack")),
            "race_numbers": numbers,
            "start_time": row.get("startTime"),
            "source": "official_calendar_raceDayKey",
        }
    return found


def diagnose_calendar_response(response: object, day: str) -> dict[str, object]:
    """Classify the *observed* date API response, never certify date coverage.

    A successful HTTP request may return an empty result even when the
    homepage and the other first-party racedays endpoint show meetings.
    Empty and out-of-date results are source observations, not evidence that
    no races are scheduled. Provenance (URL, status, SHA) is attached by the
    caller from the archived request record.
    """
    date.fromisoformat(day)
    rows_seen = target_day_rows = invalid_rows = 0
    if response is None:
        status = "SOURCE_UNAVAILABLE"
    elif not isinstance(response, dict):
        status = "SCHEMA_UNRECOGNIZED"
    elif response.get("success") is False:
        status = "SOURCE_REPORTED_FAILURE"
    elif not isinstance(response.get("result"), list):
        status = "SCHEMA_UNRECOGNIZED"
    else:
        rows = response["result"]
        rows_seen = len(rows)
        if not rows:
            status = "EMPTY_RESULT_ARRAY"
        else:
            for row in rows:
                key = row.get("raceDayKey") if isinstance(row, dict) else None
                if not isinstance(key, str) or not DAY_KEY.fullmatch(key):
                    invalid_rows += 1
                elif key.endswith("_" + day):
                    target_day_rows += 1
            if invalid_rows:
                status = "ROW_SCHEMA_UNRECOGNIZED"
            elif target_day_rows:
                status = "TARGET_DAY_ENTRIES_PRESENT"
            else:
                status = "NO_TARGET_DAY_ENTRIES"
    return {
        "status": status,
        "rows_seen": rows_seen,
        "target_day_rows": target_day_rows,
        "invalid_rows": invalid_rows,
        "date_coverage_verified": False,
    }

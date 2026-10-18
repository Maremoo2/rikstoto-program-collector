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
    if not isinstance(response, dict):
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

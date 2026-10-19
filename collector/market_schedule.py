"""Pure Oslo-local market collection planning; does not fetch or publish odds.

GitHub cron is a polling trigger, not a guaranteed minute-accurate scheduler.
All events are candidate requests, never proof that a market was captured.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

OSLO = ZoneInfo("Europe/Oslo")


def plan_market_checks(meetings: list[dict[str, Any]], *, now: datetime,
                       lookahead_minutes: int = 10) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if lookahead_minutes < 0 or lookahead_minutes > 60:
        raise ValueError("invalid lookahead")
    local = now.astimezone(OSLO)
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for meeting in meetings:
        mid = meeting.get("meeting_id")
        if not isinstance(mid, str) or not mid:
            warnings.append("MEETING_ID_MISSING")
            continue
        races = meeting.get("races")
        if not isinstance(races, list) or not races:
            warnings.append(f"{mid}:NO_VERIFIED_RACE_TIMES")
            continue
        parsed = []
        for race in races:
            try:
                number = race["race_number"]
                if type(number) is not int or number < 1:
                    raise ValueError("race number")
                start = datetime.fromisoformat(race["start_utc"].replace("Z", "+00:00"))
                if start.tzinfo is None:
                    raise ValueError("naive race time")
                parsed.append((number, start.astimezone(OSLO)))
            except (KeyError, TypeError, ValueError, AttributeError):
                warnings.append(f"{mid}:INVALID_RACE_TIME_OR_NUMBER")
        if not parsed:
            continue
        first = min(x[1] for x in parsed)
        targets = [("MEETING_T_MINUS_30", None, first - timedelta(minutes=30))]
        for n, start in parsed:
            targets.extend([("RACE_T_MINUS_10", n, start - timedelta(minutes=10)),
                            ("RACE_T_MINUS_3", n, start - timedelta(minutes=3))])
        for kind, number, target in targets:
            key = (mid, kind, f"{number}:{target.isoformat()}")
            if key in seen:
                continue
            seen.add(key)
            # A late cron run never backfills a missed prestart quote as fresh.
            if local <= target < local + timedelta(minutes=lookahead_minutes):
                events.append({"meeting_id": mid, "race_number": number,
                               "check": kind, "target_oslo": target.isoformat(),
                               "status": "DUE_UNCAPTURED"})
    return {"schema": "prewatch_market_schedule_v1",
            "generated_oslo": local.isoformat(),
            "events": sorted(events, key=lambda x: (x["target_oslo"], x["meeting_id"])),
            "warnings": sorted(set(warnings)), "odds_captured": False,
            "bet_authorized": False}

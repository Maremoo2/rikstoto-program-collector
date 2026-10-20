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


def plan_awatch_market_checks(meetings: list[dict[str, Any]], *, now: datetime,
                              lookahead_minutes: int = 10) -> dict[str, Any]:
    """Phase B only: gate collection on explicitly qualified A-WATCH races.

    Missing scores, gate failures and unverified race times fail closed. This
    does not alter the V3.3.12 scoring model or authorize a BET.
    """
    selected = []
    rejected = []
    for meeting in meetings:
        mid = meeting.get("meeting_id")
        qualified = []
        for race in meeting.get("races", []):
            score = race.get("prewatch_score")
            gates = race.get("prewatch_gates_passed")
            status = race.get("prewatch_status")
            if (type(score) in (int, float) and not isinstance(score, bool)
                    and 70 <= score <= 100 and gates is True
                    and status == "A-WATCH"):
                qualified.append(race)
            else:
                rejected.append({"meeting_id": mid, "race_number": race.get("race_number"),
                                 "reason": "NOT_QUALIFIED_A_WATCH"})
        if qualified:
            selected.append({"meeting_id": mid, "races": qualified})
    result = plan_market_checks(selected, now=now,
                                lookahead_minutes=lookahead_minutes)
    # Meeting-level checks are retained only for meetings containing A-WATCH.
    result["schema"] = "prewatch_awatch_market_schedule_v1"
    result["phase"] = "B_MARKET_ONLY"
    result["rejected"] = rejected
    result["selected_race_count"] = sum(len(m["races"]) for m in selected)
    result["prewatch_requires_win_odds"] = False
    result["bet_authorized"] = False
    return result

"""Conservative P0 source guards; not scoring or betting logic."""
from __future__ import annotations

import re
from datetime import date

CLOCK = re.compile(r"(?:[01]?\d|2[0-3]):[0-5]\d\Z")


def time_blocker(value):
    """Require separate evidence to accept midnight as a true start time."""
    if not isinstance(value, str) or not value:
        return "START_TIME_UNKNOWN"
    if not CLOCK.fullmatch(value):
        return "START_TIME_INVALID"
    if value in ("0:00", "00:00"):
        return "START_TIME_UNVERIFIED_MIDNIGHT"
    return None


def coverage_gap(*, race_date, discovered_meetings, external_cards):
    """Flag external card evidence absent in discovery; never invent race IDs."""
    date.fromisoformat(race_date)
    result = []
    for card in external_cards:
        if (card.get("date") != race_date or not card.get("source_url")
                or not card.get("country") or not card.get("track")):
            continue
        if any(m.get("track") == card["track"] and m.get("country") == card["country"]
               for m in discovered_meetings):
            continue
        result.append({
            "status": "COVERAGE_GAP", "date": race_date,
            "track": card["track"], "country": card["country"],
            "externally_listed_races": card.get("race_count"),
            "source_url": card["source_url"], "meeting_id": None,
            "source_ready": False,
        })
    return result

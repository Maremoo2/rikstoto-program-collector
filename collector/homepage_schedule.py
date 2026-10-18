"""Parse observed, first-party Rikstoto SPA rehydration race calendar.

Archived public homepage HTML on 2026-10-18 sets:
 window.__spaRehydration = {"raceDays": {"url": "/api/racedays", "data": [...]}}
No login, script evaluation, or invented meeting identifiers are required.
The SPA can list only bettable races (e.g. Parislongchamp had 1 while the
full official startlist contained 8); race numbers are DISCOVERY HINTS only.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .calendar_audit import calendar_racedays

MARKER = re.compile(r"\bwindow\.__spaRehydration\s*=\s*")
MAX_REHYDRATION_LENGTH = 5_000_000
API_RACEDAYS = "/api/racedays"


def homepage_racedays(html: str, day: str) -> dict[str, Any]:
    """Extract date-scoped race-day entries from a public browser capture."""
    out: dict[str, Any] = {
        "status": "NOT_PRESENT", "day": day,
        "source": "public_homepage_spa_rehydration",
        "api_path": None, "expires": None, "meetings": {},
        "race_counts_are_complete": False,
        "notes": ["Homepage race listings may be partial; full starts API is authoritative for race count."],
    }
    marker = MARKER.search(html)
    if marker is None:
        return out
    if len(html) - marker.end() > MAX_REHYDRATION_LENGTH:
        out["status"] = "EXCESSIVE_HTML_AFTER_MARKER"
        return out
    try:
        payload, _ = json.JSONDecoder().raw_decode(html[marker.end():])
    except (ValueError, TypeError):
        out["status"] = "INVALID_REHYDRATION_JSON"
        return out
    if not isinstance(payload, dict):
        out["status"] = "INVALID_REHYDRATION_SCHEMA"
        return out
    item = payload.get("raceDays")
    if not isinstance(item, dict) or not isinstance(item.get("data"), list):
        out["status"] = "NO_RACEDAYS_DATA"
        return out
    out["api_path"] = item.get("url") if item.get("url") == API_RACEDAYS else None
    out["expires"] = item.get("expiration")
    meetings = calendar_racedays({"result": item["data"]}, day)
    out["meetings"] = meetings
    out["status"] = "DATE_MATCHES_PRESENT" if meetings else "NO_DATE_MATCHES"
    out["source_total_meetings"] = len(item["data"])
    out["meeting_count"] = len(meetings)
    return out


def schedule_comparison(discovered: set[str], home: dict[str, Any],
                        api_meetings: dict[str, Any],
                        date_api_meetings: dict[str, Any]) -> dict[str, Any]:
    """Compare actual source sets; agreement does not certify global coverage."""
    home_ids = set(home.get("meetings", {}))
    api_ids = set(api_meetings)
    date_ids = set(date_api_meetings)
    present = [group for group in (home_ids, api_ids, date_ids) if group]
    union = set.union(*present) if present else set()
    is_consistent = (len(present) >= 2
                     and all(group == union for group in present)
                     and discovered >= union)
    return {
        "status": "CROSS_SOURCE_AGREEMENT" if is_consistent else
                  "ONE_SOURCE_ONLY" if len(present) == 1 and discovered >= union else
                  "MISSING_OR_DISAGREEMENT",
        "homepage_ids": sorted(home_ids), "racedays_api_ids": sorted(api_ids),
        "date_api_ids": sorted(date_ids), "discovered_ids": sorted(discovered),
        "missing_from_collector": sorted(union - discovered),
        "homepage_missing_in_api": sorted(home_ids - api_ids) if api_ids else None,
        "api_missing_in_homepage": sorted(api_ids - home_ids) if home_ids else None,
        "completeness_certified": False,
        "rationale": "Agreement among first-party site snapshots checks consistency, "
                     "not independently proven coverage of all racing worldwide.",
    }

"""Source-only, non-authorizing daily quality counters for discovered physical races.

Counts describe *captured* candidate races, not the authoritative all-day
denominator, true source publication time, T-4 PIT or WIN availability.
Separate individual physical meetings from X1/multiTrack product legs.
"""
from __future__ import annotations

from .source_integrity import time_blocker


def summarize_source_quality(manifest: dict, races: list[dict]) -> dict:
    meetings = manifest.get("meetings", [])
    if not isinstance(meetings, list):
        meetings = []
    physical = {}
    composites = set()
    unknown_type = set()
    for m in meetings:
        if not isinstance(m, dict):
            continue
        mid = m.get("meeting_id")
        if not isinstance(mid, str) or not mid:
            continue
        if m.get("is_multi_track_product") is True:
            composites.add(mid)
        elif m.get("is_multi_track_product") is False:
            physical[mid] = m
        else:
            unknown_type.add(mid)

    count = {
        "source_scope": "CAPTURED_PHYSICAL_CANDIDATES_ONLY",
        "full_day_denominator_independently_verified": False,
        "pit_certified": False,
        "source_publication_time_attested": False,
        "physical_meetings_observed": len(physical),
        "composite_meeting_refs": len(composites),
        "meeting_type_unknown": len(unknown_type),
        "physical_race_candidate_rows": 0,
        "distinct_physical_race_keys": 0,
        "duplicate_physical_race_keys": 0,
        "unmapped_or_composite_race_rows": 0,
        "physical_race_clock_unverified_midnight": 0,
        "physical_race_clock_missing_or_invalid": 0,
        "physical_race_number_inferred": 0,
        "physical_race_number_unknown": 0,
        "physical_races_with_reconciled_meeting_snapshot": 0,
        "physical_horse_rows": 0,
        "json_raw_receipts_verified": 0,
        "json_raw_receipts_legacy_unverifiable": 0,
        "json_raw_receipts_missing_verification": 0,
        "pdf_source_receipts": 0,
        "calendar_diagnostic_status": manifest.get(
            "calendar_source_diagnostic", {}).get("status", "UNKNOWN")
            if isinstance(manifest.get("calendar_source_diagnostic"), dict)
            else "UNKNOWN",
    }
    keys = set()
    for doc in races if isinstance(races, list) else []:
        if not isinstance(doc, dict):
            count["unmapped_or_composite_race_rows"] += 1
            continue
        details = doc.get("race")
        if not isinstance(details, dict):
            count["unmapped_or_composite_race_rows"] += 1
            continue
        mid, no = details.get("meeting_id"), details.get("race_number")
        if (not isinstance(mid, str) or mid not in physical
                or type(no) is not int or not 1 <= no <= 30):
            count["unmapped_or_composite_race_rows"] += 1
            continue
        count["physical_race_candidate_rows"] += 1
        key = (mid, no)
        if key in keys:
            count["duplicate_physical_race_keys"] += 1
        keys.add(key)
        count["physical_horse_rows"] += len(doc.get("entrants", [])) if isinstance(
            doc.get("entrants"), list) else 0
        clock_problem = time_blocker(details.get("scheduled_time_local"))
        if clock_problem == "START_TIME_UNVERIFIED_MIDNIGHT":
            count["physical_race_clock_unverified_midnight"] += 1
        elif clock_problem is not None:
            count["physical_race_clock_missing_or_invalid"] += 1
        num_source = details.get("race_number_source")
        if num_source == "pdf_order_inferred":
            count["physical_race_number_inferred"] += 1
        elif num_source not in ("pdf_heading", "pdf_heading_number"):
            count["physical_race_number_unknown"] += 1
        audit = physical[mid].get("startlist_pdf_audit")
        if (isinstance(audit, dict)
                and audit.get("status") == "MATCHED_AS_OF_SNAPSHOT"):
            count["physical_races_with_reconciled_meeting_snapshot"] += 1

    count["distinct_physical_race_keys"] = len(keys)
    requests = manifest.get("requests")
    for item in requests if isinstance(requests, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("status") == "PDF_OK":
            count["pdf_source_receipts"] += 1
        if item.get("status") != "JSON_OK":
            continue
        if item.get("raw_readback_verified") is True and item.get("raw_path"):
            count["json_raw_receipts_verified"] += 1
        elif not item.get("raw_path"):
            count["json_raw_receipts_legacy_unverifiable"] += 1
        else:
            count["json_raw_receipts_missing_verification"] += 1

    return count

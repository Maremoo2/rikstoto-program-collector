"""Phase B source probe receipts: terminal statuses, not betting approvals.

Pure post-processing of EXISTING selective WIN diagnostics. The input is not
proof of a genuinely frozen V3.3.12 A-WATCH or live market eligibility.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from typing import Any

SCHEMA = "awatch_source_receipts_v1"
QUOTE_FRESH_SECONDS = 180
_START_OFFSET = {"RACE_T_MINUS_10": 10, "RACE_T_MINUS_3": 3}


def _utc_stamp(value: Any) -> datetime | None:
    """Require explicit, UTC-offset-aware source timestamps."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(UTC)
    except ValueError:
        return None


def _due_starts(schedule: dict[str, Any]) -> tuple[dict[tuple[str, int], datetime], set[tuple[str, int]]]:
    starts: dict[tuple[str, int], datetime] = {}
    inconsistent: set[tuple[str, int]] = set()
    for event in schedule.get("events", []):
        if not isinstance(event, dict):
            continue
        method = event.get("check")
        mid, number = event.get("meeting_id"), event.get("race_number")
        if method not in _START_OFFSET or not isinstance(mid, str) or type(number) is not int:
            continue
        target = _utc_stamp(event.get("target_oslo"))
        if target is None:
            inconsistent.add((mid, number))
            continue
        start = target + timedelta(minutes=_START_OFFSET[method])
        key = (mid, number)
        if key in starts and start != starts[key]:
            inconsistent.add(key)
        starts[key] = start
    return starts, inconsistent


def _source_errors(
    entry: dict[str, Any], expected_start: datetime | None
) -> list[str]:
    """Require concrete receipt evidence, not a generic success-looking label."""
    failed: set[str] = set()
    evidence = entry.get("diagnostic")
    if not isinstance(evidence, dict):
        return ["MISSING_SOURCE_DIAGNOSTIC"]

    if evidence.get("status") != "DIAGNOSTIC_CAPTURED":
        failed.add("NO_CAPTURED_DIAGNOSTIC")
    if evidence.get("url") != entry.get("url"):
        failed.add("SOURCE_PAGE_URL_NOT_MATCHED")
    if type(evidence.get("requested_race_number")) is not int or (
        evidence["requested_race_number"] != entry.get("race_number")
    ):
        failed.add("SOURCE_RACE_NUMBER_NOT_MATCHED")
    counts = evidence.get("source_capture_counts")
    if not isinstance(counts, dict) or (
        type(counts.get("winodds")) is not int or counts["winodds"] < 1
        or type(counts.get("official_starts")) is not int
        or counts["official_starts"] < 1
    ):
        failed.add("WIN_AND_OFFICIAL_STARTLIST_NOT_BOTH_OBSERVED")

    audit = evidence.get("win_startlist_audit")
    if not isinstance(audit, dict) or (
        audit.get("status") != "STRUCTURE_VALID_UNVERIFIED"
        or audit.get("errors") != []
    ):
        failed.add("FULL_ACTIVE_FIELD_WIN_AUDIT_NOT_VALIDATED")
    screen = evidence.get("screen_parity")
    count = audit.get("runner_count") if isinstance(audit, dict) else None
    if not isinstance(screen, dict) or (
        screen.get("status") != "MATCH"
        or screen.get("api_field_complete") is not True
        or type(count) is not int or count < 1
        or type(screen.get("matched_count")) is not int
        or screen["matched_count"] != count
        or type(screen.get("expected_count")) is not int
        or screen["expected_count"] != count
    ):
        failed.add("SCREEN_API_ALL_RUNNERS_PARITY_NOT_VERIFIED")
    captured = _utc_stamp(evidence.get("captured_utc"))
    if expected_start is None or captured is None or captured >= expected_start:
        failed.add("CAPTURE_TIMESTAMP_NOT_VERIFIED_PRESTART")
    stamps = audit.get("market_last_updated") if isinstance(audit, dict) else None
    if not isinstance(stamps, list) or type(count) is not int or len(stamps) != count:
        failed.add("PER_RUNNER_MARKET_TIMESTAMPS_INCOMPLETE")
    else:
        for time in stamps:
            updated = _utc_stamp(time)
            if (
                updated is None or captured is None or expected_start is None
                or updated >= expected_start
                or not 0 <= (captured - updated).total_seconds() <= QUOTE_FRESH_SECONDS
            ):
                failed.add("PER_RUNNER_MARKET_TIMESTAMP_INVALID_OR_STALE")
                break
    if evidence.get("bet_authorized") is not False:
        failed.add("DIAGNOSTIC_IMPROPER_BET_AUTHORIZATION")
    if evidence.get("win_market_verified") is not False:
        failed.add("DIAGNOSTIC_IMPROPER_LIVE_VERIFICATION")
    return sorted(failed)


def receipt_from_selective_collection(result: dict[str, Any]) -> dict[str, Any]:
    """Read-only classification of *this* diagnostic run, not Phase B approval.

    No event = NOOP, never success. Any source-only candidate remains pending
    standalone WIN pool provenance, actual A-WATCH freeze and model p(win).
    """
    if not isinstance(result, dict) or result.get("phase") != "B_MARKET_ONLY":
        raise ValueError("Not a selective Phase B source diagnostic")
    schedule = result.get("schedule")
    entries = result.get("races")
    if not isinstance(schedule, dict) or not isinstance(entries, list):
        raise ValueError("Incomplete selective source envelope")
    if result.get("bet_authorized") is not False:
        raise ValueError("Source envelope must not authorize a bet")
    if schedule.get("phase") != "B_MARKET_ONLY" or schedule.get("bet_authorized") is not False:
        raise ValueError("Schedule must remain Phase B market-only and nonbetting")
    stated_probes = result.get("probed_race_count")
    if stated_probes is not None and (
        type(stated_probes) is not int or stated_probes != len(entries)
    ):
        raise ValueError("Probed race count contradicts diagnostic entries")

    due, mismatched_starts = _due_starts(schedule)
    selected = schedule.get("selected_race_count")
    if type(selected) is not int or selected < 0:
        raise ValueError("Invalid number of selected A-WATCH candidates")
    if selected < len(due):
        raise ValueError("More due race IDs than selected A-WATCH races")
    observed: dict[tuple[str, int], dict[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Invalid source probe entry")
        mid, race = item.get("meeting_id"), item.get("race_number")
        if not isinstance(mid, str) or type(race) is not int:
            raise ValueError("Missing exact probe race identity")
        key = (mid, race)
        if key in observed:
            raise ValueError("Repeated probe for same scheduled race")
        if key not in due:
            raise ValueError("Source probe does not match a due A-WATCH race")
        observed[key] = item

    rows = []
    statuses = Counter()
    for key in sorted(due):
        item = observed.get(key)
        if item is None:
            state = "DUE_WITHOUT_PROBE"
            reasons = ["DUE_PROBE_NOT_ATTEMPTED"]
        else:
            reasons = _source_errors(item, due[key])
            if key in mismatched_starts:
                reasons.append("CONTRADICTORY_SCHEDULE_START_TIMES")
            if reasons:
                state = "PROBED_SOURCE_INCOMPLETE"
            else:
                state = "SOURCE_CANDIDATE_ONLY_UNVERIFIED"
        statuses[state] += 1
        rows.append({
            "meeting_id": key[0],
            "race_number": key[1],
            "scheduled_start_utc_derived_from_due_event": due[key].isoformat(),
            "status": state,
            "blockers": sorted(set(reasons)),
            "standalone_win_pool_verified": False,
            "original_source_bytes_sha256_verified": False,
            "bet_authorized": False,
        })

    if selected == 0:
        terminal = "NO_QUALIFIED_A_WATCH"
    elif not due:
        terminal = "QUALIFIED_A_WATCH_NOT_DUE"
    elif not observed:
        terminal = "DUE_BUT_NO_SOURCE_PROBE"
    elif any(row["status"] != "SOURCE_CANDIDATE_ONLY_UNVERIFIED" for row in rows):
        terminal = "DUE_SOURCE_INCOMPLETE_OR_BLOCKED"
    else:
        terminal = "SOURCE_CANDIDATES_UNVERIFIED_NOT_BET"

    canonical = json.dumps(
        {"schedule": schedule, "races": entries},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema": SCHEMA,
        "status": terminal,
        "diagnostic_envelope_sha256": sha256(canonical).hexdigest(),
        "selected_by_manual_prewatch_input": selected,
        "due_unique_races": len(due),
        "probes_attempted": len(observed),
        "due_terminal_counts": dict(sorted(statuses.items())),
        "due_races": rows,
        "manual_prewatch_score_independently_verified": False,
        "full_active_field_live_source_provenance_verified": False,
        "standalone_win_pool_source_verified": False,
        "calibrated_full_field_probability_verified": False,
        "technical_source_receipt_not_BET": True,
        "complete_operational_phase_b": False,
        "bet_authorized": False,
        "BET_BLOCKED": True,
    }

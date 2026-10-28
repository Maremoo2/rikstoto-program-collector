"""Phase B read-only exact-race lineage diagnostic across 3 existing sources.

Inputs: manually submitted Pre-Watch meetings (NOT authenticated freeze),
Collector morning source index, and the selective WIN diagnostic with receipt.
This links *claims* and source-body digests only. It never reads an account,
touches an odds feed, produces probabilities or authorizes a BET.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .awatch_win_collector import _valid_meeting_id
from .market_schedule import plan_awatch_market_checks
from .phase_b_receipts import receipt_from_selective_collection

SCHEMA = "phase_b_source_race_lineage_v1"
OSLO = ZoneInfo("Europe/Oslo")
HASH_FIELDS = ("playwright_body_sha256", "body_byte_length")
WIN_PATH = "/api/betdistribution/winodds"


def _clock(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.astimezone(UTC)
    except ValueError:
        return None


def _hash_document(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _qualifying_manual_races(meetings: Any) -> dict[tuple[str, int], dict[str, Any]]:
    if not isinstance(meetings, list):
        raise ValueError("Manual Pre-Watch meetings must be a list")
    qualified: dict[tuple[str, int], dict[str, Any]] = {}
    all_keys: set[tuple[str, int]] = set()
    for meeting in meetings:
        if not isinstance(meeting, dict) or not isinstance(meeting.get("races"), list):
            raise ValueError("Invalid manual meeting structure")
        mid = meeting.get("meeting_id")
        if not _valid_meeting_id(mid):
            raise ValueError("Invalid exact meeting ID")
        for race in meeting["races"]:
            if not isinstance(race, dict):
                raise ValueError("Malformed manual race")
            n = race.get("race_number")
            if type(n) is not int or not 1 <= n <= 99:
                raise ValueError("Invalid manual race number")
            key = (mid, n)
            if key in all_keys:
                raise ValueError("Duplicate manual race identity")
            all_keys.add(key)
            # Reuse Collector's single existing A-WATCH qualification rule,
            # even for a race whose T-10/T-3 window is not currently due.
            # A zero-length window cannot schedule network requests.
            isolated = plan_awatch_market_checks(
                [{"meeting_id": mid, "races": [race]}],
                now=datetime(2000, 1, 1, tzinfo=UTC),
                lookahead_minutes=0,
            )
            if isolated["selected_race_count"] == 1:
                qualified[key] = race
    return qualified


def _morning_races(source_index: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    if (
        not isinstance(source_index, dict)
        or source_index.get("schema") != "prewatch_source_v1"
        or not isinstance(source_index.get("race_queue"), list)
    ):
        raise ValueError("Invalid morning source index")
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for item in source_index["race_queue"]:
        if not isinstance(item, dict):
            raise ValueError("Malformed morning race")
        mid, number = item.get("meeting_id"), item.get("race_number")
        if not _valid_meeting_id(mid) or type(number) is not int or not 1 <= number <= 99:
            raise ValueError("Invalid morning source race key")
        key = (mid, number)
        if key in result:
            raise ValueError("Duplicate morning race")
        if item.get("race_key") != f"{mid}|{number}":
            raise ValueError("Morning source race key and fields disagree")
        result[key] = item
    return result


def _digest_block(
    diagnostic: dict[str, Any], *, kind: str, path: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    source = diagnostic.get("source_response_provenance")
    rows = source.get(kind) if isinstance(source, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None, [f"{kind.upper()}_SOURCE_BODY_PROVENANCE_NOT_UNIQUE"]
    record = rows[0]
    reasons = []
    if (
        record.get("source_kind") != (
            "WIN_ODDS" if kind == "winodds" else "OFFICIAL_STARTLIST"
        )
        or record.get("source_path_no_query") != path
        or record.get("schema") != "phase_b_public_response_body_evidence_v1"
        or record.get("http_status") != 200
    ):
        reasons.append(f"{kind.upper()}_SOURCE_ENDPOINT_NOT_MATCHED")
    digest = record.get("playwright_body_sha256")
    if (
        not isinstance(digest, str) or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
        or type(record.get("body_byte_length")) is not int
        or record["body_byte_length"] <= 0
    ):
        reasons.append(f"{kind.upper()}_ORIGINAL_BODY_DIGEST_INVALID")
    for key in (
        "source_authority_independently_verified", "bet_authorized",
        "raw_http_wire_bytes_verified",
    ):
        if record.get(key) is not False:
            reasons.append(f"{kind.upper()}_UNSUPPORTED_SOURCE_VERIFICATION_CLAIM")
            break
    if _clock(record.get("captured_utc")) is None:
        reasons.append(f"{kind.upper()}_CAPTURE_CLOCK_MISSING")
    return record, reasons


def _source_lineage_errors(
    *, key: tuple[str, int], manual: dict[str, Any], morning: dict[str, Any] | None,
    index: dict[str, Any], observed: dict[str, Any] | None,
    terminal: dict[str, Any], schedule_generated: datetime | None,
) -> tuple[list[str], dict[str, Any]]:
    mid, n = key
    errors: set[str] = set()
    technical: dict[str, Any] = {"win_body_sha256": None, "startlist_body_sha256": None}
    started = _clock(manual.get("start_utc"))
    frozen = _clock(manual.get("frozen_at_utc"))
    source_at = _clock(index.get("created_utc"))
    lineage_start = _clock(terminal.get("scheduled_start_utc_derived_from_due_event"))

    if started is None or lineage_start is None or started != lineage_start:
        errors.add("PREWATCH_AND_DUE_START_TIME_MISMATCH")
    if not isinstance(mid, str) or len(mid) < 11 or mid[-10:] != (
        started.astimezone(OSLO).date().isoformat() if started else None
    ):
        errors.add("MEETING_ID_AND_OSLO_DATE_MISMATCH")
    if index.get("date_oslo") != (
        started.astimezone(OSLO).date().isoformat() if started else None
    ):
        errors.add("MORNING_SOURCE_DATE_NOT_SAME_RACE_DATE")
    if frozen is None:
        errors.add("MANUAL_PREWATCH_FROZEN_TIMESTAMP_MISSING")
    elif started is None or frozen >= started or (
        schedule_generated is not None and frozen > schedule_generated
    ):
        errors.add("PREWATCH_FREEZE_TIMESTAMP_AFTER_PLAN_OR_START")
    if source_at is None or (
        frozen is not None and source_at > frozen
    ) or (schedule_generated is not None and source_at > schedule_generated):
        errors.add("MORNING_SOURCE_NOT_AVAILABLE_BEFORE_PLAN")
    if schedule_generated is None or (
        started is not None and schedule_generated >= started
    ):
        errors.add("SOURCE_PLAN_TIMESTAMP_MISSING_OR_POSTSTART")
    if morning is None:
        errors.add("EXACT_RACE_MISSING_FROM_MORNING_SOURCE")
    else:
        if (
            morning.get("source_ready_snapshot") is not True
            or morning.get("source_blockers") != []
        ):
            errors.add("MORNING_RACE_SOURCE_QA_NOT_READY")
        if type(morning.get("runner_count")) is not int or morning["runner_count"] < 1:
            errors.add("MORNING_RACE_RUNNER_COUNT_MISSING")

    if terminal.get("status") != "SOURCE_CANDIDATE_ONLY_UNVERIFIED" or terminal.get(
        "blockers"
    ) != []:
        errors.add("DUE_SOURCE_RECEIPT_NOT_CANDIDATE")

    if not isinstance(observed, dict):
        errors.add("NO_MATCHING_DUE_SOURCE_PROBE")
        return sorted(errors), technical

    expected_url = (
        "https://www.rikstoto.no/Spill/"
        + quote(mid, safe="")
        + f"/V?race={n}&p={n}:0"
    )
    if observed.get("url") != expected_url:
        errors.add("SOURCE_PAGE_URL_EXACT_RACE_MISMATCH")
    diagnostic = observed.get("diagnostic")
    if not isinstance(diagnostic, dict):
        errors.add("WIN_DIAGNOSTIC_MISSING")
        return sorted(errors), technical
    if (
        observed.get("bet_authorized") is not False
        or diagnostic.get("bet_authorized") is not False
        or diagnostic.get("win_market_verified") is not False
    ):
        errors.add("BET_OR_UNSUPPORTED_LIVE_SOURCE_CLAIM")
    if diagnostic.get("url") != expected_url or diagnostic.get("requested_race_number") != n:
        errors.add("WIN_PROBE_IDENTITY_MISMATCH")
    startlist_path = f"/api/racedays/{mid}/starts"
    win, win_errors = _digest_block(
        diagnostic, kind="winodds", path=WIN_PATH,
    )
    official, official_errors = _digest_block(
        diagnostic, kind="official_starts", path=startlist_path,
    )
    errors.update(win_errors)
    errors.update(official_errors)
    received_at = _clock(diagnostic.get("captured_utc"))
    screen_at = _clock(diagnostic.get("screen_captured_utc"))
    if win is not None:
        technical["win_body_sha256"] = win.get("playwright_body_sha256")
        if _clock(win.get("captured_utc")) != received_at:
            errors.add("SELECTED_WIN_BODY_CLOCK_NOT_DIAGNOSTIC_CLOCK")
    if official is not None:
        technical["startlist_body_sha256"] = official.get("playwright_body_sha256")
    if started is None or received_at is None or received_at >= started or (
        schedule_generated is not None and received_at < schedule_generated
    ):
        errors.add("WIN_RECEIPT_NOT_IN_PRESTART_SOURCE_WINDOW")
    if (
        started is None or screen_at is None or screen_at >= started
        or received_at is None
        or not 0 <= (screen_at - received_at).total_seconds() <= 90
    ):
        errors.add("SCREEN_AND_WIN_CAPTURE_TIMES_NOT_COMPARABLE")
    if official is None or (
        started is None or (_clock(official.get("captured_utc")) or started) >= started
    ):
        errors.add("OFFICIAL_STARTLIST_NOT_OBSERVED_PRESTART")
    audit = diagnostic.get("win_startlist_audit")
    if not isinstance(audit, dict):
        errors.add("FULL_FIELD_WIN_AUDIT_MISSING")
    elif (
        win is None or official is None
        or audit.get("source_win_body_sha256") != win.get("playwright_body_sha256")
        or audit.get("source_official_startlist_body_sha256")
        != official.get("playwright_body_sha256")
    ):
        errors.add("FULL_FIELD_AUDIT_NOT_BOUND_TO_SOURCE_BODY_HASHES")
    return sorted(errors), technical


def audit_phase_b_race_lineage(
    *, prewatch: dict[str, Any], source_index: dict[str, Any],
    collection: dict[str, Any],
) -> dict[str, Any]:
    """Exact-key source evidence reconciliation, never independent freeze proof."""
    if not isinstance(prewatch, dict) or not isinstance(collection, dict):
        raise ValueError("Malformed inputs")
    morning = _morning_races(source_index)
    qualified = _qualifying_manual_races(prewatch.get("meetings"))
    if collection.get("phase") != "B_MARKET_ONLY" or collection.get(
        "bet_authorized"
    ) is not False:
        raise ValueError("Not a nonbetting selective source diagnostic")
    reported = collection.get("receipt")
    recalculated = receipt_from_selective_collection(collection)
    if not isinstance(reported, dict) or reported != recalculated:
        raise ValueError("Source receipt not equal to deterministic recomputation")
    schedule = collection["schedule"]
    generated = _clock(schedule.get("generated_oslo"))
    if schedule.get("selected_race_count") != len(qualified):
        raise ValueError("Manually scored A-WATCH count differs from scheduled selection")
    entry_by_key = {
        (entry["meeting_id"], entry["race_number"]): entry
        for entry in collection["races"]
    }
    if len(entry_by_key) != len(collection["races"]):
        raise ValueError("Duplicate source probe identity")
    rows = []
    for terminal in reported["due_races"]:
        key = (terminal["meeting_id"], terminal["race_number"])
        manual = qualified.get(key)
        if manual is None:
            raise ValueError("Due market source has no matching manually scored A-WATCH")
        errors, technical = _source_lineage_errors(
            key=key, manual=manual, morning=morning.get(key),
            index=source_index, observed=entry_by_key.get(key),
            terminal=terminal, schedule_generated=generated,
        )
        rows.append({
            "meeting_id": key[0],
            "race_number": key[1],
            "reported_due_start_utc": terminal["scheduled_start_utc_derived_from_due_event"],
            "technical_lineage_status": (
                "CLAIMED_SOURCE_LINEAGE_MATCH_UNVERIFIED" if not errors
                else "SOURCE_LINEAGE_BLOCKED"
            ),
            "diagnostic_reasons": errors,
            **technical,
            "real_A_WATCH_freeze_independently_attested": False,
            "source_release_archive_independently_verified": False,
            "standalone_win_pool_verified": False,
            "independent_calibrated_full_field_pwin_verified": False,
            "bet_authorized": False,
        })
    summary = (
        "NO_QUALIFIED_AWATCH"
        if len(qualified) == 0 else
        "A_WATCH_SELECTED_BUT_NOT_DUE" if not rows else
        "CLAIMED_LINEAGE_MATCHES_BUT_OPERATIONALLY_BLOCKED"
        if all(row["technical_lineage_status"] == "CLAIMED_SOURCE_LINEAGE_MATCH_UNVERIFIED"
               for row in rows)
        else "SOURCE_LINEAGE_BLOCKED"
    )
    return {
        "schema": SCHEMA,
        "status": summary,
        "manual_prewatch_sha256": _hash_document(prewatch),
        "source_index_sha256": _hash_document(source_index),
        "collection_sha256": _hash_document(collection),
        "manually_qualified_awatch_count": len(qualified),
        "due_race_count": len(rows),
        "due_races": rows,
        "source_body_hashes_replayed_from_original_bytes": False,
        "manual_prewatch_frozen_prospectively_authenticated": False,
        "original_source_publisher_authority_verified": False,
        "isolated_win_pool_verified": False,
        "full_phase_b_completed": False,
        "real_betting_authorized": False,
        "BET_BLOCKED": True,
        "limits": [
            "A manually submitted score and its timestamp are assertions, not independent freeze evidence.",
            "An archived morning source index is a source QA snapshot, not live scratch verification.",
            "Source body digests in diagnostics are compared, but originals are not replayed by this tool.",
            "Matching race IDs, screen times and hashes do not establish a standalone WIN pool or model edge.",
            "No after-the-fact source or odds can be converted into an earlier BET.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prewatch", type=Path, required=True)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = (args.prewatch, args.source_index, args.collection)
    if args.output.resolve() in {x.resolve() for x in paths}:
        raise ValueError("Output cannot overwrite a source input")
    data = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    report = audit_phase_b_race_lineage(
        prewatch=data[0], source_index=data[1], collection=data[2],
    )
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(
        {key: value for key, value in report.items() if key != "due_races"},
        ensure_ascii=False, indent=2,
    ))


if __name__ == "__main__":
    main()

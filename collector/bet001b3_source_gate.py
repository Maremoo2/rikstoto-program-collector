"""BET-001B3: optional, fail-closed Phase B WIN source evidence diagnostic.

Never invoked by production workflows. No networking, persistence, betting,
probabilities, or provider contract changes. Frozen HBI executable price capture
contract is NOT available: no result from this module qualifies HBI live capture.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
import re
from typing import Any

from .winodds_adapter import parse_public_winodds
from .win_evidence import assess_win_evidence

# Existing BET-001A/B LOCAL diagnostic, not the original HBI contract's
# verified five-second definition or an authorization to modify that contract.
LOCAL_DIAGNOSTIC_AGE_SECONDS = 5


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
            return None
        return timestamp.astimezone(UTC)
    except ValueError:
        return None


def _digest(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch("[0-9a-fA-F]{64}", value))


def _number(value: Any, *, nonnegative: bool = False) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and (
        not nonnegative or value >= 0)


def audit_source_claim(source: dict[str, Any], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a supplied offline claim, not a real live observation.

    Failure to produce a complete, independently verifiable source body,
    server clock, cache, start/roster and pool envelope means BLOCKED.
    Even a complete synthetic envelope is UNVERIFIED until HBI's original
    capture contract and independent first-party evidence are confirmed.
    """
    errors: set[str] = set()
    if not isinstance(source, dict):
        source = {}
        errors.add("INVALID_SOURCE_CASE")
    proof = evidence if isinstance(evidence, dict) else {}
    if not proof:
        errors.add("SOURCE_PROVENANCE_MISSING")
    meeting_id = source.get("meeting_id")
    race = source.get("race_number")
    received = _utc(source.get("received_utc"))
    scheduled = _utc(source.get("scheduled_start_utc"))
    if not isinstance(meeting_id, str) or not meeting_id or type(race) is not int or race < 1:
        errors.add("INVALID_RACE_ID")
    if received is None or scheduled is None or received >= scheduled:
        errors.add("NOT_VERIFIED_PRESTART")

    if proof.get("race_id") != f"{meeting_id}:{race}":
        errors.add("PROVENANCE_RACE_ID_MISMATCH")
    request = _utc(proof.get("request_started_utc"))
    response = _utc(proof.get("response_received_utc"))
    if request is None or response is None:
        errors.add("REQUEST_RESPONSE_CLOCKS_MISSING")
    elif received is None or request > response or response != received:
        errors.add("REQUEST_RESPONSE_CLOCKS_INCONSISTENT")
    actual_start = _utc(proof.get("actual_start_utc"))
    if actual_start is None or response is None or response >= actual_start:
        errors.add("ACTUAL_START_NOT_VERIFIED_PRESTART")
    if not proof.get("actual_start_source"):
        errors.add("ACTUAL_START_SOURCE_MISSING")
    http_date = _utc(proof.get("http_date_utc"))
    if http_date is None:
        errors.add("HTTP_DATE_MISSING")
    if type(proof.get("http_status")) is not int or proof["http_status"] != 200:
        errors.add("HTTP_STATUS_INVALID")
    if not _number(proof.get("http_age_seconds"), nonnegative=True):
        errors.add("HTTP_CACHE_AGE_UNKNOWN")
    if not isinstance(proof.get("http_cache_control"), str) or not proof["http_cache_control"]:
        errors.add("HTTP_CACHE_CONTROL_UNKNOWN")
    if not proof.get("source_version"):
        errors.add("SOURCE_VERSION_UNKNOWN")
    source_update = _utc(proof.get("source_updated_utc"))
    if source_update is None or response is None or source_update > response:
        errors.add("SOURCE_UPDATE_TIME_UNVERIFIED")
    if not _number(proof.get("clock_offset_ms")) or not _number(
            proof.get("clock_uncertainty_ms"), nonnegative=True):
        errors.add("CLOCK_OFFSET_UNCERTAINTY_MISSING")
    if not proof.get("clock_sync_source"):
        errors.add("CLOCK_SYNC_SOURCE_MISSING")
    if (http_date is not None and request is not None and response is not None
            and _number(proof.get("clock_offset_ms")) and _number(
                proof.get("clock_uncertainty_ms"), nonnegative=True)):
        offset, uncertainty = proof["clock_offset_ms"], proof["clock_uncertainty_ms"]
        if not (request.timestamp() + (offset - uncertainty) / 1000 <= http_date.timestamp()
                <= response.timestamp() + (offset + uncertainty) / 1000):
            errors.add("HTTP_DATE_CLOCK_CONFLICT")

    for key in ("win_source_uri", "official_roster_uri", "pool_source_uri"):
        uri = proof.get(key)
        if not isinstance(uri, str) or not uri.startswith("https://www.rikstoto.no/"):
            errors.add("SOURCE_URI_MISSING_OR_NOT_FIRST_PARTY:" + key)
    for key in ("official_roster_sha256", "scratch_source_sha256", "pool_source_sha256"):
        if not _digest(proof.get(key)):
            errors.add("SOURCE_DIGEST_MISSING:" + key)
    for key in ("roster_version", "scratch_version", "independent_field_confirmation_ref",
                "checkpoint_id", "pool_source_updated_utc"):
        if not proof.get(key):
            errors.add("SOURCE_VERSION_OR_CHECKPOINT_MISSING:" + key)
    if _utc(proof.get("pool_source_updated_utc")) is None:
        errors.add("POOL_UPDATE_TIME_INVALID")
    raw_body = proof.get("raw_win_body")
    if not isinstance(raw_body, str):
        errors.add("ORIGINAL_WIN_BODY_MISSING")
    elif not _digest(source.get("raw_win_body_sha256")) or hashlib.sha256(
            raw_body.encode("utf-8")).hexdigest().lower() != source["raw_win_body_sha256"].lower():
        errors.add("ORIGINAL_WIN_BODY_HASH_MISMATCH")
    else:
        try:
            if json.loads(raw_body) != source.get("win_response"):
                errors.add("ORIGINAL_WIN_BODY_CONTENT_MISMATCH")
        except ValueError:
            errors.add("ORIGINAL_WIN_BODY_NOT_JSON")

    official = source.get("official_starts")
    roster = official.get("runners") if isinstance(official, dict) else None
    if (not isinstance(official, dict) or official.get("verified_official") is not True
            or official.get("meeting_id") != meeting_id or official.get("race_number") != race
            or not isinstance(roster, list) or not roster):
        errors.add("OFFICIAL_FULL_FIELD_UNVERIFIED")
        roster = []
    expected: dict[int, str] = {}
    seen: set[int] = set()
    for runner in roster:
        if not isinstance(runner, dict):
            errors.add("INVALID_OFFICIAL_RUNNER")
            continue
        number = runner.get("startNumber")
        if type(number) is not int or number < 1 or number in seen:
            errors.add("DUPLICATE_OFFICIAL_HORSE")
            continue
        seen.add(number)
        if runner.get("raceNumber", race) != race:
            errors.add("RUNNER_RACE_ID_CONFLICT")
        if type(runner.get("isScratched")) is not bool:
            errors.add("SCRATCH_STATE_UNVERIFIED")
        if not isinstance(runner.get("horseName"), str) or not runner["horseName"].strip():
            errors.add("HORSE_IDENTITY_UNVERIFIED")
        if runner.get("isScratched") is False:
            expected[number] = runner.get("horseName", "")
    if not expected:
        errors.add("NO_VERIFIED_ACTIVE_FIELD")

    try:
        parsed = parse_public_winodds(
            source.get("win_response"), meeting_id=str(meeting_id), race_number=race,
            captured_utc=source.get("received_utc"), expected_runners=expected,
            scratches_verified="SCRATCH_STATE_UNVERIFIED" not in errors
                               and "OFFICIAL_FULL_FIELD_UNVERIFIED" not in errors,
            max_market_age_seconds=LOCAL_DIAGNOSTIC_AGE_SECONDS)
    except (TypeError, ValueError, KeyError) as exc:
        parsed = {"status": "BLOCKED", "errors": ["ODDS_ADAPTER_EXCEPTION:" + type(exc).__name__]}
    if parsed.get("status") != "STRUCTURE_VALID_UNVERIFIED":
        errors.add("WIN_FULL_FIELD_OR_SOURCE_TIMESTAMPS_UNVERIFIED")
    errors.update(parsed.get("errors", []))
    pool = source.get("win_pool")
    p = pool if isinstance(pool, dict) else {}
    if p.get("meeting_id") != meeting_id or p.get("race_number") != race:
        errors.add("POOL_RACE_ID_CONFLICT")
    if p.get("market") != "WIN" or p.get("scope") != "SINGLE_MARKET":
        errors.add("ISOLATED_WIN_POOL_MISSING")
    if not _number(p.get("turnover"), nonnegative=True):
        errors.add("WIN_POOL_TURNOVER_MISSING")
    if not isinstance(p.get("currency"), str) or not re.fullmatch("[A-Z]{3}", p["currency"]):
        errors.add("WIN_POOL_CURRENCY_MISSING")
    audit = assess_win_evidence(
        parsed, roster, official.get("captured_utc", "") if isinstance(official, dict) else "",
        p, source.get("received_utc"), max_age_seconds=LOCAL_DIAGNOSTIC_AGE_SECONDS)
    if audit["status"] == "BLOCKED":
        errors.update(audit["errors"])
    if source.get("source_kind") != "VERIFIED_FIRST_PARTY":
        errors.add("SOURCE_KIND_NOT_VERIFIED")
    return {"status": "BLOCKED" if errors else "UNVERIFIED",
            "errors": sorted(errors) if errors else ["FROZEN_HBI_CAPTURE_CONTRACT_NOT_VERIFIED"],
            "capture_contract": "NOT_VERIFIED", "observed_live": False,
            "hbi_live_qualified": False, "bet_authorized": False,
            "source_only": True, "runner_count_active": len(expected),
            "runner_count_priced": len(parsed.get("snapshot", {}).get("runners", []))}

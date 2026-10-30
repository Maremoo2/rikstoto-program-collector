"""BET-001B3: offline negative provenance regression tests, 2026-10-30.

Run inside an isolated clone of Maremoo2/rikstoto-program-collector:
  python -m pytest -q /path/to/test_hbi_v3_negative_source_evidence.py

Uses synthetic source evidence only. Makes no network calls, real bets, live
capture or production writes. DOES NOT validate the original HBI contract;
original byte scope and original frozen timing requirements are unavailable.
"""
import copy
import hashlib
import json

import pytest

from collector.bet001b3_source_gate import audit_source_claim


def synthetic_case():
    """Mirrors the public BET-001B3 main synthetic fixture, not source evidence."""
    received = "2026-10-30T11:55:00+00:00"
    prefix = "https://www.rikstoto.no/"
    source = {
        "meeting_id": "TEST_NR_2026-10-30",
        "race_number": 1,
        "received_utc": received,
        "scheduled_start_utc": "2026-10-30T12:00:00+00:00",
        "source_kind": "VERIFIED_FIRST_PARTY",  # untrusted synthetic flag
        "official_starts": {
            "verified_official": True,  # untrusted synthetic flag
            "meeting_id": "TEST_NR_2026-10-30",
            "race_number": 1,
            "captured_utc": "2026-10-30T11:54:58+00:00",
            "runners": [
                {"startNumber": 1, "horseName": "Horse One", "isScratched": False},
                {"startNumber": 2, "horseName": "Horse Two", "isScratched": False},
            ],
        },
        "win_response": {
            "success": True,
            "result": {"1": [
                {"startNumber": 1, "odds": 3.5, "lastUpdated": "2026-10-30T11:54:58+00:00"},
                {"startNumber": 2, "odds": 4.5, "lastUpdated": "2026-10-30T11:54:59+00:00"},
            ]},
        },
        "win_pool": {
            "meeting_id": "TEST_NR_2026-10-30",
            "race_number": 1,
            "market": "WIN",
            "scope": "SINGLE_MARKET",
            "turnover": 1500.0,
            "currency": "NOK",
            "source": "OFFLINE_FIXTURE",
            "captured_utc": "2026-10-30T11:54:59+00:00",
        },
    }
    body = json.dumps(source["win_response"], sort_keys=True)
    source["raw_win_body_sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    proof = {
        "race_id": "TEST_NR_2026-10-30:1",
        "request_started_utc": "2026-10-30T11:54:59+00:00",
        "response_received_utc": received,
        "http_date_utc": received,
        "actual_start_utc": "2026-10-30T12:00:01+00:00",
        "actual_start_source": "OFFLINE_TEST",
        "http_status": 200,
        "http_age_seconds": 0,
        "http_cache_control": "no-cache",
        "source_version": "TEST-ETAG",
        "source_updated_utc": "2026-10-30T11:54:59+00:00",
        "clock_offset_ms": 0,
        "clock_uncertainty_ms": 1,
        "clock_sync_source": "TEST_REFERENCE",
        "win_source_uri": prefix + "api/betdistribution/winodds",
        "official_roster_uri": prefix + "api/racedays/TEST/starts",
        "pool_source_uri": prefix + "api/pools/win",
        "official_roster_sha256": "a" * 64,
        "scratch_source_sha256": "b" * 64,
        "pool_source_sha256": "c" * 64,
        "roster_version": "test-v1",
        "scratch_version": "test-v1",
        "independent_field_confirmation_ref": "TEST_PDF",
        "checkpoint_id": "TEST_T_MINUS_5",
        "pool_source_updated_utc": "2026-10-30T11:54:58+00:00",
        "raw_win_body": body,
    }
    return source, proof


def assert_fail_closed(source, proof, expected):
    before = copy.deepcopy((source, proof))
    result = audit_source_claim(source, proof)
    assert result["status"] == "BLOCKED", result
    assert expected in result["errors"], result
    assert result["capture_contract"] == "NOT_VERIFIED"
    assert result["hbi_live_qualified"] is False
    assert result["bet_authorized"] is False
    assert (source, proof) == before, "offline auditor must not mutate supplied evidence"


@pytest.mark.parametrize("missing,expected", [
    ("request_started_utc", "REQUEST_RESPONSE_CLOCKS_MISSING"),
    ("response_received_utc", "REQUEST_RESPONSE_CLOCKS_MISSING"),
    ("http_date_utc", "HTTP_DATE_MISSING"),
    ("http_age_seconds", "HTTP_CACHE_AGE_UNKNOWN"),
    ("http_cache_control", "HTTP_CACHE_CONTROL_UNKNOWN"),
    ("source_updated_utc", "SOURCE_UPDATE_TIME_UNVERIFIED"),
    ("source_version", "SOURCE_VERSION_UNKNOWN"),
    ("clock_offset_ms", "CLOCK_OFFSET_UNCERTAINTY_MISSING"),
    ("clock_uncertainty_ms", "CLOCK_OFFSET_UNCERTAINTY_MISSING"),
    ("clock_sync_source", "CLOCK_SYNC_SOURCE_MISSING"),
    ("actual_start_utc", "ACTUAL_START_NOT_VERIFIED_PRESTART"),
    ("actual_start_source", "ACTUAL_START_SOURCE_MISSING"),
    ("pool_source_updated_utc", "SOURCE_VERSION_OR_CHECKPOINT_MISSING:pool_source_updated_utc"),
], ids=lambda x: str(x))
def test_missing_mandatory_time_or_cache_evidence(missing, expected):
    source, proof = synthetic_case()
    del proof[missing]
    assert_fail_closed(source, proof, expected)


@pytest.mark.parametrize("mutation,expected", [
    (lambda s, p: p.update(http_age_seconds=-0.1), "HTTP_CACHE_AGE_UNKNOWN"),
    (lambda s, p: p.update(http_cache_control=""), "HTTP_CACHE_CONTROL_UNKNOWN"),
    (lambda s, p: p.update(http_date_utc="2026-10-30T11:56:00+00:00"), "HTTP_DATE_CLOCK_CONFLICT"),
    (lambda s, p: p.update(source_updated_utc="2026-10-30T11:55:01+00:00"), "SOURCE_UPDATE_TIME_UNVERIFIED"),
    (lambda s, p: p.update(response_received_utc="2026-10-30T11:54:58+00:00"), "REQUEST_RESPONSE_CLOCKS_INCONSISTENT"),
    (lambda s, p: p.update(clock_uncertainty_ms=-1), "CLOCK_OFFSET_UNCERTAINTY_MISSING"),
    (lambda s, p: p.update(actual_start_utc="2026-10-30T11:55:00+00:00"), "ACTUAL_START_NOT_VERIFIED_PRESTART"),
    (lambda s, p: s.update(received_utc="2026-10-30T12:00:00+00:00"), "NOT_VERIFIED_PRESTART"),
    (lambda s, p: p.update(http_date_utc="not-a-time"), "HTTP_DATE_MISSING"),
], ids=["negative-age", "empty-control", "server-date-conflict", "future-source-update", "receipt-mismatch", "negative-clock-uncertainty", "not-pre-actual-start", "not-pre-scheduled-start", "invalid-http-date-utc"])
def test_conflicting_time_or_cache_evidence(mutation, expected):
    source, proof = synthetic_case()
    mutation(source, proof)
    assert_fail_closed(source, proof, expected)


@pytest.mark.parametrize("cache_age,cache_directive", [
    (3600, "max-age=1"),
    (3600, "no-cache"),
])
def test_unresolved_effective_cache_semantics_never_qualify_live(cache_age, cache_directive):
    """Characterization ONLY; not an acceptance claim for the unknown original.

    The existing B3 gate checks cache Age is present/nonnegative and the
    Cache-Control string is nonempty, but has no frozen effective-age formula.
    These cases cannot be certified compliant; reject any live/BET promotion.
    Do NOT assert a fabricated numeric original contract threshold here.
    """
    source, proof = synthetic_case()
    proof.update(http_age_seconds=cache_age, http_cache_control=cache_directive)
    result = audit_source_claim(source, proof)
    assert result["status"] in {"BLOCKED", "UNVERIFIED"}, result
    assert result["capture_contract"] == "NOT_VERIFIED"
    assert not result["hbi_live_qualified"] and not result["bet_authorized"]


def test_synthetic_nominal_case_never_becomes_original_contract_pass():
    source, proof = synthetic_case()
    result = audit_source_claim(source, proof)
    assert result["status"] == "UNVERIFIED", result
    assert result["errors"] == ["FROZEN_HBI_CAPTURE_CONTRACT_NOT_VERIFIED"]
    assert not result["hbi_live_qualified"] and not result["bet_authorized"]

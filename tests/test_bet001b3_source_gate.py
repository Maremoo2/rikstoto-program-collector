"""Never contacts a live source; synthetic testing only."""
import copy
import hashlib
import json
import pytest
from collector.bet001b3_source_gate import audit_source_claim


def example():
    received = "2026-10-30T11:55:00+00:00"
    u = "https://www.rikstoto.no/"
    source = {
        "meeting_id": "TEST_NR_2026-10-30", "race_number": 1,
        "received_utc": received, "scheduled_start_utc": "2026-10-30T12:00:00+00:00",
        "source_kind": "VERIFIED_FIRST_PARTY",
        "official_starts": {
            "verified_official": True, "meeting_id": "TEST_NR_2026-10-30", "race_number": 1,
            "captured_utc": "2026-10-30T11:54:58+00:00",
            "runners": [
                {"startNumber": 1, "horseName": "Horse One", "isScratched": False},
                {"startNumber": 2, "horseName": "Horse Two", "isScratched": False},
            ]},
        "win_response": {"success": True, "result": {"1": [
            {"startNumber": 1, "odds": 3.5, "lastUpdated": "2026-10-30T11:54:58+00:00"},
            {"startNumber": 2, "odds": 4.5, "lastUpdated": "2026-10-30T11:54:59+00:00"}]}},
        "win_pool": {
            "meeting_id": "TEST_NR_2026-10-30", "race_number": 1,
            "market": "WIN", "scope": "SINGLE_MARKET",
            "turnover": 1500.0, "currency": "NOK",
            "source": "OFFLINE_FIXTURE", "captured_utc": "2026-10-30T11:54:59+00:00",
        },
    }
    body = json.dumps(source["win_response"], sort_keys=True)
    source["raw_win_body_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    proof = {
        "race_id": "TEST_NR_2026-10-30:1",
        "request_started_utc": "2026-10-30T11:54:59+00:00",
        "response_received_utc": received, "http_date_utc": received,
        "actual_start_utc": "2026-10-30T12:00:01+00:00",
        "actual_start_source": "OFFLINE_TEST",
        "http_status": 200, "http_age_seconds": 0,
        "http_cache_control": "no-cache", "source_version": "TEST-ETAG",
        "source_updated_utc": "2026-10-30T11:54:59+00:00",
        "clock_offset_ms": 0, "clock_uncertainty_ms": 1,
        "clock_sync_source": "TEST_REFERENCE",
        "win_source_uri": u + "api/betdistribution/winodds",
        "official_roster_uri": u + "api/racedays/TEST/starts",
        "pool_source_uri": u + "api/pools/win",
        "official_roster_sha256": "a" * 64,
        "scratch_source_sha256": "b" * 64,
        "pool_source_sha256": "c" * 64,
        "roster_version": "test-v1", "scratch_version": "test-v1",
        "independent_field_confirmation_ref": "TEST_PDF",
        "checkpoint_id": "TEST_T_MINUS_5", "pool_source_updated_utc": "2026-10-30T11:54:58+00:00",
        "raw_win_body": body,
    }
    return source, proof


def test_positive_fixture_never_becomes_live_pass():
    source, proof = example()
    result = audit_source_claim(source, proof)
    assert result["status"] == "UNVERIFIED", result
    assert not result["bet_authorized"] and not result["hbi_live_qualified"]


@pytest.mark.parametrize("missing,expected", [
    ("request_started_utc", "REQUEST_RESPONSE_CLOCKS_MISSING"),
    ("response_received_utc", "REQUEST_RESPONSE_CLOCKS_MISSING"),
    ("http_date_utc", "HTTP_DATE_MISSING"),
    ("http_age_seconds", "HTTP_CACHE_AGE_UNKNOWN"),
    ("http_cache_control", "HTTP_CACHE_CONTROL_UNKNOWN"),
    ("source_version", "SOURCE_VERSION_UNKNOWN"),
    ("source_updated_utc", "SOURCE_UPDATE_TIME_UNVERIFIED"),
    ("actual_start_utc", "ACTUAL_START_NOT_VERIFIED_PRESTART"),
    ("actual_start_source", "ACTUAL_START_SOURCE_MISSING"),
    ("clock_offset_ms", "CLOCK_OFFSET_UNCERTAINTY_MISSING"),
    ("clock_uncertainty_ms", "CLOCK_OFFSET_UNCERTAINTY_MISSING"),
    ("clock_sync_source", "CLOCK_SYNC_SOURCE_MISSING"),
    ("official_roster_sha256", "SOURCE_DIGEST_MISSING:official_roster_sha256"),
    ("scratch_source_sha256", "SOURCE_DIGEST_MISSING:scratch_source_sha256"),
    ("pool_source_sha256", "SOURCE_DIGEST_MISSING:pool_source_sha256"),
    ("checkpoint_id", "SOURCE_VERSION_OR_CHECKPOINT_MISSING:checkpoint_id"),
    ("raw_win_body", "ORIGINAL_WIN_BODY_MISSING"),
])
def test_missing_provenance_blocks(missing, expected):
    source, proof = example()
    del proof[missing]
    result = audit_source_claim(source, proof)
    assert result["status"] == "BLOCKED" and expected in result["errors"], result


@pytest.mark.parametrize("mutation,expected", [
    (lambda s, p: p.update(http_age_seconds=None), "HTTP_CACHE_AGE_UNKNOWN"),
    (lambda s, p: p.update(http_date_utc="2026-10-30T10:00:00+00:00"), "HTTP_DATE_CLOCK_CONFLICT"),
    (lambda s, p: p.update(actual_start_utc="2026-10-30T11:54:59+00:00"), "ACTUAL_START_NOT_VERIFIED_PRESTART"),
    (lambda s, p: p.update(race_id="ANOTHER:1"), "PROVENANCE_RACE_ID_MISMATCH"),
    (lambda s, p: p.update(raw_win_body="{}"), "ORIGINAL_WIN_BODY_HASH_MISMATCH"),
    (lambda s, p: s["win_pool"].update(market="V85", scope="COMBINED"), "ISOLATED_WIN_POOL_MISSING"),
    (lambda s, p: s["win_pool"].pop("turnover"), "WIN_POOL_TURNOVER_MISSING"),
    (lambda s, p: s["official_starts"]["runners"][0].update(isScratched=None), "SCRATCH_STATE_UNVERIFIED"),
    (lambda s, p: s["official_starts"]["runners"].append(copy.deepcopy(s["official_starts"]["runners"][0])), "DUPLICATE_OFFICIAL_HORSE"),
    (lambda s, p: s["win_response"]["result"]["1"].pop(), "RUNNER_SET_MISMATCH"),
    (lambda s, p: s.update(received_utc="2026-10-30T12:00:00+00:00"), "NOT_VERIFIED_PRESTART"),
    (lambda s, p: s["win_response"]["result"]["1"][0].update(lastUpdated="2026-10-30T11:54:50+00:00"), "STALE_MARKET_ODDS"),
])
def test_invalid_input_blocks(mutation, expected):
    source, proof = example()
    mutation(source, proof)
    result = audit_source_claim(source, proof)
    assert result["status"] == "BLOCKED" and expected in result["errors"], result


def test_restarts_idempotent_and_source_immutable():
    source, proof = example()
    before = copy.deepcopy((source, proof))
    assert audit_source_claim(source, proof) == audit_source_claim(source, proof)
    assert (source, proof) == before


def test_absent_provenance_never_passes():
    source, _ = example()
    result = audit_source_claim(source)
    assert result["status"] == "BLOCKED"

"""Cross-artifact Phase B lineage contract (synthetic, offline and no betting)."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from collector.awatch_win_collector import collect
from collector.phase_b_race_lineage import audit_phase_b_race_lineage
from collector.phase_b_receipts import receipt_from_selective_collection

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
START = NOW + timedelta(minutes=3)
MEETING = "S2_NR_2026-10-20"
WIN_HASH = hashlib.sha256(b"synthetic exact WIN response bytes").hexdigest()
STARTS_HASH = hashlib.sha256(b"synthetic exact official startlist bytes").hexdigest()
URL = (
    "https://www.rikstoto.no/Spill/S2_NR_2026-10-20/V?race=2&p=2:0"
)


def _source_provenance(kind, path, digest, observed=NOW):
    return {
        "schema": "phase_b_public_response_body_evidence_v1",
        "source_kind": kind,
        "source_path_no_query": path,
        "playwright_body_sha256": digest,
        "body_byte_length": 150,
        "http_status": 200,
        "captured_utc": observed.isoformat(),
        "raw_http_wire_bytes_verified": False,
        "source_authority_independently_verified": False,
        "bet_authorized": False,
    }


def _probe(url):
    return {
        "schema": "prewatch_win_source_probe_v1",
        "status": "DIAGNOSTIC_CAPTURED",
        "url": url,
        "captured_utc": NOW.isoformat(),
        "screen_captured_utc": (NOW + timedelta(seconds=10)).isoformat(),
        "requested_race_number": 2,
        "source_capture_counts": {"winodds": 1, "official_starts": 1},
        "source_response_provenance": {
            "winodds": [_source_provenance(
                "WIN_ODDS", "/api/betdistribution/winodds", WIN_HASH,
            )],
            "official_starts": [_source_provenance(
                "OFFICIAL_STARTLIST",
                "/api/racedays/S2_NR_2026-10-20/starts", STARTS_HASH,
            )],
            "original_bodies_archived_and_readback_verified": False,
            "independently_verified_live_win": False,
            "bet_authorized": False,
        },
        "win_startlist_audit": {
            "status": "STRUCTURE_VALID_UNVERIFIED",
            "errors": [],
            "runner_count": 2,
            "market_last_updated": [
                (NOW - timedelta(seconds=10)).isoformat(),
                (NOW - timedelta(seconds=20)).isoformat(),
            ],
            "source_win_body_sha256": WIN_HASH,
            "source_official_startlist_body_sha256": STARTS_HASH,
        },
        "screen_parity": {
            "status": "MATCH", "api_field_complete": True,
            "matched_count": 2, "expected_count": 2,
        },
        "bet_authorized": False,
        "win_market_verified": False,
    }


@pytest.fixture()
def artifacts():
    manual = {
        "meetings": [{
            "meeting_id": MEETING,
            "races": [{
                "race_number": 2, "start_utc": START.isoformat(),
                "prewatch_score": 70, "prewatch_gates_passed": True,
                "prewatch_status": "A-WATCH",
                "frozen_at_utc": (NOW - timedelta(minutes=20)).isoformat(),
            }],
        }],
        "note": "Synthetic manual score; not a genuine independent A-WATCH",
    }
    source_index = {
        "schema": "prewatch_source_v1",
        "date_oslo": "2026-10-20",
        "created_utc": (NOW - timedelta(hours=3)).isoformat(),
        "collection_status": "CAPTURED_UNVERIFIED",
        "race_queue": [{
            "race_key": MEETING + "|2",
            "meeting_id": MEETING,
            "race_number": 2,
            "runner_count": 3,
            "source_ready_snapshot": True,
            "source_blockers": [],
            "start_local": "2026-10-20T14:03:00+02:00",
        }],
    }
    async def _source(url):
        return _probe(url)
    with patch(
        "collector.awatch_win_collector.probe",
        new_callable=AsyncMock,
    ) as source:
        source.side_effect = _source
        collection = asyncio.run(collect(
            manual["meetings"], now=NOW, lookahead_minutes=1,
        ))
        source.assert_awaited_once_with(URL)
    assert collection["receipt"]["status"] == (
        "SOURCE_CANDIDATES_UNVERIFIED_NOT_BET"
    )
    return manual, source_index, collection


def _report(parts):
    p, s, c = parts
    return audit_phase_b_race_lineage(
        prewatch=p, source_index=s, collection=c,
    )


def _recalculate(parts):
    parts[2]["receipt"] = receipt_from_selective_collection(parts[2])


def test_exact_race_date_source_and_hashes_linked_without_BET(artifacts):
    out = _report(artifacts)
    assert out["status"] == "CLAIMED_LINEAGE_MATCHES_BUT_OPERATIONALLY_BLOCKED"
    assert out["manually_qualified_awatch_count"] == 1
    assert out["due_race_count"] == 1
    row = out["due_races"][0]
    assert row["technical_lineage_status"] == "CLAIMED_SOURCE_LINEAGE_MATCH_UNVERIFIED"
    assert row["diagnostic_reasons"] == []
    assert row["meeting_id"] == MEETING
    assert row["race_number"] == 2
    assert row["win_body_sha256"] == WIN_HASH
    assert row["startlist_body_sha256"] == STARTS_HASH
    assert row["real_A_WATCH_freeze_independently_attested"] is False
    for key in (
        "source_body_hashes_replayed_from_original_bytes",
        "manual_prewatch_frozen_prospectively_authenticated",
        "original_source_publisher_authority_verified",
        "isolated_win_pool_verified",
        "full_phase_b_completed",
        "real_betting_authorized",
    ):
        assert out[key] is False
    assert out["BET_BLOCKED"] is True


def test_missing_freeze_timestamp_blocks_claimed_lineage(artifacts):
    p, _, _ = artifacts
    del p["meetings"][0]["races"][0]["frozen_at_utc"]
    out = _report(artifacts)
    assert out["status"] == "SOURCE_LINEAGE_BLOCKED"
    assert "MANUAL_PREWATCH_FROZEN_TIMESTAMP_MISSING" in (
        out["due_races"][0]["diagnostic_reasons"]
    )


def test_incorrect_start_time_does_not_join_due_window(artifacts):
    p, _, _ = artifacts
    p["meetings"][0]["races"][0]["start_utc"] = (
        START + timedelta(minutes=5)
    ).isoformat()
    assert "PREWATCH_AND_DUE_START_TIME_MISMATCH" in (
        _report(artifacts)["due_races"][0]["diagnostic_reasons"]
    )


def test_morning_source_not_ready_never_becomes_ready_by_late_WIN(artifacts):
    _, src, _ = artifacts
    src["race_queue"][0]["source_ready_snapshot"] = False
    src["race_queue"][0]["source_blockers"] = ["PDF_STARTLIST_NOT_FULLY_RECONCILED"]
    out = _report(artifacts)
    assert "MORNING_RACE_SOURCE_QA_NOT_READY" in (
        out["due_races"][0]["diagnostic_reasons"]
    )


def test_missing_or_altered_source_release_date_is_rejected(artifacts):
    _, src, _ = artifacts
    src["date_oslo"] = "2026-10-21"
    assert "MORNING_SOURCE_DATE_NOT_SAME_RACE_DATE" in (
        _report(artifacts)["due_races"][0]["diagnostic_reasons"]
    )


@pytest.mark.parametrize(("alter", "expected"), [
    ("wrong_win_path", "WINODDS_SOURCE_ENDPOINT_NOT_MATCHED"),
    ("invalid_digest", "WINODDS_ORIGINAL_BODY_DIGEST_INVALID"),
    ("claim_source_authority", "WINODDS_UNSUPPORTED_SOURCE_VERIFICATION_CLAIM"),
    ("missing_startlist", "OFFICIAL_STARTS_SOURCE_BODY_PROVENANCE_NOT_UNIQUE"),
    ("hash_not_bound_to_adapter", "FULL_FIELD_AUDIT_NOT_BOUND_TO_SOURCE_BODY_HASHES"),
    ("screen_too_late", "SCREEN_AND_WIN_CAPTURE_TIMES_NOT_COMPARABLE"),
    ("body_after_start", "WIN_RECEIPT_NOT_IN_PRESTART_SOURCE_WINDOW"),
])
def test_source_provenance_or_timing_mutations_fail_closed(
    artifacts, alter, expected
):
    _, _, collection = artifacts
    d = collection["races"][0]["diagnostic"]
    meta = d["source_response_provenance"]
    if alter == "wrong_win_path":
        meta["winodds"][0]["source_path_no_query"] = "/api/other"
    elif alter == "invalid_digest":
        meta["winodds"][0]["playwright_body_sha256"] = "0" * 63
    elif alter == "claim_source_authority":
        meta["winodds"][0]["source_authority_independently_verified"] = True
    elif alter == "missing_startlist":
        meta["official_starts"] = []
    elif alter == "hash_not_bound_to_adapter":
        d["win_startlist_audit"]["source_win_body_sha256"] = "0" * 64
    elif alter == "screen_too_late":
        d["screen_captured_utc"] = (NOW + timedelta(minutes=2)).isoformat()
    elif alter == "body_after_start":
        d["captured_utc"] = (START + timedelta(seconds=1)).isoformat()
        meta["winodds"][0]["captured_utc"] = d["captured_utc"]
    _recalculate(artifacts)
    out = _report(artifacts)
    assert out["status"] == "SOURCE_LINEAGE_BLOCKED"
    assert expected in out["due_races"][0]["diagnostic_reasons"]
    assert out["BET_BLOCKED"] is True


def test_collection_receipt_tampering_is_not_accepted(artifacts):
    artifacts[2]["receipt"]["due_races"][0]["status"] = "REAL_BET"
    with pytest.raises(ValueError, match="deterministic recomputation"):
        _report(artifacts)


def test_duplicate_morning_race_fails_closed(artifacts):
    artifacts[1]["race_queue"].append(
        copy.deepcopy(artifacts[1]["race_queue"][0])
    )
    with pytest.raises(ValueError, match="Duplicate morning race"):
        _report(artifacts)


def test_duplicate_manual_race_fails_closed(artifacts):
    artifacts[0]["meetings"][0]["races"].append(
        copy.deepcopy(artifacts[0]["meetings"][0]["races"][0])
    )
    with pytest.raises(ValueError, match="Duplicate manual race"):
        _report(artifacts)


def test_morning_race_key_mismatch_never_fuzzy_matches(artifacts):
    artifacts[1]["race_queue"][0]["race_key"] = MEETING + "|3"
    with pytest.raises(ValueError, match="race key and fields disagree"):
        _report(artifacts)


def test_unapproved_69_score_cannot_join_prior_70_score_collection(artifacts):
    artifacts[0]["meetings"][0]["races"][0]["prewatch_score"] = 69
    with pytest.raises(ValueError, match="A-WATCH count differs"):
        _report(artifacts)


def test_source_fixture_and_report_are_deterministic_and_unchanged(artifacts):
    frozen = copy.deepcopy(artifacts)
    a = _report(artifacts)
    b = _report(artifacts)
    assert a == b
    assert artifacts == frozen
    assert all(len(a[key]) == 64 for key in (
        "manual_prewatch_sha256", "source_index_sha256", "collection_sha256"
    ))


def test_readonly_cli_writes_new_report_and_refuses_overwrite(tmp_path, artifacts):
    names = ("prewatch", "source-index", "collection")
    paths = []
    for label, data in zip(names, artifacts, strict=True):
        path = tmp_path / (label + ".json")
        path.write_text(json.dumps(data), encoding="utf-8")
        paths.append(path)
    report_path = tmp_path / "source-lineage-audit.json"
    command = [
        sys.executable, "-m", "collector.phase_b_race_lineage",
        "--prewatch", str(paths[0]),
        "--source-index", str(paths[1]),
        "--collection", str(paths[2]),
        "--output", str(report_path),
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert json.loads(report_path.read_text(encoding="utf-8")) == _report(artifacts)
    assert json.loads(first.stdout)["BET_BLOCKED"] is True
    again = subprocess.run(command, capture_output=True, text=True, check=False)
    assert again.returncode != 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["BET_BLOCKED"] is True

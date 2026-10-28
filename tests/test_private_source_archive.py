"""Private Phase B source archive: exact Playwright body readback, synthetic only.

No real HTTP, wagering, provider credentials or public raw-data artifacts.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from collector.private_source_archive import (
    PrivateArchiveRejected,
    PrivateSourceArchive,
    verify_private_source_record,
)
from collector.win_response_provenance import decode_public_json_body

WIN_URL = "https://www.rikstoto.no/api/betdistribution/winodds"
STARTS_URL = "https://www.rikstoto.no/api/racedays/S2_NR_2026-10-20/starts"
WIN_BYTES = b'{"success":true, "result":{"2":[{"startNumber":4,"odds":3.5}]}}'
STARTS_BYTES = b'{"success":true,"result":{"2":[{"startNumber":4,"horseName":"Alpha","isScratched":false}]}}'


@pytest.fixture()
def private_root(tmp_path):
    root = tmp_path / "private-win-body"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    return root


def _evidence(body=WIN_BYTES, url=WIN_URL):
    _, record = decode_public_json_body(
        body=body, url=url, http_status=200,
        headers={
            "content-type": "application/json",
            "set-cookie": "credential-must-not-leak",
        },
        captured_utc="2026-10-20T12:00:00+00:00",
    )
    return record


def _archive(root):
    return PrivateSourceArchive(
        root, meeting_id="S2_NR_2026-10-20", race_number=2,
    )


def test_private_archive_exact_byte_readback_and_source_identity(private_root):
    archive = _archive(private_root)
    first = archive.write_body(WIN_BYTES, _evidence())
    second = archive.write_body(
        STARTS_BYTES, _evidence(STARTS_BYTES, STARTS_URL)
    )
    assert first["record_id"] != second["record_id"]
    assert first["private_readback_sha256_verified"] is True
    assert first["playwright_body_sha256"] == hashlib.sha256(WIN_BYTES).hexdigest()
    assert second["playwright_body_sha256"] == hashlib.sha256(STARTS_BYTES).hexdigest()
    for record, exact in ((first, WIN_BYTES), (second, STARTS_BYTES)):
        body_file = private_root / (record["record_id"] + ".body")
        manifest_file = private_root / (record["record_id"] + ".json")
        assert body_file.read_bytes() == exact
        assert body_file.stat().st_mode & 0o077 == 0
        assert manifest_file.stat().st_mode & 0o077 == 0
        verified = verify_private_source_record(private_root, record["record_id"])
        assert verified == record
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert manifest["meeting_id_claimed_by_probe"] == "S2_NR_2026-10-20"
        assert manifest["race_number_claimed_by_probe"] == 2
        assert manifest["source_authority_independently_verified"] is False
        assert manifest["raw_http_wire_bytes_verified"] is False
        assert manifest["immutable_or_signed_manifest_verified"] is False
        assert manifest["bet_authorized"] is False
        assert "set-cookie" not in json.dumps(manifest)
        assert "credential" not in json.dumps(manifest)
        assert "private-win-body" not in json.dumps(record)


def test_double_capture_never_overwrites_existing_archived_bytes(private_root):
    archive = _archive(private_root)
    first = archive.write_body(WIN_BYTES, _evidence())
    second = archive.write_body(WIN_BYTES, _evidence())
    assert first["record_id"] != second["record_id"]
    assert first["playwright_body_sha256"] == second["playwright_body_sha256"]
    assert len(list(private_root.iterdir())) == 4


def test_modified_local_body_fails_offline_readback(private_root):
    receipt = _archive(private_root).write_body(WIN_BYTES, _evidence())
    body_path = private_root / (receipt["record_id"] + ".body")
    altered = WIN_BYTES.replace(b"3.5", b"4.5")
    body_path.write_bytes(altered)
    with pytest.raises(PrivateArchiveRejected, match="PRIVATE_BODY_READBACK_SHA256_MISMATCH"):
        verify_private_source_record(private_root, receipt["record_id"])


def test_corrupted_manifest_claim_fails_closed(private_root):
    receipt = _archive(private_root).write_body(WIN_BYTES, _evidence())
    manifest_path = private_root / (receipt["record_id"] + ".json")
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    m["body_filename"] = "../wrong.bin"
    manifest_path.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(PrivateArchiveRejected, match="PRIVATE_MANIFEST_IDENTITY_INVALID"):
        verify_private_source_record(private_root, receipt["record_id"])


def test_symlinked_body_is_not_trusted(private_root, tmp_path):
    receipt = _archive(private_root).write_body(WIN_BYTES, _evidence())
    body_path = private_root / (receipt["record_id"] + ".body")
    body_path.unlink()
    outside = tmp_path / "outside.body"
    outside.write_bytes(WIN_BYTES)
    body_path.symlink_to(outside)
    with pytest.raises(PrivateArchiveRejected, match="PRIVATE_RECORD_NOT_READABLE"):
        verify_private_source_record(private_root, receipt["record_id"])


@pytest.mark.parametrize("invalid", [
    "relative", "wide_permissions", "not_existing", "symlink",
])
def test_unsafe_private_archive_root_rejected(tmp_path, invalid):
    root = tmp_path / "private"
    if invalid != "not_existing":
        root.mkdir(mode=0o700)
        root.chmod(0o700)
    if invalid == "relative":
        root = Path("private")
    elif invalid == "wide_permissions":
        root.chmod(0o755)
    elif invalid == "symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(root)
        root = alias
    with pytest.raises(PrivateArchiveRejected):
        _archive(root)


def test_unverified_golden_provenance_or_mismatched_source_byte_hash_is_rejected(
    private_root,
):
    record = _evidence()
    altered = dict(record, playwright_body_sha256="0" * 64)
    with pytest.raises(PrivateArchiveRejected, match="UNVERIFIED_SOURCE_BODY_EVIDENCE"):
        _archive(private_root).write_body(WIN_BYTES, altered)
    altered = dict(record, body_bytes_archived_and_readback_verified=True)
    with pytest.raises(PrivateArchiveRejected, match="UNVERIFIED_SOURCE_BODY_EVIDENCE"):
        _archive(private_root).write_body(WIN_BYTES, altered)
    assert list(private_root.iterdir()) == []


@pytest.mark.parametrize("race", [0, True, 100, "2"])
def test_archive_race_number_must_be_explicit_valid_integer(private_root, race):
    with pytest.raises(PrivateArchiveRejected, match="TARGET_RACE_IDENTITY_INVALID"):
        PrivateSourceArchive(
            private_root, meeting_id="S2_NR_2026-10-20", race_number=race,
        )


def test_invalid_offline_record_id_and_missing_file_never_pass(private_root):
    with pytest.raises(PrivateArchiveRejected, match="INVALID_RECORD_ID"):
        verify_private_source_record(private_root, "../escape")
    with pytest.raises(PrivateArchiveRejected, match="PRIVATE_RECORD_NOT_READABLE"):
        verify_private_source_record(private_root, "0" * 32)


def test_private_archive_no_token_or_query_in_record_metadata(private_root):
    archive = _archive(private_root)
    enriched = _evidence(url=WIN_URL + "?race=2&token=HIDDEN_QUERY_TOKEN")
    receipt = archive.write_body(WIN_BYTES, enriched)
    record = json.dumps(receipt)
    full_manifest = (private_root / (receipt["record_id"] + ".json")).read_text()
    assert "HIDDEN_QUERY_TOKEN" not in record + full_manifest
    assert "credential-must-not-leak" not in record + full_manifest


def test_private_archiver_is_never_a_betting_engine(private_root):
    receipt = _archive(private_root).write_body(WIN_BYTES, _evidence())
    assert receipt["bet_authorized"] is False
    assert receipt["source_authority_independently_verified"] is False
    assert receipt["raw_http_wire_bytes_verified"] is False
    assert receipt["immutable_or_signed_manifest_verified"] is False


def test_random_record_id_collision_preserves_all_prior_archived_evidence(
    private_root,
):
    archive = _archive(private_root)
    fixed_id = "a" * 32
    with patch(
        "collector.private_source_archive.secrets.token_hex",
        return_value=fixed_id,
    ):
        first = archive.write_body(WIN_BYTES, _evidence())
        original_body = (private_root / (fixed_id + ".body")).read_bytes()
        original_manifest = (private_root / (fixed_id + ".json")).read_bytes()
        with pytest.raises(FileExistsError):
            archive.write_body(STARTS_BYTES, _evidence(STARTS_BYTES, STARTS_URL))
    assert first["record_id"] == fixed_id
    assert (private_root / (fixed_id + ".body")).read_bytes() == original_body
    assert (private_root / (fixed_id + ".json")).read_bytes() == original_manifest
    assert verify_private_source_record(private_root, fixed_id) == first


def test_existing_manifest_collision_never_erases_prior_file(private_root):
    archive = _archive(private_root)
    fixed_id = "b" * 32
    path = private_root / (fixed_id + ".json")
    old_manifest = b"do not overwrite existing evidence"
    path.write_bytes(old_manifest)
    path.chmod(0o600)
    with patch(
        "collector.private_source_archive.secrets.token_hex",
        return_value=fixed_id,
    ):
        with pytest.raises(FileExistsError):
            archive.write_body(WIN_BYTES, _evidence())
    assert path.read_bytes() == old_manifest
    assert not (private_root / (fixed_id + ".body")).exists()


def test_readback_cli_reports_only_provenance_without_original_bytes(private_root):
    record = _archive(private_root).write_body(WIN_BYTES, _evidence())
    command = [
        sys.executable, "-m", "collector.private_source_archive",
        "--archive-root", str(private_root),
        "--record-id", record["record_id"],
    ]
    response = subprocess.run(command, capture_output=True, text=True, check=False)
    assert response.returncode == 0, response.stderr
    returned = json.loads(response.stdout)
    assert returned == record
    assert returned["private_readback_sha256_verified"] is True
    assert returned["bet_authorized"] is False
    assert WIN_BYTES.decode("utf-8") not in response.stdout
    assert str(private_root) not in response.stdout


def test_readback_cli_cannot_approve_tampered_source_bytes(private_root):
    record = _archive(private_root).write_body(WIN_BYTES, _evidence())
    (private_root / (record["record_id"] + ".body")).write_bytes(b'{"wrong":true}')
    response = subprocess.run(
        [
            sys.executable, "-m", "collector.private_source_archive",
            "--archive-root", str(private_root),
            "--record-id", record["record_id"],
        ],
        capture_output=True, text=True, check=False,
    )
    assert response.returncode != 0
    assert "PRIVATE_BODY_READBACK_SHA256_MISMATCH" in response.stderr
    assert "private_readback_sha256_verified" not in response.stdout

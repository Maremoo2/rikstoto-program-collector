"""Opt-in, local-only archive of public Playwright response bodies.

No network, provider access, bets, model changes or GitHub artifact upload.
Requires an EXISTING, private (0700), user-owned directory outside the repo.
Never accepts private or unvalidated responses. SHA-256 proves byte identity
after readback, NOT independent publisher authority, wire-byte identity, or
tamper-proof storage. Use only on explicitly permitted public sources.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any

ROOT_SCHEMA = "phase_b_private_response_archive_v1"
ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
MEETING_PATTERN = re.compile(r"[A-Z0-9_]{3,80}|[A-Z0-9_]{3,69}_\d{4}-\d{2}-\d{2}\Z")
FILE_MODE = 0o600
ROOT_MODE = 0o700


class PrivateArchiveRejected(ValueError):
    """Archive input or private local storage is unsafe or inconsistent."""


def _private_root(root: Path) -> Path:
    if not isinstance(root, Path) or not root.is_absolute():
        raise PrivateArchiveRejected("ARCHIVE_ROOT_MUST_BE_ABSOLUTE")
    if root.is_symlink() or not root.exists() or not root.is_dir():
        raise PrivateArchiveRejected("ARCHIVE_ROOT_MUST_EXIST_NOT_SYMLINK")
    resolved = root.resolve(strict=True)
    if resolved != root or root.is_symlink():
        raise PrivateArchiveRejected("ARCHIVE_ROOT_HAS_SYMLINK_COMPONENT")
    status = root.stat()
    if status.st_uid != os.geteuid() or stat.S_IMODE(status.st_mode) & 0o077:
        raise PrivateArchiveRejected("ARCHIVE_ROOT_MUST_BE_USER_OWNED_0700")
    repository = Path(__file__).resolve().parents[1]
    if resolved.is_relative_to(repository):
        raise PrivateArchiveRejected("ARCHIVE_ROOT_MUST_BE_OUTSIDE_REPOSITORY")
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace and resolved.is_relative_to(Path(workspace).resolve()):
        raise PrivateArchiveRejected("ARCHIVE_ROOT_MUST_BE_OUTSIDE_ACTIONS_WORKSPACE")
    return resolved


def _read_private(root: Path, filename: str) -> bytes:
    if filename not in {Path(filename).name}:
        raise PrivateArchiveRejected("INVALID_ARCHIVE_FILENAME")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(root / filename, flags)
    except (OSError, ValueError) as exc:
        raise PrivateArchiveRejected("PRIVATE_RECORD_NOT_READABLE") from exc
    with os.fdopen(fd, "rb") as stream:
        status = os.fstat(stream.fileno())
        if (not stat.S_ISREG(status.st_mode)
                or status.st_uid != os.geteuid()
                or stat.S_IMODE(status.st_mode) & 0o077):
            raise PrivateArchiveRejected("PRIVATE_RECORD_NOT_REGULAR_0600")
        return stream.read()


def _write_exclusive(root: Path, filename: str, body: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(root / filename, flags, FILE_MODE)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())


def verify_private_source_record(root: Path, record_id: str) -> dict[str, Any]:
    """Independently reopen both local files and check exact byte provenance."""
    root = _private_root(root)
    if not isinstance(record_id, str) or not ID_PATTERN.fullmatch(record_id):
        raise PrivateArchiveRejected("INVALID_RECORD_ID")
    manifest_bytes = _read_private(root, record_id + ".json")
    try:
        manifest = json.loads(manifest_bytes)
    except (ValueError, UnicodeError) as exc:
        raise PrivateArchiveRejected("PRIVATE_MANIFEST_UNREADABLE") from exc
    if (not isinstance(manifest, dict)
            or manifest.get("schema") != ROOT_SCHEMA
            or manifest.get("record_id") != record_id
            or manifest.get("body_filename") != record_id + ".body"
            or manifest.get("source_authority_independently_verified") is not False
            or manifest.get("bet_authorized") is not False):
        raise PrivateArchiveRejected("PRIVATE_MANIFEST_IDENTITY_INVALID")
    blob = _read_private(root, record_id + ".body")
    digest = hashlib.sha256(blob).hexdigest()
    if (len(blob) != manifest.get("body_byte_length")
            or digest != manifest.get("playwright_body_sha256")):
        raise PrivateArchiveRejected("PRIVATE_BODY_READBACK_SHA256_MISMATCH")
    return {
        "record_id": record_id,
        "schema": ROOT_SCHEMA,
        "playwright_body_sha256": digest,
        "body_byte_length": len(blob),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "private_readback_sha256_verified": True,
        "source_authority_independently_verified": False,
        "raw_http_wire_bytes_verified": False,
        "immutable_or_signed_manifest_verified": False,
        "bet_authorized": False,
    }


class PrivateSourceArchive:
    """Explicit opt-in archive scope bound to one target race."""

    def __init__(self, root: Path, *, meeting_id: str, race_number: int):
        self.root = _private_root(root)
        if (not isinstance(meeting_id, str)
                or not MEETING_PATTERN.fullmatch(meeting_id)
                or type(race_number) is not int
                or not 1 <= race_number <= 99):
            raise PrivateArchiveRejected("TARGET_RACE_IDENTITY_INVALID")
        self.meeting_id = meeting_id
        self.race_number = race_number

    def write_body(
        self, body: bytes, evidence: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically publish the manifest only AFTER body write/readback.

        Archive is local and append-only through exclusive random filenames.
        A manifest may be deleted/edited by the owner: no immutability claim.
        """
        digest = hashlib.sha256(body).hexdigest()
        if (evidence.get("schema") != "phase_b_public_response_body_evidence_v1"
                or evidence.get("source_kind") not in {"WIN_ODDS", "OFFICIAL_STARTLIST"}
                or evidence.get("playwright_body_sha256") != digest
                or evidence.get("body_byte_length") != len(body)
                or evidence.get("body_bytes_archived_and_readback_verified") is not False
                or evidence.get("bet_authorized") is not False):
            raise PrivateArchiveRejected("UNVERIFIED_SOURCE_BODY_EVIDENCE")
        record_id = secrets.token_hex(16)
        body_filename, manifest_filename = record_id + ".body", record_id + ".json"
        manifest = {
            "schema": ROOT_SCHEMA,
            "record_id": record_id,
            "body_filename": body_filename,
            "source_kind": evidence["source_kind"],
            "source_path_no_query": evidence["source_path_no_query"],
            "meeting_id_claimed_by_probe": self.meeting_id,
            "race_number_claimed_by_probe": self.race_number,
            "captured_utc": evidence["captured_utc"],
            "hash_scope": evidence["hash_scope"],
            "playwright_body_sha256": digest,
            "body_byte_length": len(body),
            "source_authority_independently_verified": False,
            "raw_http_wire_bytes_verified": False,
            "immutable_or_signed_manifest_verified": False,
            "bet_authorized": False,
        }
        encoded_manifest = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n"
        ).encode("utf-8")
        try:
            _write_exclusive(self.root, body_filename, body)
            # Independently reopen the original body bytes before manifest
            # publication; no reserialized JSON is used as a substitute.
            actual = _read_private(self.root, body_filename)
            if hashlib.sha256(actual).hexdigest() != digest or actual != body:
                raise PrivateArchiveRejected("PRIVATE_BODY_READBACK_SHA256_MISMATCH")
            _write_exclusive(self.root, manifest_filename, encoded_manifest)
            verified = verify_private_source_record(self.root, record_id)
        except (OSError, PrivateArchiveRejected):
            # No incomplete record can remain classified as verified.
            for filename in (manifest_filename, body_filename):
                try:
                    (self.root / filename).unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        return verified

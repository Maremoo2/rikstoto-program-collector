"""Raw HTTP JSON provenance tests. Synthetic payloads, no live request."""

import hashlib
import json
from pathlib import Path

import pytest

from collector.source_integrity import archive_json_bytes


def test_raw_bytes_survive_without_normalization_and_wrapper_hash_is_separate(tmp_path):
    raw = b'{ "result" : [1,2], "success": true }\n'
    path = tmp_path / "discovery_calendar.json"
    value, receipt = archive_json_bytes(
        raw, path, url="https://www.rikstoto.no/api/racedays",
        observed_at_utc="2026-10-31T06:17:25Z")
    assert value == {"result": [1, 2], "success": True}
    assert (tmp_path / "discovery_calendar.raw.json").read_bytes() == raw
    assert receipt["sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["wrapper_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert receipt["sha256"] != receipt["wrapper_sha256"]
    assert receipt["raw_bytes"] == len(raw)
    assert receipt["raw_readback_verified"] is True
    assert receipt["source_publication_time_attested"] is False
    wrapper = json.loads(path.read_bytes())
    assert wrapper["source_url"] == "https://www.rikstoto.no/api/racedays"
    assert wrapper["fetched_utc"] == "2026-10-31T06:17:25Z"
    assert wrapper["response"] == value


def test_raw_json_retains_original_unicode_bytes(tmp_path):
    raw = '{"horse":"Åse","ok":true}'.encode("utf-8")
    value, proof = archive_json_bytes(raw, tmp_path / "starts.json",
                                     url="https://www.rikstoto.no/api/racedays/x/starts",
                                     observed_at_utc="2026-10-31T06:00:00Z")
    assert value["horse"] == "Åse"
    assert (tmp_path / "starts.raw.json").read_bytes() == raw
    assert proof["raw_bytes"] == len(raw)


def test_invalid_json_cannot_produce_a_successful_raw_receipt(tmp_path):
    with pytest.raises(ValueError):
        archive_json_bytes(b"{bad", tmp_path / "starts.json",
                           url="https://www.rikstoto.no/api/racedays",
                           observed_at_utc="2026-10-31T06:00:00Z")
    assert not (tmp_path / "starts.json").exists()
    assert not (tmp_path / "starts.raw.json").exists()


def test_raw_readback_corruption_is_a_hard_error(tmp_path, monkeypatch):
    old = Path.read_bytes

    def tampered(path):
        if path.name.endswith(".raw.json"):
            return b"TAMPERED"
        return old(path)

    monkeypatch.setattr(Path, "read_bytes", tampered)
    with pytest.raises(OSError, match="RAW_JSON_READBACK_SHA_MISMATCH"):
        archive_json_bytes(b'{"a":1}', tmp_path / "starts.json",
                           url="https://www.rikstoto.no/api/racedays",
                           observed_at_utc="2026-10-31T06:00:00Z")


def test_wrapper_readback_corruption_is_a_hard_error(tmp_path, monkeypatch):
    old = Path.read_bytes

    def tampered(path):
        if path.name == "starts.json":
            return b"TAMPERED"
        return old(path)

    monkeypatch.setattr(Path, "read_bytes", tampered)
    with pytest.raises(OSError, match="WRAPPER_JSON_READBACK_SHA_MISMATCH"):
        archive_json_bytes(b'{"a":1}', tmp_path / "starts.json",
                           url="https://www.rikstoto.no/api/racedays",
                           observed_at_utc="2026-10-31T06:00:00Z")


@pytest.mark.parametrize("bad_destination", ["starts.txt", "starts.pdf"])
def test_non_json_destination_rejected(tmp_path, bad_destination):
    with pytest.raises(ValueError, match="destination"):
        archive_json_bytes(b'{"a":1}', tmp_path / bad_destination,
                           url="https://www.rikstoto.no/api/racedays",
                           observed_at_utc="2026-10-31T06:00:00Z")

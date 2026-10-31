"""Synthetic ZIP source-receipt checks. No independent date/PIT attestation."""
import hashlib
import json
import zipfile

from collector.archive_integrity_audit import audit_archive_zip


DAY = "2026-10-31"
RUN = "20261031T061717822793Z"


def _make(tmp_path, *, legacy=False, raw_tampered=False,
          wrapper_tampered=False, release=False, extra=None):
    path = tmp_path / "daily.zip"
    root = f"{DAY}/{RUN}/" if release else f"output/daily/{DAY}/{RUN}/"
    def original_key(name):
        return f"output/daily/{DAY}/{RUN}/{name}"

    raw = b'{ "success":true, "result":[] }\n'
    wrapped = json.dumps({"source_url": "https://www.rikstoto.no/api/racedays",
                          "fetched_utc": "2026-10-31T06:17:25Z",
                          "response": json.loads(raw)}).encode()
    pdf = b"%PDF-1.4\nsource-file"
    receipts = [
        {"status": "PDF_OK", "sha256": hashlib.sha256(pdf).hexdigest(),
         "path": original_key("meetings/BJ/full_program.pdf")},
        {"status": "JSON_OK", "sha256": hashlib.sha256(raw).hexdigest(),
         "path": original_key("discovery_calendar.json")},
    ]
    if not legacy:
        receipts[1].update({
            "raw_path": original_key("discovery_calendar.raw.json"),
            "wrapper_sha256": hashlib.sha256(wrapped).hexdigest(),
            "raw_readback_verified": True,
        })
    manifest = {
        "date_oslo": DAY, "run_id": RUN, "requests": receipts,
        "meetings": [{"meeting_id": "BJ_NR_2026-10-31",
                      "is_multi_track_product": False}],
        "counts": {"unique_track_races": 8, "unique_track_horses": 95},
        "status": "CAPTURED_UNVERIFIED", "completeness_verified": False,
        "calendar_source_diagnostic": {"status": "EMPTY_RESULT_ARRAY"},
    }
    with zipfile.ZipFile(path, "w") as out:
        out.writestr(root + "manifest.json", json.dumps(manifest))
        out.writestr(root + "meetings/BJ/full_program.pdf", pdf)
        out.writestr(root + "discovery_calendar.json",
                     b'TAMPER' if wrapper_tampered else wrapped)
        if not legacy:
            out.writestr(root + "discovery_calendar.raw.json",
                         b'TAMPER' if raw_tampered else raw)
        if extra is not None:
            out.writestr(extra, b"extra")
    return path


def test_new_exact_original_http_bytes_and_wrapper_both_attested(tmp_path):
    result = audit_archive_zip(_make(tmp_path))
    assert result["status"] == "AUDITED_SOURCE_BYTES_UNVERIFIED_DAY"
    assert result["errors"] == []
    assert result["pdf_raw_sha_verified"] == 1
    assert result["json_raw_sha_verified"] == 1
    assert result["json_wrapper_sha_verified"] == 1
    assert result["json_raw_unavailable_legacy"] == 0
    assert result["raw_provenance_complete"] is True
    assert result["physical_meeting_candidates"] == 1
    assert result["reported_unique_track_races"] == 8
    assert result["completeness_verified"] is False
    assert result["pit_certified"] is False


def test_legacy_pre_fix_archive_never_claims_original_json_hash(tmp_path):
    result = audit_archive_zip(_make(tmp_path, legacy=True))
    assert result["errors"] == []
    assert result["json_raw_unavailable_legacy"] == 1
    assert result["json_raw_sha_verified"] == 0
    assert result["pdf_raw_sha_verified"] == 1
    assert result["raw_provenance_complete"] is False
    assert result["completeness_verified"] is False


def test_release_asset_repacked_path_does_not_lose_receipts(tmp_path):
    result = audit_archive_zip(_make(tmp_path, release=True))
    assert result["raw_provenance_complete"] is True
    assert result["errors"] == []


def test_raw_body_corruption_is_a_blocker(tmp_path):
    result = audit_archive_zip(_make(tmp_path, raw_tampered=True))
    assert result["status"] == "BLOCKED"
    assert "JSON_ORIGINAL_SHA_MISMATCH" in result["errors"]
    assert result["completeness_verified"] is False


def test_wrapper_corruption_is_a_blocker(tmp_path):
    result = audit_archive_zip(_make(tmp_path, wrapper_tampered=True))
    assert result["status"] == "BLOCKED"
    assert "JSON_WRAPPER_SHA_MISMATCH" in result["errors"]


def test_unsafe_archive_path_fails_closed(tmp_path):
    result = audit_archive_zip(_make(tmp_path, extra="../escape.txt"))
    assert result["status"] == "BLOCKED"
    assert "UNSAFE_ZIP_PATH" in result["errors"]


def test_bad_archive_never_succeeds(tmp_path):
    target = tmp_path / "invalid.zip"
    target.write_bytes(b"NOT A ZIP")
    result = audit_archive_zip(target)
    assert result["status"] == "BLOCKED"
    assert result["errors"] == ["ARCHIVE_UNREADABLE:BadZipFile"]

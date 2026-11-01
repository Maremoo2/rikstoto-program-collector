"""Synthetic ZIP source-receipt checks. No independent date/PIT attestation."""
import hashlib
import json
import zipfile

from collector.archive_integrity_audit import audit_archive_zip


DAY = "2026-10-31"
RUN = "20261031T061717822793Z"


def _make(tmp_path, *, legacy=False, raw_tampered=False,
          wrapper_tampered=False, release=False, extra=None,
          duplicate_success=None, reused_original_raw=False, collision=False):
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
         "path": original_key("meetings/BJ/full_program.pdf"),
         "url": "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/BJ"},
        {"status": "JSON_OK", "sha256": hashlib.sha256(raw).hexdigest(),
         "path": original_key("discovery_calendar.json")},
    ]
    if not legacy:
        receipts[1].update({
            "raw_path": original_key("discovery_calendar.raw.json"),
            "wrapper_sha256": hashlib.sha256(wrapped).hexdigest(),
            "raw_readback_verified": True,
        })
    if duplicate_success in {"JSON", "PDF"}:
        receipts.append(dict(receipts[1 if duplicate_success == "JSON" else 0]))
    if reused_original_raw:
        receipts.append({
            **receipts[1], "path": original_key("additional_wrapper.json"),
        })
    if collision:
        receipts.append({
            "status": "SOURCE_ARCHIVE_COLLISION",
            "path": original_key("discovery_calendar.json"),
            "source_type": "JSON",
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
        if reused_original_raw:
            out.writestr(root + "additional_wrapper.json", wrapped)
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



def test_repeated_successful_original_pdf_path_is_not_two_distinct_sources(tmp_path):
    result = audit_archive_zip(_make(tmp_path, duplicate_success="PDF"))
    assert result["status"] == "BLOCKED"
    assert "DUPLICATE_SUCCESSFUL_SOURCE_PATH" in result["errors"]
    assert result["raw_provenance_complete"] is False


def test_same_original_json_wrapper_path_cannot_attest_two_http_responses(tmp_path):
    result = audit_archive_zip(_make(tmp_path, duplicate_success="JSON"))
    assert result["status"] == "BLOCKED"
    assert "DUPLICATE_SUCCESSFUL_SOURCE_PATH" in result["errors"]
    assert result["json_raw_sha_verified"] == 1
    assert result["raw_provenance_complete"] is False


def test_one_raw_json_path_cannot_be_referenced_by_two_wrappers(tmp_path):
    result = audit_archive_zip(_make(tmp_path, reused_original_raw=True))
    assert result["status"] == "BLOCKED"
    assert "REUSED_OR_INVALID_ORIGINAL_JSON_RAW_PATH" in result["errors"]
    assert result["raw_provenance_complete"] is False



def test_archived_failed_source_collision_blocks_raw_day_even_if_other_sources_good(tmp_path):
    result = audit_archive_zip(_make(tmp_path, collision=True))
    assert result["status"] == "BLOCKED"
    assert result["json_raw_sha_verified"] == 1
    assert result["pdf_raw_sha_verified"] == 1
    assert "ORIGINAL_SOURCE_PATH_COLLISION_OBSERVED" in result["errors"]
    assert result["raw_provenance_complete"] is False
    assert result["pit_certified"] is False



def test_valid_sha_from_another_capture_cannot_attest_this_day(tmp_path):
    """Foreign ZIP members must not satisfy a receipt in today's manifest."""
    target = _make(tmp_path)
    with zipfile.ZipFile(target) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    manifest_name = next(name for name in entries if name.endswith("/manifest.json"))
    manifest = json.loads(entries[manifest_name])
    receipt = next(row for row in manifest["requests"]
                   if row.get("status") == "PDF_OK")
    own_path = receipt["path"]
    foreign_path = own_path.replace(f"/{DAY}/{RUN}/", f"/2026-10-30/{RUN}/")
    assert foreign_path != own_path
    # The preserved PDF body still has the same valid SHA, but it lives
    # under a different capture identity; no source has been forged.
    entries[foreign_path] = entries.pop(own_path)
    receipt["path"] = foreign_path
    entries[manifest_name] = json.dumps(manifest).encode()
    with zipfile.ZipFile(target, "w") as rewritten:
        for name, body in entries.items():
            rewritten.writestr(name, body)
    result = audit_archive_zip(target)
    assert result["status"] == "BLOCKED"
    assert "PDF_ARCHIVE_PATH_MISSING" in result["errors"]
    assert result["raw_provenance_complete"] is False
    assert result["pit_certified"] is False


def test_json_raw_cannot_be_borrowed_from_other_capture(tmp_path):
    target = _make(tmp_path)
    with zipfile.ZipFile(target) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    manifest_name = next(name for name in entries if name.endswith("/manifest.json"))
    manifest = json.loads(entries[manifest_name])
    receipt = next(row for row in manifest["requests"]
                   if row.get("status") == "JSON_OK")
    own_path = receipt["raw_path"]
    foreign_path = own_path.replace(f"/{DAY}/{RUN}/", f"/2026-10-30/{RUN}/")
    entries[foreign_path] = entries.pop(own_path)
    receipt["raw_path"] = foreign_path
    entries[manifest_name] = json.dumps(manifest).encode()
    with zipfile.ZipFile(target, "w") as rewritten:
        for name, body in entries.items():
            rewritten.writestr(name, body)
    result = audit_archive_zip(target)
    assert result["status"] == "BLOCKED"
    assert "JSON_ORIGINAL_OR_WRAPPER_NOT_ARCHIVED" in result["errors"]
    assert result["raw_provenance_complete"] is False


def test_same_day_different_capture_cannot_attest_original_pdf(tmp_path):
    """Same racing date is insufficient; run-id must also agree."""
    target = _make(tmp_path)
    with zipfile.ZipFile(target) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    manifest_name = next(name for name in entries if name.endswith("/manifest.json"))
    manifest = json.loads(entries[manifest_name])
    receipt = next(r for r in manifest["requests"] if r["status"] == "PDF_OK")
    own_path = receipt["path"]
    foreign_path = own_path.replace(
        f"/{DAY}/{RUN}/", f"/{DAY}/20261031T060000000000Z/"
    )
    assert foreign_path != own_path
    entries[foreign_path] = entries.pop(own_path)
    receipt["path"] = foreign_path
    entries[manifest_name] = json.dumps(manifest).encode()
    with zipfile.ZipFile(target, "w") as rewritten:
        for name, body in entries.items():
            rewritten.writestr(name, body)
    report = audit_archive_zip(target)
    assert report["status"] == "BLOCKED"
    assert "PDF_ARCHIVE_PATH_MISSING" in report["errors"]
    assert report["raw_provenance_complete"] is False


def test_manifest_does_not_attest_foreign_capture_path(tmp_path):
    target = _make(tmp_path)
    with zipfile.ZipFile(target) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    manifest_name = next(name for name in entries if name.endswith("/manifest.json"))
    manifest = json.loads(entries[manifest_name])
    manifest["run_id"] = "20261031T060000000000Z"
    entries[manifest_name] = json.dumps(manifest).encode()
    with zipfile.ZipFile(target, "w") as rewritten:
        for name, body in entries.items():
            rewritten.writestr(name, body)
    result = audit_archive_zip(target)
    assert result["status"] == "BLOCKED"
    assert "MANIFEST_IDENTITY_MISMATCH" in result["errors"]
    assert result["pit_certified"] is False


def test_pdf_meeting_source_uri_must_match_archived_meeting(tmp_path):
    """A byte-identical PDF from another meeting is not valid source proof."""
    target = _make(tmp_path)
    with zipfile.ZipFile(target) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    manifest_name = next(name for name in entries if name.endswith("/manifest.json"))
    manifest = json.loads(entries[manifest_name])
    receipt = next(row for row in manifest["requests"]
                   if row.get("status") == "PDF_OK")
    own_path = receipt["path"]
    wrong_meeting_path = own_path.replace("/meetings/BJ/", "/meetings/ST/")
    entries[wrong_meeting_path] = entries.pop(own_path)
    receipt["path"] = wrong_meeting_path
    entries[manifest_name] = json.dumps(manifest).encode()
    with zipfile.ZipFile(target, "w") as rewritten:
        for name, body in entries.items():
            rewritten.writestr(name, body)
    report = audit_archive_zip(target)
    assert report["status"] == "BLOCKED"
    assert "PDF_SOURCE_MEETING_IDENTITY_MISMATCH" in report["errors"]
    assert report["pdf_raw_sha_verified"] == 0
    assert report["pit_certified"] is False

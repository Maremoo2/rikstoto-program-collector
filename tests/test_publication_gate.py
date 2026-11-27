import json
from pathlib import Path
import zipfile

import pytest

from collector import daily
from collector.release_archive import main
from tests.test_roster_handoff import DAY, _fixture


@pytest.mark.parametrize(("status", "publication_flag", "expected"), [
    ("CAPTURED_UNVERIFIED", True, 0),
    ("REVIEW_REQUIRED", False, 1),
    ("REVIEW_REQUIRED", True, 3),
    ("ERROR", True, 1),
    ("UNKNOWN", True, 1),
])
def test_capture_exit_distinguishes_controlled_review(monkeypatch, tmp_path, status,
                                                      publication_flag, expected):
    async def capture(*args, **kwargs):
        return tmp_path, {"status": status}

    argv = ["daily", "--date", DAY]
    if publication_flag:
        argv.append("--publication-exit-status")
    monkeypatch.setattr(daily, "archive_day", capture)
    monkeypatch.setattr("sys.argv", argv)
    assert daily.main() == expected


@pytest.mark.parametrize("status", ["CAPTURED_UNVERIFIED", "REVIEW_REQUIRED"])
def test_publication_command_packages_verified_scope(tmp_path, status):
    root, folder, _ = _fixture(tmp_path)
    path = folder / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["status"] = status
    manifest["completeness_verified"] = False
    manifest["meetings"].append({
        "meeting_id": f"XX_NR_{DAY}", "listing_source": {"country": "NL"},
        "program_pdf": "SOURCE_UNAVAILABLE",
    })
    _write_manifest(folder, manifest)
    original = path.read_bytes()
    assert main(_command(tmp_path, root, status)) == 0
    [archive] = (tmp_path / "assets").glob("*.zip")
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert zipped.read(f"{DAY}/{manifest['run_id']}/manifest.json") == original
    index = json.loads((tmp_path / "feed" / "index.json").read_bytes())
    assert index["collection_status"] == status
    assert len(index["race_queue"]) == 1
    assert index["race_queue"][0]["official_roster_handoff_status"] == "VERIFIED_AS_OF_SOURCE_CAPTURE"
    assert (tmp_path / "github-output").is_file()


def _command(tmp_path, root, status="REVIEW_REQUIRED", date=DAY):
    return ["--root", str(root), "--dest", str(tmp_path / "assets"),
            "--publication-feed", str(tmp_path / "feed"), "--capture-date", date,
            "--capture-status", status, "--github-output", str(tmp_path / "github-output")]


def _write_manifest(folder, manifest):
    for receipt in manifest["requests"]:
        if receipt["status"] == "JSON_OK":
            receipt["bytes"] = (folder / Path(receipt["raw_path"]).relative_to(
                "output", "daily", DAY, folder.name)).stat().st_size
            receipt["wrapper_bytes"] = (folder / Path(receipt["path"]).relative_to(
                "output", "daily", DAY, folder.name)).stat().st_size
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.parametrize(("case", "reason"), [
    ("missing", "exactly one"),
    ("invalid", "Expecting"),
    ("unknown", "binding mismatch"),
    ("fatal", "binding mismatch"),
    ("wrong_date", "binding mismatch"),
    ("wrong_run", "date/run ID"),
    ("empty", "No individually"),
    ("unverified_roster", "No individually"),
    ("unverified_race", "No individually"),
    ("missing_receipt", "Missing original"),
    ("hash", "hash mismatch"),
    ("corrupt_original", "hash mismatch"),
    ("integrity_status", "integrity failure"),
    ("corrupt_zip", "ZIP integrity"),
])
def test_publication_command_rejects_before_emitting_authorization(tmp_path, monkeypatch, case, reason):
    root, folder, _ = _fixture(tmp_path, with_changes=case != "unverified_roster")
    path = folder / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["status"] = {"unknown": "UNKNOWN", "fatal": "ERROR"}.get(case, "REVIEW_REQUIRED")
    if case == "wrong_run":
        manifest["run_id"] = "20261018T050000000001Z"
    if case == "empty":
        manifest["meetings"].clear()
    if case == "unverified_race":
        manifest["meetings"][0]["startlist_pdf_audit"]["status"] = "PARTIAL_OR_UNVERIFIED"
    if case == "missing_receipt":
        manifest["requests"].pop()
    if case == "hash":
        manifest["requests"][0]["sha256"] = "0" * 64
    if case == "integrity_status":
        manifest["requests"].append({"status": "ARCHIVE_READBACK_FAILED"})
    if case == "corrupt_zip":
        monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: "manifest.json")
    _write_manifest(folder, manifest)
    if case == "corrupt_original":
        raw = next(folder.rglob("*.raw.json"))
        original = raw.read_bytes()
        raw.write_bytes(b"[" + original[1:])
    if case == "missing":
        path.unlink()
    if case == "invalid":
        path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match=reason):
        main(_command(tmp_path, root, date="2026-10-19" if case == "wrong_date" else DAY))
    assert not (tmp_path / "github-output").exists()
    if case == "unverified_roster":
        [row] = json.loads((tmp_path / "feed" / "index.json").read_bytes())["race_queue"]
        assert row["source_ready_snapshot"] is True
        assert row["official_roster_handoff_status"] != "VERIFIED_AS_OF_SOURCE_CAPTURE"

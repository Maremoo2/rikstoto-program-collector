"""Local-only reproducible archive packaging tests (no GitHub API)."""
import hashlib
import json
import zipfile

import pytest

from collector.release_archive import build_release_archive, find_latest_run


def test_package_source_files_with_timestamp_and_checksum(tmp_path):
    root = tmp_path / "daily"
    folder = root / "2026-10-18" / "20261018T070001123456Z"
    pdfdir = folder / "meetings" / "OR_NR_2026-10-18"
    pdfdir.mkdir(parents=True)
    (pdfdir / "full_program.pdf").write_bytes(b"%PDF-1.4\npublic example")
    (folder / "manifest.json").write_text(json.dumps({
        "date_oslo": "2026-10-18",
        "run_id": "20261018T070001123456Z",
        "status": "CAPTURED_UNVERIFIED", "meetings": [{"meeting_id": "OR_NR_2026-10-18"}],
    }))
    packaged = build_release_archive(root, tmp_path / "assets")
    assert packaged["tag"] == "rikstoto-program-2026-10-18"
    assert packaged["collection_status"] == "CAPTURED_UNVERIFIED"
    with zipfile.ZipFile(packaged["archive"]) as z:
        paths = sorted(z.namelist())
        assert len(paths) == 2
        assert all(path.startswith("2026-10-18/20261018T070001123456Z/") for path in paths)
        assert any(path.endswith("/full_program.pdf") for path in paths)
    digest = hashlib.sha256(open(packaged["archive"], "rb").read()).hexdigest()
    assert digest == packaged["sha256"]
    assert packaged["sha256"] in open(packaged["checksum"]).read()


def test_empty_archive_refused(tmp_path):
    with pytest.raises(ValueError, match="No daily manifest"):
        find_latest_run(tmp_path)


def test_mismatched_date_refused(tmp_path):
    folder = tmp_path / "daily" / "2026-10-18" / "20261018T070001123456Z"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({
        "date_oslo": "2026-10-17", "run_id": "20261018T070001123456Z"
    }))
    with pytest.raises(ValueError, match="does not match"):
        find_latest_run(tmp_path / "daily")

"""Regression tests for SHA-verified Pre-Watch roster handoff."""
import copy
import hashlib
import json

import pytest

from collector.prewatch_handoff import build_handoff, SCHEMA
from collector.roster_handoff import (
    compare_roster_snapshots, latest_snapshot_by_observation, roster_for_meeting,
)
from tests.test_prewatch_handoff import DAY, RUN, write_fixture


def _put_official(folder, manifest, mid, filename, value, stamp):
    tail = (
        f"/api/racedays/{mid}/starts" if filename == "starts.json"
        else f"/api/game/program/{mid}/driverChanges"
    )
    url = "https://www.rikstoto.no" + tail
    sub = folder / "meetings" / mid
    sub.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    wrapped = json.dumps({
        "source_url": url, "fetched_utc": stamp, "response": value
    }, ensure_ascii=False, indent=2).encode()
    path = sub / filename
    raw_path = path.with_name(path.stem + ".raw.json")
    path.write_bytes(wrapped)
    raw_path.write_bytes(raw)
    receipt = {
        "url": url, "status": "JSON_OK",
        "at_utc": stamp,
        "path": f"output/daily/{DAY}/{RUN}/meetings/{mid}/{filename}",
        "raw_path": f"output/daily/{DAY}/{RUN}/meetings/{mid}/{raw_path.name}",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "wrapper_sha256": hashlib.sha256(wrapped).hexdigest(),
        "raw_readback_verified": True,
        "source_publication_time_attested": False,
    }
    manifest.setdefault("requests", []).append(receipt)
    return path, raw_path


def _fixture(tmp_path, *, with_changes=True):
    root = write_fixture(tmp_path)
    folder = next(root.glob("*/*"))
    mid = "OR_NR_2026-10-18"
    mp = folder / "manifest.json"
    manifest = json.loads(mp.read_text())
    # Test the discrepancy itself: PDF prints the new name, while the
    # official starts response still has the earlier registered driver.
    dp = folder / "structured_program_day.json"
    data = json.loads(dp.read_text())
    data["races"][0]["entrants"][0]["driver"] = "Louane Leroux"
    data["races"][0]["entrants"][0]["scratch_state"] = "SCRATCHED_AS_OF_SNAPSHOT"
    dp.write_text(json.dumps(data))
    starts = {"success": True, "result": {
        "6": [{
            "raceNumber": 6, "raceKey": f"{mid}#6",
            "startNumber": 2, "horseName": "Lesja Loke",
            "driverName": "Martine Finsand", "isScratched": True
        }],
    }}
    _put_official(folder, manifest, mid, "starts.json", starts, "2026-10-18T05:00:05+00:00")
    if with_changes:
        change = {"success": True, "result": [{
            "raceNumber": 6, "raceKey": f"{mid}#6",
            "startNumber": 2, "newDriver": "Louane Leroux",
            "driverLicenseNumber": "30078856",
        }]}
        _put_official(folder, manifest, mid, "driver_changes.json",
                      change, "2026-10-18T05:00:15+00:00")
    mp.write_text(json.dumps(manifest))
    return root, folder, mid


def _build(tmp_path, *, with_changes=True):
    root, folder, mid = _fixture(tmp_path, with_changes=with_changes)
    dest = tmp_path / "handoff"
    index = build_handoff(root, dest)
    return root, folder, mid, index, dest


def test_official_driver_change_and_scratch_replay(tmp_path):
    _, _, _, index, dest = _build(tmp_path)
    race = index["race_queue"][0]
    assert index["schema"] == SCHEMA
    assert index["snapshot_observed_utc"] == "2026-10-18T05:00:15+00:00"
    assert race["source_ready_snapshot"] is True
    assert race["official_roster_handoff_status"] == "VERIFIED_AS_OF_SOURCE_CAPTURE"
    assert len(race["official_roster"]) == 1
    assert race["official_roster"][0]["is_scratched"] is True
    assert race["official_roster"][0]["original_official_driver"] == "Martine Finsand"
    assert race["official_roster"][0]["original_pdf_driver"] == "Louane Leroux"
    assert race["official_roster"][0]["effective_driver"] == "Louane Leroux"
    assert race["official_driver_changes"][0]["new_driver"] == "Louane Leroux"
    assert race["official_starts_source"]["sha256"]
    assert race["official_driver_changes_source"]["sha256"]
    body = (dest / index["meeting_feeds"][0]["markdown_name"]).read_text()
    assert "OFFICIAL_DRIVER_CHANGE previous_driver=Martine Finsand" in body
    assert "effective_driver=Louane Leroux" in body
    assert "SCRATCHED_AS_OF_SNAPSHOT" in body
    assert "05.10.26-3" in body


def test_machine_race_pack_preserves_whole_original_field_and_source_hashes(tmp_path):
    _, folder, _, index, dest = _build(tmp_path)
    race = index["race_queue"][0]
    payload = (dest / race["race_pack_file"]).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == race["race_pack_sha256"]
    pack = json.loads(payload)
    original_bytes = (folder / "structured_program_day.json").read_bytes()
    original = json.loads(original_bytes)["races"][0]
    assert pack["program"] == original
    assert pack["structured_original_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert pack["manifest_sha256"] == hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest()
    assert pack["race_id"] == "RIKSTOTO:OR_NR_2026-10-18:6"
    assert pack["official_roster"]["runners"] == race["official_roster"]
    assert pack["source_run_id"] == index["run_id"]
    assert pack["phase_a_completed"] is False
    assert pack["bet_authority"] is False
    assert pack["missing_or_unverified"]
    # Repeat packaging is stable, but a conflicting pack must not overwrite
    # any previously frozen bytes.
    build_handoff(folder.parent.parent, dest)
    assert (dest / race["race_pack_file"]).read_bytes() == payload
    (dest / race["race_pack_file"]).write_bytes(b"conflicting existing artifact")
    with pytest.raises(ValueError, match="RACE_PACK_READBACK_CONFLICT"):
        build_handoff(folder.parent.parent, dest)


def test_missing_driver_change_source_does_not_imply_no_changes(tmp_path):
    _, _, _, index, dest = _build(tmp_path, with_changes=False)
    race = index["race_queue"][0]
    assert race["official_roster_handoff_status"] == "ROSTER_EVIDENCE_UNVERIFIED"
    assert race["official_roster_first_blocker"] == "SOURCE_RECEIPT_NOT_UNIQUE"
    assert race["official_roster"] == []
    body = (dest / index["meeting_feeds"][0]["markdown_name"]).read_text()
    assert "official_roster_handoff_status=ROSTER_EVIDENCE_UNVERIFIED" in body
    assert "effective_driver=" not in body
    assert "Lesja Loke" in body


def test_tampered_source_fails_closed_even_when_wrapper_is_unchanged(tmp_path):
    root, folder, mid = _fixture(tmp_path)
    (folder / "meetings" / mid / "driver_changes.raw.json").write_bytes(b"{}")
    index = build_handoff(root, tmp_path / "out")
    race = index["race_queue"][0]
    assert race["official_roster_first_blocker"] == "SOURCE_SHA_MISMATCH"
    assert race["official_driver_changes"] == []


def test_unrecognized_driver_change_identity_blocks_effective_driver(tmp_path):
    root, folder, mid = _fixture(tmp_path)
    path = folder / "meetings" / mid / "driver_changes.json"
    raw_path = path.with_name("driver_changes.raw.json")
    # Must keep SHA receipts internally consistent to isolate identity rejection.
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["requests"] = [r for r in manifest["requests"] if "driverChanges" not in r["url"]]
    path.unlink()
    raw_path.unlink()
    _put_official(folder, manifest, mid, "driver_changes.json",
                  {"success": True, "result": [{
                      "raceNumber": 6, "startNumber": 99,
                      "newDriver": "Unknown", "raceKey": f"{mid}#6"
                  }]}, "2026-10-18T05:00:16+00:00")
    manifest_path.write_text(json.dumps(manifest))
    index = build_handoff(root, tmp_path / "out")
    race = index["race_queue"][0]
    assert race["official_roster_first_blocker"] == "DRIVER_CHANGE_IDENTITY_INVALID"
    assert race["official_roster"] == []


def test_latest_snapshot_selection_is_by_observed_time_not_release_order():
    def item(run, stamp):
        return {
            "schema": SCHEMA, "date_oslo": DAY, "run_id": run,
            "source_archive_tag": f"rikstoto-program-{DAY}-{run}",
            "snapshot_observed_utc": stamp,
        }
    late = item("20261018T120001123456Z", "2026-10-18T12:00:29+00:00")
    early = item("20261018T050001123456Z", "2026-10-18T05:00:29+00:00")
    wrong_day = item("20261017T050001123456Z", "2026-10-18T15:00:29+00:00")
    assert latest_snapshot_by_observation(
        [early, wrong_day, late], DAY
    ) is late
    assert latest_snapshot_by_observation([late, early], DAY) is late
    assert latest_snapshot_by_observation([dict(early, snapshot_observed_utc=None)], DAY) is None


def test_two_immutable_snapshots_can_be_diffed_without_merging():
    before = {
        "status": "VERIFIED_AS_OF_SOURCE_CAPTURE", "source_run_id": "old",
        "runners": [{"start_number": 2, "horse_name": "Dea Orientis W.H.",
                     "is_scratched": False, "effective_driver": "Martine Finsand"}],
    }
    after = copy.deepcopy(before)
    after["source_run_id"] = "new"
    after["runners"][0]["effective_driver"] = "Louane Leroux"
    after["runners"][0]["is_scratched"] = True
    changes = compare_roster_snapshots(before, after)
    assert len(changes) == 2
    assert {c["field"] for c in changes} == {"effective_driver", "is_scratched"}
    assert before["runners"][0]["effective_driver"] == "Martine Finsand"
    with pytest.raises(ValueError, match="full field|Full field"):
        compare_roster_snapshots(before, dict(after, runners=[]))


def test_handoff_keeps_original_snapshot_bytes_unchanged(tmp_path):
    root, folder, mid = _fixture(tmp_path)
    original = {
        p.relative_to(folder): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*") if p.is_file()
    }
    result = build_handoff(root, tmp_path / "handoff")
    assert result["race_count"] == 1
    assert original == {
        p.relative_to(folder): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*") if p.is_file()
    }


def test_no_newer_snapshot_does_not_claim_updated_roster(tmp_path):
    _, _, _, index, _ = _build(tmp_path)
    race = index["race_queue"][0]
    assert race["official_roster_handoff_status"] == "VERIFIED_AS_OF_SOURCE_CAPTURE"
    assert race["official_starts_source"]["source_publication_time_attested"] is False
    assert index["snapshot_clock_source"] == "LATEST_OFFICIAL_ROSTER_RECEIPT"
    # Date-time is the collector's GET observation, NOT a promise of live status.
    assert race["official_starts_source"]["observed_utc"].startswith(DAY)

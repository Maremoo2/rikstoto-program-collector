"""Offline interface tests for Pre-Watch-to-GitHub draft release handoff."""
import json
from pathlib import Path

import pytest

from collector.prewatch_handoff import build_handoff, SCHEMA


RUN = "20261018T070001123456Z"
DAY = "2026-10-18"


def write_fixture(tmp_path):
    root = tmp_path / "daily"
    folder = root / DAY / RUN
    folder.mkdir(parents=True)
    entries = [
        {"meeting_id": "OR_NR_2026-10-18", "is_multi_track_product": False,
         "listing_source": {"country": "NO", "track": "Varig Orkla"},
         "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT"}},
        {"meeting_id": "X1_NR_2026-10-18", "is_multi_track_product": True,
         "listing_source": {"country": "", "track": "Xpress"}},
        {"meeting_id": "F1_NR_2026-10-18", "is_multi_track_product": False,
         "listing_source": {"country": "FR", "track": "Parislongchamp"}},
    ]
    manifest = {"date_oslo": DAY, "run_id": RUN,
                "status": "CAPTURED_UNVERIFIED",
                "created_utc": "2026-10-18T05:00:01Z",
                "schedule_comparison": {"status": "CROSS_SOURCE_AGREEMENT"},
                "meetings": entries}
    horse = {"program_number": 2, "name": "Lesja Loke", "driver": "Test Driver",
             "scratch_state": "SCRATCHED_AS_OF_SNAPSHOT",
             "scratch_captured_utc": "2026-10-18T05:00:02Z",
             "past_starts": [
                 {"date": "2026-10-05", "race_number": 3,
                  "raw_text": "Test Dr OA 05.10.26-3|2 4 5 2300 35,8 galopp"},
                 {"date": "2026-09-28", "race_number": 6,
                  "raw_text": "Test Dr OA 28.09.26-6|1 1 2 2300 32,7"}
             ]}
    race = {"race": {"meeting_id": "OR_NR_2026-10-18", "race_number": 6,
                     "track": "Varig Orkla", "scheduled_time_local": "20:47",
                     "distance_m": 1720, "start_method": "Voltestart",
                     "source_url": "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/OR_NR_2026-10-18",
                     "captured_at_utc": "2026-10-18T05:00:01Z",
                     "race_number_source": "pdf_heading"},
            "qa": {"past_start_rows": 2, "warnings": ["SCRATCH_STATUS_MAY_CHANGE"],
                   "scratch_verification": "COMPLETE_AS_OF_SNAPSHOT"},
            "entrants": [horse]}
    structured = {"date": DAY, "run_id": RUN,
                  "races": [race, dict(race, race=dict(race["race"],
                                                    meeting_id="X1_NR_2026-10-18"))]}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "structured_program_day.json").write_text(json.dumps(structured), encoding="utf-8")
    return root


def test_one_meeting_feed_excludes_composite_and_france(tmp_path):
    root = write_fixture(tmp_path)
    dest = tmp_path / "handoff"
    result = build_handoff(root, dest)
    assert result["schema"] == SCHEMA
    assert result["meeting_count"] == 1
    assert result["race_count"] == 1
    assert result["runner_count"] == 1
    assert len(result["meeting_feeds"]) == 1
    part = result["meeting_feeds"][0]
    body = (dest / part["markdown_name"]).read_text(encoding="utf-8")
    assert "Lesja Loke" in body
    assert "SCRATCHED_AS_OF_SNAPSHOT" in body
    assert "05.10.26-3" in body
    assert "previous_race=6" in body
    assert "X1_NR" not in body
    assert "F1_NR" not in body
    assert len(body) <= 95_000
    assert part["race_numbers"] == [6]
    assert "race_numbers=[6]" in (dest / "index.md").read_text(encoding="utf-8")
    assert "not a betting recommendation" in body
    assert result["date_oslo"] == DAY
    assert "prewatch-src-2026-10-18-OR_NR_2026-10-18" in part["release_tag"]


def test_run_mismatch_fails_no_handoff(tmp_path):
    root = write_fixture(tmp_path)
    f = next(root.glob("*/*/structured_program_day.json"))
    obj = json.loads(f.read_text())
    obj["run_id"] = "20261018T070001123457Z"
    f.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match="Date/run mismatch"):
        build_handoff(root, tmp_path / "broken")


def test_no_source_manifest_rejected(tmp_path):
    with pytest.raises(ValueError, match="Missing daily manifest"):
        build_handoff(tmp_path, tmp_path / "out")


def test_error_status_does_not_publish_false_source(tmp_path):
    root = write_fixture(tmp_path)
    f = next(root.glob("*/*/manifest.json"))
    obj = json.loads(f.read_text())
    obj["status"] = "ERROR"
    f.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match="Collector failed"):
        build_handoff(root, tmp_path / "out")


def test_preserves_longer_trip_comment_without_claiming_full_source(tmp_path):
    root = write_fixture(tmp_path)
    f = next(root.glob("*/*/structured_program_day.json"))
    data = json.loads(f.read_text(encoding="utf-8"))
    comment = "L" * 140 + " outside leader with no cover and still finishing strongly"
    data["races"][0]["entrants"][0]["past_starts"][0]["raw_text"] = comment
    f.write_text(json.dumps(data), encoding="utf-8")
    dest = tmp_path / "handoff"
    result = build_handoff(root, dest)
    body = (dest / result["meeting_feeds"][0]["markdown_name"]).read_text(encoding="utf-8")
    assert "outside leader with no cover" in body
    assert "Raw previous-start lines are limited excerpts" in body

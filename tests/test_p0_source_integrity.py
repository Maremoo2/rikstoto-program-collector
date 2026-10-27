"""P0 source QA regression; synthetic fixture, real archived L D header text."""
import json
import pytest

from collector.pdf_program import _horse_header, parse_extended_pdf
from collector.prewatch_handoff import build_handoff
from collector.startlist_audit import reconcile_startlist
from collector.source_integrity import time_blocker, coverage_gap


def test_ld_identity_separates_history():
    assert _horse_header("6 L D, Mathias Jensen  / 2 41,045")[:2] == (6, "L D")
    assert _horse_header("6 J.C., Thomas Dalborg")[:2] == (6, "J.C.")
    assert _horse_header("6 L, Driver") is None
    text = ("Løp 9\n2140m Voltestart START KL. 20:36\n"
            "5 LEIKA TIME, Driver\n4-års hp\nTr: Trainer\n"
            "Dr Aa 01.10.26-7|3 6 1 2160\n"
            "6 L D, Mathias Jensen  / 2 41,045\n4-års v\nTr: Trainer\n"
            "Ma Jen Aa 15.10.26-3|3 3 d 1800\n"
            "Odense 23.10.2026 Utvidet - rikstoto.no Side: 9 av 10\n")
    parsed = parse_extended_pdf(text, meeting_id="S3_NR_2026-10-23", date="2026-10-23",
                                url="offline fixture", captured_at="2026-10-23T05:17:00Z")
    horses = parsed["races"][0]["entrants"]
    assert [(h["name"], len(h["past_starts"])) for h in horses] == [
        ("LEIKA TIME", 1), ("L D", 1)]
    starts = {"success": True, "result": {"9": [
        {"startNumber": 5, "horseName": "Leika Time", "isScratched": False},
        {"startNumber": 6, "horseName": "L D", "isScratched": False},
    ]}}
    audit = reconcile_startlist(parsed["races"], starts, captured_at="2026-10-23T05:17:01Z")
    assert audit["status"] == "MATCHED_AS_OF_SNAPSHOT"
    assert audit["horses_verified"] == 2


def test_mixed_release_contains_source_status_per_race(tmp_path):
    run = "20261027T060000123456Z"
    root = tmp_path / "daily"
    folder = root / "2026-10-27" / run
    folder.mkdir(parents=True)
    manifest = {"date_oslo": "2026-10-27", "run_id": run,
                "status": "CAPTURED_UNVERIFIED", "created_utc": "2026-10-27T06:00:00Z",
                "schedule_comparison": {}, "meetings": [
                    {"meeting_id": "S2_NR_2026-10-27", "is_multi_track_product": False,
                     "listing_source": {"country": "SE", "track": "Axevalla"},
                     "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT",
                                             "race_numbers_match": True, "race_matches": 3}}]}
    def one(n, clock):
        return {"race": {"meeting_id": "S2_NR_2026-10-27", "race_number": n,
                         "track": "Axevalla", "scheduled_time_local": clock,
                         "source_url": "offline fixture", "captured_at_utc": "2026-10-27T06:00:00Z"},
                "qa": {"past_start_rows": 0, "warnings": []},
                "entrants": [{"program_number": 1, "name": "TEST HORSE",
                              "driver": "X", "scratch_state": "UNVERIFIED", "past_starts": []}]}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    (folder / "structured_program_day.json").write_text(json.dumps({
        "date": "2026-10-27", "run_id": run,
        "races": [one(1, "00:00"), one(2, "19:05"), one(3, "25:90")]}))
    target = tmp_path / "handoff"
    result = build_handoff(root, target)
    assert result["race_count"] == 3
    assert result["queue_ready_races"] == result["source_ready_races"] == 1
    assert result["queue_review_races"] == result["source_blocked_races"] == 2
    assert [r["source_blockers"] for r in result["race_queue"]] == [
        ["START_TIME_UNVERIFIED_MIDNIGHT"], [], ["START_TIME_INVALID"]]
    part = result["meeting_feeds"][0]
    assert part["source_ready_race_count"] == 1
    assert part["source_blocked_race_count"] == 2
    assert part["source_ready_snapshot"] is False
    body = (target / part["markdown_name"]).read_text()
    for n, ready in ((1, False), (2, True), (3, False)):
        section = body.split(f"### Race {n} |", 1)[1].split("### Race ", 1)[0]
        assert f"source_ready_snapshot={ready}" in section
        assert ("source_blockers=[]" in section) is ready


@pytest.mark.parametrize("clock,expected", [
    (None, "START_TIME_UNKNOWN"), ("", "START_TIME_UNKNOWN"),
    ("00:00", "START_TIME_UNVERIFIED_MIDNIGHT"),
    ("0:00", "START_TIME_UNVERIFIED_MIDNIGHT"),
    ("21:33", None), ("25:90", "START_TIME_INVALID")])
def test_time_blocker(clock, expected):
    assert time_blocker(clock) == expected


def test_jagersro_gap_never_fabricates_id():
    discovered = [{"country": "NO", "track": "Bjerke", "meeting_id": "BJ_NR_2026-10-27"},
                  {"country": "SE", "track": "Axevalla", "meeting_id": "S2_NR_2026-10-27"}]
    card = [{"country": "SE", "track": "Jägersro", "date": "2026-10-27",
             "race_count": 8, "source_url": "https://sulkysport.se/lopp/jagersro-2026-10-27/"}]
    gaps = coverage_gap(race_date="2026-10-27",
                        discovered_meetings=discovered, external_cards=card)
    assert len(gaps) == 1
    assert gaps[0]["status"] == "COVERAGE_GAP"
    assert gaps[0]["meeting_id"] is None
    assert gaps[0]["source_ready"] is False

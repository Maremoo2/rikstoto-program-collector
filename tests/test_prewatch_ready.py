"""Synthetic unit tests; real archived-source regression is separate."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from collector.prewatch_ready import build_ready, digest, encoded, stamp
from collector.prewatch_ready_mailbox import prepare_update

DAY = "2026-11-25"
RUN = "20261125T075221791585Z"
MID = "S2_NR_2026-11-25"
ARCH = f"rikstoto-program-{DAY}-{RUN}"
TAG = f"prewatch-src-{DAY}-{MID}-p1-{RUN}"
NOW = stamp("2026-11-25T08:10:03Z")
RELEASES = {ARCH: 100, TAG: 101}


def fixture(folder, *, race_numbers=(1, 2)):
    folder.mkdir(parents=True, exist_ok=True)
    index = {"schema": "prewatch_source_v1", "date_oslo": DAY, "run_id": RUN,
             "snapshot_observed_utc": "2026-11-25T07:53:01Z", "source_archive_tag": ARCH,
             "collection_status": "CAPTURED_UNVERIFIED", "race_queue": [],
             "meeting_feeds": [{"meeting_id": MID, "race_numbers": list(race_numbers), "release_tag": TAG}]}
    for n in race_numbers:
        receipts = [{"status": "SHA_VERIFIED_SOURCE_RECEIPT", "sha256": "a" * 64,
                     "url": "https://www.rikstoto.no" + url, "observed_utc": "2026-11-25T07:53:00Z"}
                    for url in (f"/api/racedays/{MID}/starts", f"/api/game/program/{MID}/driverChanges")]
        entries = [{"program_number": k, "name": f"Example {k}", "scratch_state": "ACTIVE_AS_OF_SNAPSHOT",
                    "past_starts": [{"date": "2026-11-10", "raw_text": f"synthetic history {i}"} for i in range(5)]}
                   for k in range(1, 4)]
        rows = [{"start_number": k, "horse_name": f"Example {k}", "is_scratched": False,
                 "driver_change_documented": False, "effective_driver": "A", "original_official_driver": "A"}
                for k in range(1, 4)]
        roster = {"status": "VERIFIED_AS_OF_SOURCE_CAPTURE", "source_run_id": RUN, "first_blocker": None,
                  "starts_source": receipts[0], "driver_changes_source": receipts[1], "runners": rows, "driver_changes": []}
        pack = {"schema": "prewatch_source_v1", "record_type": "FULL_RACE_SOURCE_PACK", "race_id": f"RIKSTOTO:{MID}:{n}",
                "date_oslo": DAY, "source_run_id": RUN, "source_archive_tag": ARCH, "phase_a_completed": False,
                "bet_authority": False, "source_receipts": [], "official_roster": roster,
                "program": {"race": {"meeting_id": MID, "race_number": n, "track": "Solvalla", "scheduled_time_local": f"19:{n:02d}",
                                      "distance_m": 2140, "start_method": "Autostart"}, "entrants": entries, "win_odds": ["synthetic forbidden current market"]}}
        q = {"race_key": f"{MID}|{n}", "meeting_id": MID, "race_number": n, "track": "Solvalla", "start_local": f"19:{n:02d}",
             "runner_count": len(rows), "race_pack_file": f"race_pack_{MID}_{n}.json", "source_ready_snapshot": True, "source_blockers": [],
             "official_roster_handoff_status": roster["status"], "official_starts_source": receipts[0], "official_driver_changes_source": receipts[1],
             "official_roster": rows, "official_driver_changes": []}
        write_pack(folder, q, pack)
        index["race_queue"].append(q)
    write_index(folder, index)
    return index


def write_pack(folder, q, pack):
    raw = encoded(pack)
    (folder / q["race_pack_file"]).write_bytes(raw)
    q["race_pack_sha256"] = digest(raw)


def write_index(folder, index):
    (folder / "index.json").write_bytes(encoded(index))


def mutate(folder, index, change):
    q = index["race_queue"][0]
    pack = json.loads((folder / q["race_pack_file"]).read_text())
    change(q, pack)
    write_pack(folder, q, pack)
    write_index(folder, index)


def build(folder, **kwargs):
    return build_ready([folder], RELEASES, NOW, **kwargs)


def test_ready_and_deterministic(tmp_path):
    i = fixture(tmp_path)
    a = build(tmp_path)
    assert a["status"] == "SOURCE_READY" and len(a["queue"]) == 2
    assert a["selected"]["metadata"]["active_numbers"] == [1, 2, 3]
    assert a["selected"]["metadata"]["history_rows"] == 15
    assert "win_odds" not in a["selected"]["source_pack"]["program"]
    assert a["selected"]["source_pack"]["program"]["entrants"][0]["past_starts"][4]["raw_text"] == "synthetic history 4"
    assert encoded(a) == encoded(build(tmp_path))
    i["race_queue"].reverse(); write_index(tmp_path, i)
    assert build(tmp_path)["selected"]["metadata"] == a["selected"]["metadata"]


@pytest.mark.parametrize("case,code", [("missing", "SOURCE_NOT_READY"), ("history", "HISTORY_MISSING_OR_NOT_PRE_DATE"),
    ("future_history", "HISTORY_MISSING_OR_NOT_PRE_DATE"), ("field", "FIELD_MISMATCH"),
    ("name", "ROSTER_FIELD_CONFLICT"), ("driver", "ROSTER_FIELD_CONFLICT"),
    ("started", "RACE_STARTED_OR_DUE"), ("receipt", "RECEIPT_INVALID"), ("future_receipt", "FUTURE_ROSTER_RECEIPT")])
def test_blocked_cases(tmp_path, case, code):
    i = fixture(tmp_path, race_numbers=(1,))
    def change(q, p):
        if case == "missing": q["source_ready_snapshot"] = False
        if case == "history": p["program"]["entrants"][0]["past_starts"] = []
        if case == "future_history": p["program"]["entrants"][0]["past_starts"][0]["date"] = DAY
        if case == "field": p["program"]["entrants"].pop()
        if case == "name": p["program"]["entrants"][0]["name"] = "Different"
        if case == "driver": p["official_roster"]["runners"][0]["effective_driver"] = "B"; q["official_roster"] = p["official_roster"]["runners"]
        if case == "started": q["start_local"] = p["program"]["race"]["scheduled_time_local"] = "09:00"
        if case in {"receipt", "future_receipt"}:
            p["official_roster"]["starts_source"]["status" if case == "receipt" else "observed_utc"] = "UNKNOWN" if case == "receipt" else "2026-11-25T08:11:00Z"
            q["official_starts_source"] = p["official_roster"]["starts_source"]
    mutate(tmp_path, i, change)
    r = build(tmp_path)
    assert r["status"] == "NO_ELIGIBLE_RACE" and r["blocked"][0]["code"] == code


def test_stale_and_short_window(tmp_path):
    fixture(tmp_path, race_numbers=(1,))
    assert build_ready([tmp_path], RELEASES, stamp("2026-11-25T08:24:00Z"))["blocked"][0]["code"] == "ROSTER_STALE"
    assert build_ready([tmp_path], RELEASES, stamp("2026-11-25T08:22:00Z"))["blocked"][0]["code"] == "INSUFFICIENT_ANALYSIS_WINDOW"


def test_scratch_and_driver_change(tmp_path):
    i = fixture(tmp_path, race_numbers=(1,))
    def change(q, p):
        p["program"]["entrants"][0]["scratch_state"] = "SCRATCHED_AS_OF_SNAPSHOT"
        r = p["official_roster"]
        r["runners"][0]["is_scratched"] = True
        r["runners"][1].update(driver_change_documented=True, effective_driver="B")
        r["driver_changes"] = [{"start_number": 2, "new_driver": "B"}]
        q["official_roster"], q["official_driver_changes"] = r["runners"], r["driver_changes"]
    mutate(tmp_path, i, change)
    r = build(tmp_path)
    assert r["selected"]["metadata"]["active_numbers"] == [2, 3]
    assert r["selected"]["metadata"]["scratch_numbers"] == [1]
    assert r["selected"]["source_pack"]["official_roster"]["driver_changes"][0]["new_driver"] == "B"


def test_duplicate_and_hash_and_release_id(tmp_path):
    i = fixture(tmp_path, race_numbers=(1,))
    i["race_queue"].append(deepcopy(i["race_queue"][0])); write_index(tmp_path, i)
    assert {x["code"] for x in build(tmp_path)["blocked"]} == {"DUPLICATE_RACE_KEY"}
    i["race_queue"].pop(); write_index(tmp_path, i)
    assert build_ready([tmp_path], {}, NOW)["blocked"][0]["code"] == "RELEASE_ID_UNVERIFIED"
    (tmp_path / i["race_queue"][0]["race_pack_file"]).write_bytes(b"{}")
    assert build(tmp_path)["blocked"][0]["code"] == "PACK_SHA_MISMATCH"


def test_verified_exclusion(tmp_path):
    fixture(tmp_path)
    r = build(tmp_path, completed={f"{DAY}|Solvalla|1"})
    assert r["selected"]["metadata"]["ledger_race_id"] == f"{DAY}|Solvalla|2"
    assert r["ledger_exclusion"] == "CALLER_SUPPLIED_VERIFIED_IDS"


def test_latest_observation(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    i, j = fixture(a), fixture(b)
    i["snapshot_observed_utc"] = "2026-11-25T07:51:00Z"; write_index(a, i)
    assert build_ready([b, a], RELEASES, NOW)["index_sha256"] == digest((b / "index.json").read_bytes())
    j["snapshot_observed_utc"] = "2026-11-25T08:11:00Z"; write_index(b, j)
    with pytest.raises(ValueError, match="FUTURE_INDEX_OBSERVATION"):
        build_ready([b, a], RELEASES, NOW)


def test_mailbox_guards(tmp_path):
    fixture(tmp_path)
    packet = build(tmp_path, completed=set())
    packet["operational_publication_allowed"] = True
    mailbox = {"id": 9, "tag_name": "prewatch-ready-v1", "draft": True, "published_at": None, "assets": [],
               "body": json.dumps({"schema": "prewatch_ready_v1", "bet_authority": False})}
    assert json.loads(prepare_update(packet, mailbox, 9, NOW)["body"]) == packet
    with pytest.raises(ValueError, match="LEDGER_OR_PUBLICATION_NOT_VERIFIED"):
        prepare_update(build(tmp_path), mailbox, 9, NOW)
    with pytest.raises(ValueError, match="UNSAFE_PACKET"):
        prepare_update(build(tmp_path, replay=True), mailbox, 9, NOW)
    with pytest.raises(ValueError, match="UNSAFE_MAILBOX"):
        prepare_update(packet, dict(mailbox, draft=False), 9, NOW)
    with pytest.raises(ValueError, match="UNSAFE_MAILBOX"):
        prepare_update(packet, dict(mailbox, tag_name=ARCH), 9, NOW)
    with pytest.raises(ValueError, match="PACKET_NOT_CURRENT"):
        prepare_update(packet, mailbox, 9, stamp("2026-11-25T08:16:00Z"))

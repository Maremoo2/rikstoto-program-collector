"""Synthetic release/ZIP checks; actual archived regression runs separately."""
import json
import zipfile
from copy import deepcopy

import pytest

from collector.prewatch_ready import digest, encoded, stamp
from collector.prewatch_ready_integration import prepare
from collector.prewatch_ready_mailbox import prepare_update
from test_prewatch_ready import fixture, write_pack, write_index, DAY, RUN, MID, ARCH, TAG, NOW


def source_fixture(tmp_path):
    feed = tmp_path / "feed"
    index = fixture(feed, race_numbers=(1,))
    q = index["race_queue"][0]
    pack = json.loads((feed / q["race_pack_file"]).read_text())
    manifest = encoded({"date_oslo": DAY, "run_id": RUN})
    structured = encoded({"date": DAY, "run_id": RUN, "races": [pack["program"]]})
    pack["manifest_sha256"], pack["structured_original_sha256"] = digest(manifest), digest(structured)
    archive = tmp_path / "archive.zip"
    prefix = f"{DAY}/{RUN}/"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(prefix + "manifest.json", manifest)
        z.writestr(prefix + "structured_program_day.json", structured)
        for key, qkey, name in (("starts_source", "official_starts_source", "starts"),
                                ("driver_changes_source", "official_driver_changes_source", "driver_changes")):
            raw = encoded({"result": name, "synthetic": True})
            wrapper = encoded({"response": json.loads(raw)})
            base = prefix + f"meetings/{MID}/{name}"
            z.writestr(base + ".raw.json", raw)
            z.writestr(base + ".json", wrapper)
            receipt = pack["official_roster"][key]
            receipt.update(sha256=digest(raw), wrapper_sha256=digest(wrapper))
            q[qkey] = receipt
    write_pack(feed, q, pack)
    notes = tmp_path / "notes.md"
    notes.write_text("Synthetic notes\n")
    (feed / "index.md").write_text("SNAPSHOT_OBSERVED_UTC=2026-11-25T07:53:01Z | SOURCE_CLOCK=LATEST_OFFICIAL_ROSTER_RECEIPT\n")
    (feed / "meeting.md").write_text("Synthetic source body\n")
    m = index["meeting_feeds"][0]
    m.update(markdown_name="meeting.md", sha256=digest((feed / "meeting.md").read_bytes()))
    write_index(feed, index)
    body = notes.read_bytes() + b"\n\n" + (feed / "index.md").read_bytes()
    records = [
        {"id": 100, "tag_name": ARCH, "draft": True, "published_at": None, "body": body.decode(),
         "body_sha256": digest(body), "assets": [{"name": archive.name, "digest": "sha256:" + digest(archive.read_bytes())}]},
        {"id": 101, "tag_name": TAG, "draft": True, "published_at": None, "body_sha256": m["sha256"], "assets": []},
    ]
    return feed, archive, notes, records


def test_source_integration_and_expiry(tmp_path):
    args = source_fixture(tmp_path)
    p = prepare(*args, NOW, replay=True)
    assert p["status"] == "SOURCE_READY" and len(p["queue"]) == 1
    assert p["operational_publication_allowed"] is False and p["ledger_exclusion"] == "NOT_CHECKED"
    assert encoded(p) == encoded(prepare(*args, NOW, replay=True))
    expired = prepare(*args, stamp("2026-11-25T08:30:00Z"), replay=True)
    assert expired["status"] == "NO_ELIGIBLE_RACE" and expired["blocked"][0]["code"] == "ROSTER_STALE"
    live = prepare(*args, NOW)
    mailbox = {"id": 9, "tag_name": "prewatch-ready-v1", "draft": True, "published_at": None, "assets": [],
               "body": json.dumps({"schema": "prewatch_ready_v1", "bet_authority": False})}
    with pytest.raises(ValueError, match="LEDGER_OR_PUBLICATION_NOT_VERIFIED"):
        prepare_update(live, mailbox, 9, NOW)


@pytest.mark.parametrize("case,code", [("meeting_hash", "MEETING_RELEASE_BODY_MISMATCH"),
    ("archive_hash", "ARCHIVE_ASSET_SHA_MISMATCH"), ("body", "ARCHIVE_RELEASE_BODY_MISMATCH"),
    ("public", "RELEASE_NOT_PRIVATE_DRAFT"), ("duplicate", "RELEASE_ID_OR_TAG_DUPLICATE"),
    ("newer", "NEWER_ARCHIVE_AVAILABLE"), ("pack", "PACK_ARCHIVE_MISMATCH")])
def test_bad_source_evidence(tmp_path, case, code):
    feed, archive, notes, records = source_fixture(tmp_path)
    if case == "meeting_hash": records[1]["body_sha256"] = "b" * 64
    if case == "archive_hash": records[0]["assets"][0]["digest"] = "sha256:" + "b" * 64
    if case == "body": records[0]["body"] += "modified"
    if case == "public": records[1]["draft"] = False
    if case == "duplicate": records.append(deepcopy(records[1]))
    if case == "newer":
        records.append({"id": 102, "tag_name": ARCH + "-newer", "draft": True, "published_at": None,
                        "body": "SNAPSHOT_OBSERVED_UTC=2026-11-25T08:00:00Z | SOURCE_CLOCK=LATEST_OFFICIAL_ROSTER_RECEIPT"})
    if case == "pack":
        q = json.loads((feed / "index.json").read_text())["race_queue"][0]
        (feed / q["race_pack_file"]).write_text("{}")
    with pytest.raises(ValueError, match=code):
        prepare(feed, archive, notes, records, NOW, replay=True)

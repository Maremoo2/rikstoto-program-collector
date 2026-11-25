"""Verify existing Collector artifacts against authenticated releases before ready generation.

Read-only source preparation. No ledger writes, no release publishing, no AI or betting.
Offline evidence input is explicitly replay-only. Production caller must use gh API.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import zipfile

from .prewatch_ready import build_ready, digest, encoded, require, stamp

REPO = "Maremoo2/rikstoto-program-collector"
OBS = re.compile(r"^SNAPSHOT_OBSERVED_UTC=([^ |\n]+) \| SOURCE_CLOCK=LATEST_OFFICIAL_ROSTER_RECEIPT$", re.M)


def gh_json(*args):
    return json.loads(subprocess.run(["gh", "api", *args], check=True,
                                    capture_output=True, text=True).stdout)


def observe(release):
    matches = OBS.findall(release.get("body") or "")
    require(len(matches) == 1, "ARCHIVE_OBSERVATION_INVALID")
    return stamp(matches[0])


def release_evidence(index):
    """Numeric lookups, never assume draft tag endpoints or list order work."""
    pages = gh_json(f"repos/{REPO}/releases?per_page=100", "--paginate", "--slurp")
    rows = [r for page in pages for r in page]
    day = index["date_oslo"]
    wanted = {m["release_tag"] for m in index["meeting_feeds"]}
    archives = [r for r in rows if r.get("tag_name", "").startswith(f"rikstoto-program-{day}-") and r.get("draft") is True]
    tags = wanted | {r["tag_name"] for r in archives}
    records = []
    for tag in sorted(tags):
        matching = [r for r in rows if r.get("tag_name") == tag]
        require(len(matching) == 1, "RELEASE_TAG_NOT_UNIQUE")
        rid = matching[0]["id"]
        r = gh_json(f"repos/{REPO}/releases/{rid}")
        require(r.get("id") == rid and r.get("tag_name") == tag, "RELEASE_IDENTITY_MISMATCH")
        body = r.get("body")
        require(isinstance(body, str), "RELEASE_BODY_MISSING")
        record = {k: r.get(k) for k in ("id", "tag_name", "draft", "published_at", "assets")}
        record["body_sha256"] = digest(body.encode("utf-8"))
        if tag not in wanted:
            record["body"] = body
        records.append(record)
    return records


def verify_sources(feed, archive, notes, records, now):
    index = json.loads((feed / "index.json").read_bytes())
    day, run = index["date_oslo"], index["run_id"]
    archive_tag = f"rikstoto-program-{day}-{run}"
    by_tag = {}
    ids = set()
    for r in records:
        tag, rid = r["tag_name"], r["id"]
        require(tag not in by_tag and type(rid) is int and rid > 0 and rid not in ids,
                "RELEASE_ID_OR_TAG_DUPLICATE")
        require(r.get("draft") is True and r.get("published_at") is None, "RELEASE_NOT_PRIVATE_DRAFT")
        by_tag[tag] = r
        ids.add(rid)
    candidates = [(observe(r), t) for t, r in by_tag.items() if t.startswith(f"rikstoto-program-{day}-")]
    require(candidates and all(t <= now for t, _ in candidates), "ARCHIVE_CLOCK_INVALID")
    require(max(candidates)[1] == archive_tag, "NEWER_ARCHIVE_AVAILABLE")
    original = by_tag[archive_tag]
    require(observe(original) == stamp(index["snapshot_observed_utc"]), "INDEX_OBSERVATION_MISMATCH")
    body = notes.read_bytes() + b"\n\n" + (feed / "index.md").read_bytes()
    require(digest(body) == original["body_sha256"] and body.decode() == original["body"], "ARCHIVE_RELEASE_BODY_MISMATCH")
    assets = [a for a in original["assets"] if a["name"] == archive.name]
    require(len(assets) == 1 and assets[0].get("digest") == "sha256:" + digest(archive.read_bytes()), "ARCHIVE_ASSET_SHA_MISMATCH")
    release_ids = {archive_tag: original["id"]}
    for m in index["meeting_feeds"]:
        r = by_tag[m["release_tag"]]
        actual = digest((feed / m["markdown_name"]).read_bytes())
        require(actual == m["sha256"] == r["body_sha256"], "MEETING_RELEASE_BODY_MISMATCH")
        release_ids[m["release_tag"]] = r["id"]
    prefix = f"{day}/{run}/"
    with zipfile.ZipFile(archive) as z:
        require(len(z.namelist()) == len(set(z.namelist())), "ARCHIVE_DUPLICATE_MEMBER")
        manifest = z.read(prefix + "manifest.json")
        structured = z.read(prefix + "structured_program_day.json")
        mdoc, sdoc = json.loads(manifest), json.loads(structured)
        require(mdoc["date_oslo"] == sdoc["date"] == day and mdoc["run_id"] == sdoc["run_id"] == run, "ARCHIVE_IDENTITY_MISMATCH")
        target_keys = {(q["meeting_id"], q["race_number"]) for q in index["race_queue"]}
        races = {}
        for d in sdoc["races"]:
            key = (d["race"]["meeting_id"], d["race"]["race_number"])
            if key not in target_keys:
                continue
            require(key not in races, "ARCHIVE_DUPLICATE_RACE")
            races[key] = d
        for q in index["race_queue"]:
            mid, number = q["meeting_id"], q["race_number"]
            require(q["race_pack_file"] == f"race_pack_{mid}_{number}.json", "PACK_PATH_INVALID")
            raw = (feed / q["race_pack_file"]).read_bytes()
            pack = json.loads(raw)
            require(digest(raw) == q["race_pack_sha256"] and pack["manifest_sha256"] == digest(manifest)
                    and pack["structured_original_sha256"] == digest(structured)
                    and pack["program"] == races[(mid, number)], "PACK_ARCHIVE_MISMATCH")
            roster = pack["official_roster"]
            if roster["status"] != "VERIFIED_AS_OF_SOURCE_CAPTURE":
                continue  # ready validator separately excludes unverified rosters
            for key, name in (("starts_source", "starts"), ("driver_changes_source", "driver_changes")):
                receipt = roster[key]
                base = prefix + f"meetings/{mid}/{name}"
                require(digest(z.read(base + ".raw.json")) == receipt["sha256"]
                        and digest(z.read(base + ".json")) == receipt["wrapper_sha256"], "ROSTER_ARCHIVE_SHA_MISMATCH")
    return release_ids


def prepare(feed, archive, notes, records, now, *, replay=False):
    ids = verify_sources(feed, archive, notes, records, now)
    packet = build_ready([feed], ids, now, replay=replay)
    packet["transport_evidence"] = "NUMERIC_RELEASE_BODY_AND_ORIGINAL_ARCHIVE_SHA_VERIFIED"
    packet["operational_publication_allowed"] = False  # no authenticated Ledger integration yet
    require(len(encoded(packet)) <= 95_000, "READY_PACKET_TOO_LARGE")
    return packet


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--feed", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--notes", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--evidence", type=Path, help="Offline authenticated readback receipt; replay only")
    p.add_argument("--replay-at", help="Explicit archived test clock, not a live freeze")
    a = p.parse_args()
    require(bool(a.evidence) == bool(a.replay_at), "OFFLINE_EVIDENCE_REQUIRES_REPLAY_CLOCK")
    idx = json.loads((a.feed / "index.json").read_bytes())
    records = json.loads(a.evidence.read_bytes()) if a.evidence else release_evidence(idx)
    now = stamp(a.replay_at) if a.replay_at else datetime.now(timezone.utc)
    packet = prepare(a.feed, a.archive, a.notes, records, now, replay=bool(a.replay_at))
    raw = encoded(packet)
    with a.output.open("xb") as f:
        f.write(raw)
    require(a.output.read_bytes() == raw, "PACKET_READBACK_MISMATCH")
    print(json.dumps({"status": packet["status"], "sha256": digest(raw), "eligible": len(packet["queue"]),
                      "replay_only": packet["replay_only"], "publication_allowed": False}))


if __name__ == "__main__":
    main()

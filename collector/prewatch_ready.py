"""Build a source-only ready packet from existing verified handoff race packs.

No network, scoring, betting, or production writes. A replay is never live.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from copy import deepcopy
from zoneinfo import ZoneInfo

OSLO = ZoneInfo("Europe/Oslo")
SCHEMA = "prewatch_ready_v1"
SOURCE = "prewatch_source_v1"
SHA = re.compile(r"[0-9a-f]{64}\Z")
RUN = re.compile(r"\d{8}T\d{12}Z\Z")
MID = re.compile(r"[A-Z0-9]+_NR_\d{4}-\d{2}-\d{2}\Z")


def stamp(value):
    if not isinstance(value, str):
        raise ValueError("TIMESTAMP_INVALID")
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return t.astimezone(timezone.utc)


def require(ok, code):
    if not ok:
        raise ValueError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def normalized_name(value):
    # Same normalization as the existing startlist audit. No permanent-ID claim.
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold())


def transport_projection(pack):
    """Preserve every history row; omit duplicated raw sections and current market."""
    value = deepcopy(pack)
    for horse in value["program"]["entrants"]:
        horse.pop("raw_section", None)
    value["program"].pop("win_odds", None)
    value["source_receipts"] = [{k: v for k, v in row.items() if k in {"url", "at_utc", "sha256", "status"}}
                                for row in value["source_receipts"]]
    value["record_type"] = "PHASE_A_SOURCE_PROJECTION"
    return value


def read_json(path):
    raw = path.read_bytes()
    return json.loads(raw), digest(raw)


def choose_index(folders, now):
    day = now.astimezone(OSLO).date().isoformat()
    candidates = []
    for folder in folders:
        index, sha = read_json(folder / "index.json")
        run = index.get("run_id", "")
        if (index.get("schema") == SOURCE and index.get("date_oslo") == day
                and RUN.fullmatch(run) and run.startswith(day.replace("-", ""))
                and index.get("source_archive_tag") == f"rikstoto-program-{day}-{run}"
                and index.get("collection_status") in {"CAPTURED_UNVERIFIED", "REVIEW_REQUIRED"}):
            observed = stamp(index["snapshot_observed_utc"])
            require(observed <= now, "FUTURE_INDEX_OBSERVATION")
            candidates.append((observed, run, sha, folder, index))
    if not candidates:
        raise ValueError("NO_VALID_INDEX")
    newest = max(x[:2] for x in candidates)
    selected = [x for x in candidates if x[:2] == newest]
    require(len({x[2] for x in selected}) == 1, "CONFLICTING_INDEX")
    return selected[0][3], selected[0][4], selected[0][2]


def validate_race(folder, index, q, now, releases, min_seconds):
    day, run = index["date_oslo"], index["run_id"]
    mid, n = q["meeting_id"], q["race_number"]
    require(MID.fullmatch(mid) and mid.endswith(day) and type(n) is int and n > 0
            and q["race_key"] == f"{mid}|{n}", "RACE_ID_INVALID")
    require(q["source_ready_snapshot"] is True and not q["source_blockers"], "SOURCE_NOT_READY")
    require(q["race_pack_file"] == f"race_pack_{mid}_{n}.json", "PACK_PATH_INVALID")
    pack, sha = read_json(folder / q["race_pack_file"])
    require(sha == q["race_pack_sha256"], "PACK_SHA_MISMATCH")
    require(pack["schema"] == SOURCE and pack["record_type"] == "FULL_RACE_SOURCE_PACK"
            and pack["race_id"] == f"RIKSTOTO:{mid}:{n}" and pack["date_oslo"] == day
            and pack["source_run_id"] == run and pack["source_archive_tag"] == index["source_archive_tag"]
            and pack["phase_a_completed"] is False and pack["bet_authority"] is False, "PACK_IDENTITY_INVALID")
    race = pack["program"]["race"]
    require(race["meeting_id"] == mid and race["race_number"] == n and race["track"] == q["track"]
            and race["scheduled_time_local"] == q["start_local"] and type(race["distance_m"]) is int
            and race["distance_m"] > 0 and bool(race["start_method"]), "RACE_METADATA_INVALID")
    clock = race["scheduled_time_local"]
    require(re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", clock) and clock not in {"0:00", "00:00"}, "START_TIME_INVALID")
    start = datetime.combine(now.astimezone(OSLO).date(), datetime.strptime(clock, "%H:%M").time(), OSLO)
    require(start > now, "RACE_STARTED_OR_DUE")
    roster = pack["official_roster"]
    require(roster["status"] == q["official_roster_handoff_status"] == "VERIFIED_AS_OF_SOURCE_CAPTURE"
            and roster["source_run_id"] == run and roster["first_blocker"] is None, "ROSTER_UNVERIFIED")
    times = []
    for key, qkey, url in (("starts_source", "official_starts_source", f"/api/racedays/{mid}/starts"),
                          ("driver_changes_source", "official_driver_changes_source", f"/api/game/program/{mid}/driverChanges")):
        r = roster[key]
        require(r == q[qkey] and r["status"] == "SHA_VERIFIED_SOURCE_RECEIPT"
                and r["url"] == "https://www.rikstoto.no" + url and SHA.fullmatch(r["sha256"]), "RECEIPT_INVALID")
        t = stamp(r["observed_utc"])
        require(t <= now, "FUTURE_ROSTER_RECEIPT")
        times.append(t)
    oldest = min(times)
    deadline = min(oldest + timedelta(minutes=30), start.astimezone(timezone.utc))
    require(now - oldest <= timedelta(minutes=30), "ROSTER_STALE")
    require((deadline - now).total_seconds() >= min_seconds, "INSUFFICIENT_ANALYSIS_WINDOW")
    entries, rows = pack["program"]["entrants"], roster["runners"]
    by_number = {h["program_number"]: h for h in entries}
    official = {h["start_number"]: h for h in rows}
    require(len(entries) == len(by_number) == len(rows) == len(official) == q["runner_count"]
            and set(by_number) == set(official) and rows == q["official_roster"], "FIELD_MISMATCH")
    require(all(type(k) is int and k > 0 for k in by_number), "FIELD_NUMBER_INVALID")
    require(roster["driver_changes"] == q["official_driver_changes"], "DRIVER_CHANGE_MISMATCH")
    changes = {c["start_number"]: c for c in roster["driver_changes"]}
    require(len(changes) == len(roster["driver_changes"]) and set(changes) <= set(official), "DRIVER_CHANGE_MISMATCH")
    active = []
    for k, h in sorted(by_number.items()):
        r = official[k]
        require(type(r["is_scratched"]) is bool and type(r["driver_change_documented"]) is bool
                and bool(r["effective_driver"]) and bool(h["name"]) and bool(r["horse_name"])
                and normalized_name(h["name"]) == normalized_name(r["horse_name"])
                and h["scratch_state"] == ("SCRATCHED_AS_OF_SNAPSHOT" if r["is_scratched"] else "ACTIVE_AS_OF_SNAPSHOT")
                and r["driver_change_documented"] == (k in changes)
                and (r["effective_driver"] == changes[k]["new_driver"] if k in changes else r["effective_driver"] == r["original_official_driver"]), "ROSTER_FIELD_CONFLICT")
        history = h["past_starts"]
        require(isinstance(history, list), "HISTORY_INVALID")
        if not r["is_scratched"]:
            require(history and all(x.get("date") and x.get("raw_text") and date.fromisoformat(x["date"]) < date.fromisoformat(day) for x in history), "HISTORY_MISSING_OR_NOT_PRE_DATE")
            active.append(k)
    require(active, "NO_ACTIVE_RUNNERS")
    parts = [m for m in index["meeting_feeds"] if m["meeting_id"] == mid and n in m["race_numbers"]]
    require(len(parts) == 1, "MEETING_PART_NOT_UNIQUE")
    tag = parts[0]["release_tag"]
    require(tag.startswith(f"prewatch-src-{day}-{mid}-") and tag.endswith("-" + run), "MEETING_TAG_INVALID")
    archive_id, meeting_id = releases.get(index["source_archive_tag"]), releases.get(tag)
    require(type(archive_id) is int and archive_id > 0 and type(meeting_id) is int and meeting_id > 0, "RELEASE_ID_UNVERIFIED")
    meta = {"race_id": pack["race_id"], "ledger_race_id": unicodedata.normalize("NFC", f"{day}|{race['track']}|{n}"),
            "scheduled_start_iso": start.isoformat(), "active_numbers": active,
            "scratch_numbers": sorted(set(by_number) - set(active)), "history_rows": sum(len(by_number[k]["past_starts"]) for k in active),
            "history_complete_five": all(len(by_number[k]["past_starts"]) >= 5 for k in active),
            "roster_age_seconds": (now - oldest).total_seconds(), "latest_freeze_utc": deadline.isoformat(),
            "source_archive_release_id": archive_id, "meeting_release_id": meeting_id,
            "meeting_release_tag": tag, "race_pack_sha256": sha, "data_quality": "SOURCE_READY_AS_OF_CAPTURE"}
    return meta, pack


def build_ready(folders, releases, now, *, completed=None, min_seconds=120, replay=False):
    require(now.tzinfo is not None and min_seconds >= 0, "INVALID_REFERENCE_TIME_OR_WINDOW")
    folder, index, index_sha = choose_index(folders, now)
    keys = Counter(q.get("race_key") for q in index["race_queue"])
    eligible, blocked = [], []
    for q in index["race_queue"]:
        key = q.get("race_key")
        try:
            require(keys[key] == 1, "DUPLICATE_RACE_KEY")
            meta, pack = validate_race(folder, index, q, now, releases, min_seconds)
            require(completed is None or meta["ledger_race_id"] not in completed, "ALREADY_COMPLETED")
            projection = transport_projection(pack)
            require(len(encoded(projection)) < 80_000, "PACK_TOO_LARGE_FOR_TRANSPORT")
            eligible.append((meta, projection))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            blocked.append({"race_key": key, "code": str(exc) if isinstance(exc, ValueError) else "SOURCE_STRUCTURE_OR_READ_ERROR"})
    eligible.sort(key=lambda pair: (not pair[0]["history_complete_five"], len(pair[0]["active_numbers"]), pair[0]["scheduled_start_iso"], pair[0]["race_id"]))
    result = {"schema": SCHEMA, "reference_utc": now.astimezone(timezone.utc).isoformat(),
              "generated_at_utc": now.astimezone(timezone.utc).isoformat() if not replay else None,
              "replay_only": replay, "date_oslo": index["date_oslo"], "collector_run_id": index["run_id"],
              "index_sha256": index_sha, "min_analysis_window_seconds": min_seconds,
              "ledger_exclusion": "NOT_CHECKED" if completed is None else "CALLER_SUPPLIED_VERIFIED_IDS",
              "status": "SOURCE_READY" if eligible else "NO_ELIGIBLE_RACE", "queue": [m for m, _ in eligible],
              "blocked": sorted(blocked, key=lambda x: (str(x["race_key"]), x["code"])),
              "selected": None if not eligible else {"metadata": eligible[0][0], "source_pack": eligible[0][1]},
              "phase_a_completed": False, "bet_authority": False, "freeze_recheck_required": True}
    require(len(encoded(result)) <= 95_000, "READY_PACKET_TOO_LARGE")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--feed", type=Path, action="append", required=True)
    p.add_argument("--release-ids", type=Path, required=True, help="Exact authenticated tag-to-numeric-ID map")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--replay-at", help="Archived-data test only; never use as a live source")
    args = p.parse_args()
    now = stamp(args.replay_at) if args.replay_at else datetime.now(timezone.utc)
    result = build_ready(args.feed, json.loads(args.release_ids.read_text()), now, replay=bool(args.replay_at))
    raw = encoded(result)
    with args.output.open("xb") as stream:
        stream.write(raw)
    require(args.output.read_bytes() == raw, "READY_READBACK_MISMATCH")
    print(json.dumps({"status": result["status"], "sha256": digest(raw), "replay_only": result["replay_only"]}))


if __name__ == "__main__":
    main()

"""Read-optimized, privately archived NO/SE race data for Pre-Watch.

Immutable source handoff only: no sports scoring, probabilities, bets or odds.
Publish as draft GitHub Release descriptions, readable as release.body through
the connected GitHub reader. Source PDFs remain in the original archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .source_integrity import time_blocker
from .roster_handoff import roster_for_meeting, _utc

MAX_BODY = 95_000
HISTORY_LIMIT = 500
SCHEMA = "prewatch_source_v1"


# Snapshot QA only: never infer current scratches, betting prices or A-WATCH.
SOURCE_READY_STATUSES = {"MATCHED_AS_OF_SNAPSHOT"}

# These describe the freshness limits of every honest morning capture.
# They MUST remain visible, but are not failed PDF/startlist QA.
ADVISORY_RACE_WARNINGS = {"PDF_SNAPSHOT_NOT_LIVE", "SCRATCH_STATUS_MAY_CHANGE"}


def classify_race_warnings(qa, *, meeting_audit):
    """Separate source-freshness notices from genuine reconciliation blockers.

    A PDF-inferred race number is safe for source shortlisting ONLY if the
    independent official startlist explicitly validated the entire race set.
    All unknown/future warning codes fail closed, pending human review.
    """
    raw = qa.get("warnings", [])
    if not isinstance(raw, list) or any(not isinstance(w, str) for w in raw):
        return [], ["MALFORMED_RACE_QA_WARNINGS"]
    advisories, review = [], []
    for warning in raw:
        if warning in ADVISORY_RACE_WARNINGS:
            advisories.append(warning)
        elif warning == "RACE_NUMBER_INFERRED" and (
            meeting_audit.get("status") == "MATCHED_AS_OF_SNAPSHOT"
            and meeting_audit.get("race_numbers_match") is True
        ):
            advisories.append(warning)
        else:
            review.append(warning)
    return advisories, review



def source_readiness(meeting):
    audit = meeting.get("startlist_pdf_audit") or {}
    status = audit.get("status", "UNKNOWN")
    ready = status in SOURCE_READY_STATUSES
    return {
        "source_ready_snapshot": ready,
        "source_blocker": None if ready else "PDF_STARTLIST_NOT_FULLY_RECONCILED",
        "meeting_source_status": status,
    }


def compact(value, limit=160):
    if value is None:
        return "UNKNOWN"
    return " ".join(str(value).split()).replace("|", "/")[:limit] or "UNKNOWN"


def race_card(doc, *, source_status=None, official_roster=None):
    race = doc["race"]
    qa = doc.get("qa", {})
    lines = [
        f"### Race {race['race_number']} | {compact(race.get('track'))}",
        f"race_key={race['meeting_id']}|{race['race_number']}"
        f" | start_local={compact(race.get('scheduled_time_local'))}"
        f" | distance_m={race.get('distance_m')}"
        f" | start_method={compact(race.get('start_method'))}",
        f"pdf_source_url={race.get('source_url')} | captured_utc={race.get('captured_at_utc')}",
        f"race_number_evidence={compact(race.get('race_number_source'))}"
        f" | horse_count={len(doc.get('entrants', []))}"
        f" | previous_start_rows={qa.get('past_start_rows', 0)}"
        f" | scratch_qa={qa.get('scratch_verification', 'UNVERIFIED')}",
        "QA_WARNINGS=" + json.dumps(qa.get("warnings", []), ensure_ascii=False),
    ]
    # Consumers of draft Releases must see status for every individual race.
    if source_status is not None:
        lines.append(
            "source_ready_snapshot=" + str(source_status["source_ready_snapshot"])
            + " | source_blockers=" + json.dumps(source_status["source_blockers"])
        )
    roster = official_roster or {}
    lines.append(
        "official_roster_handoff_status=" + roster.get("status", "NOT_AVAILABLE")
        + " | roster_first_blocker=" + str(roster.get("first_blocker") or "NONE")
        + " | source_run_id=" + str(roster.get("source_run_id") or "UNKNOWN")
    )
    for label, key in (("starts", "starts_source"), ("driver_changes", "driver_changes_source")):
        receipt = roster.get(key) or {}
        lines.append(
            f"official_{label}_url={compact(receipt.get('url'))}"
            f" | observed_utc={compact(receipt.get('observed_utc'))}"
            f" | raw_sha256={compact(receipt.get('sha256'))}"
            f" | receipt_status={compact(receipt.get('status'))}"
        )
    roster_by_number = {x["start_number"]: x for x in roster.get("runners", [])}
    for horse in sorted(doc.get("entrants", []), key=lambda h: h.get("program_number") or 999):
        lines.append(
            f"#{horse.get('program_number')} {compact(horse.get('name'), 100)}"
            f" | driver={compact(horse.get('driver'), 80)}"
            f" | scratch={horse.get('scratch_state', 'UNVERIFIED')}"
            f" | scratch_asof_utc={horse.get('scratch_captured_utc', 'UNKNOWN')}"
            f" | historical_count={len(horse.get('past_starts', []))}"
        )
        official = roster_by_number.get(horse.get("program_number"))
        if official is not None:
            lines.append(
                f"  official_startlist_driver={compact(official['original_official_driver'])}"
                f" | original_pdf_driver={compact(official.get('original_pdf_driver'))}"
                f" | effective_driver={compact(official['effective_driver'])}"
                f" | driver_change_documented={official['driver_change_documented']}"
                f" | official_is_scratched={official['is_scratched']}"
            )
            if official["driver_change_documented"]:
                changes = [x for x in roster["driver_changes"]
                           if x["start_number"] == horse["program_number"]]
                change = changes[0]
                lines.append(
                    f"  OFFICIAL_DRIVER_CHANGE previous_driver={compact(change['previous_driver'])}"
                    f" | new_driver={compact(change['new_driver'])}"
                    f" | observed_utc={change['observed_utc']}"
                    f" | new_license={compact(change.get('new_driver_license_number'))}"
                )
        for past in horse.get("past_starts", [])[-5:]:
            lines.append(
                f"  - {past.get('date') or '?'} previous_race={past.get('race_number') or '?'}"
                f" | original={compact(past.get('raw_text'), HISTORY_LIMIT)}"
            )
    return "\n".join(lines) + "\n\n"


def write_race_pack(dest, doc, roster, manifest, folder):
    """Expose the existing parsed document losslessly, without a new parser.

    The original archive remains authoritative. A machine-readable transport
    must not turn raw/unverified history cells into approved model features.
    """
    mid = doc["race"]["meeting_id"]
    number = doc["race"]["race_number"]
    if (not isinstance(mid, str) or not mid or "/" in mid or "\\" in mid
            or type(number) is not int or number < 1
            or doc["race"].get("meeting_id") not in {
                m.get("meeting_id") for m in manifest.get("meetings", [])
                if isinstance(m, dict)
            }):
        raise ValueError("RACE_PACK_IDENTITY_INVALID")
    gaps = ["PERMANENT_IDENTITY_NOT_ATTESTED", "CURRENT_WIN_NOT_INCLUDED",
            "SOURCE_SNAPSHOT_NOT_LIVE_CERTIFICATION"]
    if any(
        past.get("cell_contract") == "UNVERIFIED_PDF_LAYOUT"
        for horse in doc.get("entrants", []) for past in horse.get("past_starts", [])
    ):
        gaps.append("STRUCTURED_HISTORY_CELLS_UNVERIFIED")
    if roster.get("status") != "VERIFIED_AS_OF_SOURCE_CAPTURE":
        gaps.append(roster.get("first_blocker") or "OFFICIAL_ROSTER_UNVERIFIED")
    pack = {
        "schema": SCHEMA, "record_type": "FULL_RACE_SOURCE_PACK",
        "race_id": f"RIKSTOTO:{mid}:{number}",
        "date_oslo": manifest["date_oslo"], "source_run_id": manifest["run_id"],
        "source_archive_tag": f"rikstoto-program-{manifest['date_oslo']}-{manifest['run_id']}",
        "manifest_sha256": hashlib.sha256((folder / "manifest.json").read_bytes()).hexdigest(),
        "structured_original_sha256": hashlib.sha256(
            (folder / "structured_program_day.json").read_bytes()).hexdigest(),
        "program": doc, "official_roster": roster,
        "source_receipts": [
            r for r in manifest.get("requests", [])
            if isinstance(r, dict) and isinstance(r.get("url"), str)
            and mid in r["url"]
        ],
        "missing_or_unverified": gaps,
        "phase_a_completed": False, "bet_authority": False,
    }
    raw = (json.dumps(pack, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    name = f"race_pack_{mid}_{number}.json"
    path = dest / name
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError("RACE_PACK_READBACK_CONFLICT") from None
    if path.read_bytes() != raw:
        raise ValueError("RACE_PACK_READBACK_CONFLICT")
    return name, hashlib.sha256(raw).hexdigest()


def build_handoff(root: Path, dest: Path):
    manifests = sorted(root.glob("*/*/manifest.json"))
    if not manifests:
        raise ValueError("Missing daily manifest; cannot publish Pre-Watch feed")
    folder = manifests[-1].parent
    m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    data = json.loads((folder / "structured_program_day.json").read_text(encoding="utf-8"))
    day, run_id = m["date_oslo"], m["run_id"]
    if day != data.get("date") or run_id != data.get("run_id"):
        raise ValueError("Date/run mismatch between manifest and structured program")
    if m.get("status") not in ("CAPTURED_UNVERIFIED", "REVIEW_REQUIRED"):
        raise ValueError("Collector failed; do not publish a Pre-Watch source snapshot")
    meetings = [
        x for x in m.get("meetings", [])
        if x.get("listing_source", {}).get("country") in ("NO", "SE")
        and not x.get("is_multi_track_product")
    ]
    races = {}
    for doc in data.get("races", []):
        races.setdefault(doc["race"]["meeting_id"], []).append(doc)
    # The full official roster and driverChanges are already archived by daily.py.
    # Reconcile their *original SHA-verified bytes* here; never infer no change
    # from an absent/invalid official response.
    official_rosters = {
        entry["meeting_id"]: roster_for_meeting(
            folder, m, entry["meeting_id"], races.get(entry["meeting_id"], []),
            entry.get("startlist_pdf_audit") or {},
        )
        for entry in meetings
    }
    official_stamps = [
        (stamp, rec.get("at_utc")) for rec in m.get("requests", [])
        if isinstance(rec, dict) and rec.get("status") == "JSON_OK"
        and isinstance(rec.get("url"), str)
        and (rec["url"].endswith("/starts") or rec["url"].endswith("/driverChanges"))
        if (stamp := _utc(rec.get("at_utc"))) is not None
    ]
    newest_official_observation = (
        max(official_stamps, key=lambda x: x[0])[1] if official_stamps else None
    )
    dest.mkdir(parents=True, exist_ok=True)
    index = {
        "schema": SCHEMA, "date_oslo": day, "run_id": run_id,
        "created_utc": m.get("created_utc"),
        "snapshot_observed_utc": newest_official_observation,
        "snapshot_clock_source": "LATEST_OFFICIAL_ROSTER_RECEIPT" if newest_official_observation else "UNVERIFIED",
        "collection_status": m.get("status"),
        "source_archive_tag": f"rikstoto-program-{day}-{run_id}",
        "schedule_qa": m.get("schedule_comparison", {}),
        "meeting_feeds": [], "no_race_meetings": [], "race_queue": [],
        "notes": ["Races and starts only; no current WIN prices or V3 sports scoring.",
                  "All scratch statuses are time-stamped snapshots, not final.",
                  "GitHub draft Releases must be fetched by numeric release ID, not by tag."],
    }
    for meeting in meetings:
        mid = meeting["meeting_id"]
        docs = sorted(races.get(mid, []), key=lambda doc: doc["race"]["race_number"])
        if not docs:
            index["no_race_meetings"].append(mid)
            continue
        readiness = source_readiness(meeting)
        for doc in docs:
            race = doc["race"]
            qa = doc.get("qa", {})
            runners = doc.get("entrants", [])
            blockers = []
            if not readiness["source_ready_snapshot"]:
                blockers.append(readiness["source_blocker"])
            if not runners:
                blockers.append("NO_RUNNERS")
            clock_blocker = time_blocker(race.get("scheduled_time_local"))
            if clock_blocker:
                blockers.append(clock_blocker)
            advisories, review_warnings = classify_race_warnings(
                qa, meeting_audit=meeting.get("startlist_pdf_audit") or {})
            if review_warnings:
                blockers.append("RACE_QA_WARNINGS_REVIEW")
            roster = official_rosters.get(mid, {}).get(race["race_number"], {})
            pack_file, pack_sha = write_race_pack(dest, doc, roster, m, folder)
            index["race_queue"].append({
                "race_key": f"{mid}|{race['race_number']}",
                "meeting_id": mid, "race_number": race["race_number"],
                "track": meeting["listing_source"].get("track"),
                "start_local": race.get("scheduled_time_local"),
                "runner_count": len(runners),
                "history_rows": qa.get("past_start_rows", 0),
                "race_pack_file": pack_file, "race_pack_sha256": pack_sha,
                "official_roster_handoff_status": roster.get("status", "NOT_AVAILABLE"),
                "official_roster_first_blocker": roster.get("first_blocker"),
                "official_starts_source": roster.get("starts_source"),
                "official_driver_changes_source": roster.get("driver_changes_source"),
                "official_roster": roster.get("runners", []),
                "official_driver_changes": roster.get("driver_changes", []),
                "source_ready_snapshot": not blockers,
                "source_blockers": blockers,
                "race_qa_advisories": advisories,
                "race_qa_review_warnings": review_warnings,
                "source_release_tag_prefix": f"prewatch-src-{day}-{mid}-",
            })
        meeting_queue = [r for r in index["race_queue"] if r["meeting_id"] == mid]
        queue_by_number = {r["race_number"]: r for r in meeting_queue}
        meeting_all_ready = all(r["source_ready_snapshot"] for r in meeting_queue)
        meeting_blocker = (None if meeting_all_ready else
                           readiness["source_blocker"] or "RACE_SOURCE_BLOCKERS_REVIEW")
        header = (
            "# PRE-WATCH DATA FEED (not a betting recommendation)\n\n"
            f"Schema={SCHEMA} | Date={day} Europe/Oslo | Run={run_id}\n"
            f"Meeting={mid} | Track={compact(meeting.get('listing_source', {}).get('track'))}"
            f" | Country={meeting.get('listing_source', {}).get('country')}\n"
            f"Source ZIP tag={index['source_archive_tag']}"
            f" | PDF/Startlist audit={meeting.get('startlist_pdf_audit', {}).get('status', 'UNKNOWN')}\n"
            f"Collection status={m.get('status')} | Snapshot UTC={m.get('created_utc')}\n"
            f"Source ready snapshot={meeting_all_ready}"
            f" | Source blocker={meeting_blocker or 'NONE'}\n"
            f"Official roster handoff is an as-of capture, not live certification.\n"
            "This is historical/static source evidence for shortlisting, NOT a fresh WIN market."
            " Recheck current scratches, equipment, start times and prices before action.\n"
            "Raw previous-start lines are limited excerpts and are NOT complete trip interpretation.\n\n"
        )
        chunks, current = [], header
        for doc in docs:
            card = race_card(
                doc, source_status=queue_by_number[doc["race"]["race_number"]],
                official_roster=official_rosters.get(mid, {}).get(doc["race"]["race_number"]),
            )
            if len(header) + len(card) > MAX_BODY:
                raise ValueError(f"Race too large for release note: {mid}")
            if len(current) + len(card) > MAX_BODY and current != header:
                chunks.append(current)
                current = header
            current += card
        if current != header:
            chunks.append(current)
        for number, text in enumerate(chunks, 1):
            race_numbers_in_part = [
                int(line.split(" | ", 1)[0].split()[-1])
                for line in text.splitlines() if line.startswith("### Race ")
            ]
            part_queue = [r for r in meeting_queue if r["race_number"] in race_numbers_in_part]
            ready_in_part = sum(r["source_ready_snapshot"] is True for r in part_queue)
            blocked_in_part = len(part_queue) - ready_in_part
            tag = f"prewatch-src-{day}-{mid}-p{number}-{run_id}"
            name = f"prewatch_{mid}_p{number}.md"
            (dest / name).write_text(text, encoding="utf-8")
            index["meeting_feeds"].append({
                "meeting_id": mid, "country": meeting["listing_source"]["country"],
                "track": meeting["listing_source"].get("track"),
                "part": number, "parts": len(chunks),
                "release_tag": tag, "markdown_name": name,
                "race_count": len(race_numbers_in_part),
                "race_numbers": race_numbers_in_part,
                "body_length": len(text),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "source_ready_snapshot": blocked_in_part == 0,
                "source_blocker": None if blocked_in_part == 0 else (
                    readiness["source_blocker"] or "RACE_SOURCE_BLOCKERS_REVIEW"),
                "source_ready_race_count": ready_in_part,
                "source_blocked_race_count": blocked_in_part,
                "meeting_source_status": readiness["meeting_source_status"],
            })
    # Aggregate only per-race decisions, not part-level flags (which can mix).
    index["queue_ready_races"] = sum(r["source_ready_snapshot"] is True for r in index["race_queue"])
    index["queue_review_races"] = len(index["race_queue"]) - index["queue_ready_races"]
    index["source_ready_races"] = index["queue_ready_races"]
    index["source_blocked_races"] = index["queue_review_races"]
    index["meeting_count"] = len(meetings)
    index["race_count"] = sum(len(races.get(x["meeting_id"], [])) for x in meetings)
    index["runner_count"] = sum(len(doc.get("entrants", []))
                                for x in meetings for doc in races.get(x["meeting_id"], []))
    (dest / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# Pre-Watch source bridge {day} (not a sports recommendation)",
        f"SCHEMA={SCHEMA} | RUN={run_id} | DATE_OSLO={day} | SNAPSHOT_UTC={index['created_utc']}",
        f"SNAPSHOT_OBSERVED_UTC={index['snapshot_observed_utc'] or 'UNKNOWN'}"
        f" | SOURCE_CLOCK={index['snapshot_clock_source']}",
        f"NO_SE_MEETINGS={index['meeting_count']} | RACES={index['race_count']}"
        f" | RUNNERS={index['runner_count']} | COLLECTOR_STATUS={index['collection_status']}",
        "Read first-party GitHub REST /repos/Maremoo2/rikstoto-program-collector/releases "
        "via authenticated connector; find matching draft tag, then read /releases/{numeric_id}.body.",
        "A draft may return 404 on /releases/tags/{tag}; use numeric ID from list.",
        f"QUEUE_READY_RACES={index['queue_ready_races']} | QUEUE_REVIEW_RACES={index['queue_review_races']}",
        "Meeting source-release tags:",
    ]
    for item in index["meeting_feeds"]:
        lines.append(f"- {item['release_tag']} | race_numbers={item['race_numbers']}"
                     f" | sha256={item['sha256'][:16]}"
                     f" | source_ready_snapshot={item['source_ready_snapshot']}"
                     f" | source_blocker={item['source_blocker'] or 'NONE'}")
    lines += [
        "",
        "SOURCE SNAPSHOT ONLY: compare SNAPSHOT_OBSERVED_UTC across all same-day run IDs,"
        " not Release display order. Keep older runs as historical evidence.",
        "Recheck fresh official scratches, driver changes, gear and race-start clock before action.",
        "NO WIN ODDS HERE. Do not infer current betting prices, EV, p(win), or WATCH/BET.",
        "The model, thresholds, V3.3.12 write-audit, and all betting rules remain unchanged.",
    ]
    (dest / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("output/daily"))
    p.add_argument("--dest", type=Path, default=Path("prewatch_feed"))
    args = p.parse_args()
    index = build_handoff(args.root, args.dest)
    print(json.dumps({"schema": index["schema"], "day": index["date_oslo"],
                      "meeting_count": index["meeting_count"],
                      "races": index["race_count"], "parts": len(index["meeting_feeds"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

MAX_BODY = 95_000
HISTORY_LIMIT = 500
SCHEMA = "prewatch_source_v1"


def compact(value, limit=160):
    if value is None:
        return "UNKNOWN"
    return " ".join(str(value).split()).replace("|", "/")[:limit] or "UNKNOWN"


def race_card(doc):
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
    for horse in sorted(doc.get("entrants", []), key=lambda h: h.get("program_number") or 999):
        lines.append(
            f"#{horse.get('program_number')} {compact(horse.get('name'), 100)}"
            f" | driver={compact(horse.get('driver'), 80)}"
            f" | scratch={horse.get('scratch_state', 'UNVERIFIED')}"
            f" | scratch_asof_utc={horse.get('scratch_captured_utc', 'UNKNOWN')}"
            f" | historical_count={len(horse.get('past_starts', []))}"
        )
        for past in horse.get("past_starts", [])[-5:]:
            lines.append(
                f"  - {past.get('date') or '?'} previous_race={past.get('race_number') or '?'}"
                f" | original={compact(past.get('raw_text'), HISTORY_LIMIT)}"
            )
    return "\n".join(lines) + "\n\n"


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
    dest.mkdir(parents=True, exist_ok=True)
    index = {
        "schema": SCHEMA, "date_oslo": day, "run_id": run_id,
        "created_utc": m.get("created_utc"),
        "collection_status": m.get("status"),
        "source_archive_tag": f"rikstoto-program-{day}-{run_id}",
        "schedule_qa": m.get("schedule_comparison", {}),
        "meeting_feeds": [], "no_race_meetings": [],
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
        header = (
            "# PRE-WATCH DATA FEED (not a betting recommendation)\n\n"
            f"Schema={SCHEMA} | Date={day} Europe/Oslo | Run={run_id}\n"
            f"Meeting={mid} | Track={compact(meeting.get('listing_source', {}).get('track'))}"
            f" | Country={meeting.get('listing_source', {}).get('country')}\n"
            f"Source ZIP tag={index['source_archive_tag']}"
            f" | PDF/Startlist audit={meeting.get('startlist_pdf_audit', {}).get('status', 'UNKNOWN')}\n"
            f"Collection status={m.get('status')} | Snapshot UTC={m.get('created_utc')}\n"
            "This is historical/static source evidence for shortlisting, NOT a fresh WIN market."
            " Recheck current scratches, equipment, start times and prices before action.\n"
            "Raw previous-start lines are limited excerpts and are NOT complete trip interpretation.\n\n"
        )
        chunks, current = [], header
        for doc in docs:
            card = race_card(doc)
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
                "meeting_source_status": meeting.get("startlist_pdf_audit", {}).get("status"),
            })
    index["meeting_count"] = len(meetings)
    index["race_count"] = sum(len(races.get(x["meeting_id"], [])) for x in meetings)
    index["runner_count"] = sum(len(doc.get("entrants", []))
                                for x in meetings for doc in races.get(x["meeting_id"], []))
    (dest / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# Pre-Watch source bridge {day} (not a sports recommendation)",
        f"SCHEMA={SCHEMA} | RUN={run_id} | DATE_OSLO={day} | SNAPSHOT_UTC={index['created_utc']}",
        f"NO_SE_MEETINGS={index['meeting_count']} | RACES={index['race_count']}"
        f" | RUNNERS={index['runner_count']} | COLLECTOR_STATUS={index['collection_status']}",
        "Read first-party GitHub REST /repos/Maremoo2/rikstoto-program-collector/releases "
        "via authenticated connector; find matching draft tag, then read /releases/{numeric_id}.body.",
        "A draft may return 404 on /releases/tags/{tag}; use numeric ID from list.",
        "Meeting source-release tags:",
    ]
    for item in index["meeting_feeds"]:
        lines.append(f"- {item['release_tag']} | race_numbers={item['race_numbers']}"
                     f" | sha256={item['sha256'][:16]}")
    lines += [
        "",
        "MORNING SNAPSHOT ONLY: check fresh official scratched/gear changes and race-start clock.",
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

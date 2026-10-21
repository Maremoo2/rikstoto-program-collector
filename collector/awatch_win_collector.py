"""Selective, read-only Phase B market probe. Never places or authorizes bets."""
from __future__ import annotations
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import quote
from .market_schedule import plan_awatch_market_checks
from .win_source_probe import probe


def _valid_meeting_id(meeting_id):
    """Accept legacy IDs or an underscore-prefixed ISO calendar date, and nothing else."""
    if not isinstance(meeting_id, str):
        return False
    if re.fullmatch(r"[A-Z0-9_]{3,80}", meeting_id):
        return True
    dated = re.fullmatch(r"[A-Z0-9_]{3,69}_(\\d{4}-\\d{2}-\\d{2})", meeting_id)
    if dated is None:
        return False
    try:
        datetime.fromisoformat(dated.group(1))
    except ValueError:
        return False
    return True


def eligible_race_urls(meetings, *, now, lookahead_minutes=10):
    schedule = plan_awatch_market_checks(meetings, now=now,
                                        lookahead_minutes=lookahead_minutes)
    # Use the planner as the single source of qualification truth.
    # Do not independently reinterpret scores or create divergent gates.
    allowed = {(e["meeting_id"], e["race_number"])
               for e in schedule["events"] if e["race_number"] is not None}
    candidates = {}
    for event in schedule["events"]:
        key = (event["meeting_id"], event["race_number"])
        if key not in allowed:
            continue
        meeting_id, race = key
        if (not _valid_meeting_id(meeting_id)
                or type(race) is not int or race < 1 or race > 99):
            continue
        # First-party public page only. Probe separately enforces robots.
        url = ("https://www.rikstoto.no/Spill/"
               + quote(meeting_id, safe="")
               + "/V?race=" + str(race) + "&p=" + str(race) + ":0")
        candidates[key] = url
    return schedule, candidates


async def collect(meetings, *, now, lookahead_minutes=10):
    schedule, candidates = eligible_race_urls(meetings, now=now,
                                              lookahead_minutes=lookahead_minutes)
    results = []
    for (meeting_id, race_number), url in sorted(candidates.items()):
        try:
            result = await probe(url)
        except Exception as exc:
            result = {"status": "BLOCKED", "reason": "PROBE_EXCEPTION:" + type(exc).__name__,
                      "bet_authorized": False}
        results.append({"meeting_id": meeting_id, "race_number": race_number,
                        "url": url, "diagnostic": result,
                        "bet_authorized": False})
    return {"schema": "prewatch_awatch_win_collection_v1",
            "phase": "B_MARKET_ONLY", "schedule": schedule,
            "probed_race_count": len(results), "races": results,
            "bet_authorized": False, "automated_betting": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lookahead-minutes", type=int, default=10)
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("meetings"), list):
        raise SystemExit("BLOCKED: independently scored Pre-Watch meetings required")
    result = asyncio.run(collect(data["meetings"], now=datetime.now(timezone.utc),
                                 lookahead_minutes=args.lookahead_minutes))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"phase": result["phase"],
                      "probed_race_count": result["probed_race_count"],
                      "bet_authorized": False}))


if __name__ == "__main__":
    main()

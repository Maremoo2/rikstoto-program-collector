"""Read-only preflight for a ready packet and dedicated private draft.

The future mailbox is mutable; original source Releases remain immutable.
Publication is deliberately disabled until a separately approved activation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

from .prewatch_ready import OSLO, SCHEMA, encoded, require, stamp

REPO = "Maremoo2/rikstoto-program-collector"
MAILBOX = "prewatch-ready-v1"


def prepare_update(packet, release, draft_id, now):
    require(type(draft_id) is int and draft_id > 0 and release.get("id") == draft_id
            and release.get("tag_name") == MAILBOX and release.get("draft") is True
            and release.get("published_at") is None and release.get("assets") == [], "UNSAFE_MAILBOX")
    require(packet.get("schema") == SCHEMA and packet.get("replay_only") is False
            and packet.get("phase_a_completed") is False and packet.get("bet_authority") is False
            and packet.get("freeze_recheck_required") is True, "UNSAFE_PACKET")
    require(packet.get("operational_publication_allowed") is True
            and packet.get("ledger_exclusion") == "CALLER_SUPPLIED_VERIFIED_IDS", "LEDGER_OR_PUBLICATION_NOT_VERIFIED")
    ref = stamp(packet["reference_utc"])
    require(packet.get("generated_at_utc") == packet["reference_utc"]
            and packet.get("date_oslo") == now.astimezone(OSLO).date().isoformat()
            and timedelta(0) <= now - ref <= timedelta(minutes=5), "PACKET_NOT_CURRENT")
    selected = packet.get("selected")
    if packet.get("status") == "SOURCE_READY":
        require(isinstance(selected, dict) and stamp(selected["metadata"]["latest_freeze_utc"]) > now
                and stamp(selected["metadata"]["scheduled_start_iso"]) > now, "PACKET_EXPIRED")
    else:
        require(packet.get("status") == "NO_ELIGIBLE_RACE" and selected is None, "PACKET_STATUS_INVALID")
    previous = json.loads(release.get("body") or "{}")
    require(previous.get("schema") == SCHEMA and previous.get("bet_authority") is False, "MAILBOX_MARKER_INVALID")
    if previous.get("reference_utc"):
        require(stamp(previous["reference_utc"]) <= ref, "MAILBOX_NEWER_THAN_PACKET")
        if stamp(previous["reference_utc"]) == ref:
            require(previous == packet, "MAILBOX_SAME_CLOCK_CONFLICT")
    body = encoded(packet).decode("utf-8")
    require(len(body.encode("utf-8")) <= 95_000, "READY_PACKET_TOO_LARGE")
    return {"body": body}


def gh_api(path):
    return json.loads(subprocess.run(["gh", "api", "--method", "GET", path],
                                    text=True, capture_output=True, check=True).stdout)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--draft-id", type=int, required=True)
    p.add_argument("--packet", type=Path, required=True)
    p.add_argument("--apply", action="store_true", help="Reserved for future separately approved activation; currently rejected")
    args = p.parse_args()
    # Fail before reading a local packet or calling GitHub. The future writer
    # must be separately reviewed, serialized and activation-gated.
    require(not args.apply, "MAILBOX_PUBLICATION_DISABLED")
    path = f"repos/{REPO}/releases/{args.draft_id}"
    packet = json.loads(args.packet.read_text(encoding="utf-8"))
    release = gh_api(path)
    prepare_update(packet, release, args.draft_id, datetime.now(timezone.utc))
    print("MAILBOX_PREFLIGHT_PASS_NO_WRITE")


if __name__ == "__main__":
    main()

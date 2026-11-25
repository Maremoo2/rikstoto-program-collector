"""Manually authorized shadow transport. Never grants Phase A or BET authority.

One serialized Actions job; only the fixed draft's body can be patched.
No Ledger write, public artifacts or ordinary Pre-Watch activation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
import zipfile

from . import prewatch_release_readback as releases
from .prewatch_ledger_reader import read_live, SCOPE
from .prewatch_ready import OSLO, SCHEMA, digest, encoded, require, stamp, validate_race, transport_projection
from .prewatch_ready_integration import prepare, verify_sources, check_live_packet

APPROVAL = "PUBLISH_SHADOW_ONLY_458013574"
WORKFLOW = releases.REPO + "/.github/workflows/prewatch-ledger-read-diagnostic.yml@refs/heads/main"
MARKER_PATH = "releases/458013574"
MAX_BODY = 95_000
MAX_FINAL_AGE = 30


def now():
    return datetime.now(timezone.utc)


def context(env):
    require(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_REPOSITORY_ID") == str(releases.REPO_ID)
            and env.get("GITHUB_REF") == "refs/heads/main" and env.get("GITHUB_WORKFLOW_REF") == WORKFLOW
            and env.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and env.get("GITHUB_JOB") == "shadow",
            "SHADOW_CONTEXT_INVALID")
    mode = env.get("SHADOW_MODE")
    require(mode in {"shadow_preflight", "shadow_publish", "shadow_consume"}, "SHADOW_MODE_INVALID")
    require(mode != "shadow_publish" or (env.get("SHADOW_APPROVAL") == APPROVAL
            and env.get("SHADOW_CONSUMER_GUARD_VERIFIED") == "true"), "SHADOW_APPROVAL_REQUIRED")
    require(all(re.fullmatch(r"[0-9]{1,20}", env.get(k, "")) for k in ("COLLECTOR_RUN_ID", "GITHUB_RUN_ID")),
            "SHADOW_RUN_ID_INVALID")
    require(bool(env.get("PREWATCH_LEDGER_ACCESS_TOKEN")), "SHADOW_LEDGER_TOKEN_REQUIRED")
    return mode


def envelope(packet, run_id):
    require(packet["status"] == "SOURCE_READY" and bool(packet["selected"]) and bool(packet["queue"]),
            "SHADOW_NO_ELIGIBLE_RACE")
    require(packet["schema"] == SCHEMA and packet["diagnostic_status"] == "LIVE_LEDGER_SOURCE_DIAGNOSTIC"
            and packet["replay_only"] is False and packet["phase_a_completed"] is False
            and packet["bet_authority"] is False and packet["operational_publication_allowed"] is False
            and packet["freeze_recheck_required"] is True
            and packet["ledger_exclusion"] == "CALLER_SUPPLIED_VERIFIED_IDS"
            and packet["ledger_evidence"]["evidence_kind"] == "GOOGLE_API_READ"
            and packet["ledger_evidence"]["scope"] == SCOPE,
            "SHADOW_PACKET_BOUNDARY_INVALID")
    return {"schema": SCHEMA, "status": "SHADOW_ONLY", "shadow_protocol": "prewatch_shadow_v1",
            "mailbox_id": releases.MARKER_ID, "collector_actions_run_id": str(run_id),
            "reference_utc": packet["reference_utc"], "phase_a_completed": False,
            "bet_authority": False, "operational_publication_allowed": False,
            "packet_sha256": digest(encoded(packet)), "packet": packet}


def decode_body(body):
    require(isinstance(body, str) and len(body.encode("utf-8")) <= MAX_BODY, "SHADOW_BODY_INVALID")
    value = json.loads(body)
    require(isinstance(value, dict), "SHADOW_BODY_INVALID")
    if value == {"schema": SCHEMA, "status": "NOT_INITIALIZED", "bet_authority": False}:
        return None
    require(value.get("shadow_protocol") == "prewatch_shadow_v1" and isinstance(value.get("packet"), dict)
            and re.fullmatch(r"[0-9]{1,20}", value.get("collector_actions_run_id", "")), "SHADOW_ENVELOPE_INVALID")
    expected = envelope(value["packet"], value["collector_actions_run_id"])
    require(value == expected and encoded(value).decode("utf-8") == body, "SHADOW_HASH_OR_ENVELOPE_INVALID")
    return value


def mailbox(getter=releases.get):
    r = getter(MARKER_PATH)
    require(isinstance(r, dict) and r.get("id") == releases.MARKER_ID and r.get("tag_name") == releases.MARKER_TAG
            and r.get("draft") is True and r.get("published_at") is None and r.get("assets") == [],
            "SHADOW_MAILBOX_IDENTITY_INVALID")
    return r, decode_body(r.get("body"))


def plan_body(current, value):
    """No mutation. Reject stale/same-clock conflicts; same exact body is a no-op."""
    _, previous = current
    raw = encoded(value).decode("utf-8")
    require(len(raw.encode("utf-8")) <= MAX_BODY, "SHADOW_BODY_TOO_LARGE")
    if previous is not None:
        before, after = stamp(previous["reference_utc"]), stamp(value["reference_utc"])
        require(before <= after, "SHADOW_OLDER_WRITE_REJECTED")
        if before == after:
            require(previous == value, "SHADOW_SAME_CLOCK_CONFLICT")
            return raw, False
    return raw, True


def patch_body(body, env):
    # Recheck exact runtime approval at the only mutation entry point.
    require(context(env) == "shadow_publish", "SHADOW_WRITE_DISABLED")
    value = decode_body(body)
    require(value is not None, "SHADOW_MARKER_WRITE_FORBIDDEN")
    token = env.get("GH_TOKEN", "")
    require(bool(token), "SHADOW_GITHUB_TOKEN_REQUIRED")
    req = urllib.request.Request(
        "https://api.github.com/repos/" + releases.REPO + "/" + MARKER_PATH,
        data=encoded({"body": body}), method="PATCH",
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "prewatch-shadow-mailbox"})
    # No retry: an ambiguous result must be independently read back, not overwritten.
    try:
        with urllib.request.build_opener(releases.NoRedirect()).open(req, timeout=15) as response:
            require(response.status == 200, "SHADOW_PATCH_STATUS_INVALID")
    except (OSError, urllib.error.HTTPError):
        raise ValueError("SHADOW_PATCH_UNCERTAIN_READBACK_REQUIRED") from None


def official_get(url):
    require(re.fullmatch(r"https://www\.rikstoto\.no/api/(?:racedays/[A-Z0-9]+_NR_\d{4}-\d{2}-\d{2}/starts|game/program/[A-Z0-9]+_NR_\d{4}-\d{2}-\d{2}/driverChanges)", url),
            "SHADOW_OFFICIAL_URL_INVALID")
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json",
        "Cache-Control": "no-cache", "User-Agent": "prewatch-shadow-recheck"})
    try:
        with urllib.request.build_opener(releases.NoRedirect()).open(req, timeout=12) as response:
            require(response.status == 200, "SHADOW_OFFICIAL_HTTP_INVALID")
            raw = response.read(8_388_609)
            require(len(raw) <= 8_388_608, "SHADOW_OFFICIAL_RESPONSE_TOO_LARGE")
            value = json.loads(raw)
    except (OSError, ValueError):
        raise ValueError("SHADOW_OFFICIAL_RECHECK_UNAVAILABLE") from None
    require(isinstance(value, dict) and value.get("success") is True, "SHADOW_OFFICIAL_RESPONSE_INVALID")
    return value


def race_payload(value, name, number):
    require(isinstance(value, dict) and value.get("success") is True, "SHADOW_OFFICIAL_RESPONSE_INVALID")
    result = value.get("result")
    if name == "starts":
        require(isinstance(result, dict) and isinstance(result.get(str(number)), list)
                and bool(result[str(number)]), "SHADOW_OFFICIAL_RACE_MISSING")
        return result[str(number)]
    require(isinstance(result, list), "SHADOW_DRIVER_CHANGES_INVALID")
    return result  # conservative: any meeting driver change requires refreshed source


def recheck_roster(packet, archive, *, getter=official_get, clock=now):
    pack = packet["selected"]["source_pack"]
    race = pack["program"]["race"]
    mid, n = race["meeting_id"], race["race_number"]
    prefix = f"{packet['date_oslo']}/{packet['collector_run_id']}/meetings/{mid}/"
    started = clock()
    with zipfile.ZipFile(archive) as z:
        for key, name, path in (("starts_source", "starts", f"/api/racedays/{mid}/starts"),
                                ("driver_changes_source", "driver_changes", f"/api/game/program/{mid}/driverChanges")):
            receipt = pack["official_roster"][key]
            url = "https://www.rikstoto.no" + path
            original = z.read(prefix + name + ".raw.json")
            require(receipt["url"] == url and digest(original) == receipt["sha256"], "SHADOW_ROSTER_RECEIPT_INVALID")
            fresh = getter(url)
            require(race_payload(json.loads(original), name, n) == race_payload(fresh, name, n),
                    "SHADOW_ROSTER_CHANGED_REFRESH_REQUIRED")
    finished = clock()
    require(0 <= (finished - started).total_seconds() <= 30, "SHADOW_ROSTER_RECHECK_TOO_SLOW")
    return finished


def final_ledger(packet, *, reader=read_live, clock=now):
    result = reader(packet["date_oslo"])
    require(result["evidence_kind"] == "GOOGLE_API_READ" and result["scope"] == SCOPE, "SHADOW_LEDGER_EVIDENCE_INVALID")
    require(0 <= (clock() - stamp(result["read_finished_utc"])).total_seconds() <= MAX_FINAL_AGE, "SHADOW_LEDGER_STALE")
    race_id = packet["selected"]["metadata"]["ledger_race_id"]
    require(race_id not in result["completed_ids"], "SHADOW_ALREADY_COMPLETED")
    require(not ({m["ledger_race_id"] for m in packet["queue"]} & set(result["completed_ids"])),
            "SHADOW_QUEUE_LEDGER_CHANGED")
    return result


def current_archive(index, *, getter=releases.get, clock=now):
    day, _, archive, _ = releases.index_tags(index)
    prefix = f"rikstoto-program-{day}-"
    rows = releases.list_rows(getter)
    require(any(r["id"] == releases.MARKER_ID and r["tag_name"] == releases.MARKER_TAG and r["draft"] is True for r in rows),
            "SHADOW_DRAFT_VISIBILITY_UNCONFIRMED")
    candidates = []
    for r in rows:
        if r["tag_name"].startswith(prefix):
            require(r["draft"] is True, "SHADOW_ARCHIVE_NOT_DRAFT")
            candidates.append(r["tag_name"])
    require(candidates and len(set(candidates)) == len(candidates), "SHADOW_ARCHIVE_TAGS_INVALID")
    # Run IDs are UTC chronological; require BOTH latest run ID and earlier
    # verified observation ordering. A newly visible archive is fail-closed.
    require(max(candidates) == archive, "SHADOW_NEWER_ARCHIVE_AVAILABLE")
    return clock()


def final_gate(packet, roster_at, archive_at, ledger, *, clock=now):
    at = clock()
    check_live_packet(packet, at)
    for t in (roster_at, archive_at, stamp(ledger["read_finished_utc"])):
        require(0 <= (at - t).total_seconds() <= MAX_FINAL_AGE, "SHADOW_FINAL_RECHECK_EXPIRED")
    return at


def validate_consumed(value, feed, index, ids, at):
    require(value is not None, "SHADOW_MAILBOX_NOT_INITIALIZED")
    packet = value["packet"]
    check_live_packet(packet, at)
    require(packet["collector_run_id"] == index["run_id"] and packet["date_oslo"] == index["date_oslo"]
            and packet["index_sha256"] == digest((feed / "index.json").read_bytes()), "SHADOW_SOURCE_IDENTITY_MISMATCH")
    meta = packet["selected"]["metadata"]
    matching = [q for q in index["race_queue"] if q.get("race_key") ==
                meta["race_id"].removeprefix("RIKSTOTO:").replace(":", "|")]
    require(len(matching) == 1 and sum(m == meta for m in packet["queue"]) == 1, "SHADOW_SELECTED_IDENTITY_INVALID")
    rebuilt, pack = validate_race(feed, index, matching[0], at, ids, packet["min_analysis_window_seconds"])
    omit = lambda x: {k: v for k, v in x.items() if k != "roster_age_seconds"}
    require(omit(rebuilt) == omit(meta) and transport_projection(pack) == packet["selected"]["source_pack"],
            "SHADOW_FULL_FIELD_MISMATCH")
    return packet


def main():
    try:
        mode = context(os.environ)
        root = Path(os.environ["RUNNER_TEMP"]) / "shadow-source"
        feed, assets = root / "prewatch_feed", root / "release-assets"
        archives = list(assets.glob("rikstoto-*.zip"))
        require(len(archives) == 1, "SHADOW_SOURCE_ARTIFACT_INVALID")
        archive, notes = archives[0], assets / "release_notes.md"
        index = json.loads((feed / "index.json").read_bytes())
        run_id = os.environ["COLLECTOR_RUN_ID"]
        receipt = releases.readback(index, run_id, os.environ["GITHUB_RUN_ID"])
        records = receipt["records"]
        if mode == "shadow_consume":
            _, value = mailbox()
            require(value is not None and value["collector_actions_run_id"] == run_id, "SHADOW_SOURCE_RUN_MISMATCH")
            ids = verify_sources(feed, archive, notes, records, now(), verified_receipt=True)
            packet = validate_consumed(value, feed, index, ids, now())
        else:
            packet = prepare(feed, archive, notes, records, now(), read_ledger=True, release_receipt=receipt)
            value = envelope(packet, run_id)
        # Final live checks: no grace period or renewal of original 30-minute clock.
        roster_at = recheck_roster(packet, archive)
        archive_at = current_archive(index)
        ledger = final_ledger(packet)
        current = mailbox()
        final_gate(packet, roster_at, archive_at, ledger)
        if mode == "shadow_consume":
            require(current[1] == value, "SHADOW_MAILBOX_CHANGED_DURING_READ")
            print("SHADOW_CONSUMER_READBACK_PASS_NO_PHASE_A")
        else:
            body, write_needed = plan_body(current, value)
            if mode == "shadow_preflight":
                print("SHADOW_PREFLIGHT_PASS_NO_WRITE")
            else:
                final_gate(packet, roster_at, archive_at, ledger)
                if write_needed:
                    patch_body(body, os.environ)
                actual, decoded = mailbox()
                require(actual["body"] == body and decoded == value and
                        digest(actual["body"].encode("utf-8")) == digest(body.encode("utf-8")),
                        "SHADOW_PATCH_READBACK_MISMATCH")
                check_live_packet(packet, now())
                print("SHADOW_WRITE_READBACK_PASS" if write_needed else "SHADOW_IDEMPOTENT_READBACK_PASS")
                print("SHADOW_BODY_SHA256=" + digest(body.encode("utf-8")))
        print("SHADOW_LEDGER_READ_PASS")
        print("SHADOW_PACKET_SHA256=" + value["packet_sha256"])
        print("SHADOW_ELIGIBLE_COUNT=" + str(len(packet["queue"])))
        print("SHADOW_NO_BET_NO_PHASE_A")
    except Exception as exc:
        code = str(exc)
        print(code if re.fullmatch(r"[A-Z][A-Z0-9_]{2,90}", code) else "SHADOW_FAILED_CLOSED")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

"""Verified read-only official roster receipts for the existing Pre-Watch handoff.

The raw first-party HTTP bodies and request receipts are already collected by
collector.daily. This module reads those originals without making network
requests or changing the PDF/startlist reconciliation contract.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .startlist_audit import normalized_horse_name

RUN_ID = re.compile(r"\d{8}T\d{12}Z\Z")
SCHEMA = "prewatch_source_v1"


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def official_receipt(folder: Path, manifest: dict, meeting_id: str,
                     filename: str, suffix: str) -> dict:
    """Require the original JSON bytes, wrapper and matching SHA receipt.

    A missing or contradictory source must not become an assumed empty
    driver-change list or a supposedly un-scratched field.
    """
    url = "https://www.rikstoto.no" + suffix.format(meeting=meeting_id)
    records = [
        r for r in manifest.get("requests", [])
        if isinstance(r, dict) and r.get("url") == url and r.get("status") == "JSON_OK"
    ]
    if len(records) != 1:
        return {"status": "SOURCE_RECEIPT_NOT_UNIQUE", "url": url}
    receipt = records[0]
    observed = receipt.get("at_utc")
    if (_utc(observed) is None or receipt.get("raw_readback_verified") is not True
            or receipt.get("source_publication_time_attested") is not False):
        return {"status": "SOURCE_RECEIPT_INVALID", "url": url}
    expected_tail = f"/meetings/{meeting_id}/{filename}"
    path_claim = receipt.get("path")
    if not isinstance(path_claim, str) or not path_claim.endswith(expected_tail):
        return {"status": "SOURCE_PATH_MISMATCH", "url": url}
    base = folder / "meetings" / meeting_id
    path = base / filename
    raw_path = path.with_name(path.stem + ".raw.json")
    if not path.is_file() or not raw_path.is_file() or path.is_symlink() or raw_path.is_symlink():
        return {"status": "SOURCE_BYTES_MISSING", "url": url}
    raw_claim = receipt.get("raw_path")
    if not isinstance(raw_claim, str) or not raw_claim.endswith(
        f"/meetings/{meeting_id}/{raw_path.name}"
    ):
        return {"status": "SOURCE_RAW_PATH_MISMATCH", "url": url}
    original, wrapper = raw_path.read_bytes(), path.read_bytes()
    raw_sha = hashlib.sha256(original).hexdigest()
    wrap_sha = hashlib.sha256(wrapper).hexdigest()
    if raw_sha != receipt.get("sha256") or wrap_sha != receipt.get("wrapper_sha256"):
        return {"status": "SOURCE_SHA_MISMATCH", "url": url}
    try:
        response = json.loads(original)
        envelope = json.loads(wrapper)
    except (ValueError, UnicodeDecodeError):
        return {"status": "SOURCE_JSON_INVALID", "url": url}
    if (not isinstance(envelope, dict) or envelope.get("response") != response
            or envelope.get("source_url") != url
            or envelope.get("fetched_utc") != observed
            or not isinstance(response, dict) or response.get("success") is not True):
        return {"status": "SOURCE_WRAPPER_MISMATCH", "url": url}
    return {
        "status": "SHA_VERIFIED_SOURCE_RECEIPT", "url": url,
        "observed_utc": observed, "sha256": raw_sha,
        "wrapper_sha256": wrap_sha, "raw_path": raw_claim,
        "source_publication_time_attested": False, "response": response,
    }


def roster_for_meeting(folder: Path, manifest: dict, meeting_id: str,
                       docs: list[dict], audit: dict) -> dict[int, dict]:
    """Produce one verifiable field per race; never claim it is still live."""
    starts = official_receipt(
        folder, manifest, meeting_id, "starts.json",
        "/api/racedays/{meeting}/starts",
    )
    changes = official_receipt(
        folder, manifest, meeting_id, "driver_changes.json",
        "/api/game/program/{meeting}/driverChanges",
    )
    result = {}
    for doc in docs:
        n = doc["race"]["race_number"]
        evidence = {
            "status": "ROSTER_EVIDENCE_UNVERIFIED",
            "source_run_id": manifest["run_id"],
            "starts_source": {k: v for k, v in starts.items() if k != "response"},
            "driver_changes_source": {k: v for k, v in changes.items() if k != "response"},
            "runners": [], "driver_changes": [], "first_blocker": None,
        }
        result[n] = evidence
        if audit.get("status") != "MATCHED_AS_OF_SNAPSHOT":
            evidence["first_blocker"] = "PDF_STARTLIST_NOT_FULLY_RECONCILED"
            continue
        if starts["status"] != "SHA_VERIFIED_SOURCE_RECEIPT":
            evidence["first_blocker"] = starts["status"]
            continue
        if changes["status"] != "SHA_VERIFIED_SOURCE_RECEIPT":
            evidence["first_blocker"] = changes["status"]
            continue
        start_result = starts["response"].get("result")
        change_result = changes["response"].get("result")
        if not isinstance(start_result, dict) or not isinstance(change_result, list):
            evidence["first_blocker"] = "OFFICIAL_RESPONSE_SCHEMA_INVALID"
            continue
        rows = start_result.get(str(n))
        if not isinstance(rows, list) or not rows:
            evidence["first_blocker"] = "RACE_NOT_IN_OFFICIAL_STARTS"
            continue
        pdf = doc.get("entrants", [])
        horses = {h.get("program_number"): h for h in pdf}
        if len(horses) != len(pdf):
            evidence["first_blocker"] = "AMBIGUOUS_PDF_HORSE_NUMBERS"
            continue
        official = {}
        valid = True
        for row in rows:
            if (not isinstance(row, dict) or type(row.get("raceNumber")) is not int
                    or row["raceNumber"] != n
                    or type(row.get("startNumber")) is not int
                    or row["startNumber"] in official
                    or not isinstance(row.get("horseName"), str)
                    or not isinstance(row.get("driverName"), str)
                    or not row["driverName"].strip()
                    or type(row.get("isScratched")) is not bool
                    or row.get("raceKey") not in (None, f"{meeting_id}#{n}")):
                valid = False
                break
            official[row["startNumber"]] = row
        if not valid or set(official) != set(horses):
            evidence["first_blocker"] = "OFFICIAL_FIELD_IDENTITY_MISMATCH"
            continue
        if any(
            normalized_horse_name(official[k]["horseName"]) != normalized_horse_name(horses[k]["name"])
            or horses[k].get("scratch_state") != (
                "SCRATCHED_AS_OF_SNAPSHOT" if official[k]["isScratched"] else "ACTIVE_AS_OF_SNAPSHOT"
            )
            for k in official
        ):
            evidence["first_blocker"] = "OFFICIAL_HORSE_OR_SCRATCH_MISMATCH"
            continue
        edits = {}
        for change in change_result:
            if not isinstance(change, dict):
                valid = False
                break
            # Other races in this meeting are allowed. A target-race change
            # must identify exactly one of this race's official starters.
            if change.get("raceNumber") != n:
                continue
            number = change.get("startNumber")
            if (type(number) is not int or number not in official or number in edits
                    or change.get("raceKey") not in (None, f"{meeting_id}#{n}")
                    or not isinstance(change.get("newDriver"), str)
                    or not change["newDriver"].strip()):
                valid = False
                break
            edits[number] = change
        if not valid:
            evidence["first_blocker"] = "DRIVER_CHANGE_IDENTITY_INVALID"
            continue
        for number in sorted(official):
            row = official[number]
            new = edits.get(number)
            entry = {
                "start_number": number, "horse_name": row["horseName"],
                "is_scratched": row["isScratched"],
                "original_official_driver": row["driverName"],
                "original_pdf_driver": horses[number].get("driver"),
                "effective_driver": new["newDriver"] if new else row["driverName"],
                "driver_change_documented": bool(new),
                "starts_observed_utc": starts["observed_utc"],
                "driver_changes_observed_utc": changes["observed_utc"],
            }
            evidence["runners"].append(entry)
            if new:
                evidence["driver_changes"].append({
                    "start_number": number, "horse_name": row["horseName"],
                    "previous_driver": row["driverName"],
                    "new_driver": new["newDriver"],
                    "new_driver_license_number": new.get("driverLicenseNumber"),
                    "observed_utc": changes["observed_utc"],
                })
        evidence["status"] = "VERIFIED_AS_OF_SOURCE_CAPTURE"
    return result


def latest_snapshot_by_observation(indexes: list[dict], date_oslo: str) -> dict | None:
    """Choose newest *observed* source index, not the latest Release ID.

    The consumer must separately verify the associated Release/source archive.
    This does not certify provider publication time or live freshness.
    """
    candidates = []
    for item in indexes:
        if not isinstance(item, dict) or item.get("schema") != SCHEMA:
            continue
        run = item.get("run_id")
        if (item.get("date_oslo") != date_oslo or not isinstance(run, str)
                or not RUN_ID.fullmatch(run) or not run.startswith(date_oslo.replace("-", ""))
                or item.get("source_archive_tag") != f"rikstoto-program-{date_oslo}-{run}"):
            continue
        stamp = _utc(item.get("snapshot_observed_utc"))
        if stamp is None:
            continue
        candidates.append((stamp, run, item))
    return max(candidates, key=lambda candidate: candidate[:2])[2] if candidates else None


def compare_roster_snapshots(previous: dict, current: dict) -> list[dict]:
    """Diff two verified records of the SAME physical race, without overwrites."""
    if (previous.get("status") != "VERIFIED_AS_OF_SOURCE_CAPTURE"
            or current.get("status") != "VERIFIED_AS_OF_SOURCE_CAPTURE"):
        raise ValueError("Both snapshots must have verified source evidence")
    before = {x["start_number"]: x for x in previous["runners"]}
    after = {x["start_number"]: x for x in current["runners"]}
    if before.keys() != after.keys() or any(
        normalized_horse_name(before[n]["horse_name"]) != normalized_horse_name(after[n]["horse_name"])
        for n in before
    ):
        raise ValueError("Full field identity changed; requires independent QA")
    changes = []
    for n in sorted(before):
        for field in ("is_scratched", "effective_driver"):
            if before[n][field] != after[n][field]:
                changes.append({
                    "start_number": n, "horse_name": after[n]["horse_name"],
                    "field": field, "previous": before[n][field], "current": after[n][field],
                    "source_run_id": current.get("source_run_id"),
                })
    return changes

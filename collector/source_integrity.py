"""Conservative P0 source guards; not scoring or betting logic."""
from __future__ import annotations

import re
from datetime import date

CLOCK = re.compile(r"(?:[01]?\d|2[0-3]):[0-5]\d\Z")


def time_blocker(value):
    """Require separate evidence to accept midnight as a true start time."""
    if not isinstance(value, str) or not value:
        return "START_TIME_UNKNOWN"
    if not CLOCK.fullmatch(value):
        return "START_TIME_INVALID"
    if value in ("0:00", "00:00"):
        return "START_TIME_UNVERIFIED_MIDNIGHT"
    return None


def coverage_gap(*, race_date, discovered_meetings, external_cards):
    """Flag external card evidence absent in discovery; never invent race IDs."""
    date.fromisoformat(race_date)
    result = []
    for card in external_cards:
        if (card.get("date") != race_date or not card.get("source_url")
                or not card.get("country") or not card.get("track")):
            continue
        if any(m.get("track") == card["track"] and m.get("country") == card["country"]
               for m in discovered_meetings):
            continue
        result.append({
            "status": "COVERAGE_GAP", "date": race_date,
            "track": card["track"], "country": card["country"],
            "externally_listed_races": card.get("race_count"),
            "source_url": card["source_url"], "meeting_id": None,
            "source_ready": False,
        })
    return result


def archive_json_bytes(raw: bytes, path, *, url: str, observed_at_utc: str):
    """Persist exact HTTP JSON bytes alongside the legacy formatted wrapper.

    Source SHA-256 is over HTTP body bytes, not the formatted wrapper. A
    successful write requires byte-for-byte readback of both files. Old
    archived wrappers cannot recover absent raw HTTP bytes.
    """
    import hashlib
    import json
    from pathlib import Path

    if not isinstance(raw, bytes):
        raise TypeError("Original JSON response must be bytes")
    destination = Path(path)
    if destination.suffix != ".json":
        raise ValueError("JSON archive destination must end in .json")
    value = json.loads(raw)
    raw_path = destination.with_name(destination.stem + ".raw.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw_sha = hashlib.sha256(raw).hexdigest()
    raw_path.write_bytes(raw)
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != raw_sha:
        raise OSError("RAW_JSON_READBACK_SHA_MISMATCH")

    wrapper = json.dumps(
        {"source_url": url, "fetched_utc": observed_at_utc, "response": value},
        ensure_ascii=False, indent=2,
    ).encode("utf-8")
    wrapper_sha = hashlib.sha256(wrapper).hexdigest()
    destination.write_bytes(wrapper)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != wrapper_sha:
        raise OSError("WRAPPER_JSON_READBACK_SHA_MISMATCH")
    return value, {
        "raw_path": str(raw_path), "sha256": raw_sha,
        "wrapper_sha256": wrapper_sha,
        "raw_bytes": len(raw), "wrapper_bytes": len(wrapper),
        "raw_readback_verified": True,
        "source_publication_time_attested": False,
    }

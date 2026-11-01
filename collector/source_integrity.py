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



def write_original_bytes_once(raw: bytes, path, *, label: str) -> str:
    """Exclusive, byte-identical source archive; pre-existing source is immutable.

    Never trust a file left by a previous attempt as current source bytes.
    No overwrite, including when a previous file contains identical bytes.
    """
    import hashlib
    import os
    from pathlib import Path

    if not isinstance(raw, bytes):
        raise TypeError("Original HTTP response body must be bytes")
    if label not in {"PDF", "RAW_JSON", "WRAPPER_JSON",
                     "OFFICIAL_CALENDAR_HTML", "OFFICIAL_ROBOTS_TEXT"}:
        raise ValueError("Unexpected source archive kind")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    # O_EXCL ensures a repeated GET cannot silently replace the first
    # original response, even if the two HTTP representations are identical.
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise OSError(f"{label}_READBACK_SHA_MISMATCH")
    except BaseException:
        # The exclusive open above owned this new path, not any prior archive.
        # Leave NO successful manifest receipt; remove only our failed write.
        target.unlink(missing_ok=True)
        raise
    return digest


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
    raw_sha = hashlib.sha256(raw).hexdigest()
    wrapper = json.dumps(
        {"source_url": url, "fetched_utc": observed_at_utc, "response": value},
        ensure_ascii=False, indent=2,
    ).encode("utf-8")
    wrapper_sha = hashlib.sha256(wrapper).hexdigest()
    # Check both paths before creation to avoid leaving a new raw orphan
    # when an earlier wrapper already exists. Exclusive OS writes below
    # remain authoritative for races between this check and creation.
    if destination.exists() or destination.is_symlink() or raw_path.exists() or raw_path.is_symlink():
        raise FileExistsError("ORIGINAL_SOURCE_ARCHIVE_COLLISION")
    write_original_bytes_once(raw, raw_path, label="RAW_JSON")
    try:
        write_original_bytes_once(wrapper, destination, label="WRAPPER_JSON")
    except BaseException:
        # Only remove the raw file successfully created by THIS call.
        raw_path.unlink(missing_ok=True)
        raise
    return value, {
        "raw_path": str(raw_path), "sha256": raw_sha,
        "wrapper_sha256": wrapper_sha,
        "raw_bytes": len(raw), "wrapper_bytes": len(wrapper),
        "raw_readback_verified": True,
        "original_archive_append_only_exclusive_create": True,
        "source_publication_time_attested": False,
    }

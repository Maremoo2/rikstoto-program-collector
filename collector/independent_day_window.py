"""Read-only source-attached NO/SE trotting calendar comparison for day + 2.

This is a forensic aid, NEVER a complete-day denominator certification.
Official-host URL plus a locally hashed page copy is *not* proof that the
page was captured from that host; no transport signature or independent
human review is implied. Does not fetch websites or change production files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from .no_se_calendar import audit_no_se_trot_discovery

SCHEMA = "independent_official_calendar_evidence_v1"
REPORT_SCHEMA = "collector_no_se_day_plus_two_comparison_v1"
OFFICIAL_HOSTS = {
    "NO": {"travsport.no", "www.travsport.no", "old.travsport.no"},
    "SE": {"travsport.se", "www.travsport.se"},
}
SHA = re.compile(r"[0-9a-f]{64}\Z")
VENUE_SUFFIX = re.compile(r"\s+(travbane|travpark|travet|arena)\Z")
MAX_RAW_BYTES = 8_000_000


def _venue_name(name: str) -> str:
    """Deterministic candidate normalization, not a horse/race ID mapping."""
    value = " ".join(unicodedata.normalize("NFKC", name).casefold().split())
    return VENUE_SUFFIX.sub("", value)


def _utc(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return stamp.tzinfo is not None and stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() == 0


def _trusted_official_url(url: Any, country: str) -> bool:
    if not isinstance(url, str) or country not in OFFICIAL_HOSTS:
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https"
                and parsed.hostname in OFFICIAL_HOSTS[country]
                and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None
                and not parsed.fragment and bool(parsed.path))
    except ValueError:
        return False


def _source_bytes(directory: Path, relative: Any, claimed_sha: Any) -> tuple[str | None, str | None]:
    """Require original local bytes to match SHA; no URL/network reads."""
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or not isinstance(claimed_sha, str) or not SHA.fullmatch(claimed_sha)):
        return None, "MALFORMED_RAW_SOURCE_RECEIPT"
    logical = PurePosixPath(relative)
    if (logical.is_absolute() or any(part in (".", "..") for part in relative.split("/"))
            or not logical.parts):
        return None, "UNSAFE_RAW_SOURCE_PATH"
    target = (directory / relative).resolve()
    root = directory.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None, "RAW_SOURCE_NOT_LOCAL_FILE"
    if target.stat().st_size > MAX_RAW_BYTES:
        return None, "RAW_SOURCE_TOO_LARGE"
    content = target.read_bytes()
    if hashlib.sha256(content).hexdigest() != claimed_sha:
        return None, "RAW_SOURCE_SHA_MISMATCH"
    try:
        return content.decode("utf-8-sig"), None
    except UnicodeError:
        return None, "RAW_SOURCE_NOT_UTF8"


def read_official_bundle(path: Path, *, day: str) -> dict[str, Any]:
    """Validate local source-copy integrity and each quoted calendar event.

    The bundle is a reviewable claim about offline bytes. No API proof,
    original HTTP Date, completeness or source publication time is inferred.
    """
    result: dict[str, Any] = {
        "status": "BLOCKED", "date_oslo": day, "source_receipts_verified": 0,
        "countries_with_source_copy": [], "events": [], "errors": [],
        "independent_transport_origin_attested": False,
        "independent_all_meetings_denominator_verified": False,
        "independent_all_races_denominator_verified": False,
        "pit_certified": False,
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        result["errors"].append("BUNDLE_UNREADABLE")
        return result
    if (not isinstance(payload, dict) or payload.get("schema") != SCHEMA
            or payload.get("date_oslo") != day
            or not isinstance(payload.get("sources"), list)
            or not payload["sources"]):
        result["errors"].append("BUNDLE_SCHEMA_OR_DAY_MISMATCH")
        return result
    seen_sources: set[str] = set()
    seen_venues: set[tuple[str, str]] = set()
    countries: set[str] = set()
    for source in payload["sources"]:
        if not isinstance(source, dict):
            result["errors"].append("MALFORMED_SOURCE_ITEM")
            continue
        country = source.get("country")
        url = source.get("source_url")
        if not _trusted_official_url(url, country):
            result["errors"].append("UNTRUSTED_OFFICIAL_CALENDAR_ORIGIN")
            continue
        if (source.get("http_status") != 200 or not _utc(source.get("observed_at_utc"))
                or source.get("source_publication_time_attested") is True):
            result["errors"].append("UNSUPPORTED_SOURCE_RECEIPT_OR_TIME_CLAIM")
            continue
        if url in seen_sources:
            result["errors"].append("DUPLICATE_OFFICIAL_SOURCE_URL")
            continue
        seen_sources.add(url)
        raw, err = _source_bytes(path.parent, source.get("raw_path"), source.get("raw_sha256"))
        if err:
            result["errors"].append(err)
            continue
        result["source_receipts_verified"] += 1
        countries.add(country)
        meetings = source.get("meetings")
        if not isinstance(meetings, list):
            result["errors"].append("OFFICIAL_MEETING_LIST_NOT_PRESENT")
            continue
        for row in meetings:
            if not isinstance(row, dict):
                result["errors"].append("MALFORMED_OFFICIAL_MEETING")
                continue
            venue, excerpt = row.get("venue"), row.get("evidence_excerpt")
            if (row.get("date") != day or not isinstance(venue, str)
                    or not venue.strip() or len(venue) > 130
                    or not isinstance(excerpt, str) or not excerpt.strip()
                    or len(excerpt) > 1000):
                result["errors"].append("OFFICIAL_MEETING_DAY_OR_TEXT_INVALID")
                continue
            # A copied web page can vary in presentation, so support two
            # unambiguous date spellings only. A yearless header is NOT enough.
            day_date = date.fromisoformat(day)
            date_tokens = (day, day_date.strftime("%d.%m.%Y"))
            if (excerpt not in raw or not any(token in excerpt for token in date_tokens)
                    or _venue_name(venue) not in _venue_name(excerpt)):
                result["errors"].append("SOURCE_EVENT_EXCERPT_NOT_ATTESTED")
                continue
            key = (country, _venue_name(venue))
            if key in seen_venues:
                result["errors"].append("DUPLICATE_OFFICIAL_VENUE")
                continue
            seen_venues.add(key)
            result["events"].append({
                "date_oslo": day, "country": country, "venue": venue,
                "venue_key": key[1], "source_url": url,
                "source_raw_sha256": source["raw_sha256"],
                "observed_at_utc": source["observed_at_utc"],
                "race_numbers_independently_verified": False,
            })
    result["countries_with_source_copy"] = sorted(countries)
    if not result["errors"] and countries == {"NO", "SE"}:
        result["status"] = "SOURCE_COPIES_HASHED_CANDIDATE_LIST_ONLY"
    else:
        if countries != {"NO", "SE"}:
            result["errors"].append("MISSING_NO_OR_SE_OFFICIAL_SOURCE_COPY")
    result["errors"] = sorted(set(result["errors"]))
    return result


def audit_official_day(manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Compare track-name candidates without claiming all-races completeness."""
    day = manifest.get("date_oslo")
    if not isinstance(day, str) or source.get("date_oslo") != day:
        raise ValueError("Manifest/official calendar day mismatch")
    discovered = audit_no_se_trot_discovery(manifest)
    target = set(discovered["no_se_trot_physical_candidate_ids"])
    meetings = {r["meeting_id"]: r for r in manifest.get("meetings", [])
                if isinstance(r, dict) and isinstance(r.get("meeting_id"), str)}
    collector_index: dict[tuple[str, str], list[str]] = {}
    source_no_track: list[str] = []
    for mid in target:
        r = meetings.get(mid)
        if r is None:
            source_no_track.append(mid)
            continue
        listing = r.get("listing_source") if isinstance(r.get("listing_source"), dict) else {}
        calendar = r.get("calendar_source") if isinstance(r.get("calendar_source"), dict) else {}
        track = listing.get("track") or calendar.get("track")
        country = listing.get("country") or calendar.get("country")
        if not isinstance(track, str) or not track.strip() or country not in {"NO", "SE"}:
            source_no_track.append(mid)
            continue
        collector_index.setdefault((country, _venue_name(track)), []).append(mid)
    matched, unmatched, ambiguous = [], [], []
    used_ids = set()
    for event in source.get("events", []):
        key = (event["country"], event["venue_key"])
        candidates = collector_index.get(key, [])
        if len(candidates) == 1 and source.get("status") == "SOURCE_COPIES_HASHED_CANDIDATE_LIST_ONLY":
            mid = candidates[0]
            matched.append({"country": key[0], "venue": event["venue"],
                            "collector_meeting_id": mid})
            used_ids.add(mid)
        elif len(candidates) > 1:
            ambiguous.append({"venue": event["venue"], "collector_ids": sorted(candidates)})
        else:
            unmatched.append({"venue": event["venue"], "country": event["country"]})
    remaining = sorted(target - used_ids)
    return {
        "schema": REPORT_SCHEMA, "date_oslo": day,
        "status": "BLOCKED_INDEPENDENT_FULL_DAY_DENOMINATOR",
        "official_source_receipts_verified": source.get("source_receipts_verified", 0),
        "official_source_errors": source.get("errors", []),
        "official_venues_in_attached_copies": len(source.get("events", [])),
        "collector_observed_target_meetings": len(target),
        "matched_venue_candidates": matched,
        "independent_venues_unmatched_to_collector": unmatched,
        "ambiguous_venue_matches": ambiguous,
        "collector_candidates_not_correlated_to_official": remaining,
        "collector_candidates_without_typed_venue": sorted(source_no_track),
        "source_countries_missing": sorted({"NO", "SE"} - set(source.get("countries_with_source_copy", []))),
        "race_denominator_independently_verified": False,
        "meeting_denominator_independently_verified": False,
        "coverage_percentage": None, "c1_coverage_eligible": False,
        "pit_certified": False, "bet_authorized": False,
        "notes": ["URL allowlist and SHA only attest a locally retained source copy; not its live origin.",
                  "A meeting-level calendar never establishes the number of physical races.",
                  "Unmatched and ambiguous venue names require source-based human adjudication."],
    }


def window_dates(day: str) -> list[str]:
    first = date.fromisoformat(day)
    if first.isoformat() != day:
        raise ValueError("Date must be YYYY-MM-DD")
    return [(first + timedelta(days=i)).isoformat() for i in range(3)]


def audit_window(start_day: str, manifests: dict[str, dict],
                 bundles: dict[str, dict]) -> dict[str, Any]:
    """Three-day read-only diagnostics: missing days remain BLOCKED."""
    rows = []
    for day in window_dates(start_day):
        manifest = manifests.get(day)
        bundle = bundles.get(day)
        if manifest is None or bundle is None:
            rows.append({"date_oslo": day, "status": "BLOCKED_MISSING_EVIDENCE",
                         "missing_collector_manifest": manifest is None,
                         "missing_official_bundle": bundle is None,
                         "coverage_percentage": None, "pit_certified": False})
            continue
        rows.append(audit_official_day(manifest, bundle))
    return {
        "schema": REPORT_SCHEMA, "window_start": start_day,
        "window_dates": window_dates(start_day), "days": rows,
        "status": "BLOCKED_INDEPENDENT_FULL_DAY_DENOMINATOR",
        "independent_meeting_denominator_verified": False,
        "independent_race_denominator_verified": False,
        "coverage_percentage": None,
        "c1_14_day_coverage_eligible": False,
        "pit_certified": False, "bet_authorized": False,
    }


def _arg_items(values: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("Expected DATE=FILE")
        day, location = value.split("=", 1)
        date.fromisoformat(day)
        if day in out:
            raise ValueError("Duplicate date argument")
        out[day] = Path(location)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", required=True, help="Explicit Oslo date YYYY-MM-DD")
    parser.add_argument("--manifest", action="append", default=[], help="DATE=archived-manifest.json")
    parser.add_argument("--source-bundle", action="append", default=[], help="DATE=offline-official-source-index.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    manifests = {}
    for day, path in _arg_items(args.manifest).items():
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or obj.get("date_oslo") != day:
            raise ValueError("Manifest day mismatch")
        manifests[day] = obj
    bundles = {day: read_official_bundle(path, day=day)
               for day, path in _arg_items(args.source_bundle).items()}
    report = audit_window(args.today, manifests, bundles)
    body = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body + "\n", encoding="utf-8")
    print(body)
    # Intentionally not a passing C1 certification command.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

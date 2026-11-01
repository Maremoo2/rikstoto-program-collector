"""C-DEV-01/C1 opt-in official NO/SE calendar HTTP source acquisition.

Fills the original-byte transport step before independent_day_window.
Invoked only from a private terminal, never scheduled or C1 certified.
No Betting code, production collector or old source archive is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from .independent_day_window import (
    SCHEMA as BUNDLE_SCHEMA,
    _trusted_official_url,
    read_official_bundle,
)
from .private_source_archive import _private_root
from .source_integrity import write_original_bytes_once

SCHEMA = "collector_cdev01_official_http_capture_v1"
USER_AGENT = "Collector-C1-Source-Evidence/1.0"
DEFAULT_OFFICIAL_URLS = {
    "NO": "https://old.travsport.no/Sport/Terminliste/",
    "SE": "https://www.travsport.se/",
}
MAX_HTML = 8_000_000
MAX_ROBOTS = 120_000
DAY = re.compile(r"20\d{2}-\d{2}-\d{2}\Z")


class OfficialCaptureBlocked(ValueError):
    """No source success receipt permitted for this acquisition."""


@dataclass(frozen=True)
class HTTPSReply:
    status: int
    url: str
    content_type: str
    body: bytes
    http_date: str | None = None


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _get_https(url: str, *, max_bytes: int) -> HTTPSReply:
    """OS-verified HTTPS, no redirects, bounded bytes or retries."""
    req = urllib.request.Request(
        url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,text/plain,application/xhtml+xml",
            "Accept-Encoding": "identity",
        }, method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirects)
    try:
        with opener.open(req, timeout=16) as response:
            body = response.read(max_bytes + 1)
            return HTTPSReply(
                status=response.status, url=response.geturl(),
                content_type=response.headers.get("Content-Type", ""),
                body=body, http_date=response.headers.get("Date"),
            )
    except urllib.error.HTTPError as exc:
        raise OfficialCaptureBlocked("HTTP_OR_REDIRECT_BLOCKED:" + str(exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OfficialCaptureBlocked("HTTPS_ORIGIN_TRANSPORT_UNAVAILABLE") from exc


def _datetime_utc(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise OfficialCaptureBlocked("CAPTURE_CLOCK_NOT_AWARE")
    return value.astimezone(UTC).isoformat()


def _read_reply(
    reply: HTTPSReply, url: str, *, maximum: int, robots: bool
) -> bytes:
    if (not isinstance(reply, HTTPSReply) or reply.url != url
            or reply.status != 200
            or not isinstance(reply.body, bytes)
            or not reply.body or len(reply.body) > maximum):
        raise OfficialCaptureBlocked(
            "ROBOTS_HTTP_IDENTITY_OR_SIZE_INVALID"
            if robots else "OFFICIAL_HTTP_IDENTITY_OR_SIZE_INVALID"
        )
    content_type = reply.content_type.lower().split(";", 1)[0].strip()
    allowed = {"text/plain"} if robots else {
        "text/plain", "text/html", "application/xhtml+xml",
    }
    if content_type not in allowed:
        raise OfficialCaptureBlocked("UNEXPECTED_SOURCE_CONTENT_TYPE")
    try:
        reply.body.decode("utf-8-sig")
    except UnicodeError as exc:
        raise OfficialCaptureBlocked("OFFICIAL_SOURCE_NOT_UTF8") from exc
    return reply.body


def _robots_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))


def _robots_permits(raw: bytes, url: str) -> bool:
    try:
        text = raw.decode("utf-8-sig")
        lines = text.splitlines()
        if not any(line.lstrip().lower().startswith("user-agent:") for line in lines):
            return False
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(lines)
        return parser.can_fetch(USER_AGENT, url)
    except (UnicodeError, ValueError):
        return False


def capture_official_calendar(
    *,
    day: str,
    private_root: Path,
    sources: dict[str, str] | None = None,
    transport: Callable[..., HTTPSReply] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict:
    """Fetch both original public sources and create exclusive source bundle.

    Injected transports are explicitly simulated and never accepted as
    authenticated live origins. Real HTTPS also is not full-day coverage.
    """
    if not isinstance(day, str) or not DAY.fullmatch(day):
        raise OfficialCaptureBlocked("CALENDAR_DAY_NOT_ISO")
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except ValueError as exc:
        raise OfficialCaptureBlocked("CALENDAR_DAY_NOT_ISO") from exc
    root = _private_root(private_root)
    selected = dict(DEFAULT_OFFICIAL_URLS if sources is None else sources)
    if set(selected) != {"NO", "SE"}:
        raise OfficialCaptureBlocked("REQUIRE_BOTH_OFFICIAL_COUNTRIES")
    for country, url in selected.items():
        if not _trusted_official_url(url, country):
            raise OfficialCaptureBlocked("OFFICIAL_CALENDAR_HOST_REJECTED")
    fetch = _get_https if transport is None else transport
    now = (lambda: datetime.now(UTC)) if clock is None else clock
    real_transport = transport is None
    receipts = []
    raw_source: dict[str, bytes] = {}
    robots_source: dict[str, bytes] = {}

    # No incomplete positive bundle when either country source is blocked.
    for country in ("NO", "SE"):
        url = selected[country]
        robot_url = _robots_url(url)
        if url == robot_url:
            raise OfficialCaptureBlocked("ROBOTS_URL_EQUALS_CALENDAR")
        robots_reply = fetch(robot_url, max_bytes=MAX_ROBOTS)
        robot_bytes = _read_reply(
            robots_reply, robot_url, maximum=MAX_ROBOTS, robots=True)
        if not _robots_permits(robot_bytes, url):
            raise OfficialCaptureBlocked("ROBOTS_NOT_PERMITTED:" + country)
        page_reply = fetch(url, max_bytes=MAX_HTML)
        body = _read_reply(
            page_reply, url, maximum=MAX_HTML, robots=False)
        observed = _datetime_utc(now())
        raw_source[country], robots_source[country] = body, robot_bytes
        receipts.append({
            "country": country, "source_url": url, "http_status": 200,
            "observed_at_utc": observed, "source_publication_time_attested": False,
            "raw_sha256": hashlib.sha256(body).hexdigest(),
            "raw_size": len(body), "raw_path": None,
            "robots_sha256": hashlib.sha256(robot_bytes).hexdigest(),
            "robots_url": robot_url, "robots_path": None,
            "http_date_header_unverified": page_reply.http_date,
            "meetings": [],
            "calendar_events_independently_adjudicated": False,
            "network_https_response_observed": real_transport,
            "independent_transport_origin_attested": False,
        })
    timestamp = now().astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    identity = "official_" + day + "_" + timestamp
    for receipt in receipts:
        country = receipt["country"].lower()
        source_name = identity + "." + country + ".source.html"
        robots_name = identity + "." + country + ".robots.txt"
        write_original_bytes_once(
            robots_source[receipt["country"]], root / robots_name,
            label="OFFICIAL_ROBOTS_TEXT")
        write_original_bytes_once(
            raw_source[receipt["country"]], root / source_name,
            label="OFFICIAL_CALENDAR_HTML")
        receipt["raw_path"], receipt["robots_path"] = source_name, robots_name

    bundle = {
        "schema": BUNDLE_SCHEMA,
        "date_oslo": day,
        "sources": receipts,
        "capture_contract": SCHEMA,
        "capture_status": "ORIGINAL_HTTPS_SOURCE_COPIES_REVIEW_REQUIRED",
        "capture_method": ("OS_HTTPS_GET_NO_REDIRECTS_ROBOTS_CHECK"
                           if real_transport else "INJECTED_OFFLINE_TRANSPORT_TEST"),
        "captured_original_source_bodies": 2,
        "original_bytes_sha256_readback_verified": True,
        "source_meeting_extract_reviewed": False,
        "independent_complete_day_denominator_verified": False,
        "independent_race_denominator_verified": False,
        "source_first_publication_time_attested": False,
        "c6_pit_certified": False,
        "bet_authorized": False,
        "hq_accepted": False,
    }
    target = root / (identity + ".json")
    write_original_bytes_once(
        (json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False)
         + "\n").encode("utf-8"), target, label="WRAPPER_JSON")
    source_check = read_official_bundle(target, day=day)
    if source_check["errors"]:
        raise OfficialCaptureBlocked(
            "CAPTURED_SOURCE_BUNDLE_READBACK_INVALID:" +
            ",".join(source_check["errors"]))
    return {
        "bundle_path": str(target),
        "source_sha256": {r["country"]: r["raw_sha256"] for r in receipts},
        "source_bytes": {r["country"]: r["raw_size"] for r in receipts},
        "status": bundle["capture_status"],
        "source_meetings_independently_verified": False,
        "independent_calendar_day_coverage_verified": False,
        "c6_pit_certified": False,
        "bet_authorized": False,
        "hq_accepted": False,
    }


def attach_reviewed_calendar_claims(
    *, bundle_path: Path, claims: dict[str, list[dict]], output_path: Path
) -> dict:
    """Attach human source excerpts without marking calendar coverage complete.

    The incumbent C1 reader validates the original bytes, date and excerpt.
    """
    if not isinstance(claims, dict) or set(claims) != {"NO", "SE"}:
        raise OfficialCaptureBlocked("CLAIMS_REQUIRE_NO_SE_SOURCE_PAIRS")
    if (bundle_path.resolve() == output_path.resolve()
            or output_path.parent.resolve() != bundle_path.parent.resolve()
            or output_path.exists() or output_path.is_symlink()):
        raise OfficialCaptureBlocked("ANNOTATED_OUTPUT_MUST_BE_NEW_SAME_PRIVATE_ROOT")
    root = _private_root(bundle_path.parent)
    if bundle_path.is_symlink() or not bundle_path.is_file():
        raise OfficialCaptureBlocked("ORIGINAL_BUNDLE_MISSING_OR_SYMLINK")
    original = json.loads(bundle_path.read_text(encoding="utf-8"))
    if (not isinstance(original, dict)
            or original.get("schema") != BUNDLE_SCHEMA
            or original.get("source_meeting_extract_reviewed") is not False
            or original.get("source_first_publication_time_attested") is not False
            or not isinstance(original.get("sources"), list)
            or len(original["sources"]) != 2):
        raise OfficialCaptureBlocked("UNREVIEWED_SOURCE_BUNDLE_INVALID")
    day = original.get("date_oslo")
    prior = read_official_bundle(bundle_path, day=day)
    if prior["errors"] or prior["source_receipts_verified"] != 2:
        raise OfficialCaptureBlocked("ORIGINAL_SOURCE_BUNDLE_UNVERIFIED")
    for country in ("NO", "SE"):
        if not isinstance(claims[country], list):
            raise OfficialCaptureBlocked("INVALID_COUNTRY_CLAIM_LIST")
    candidate = json.loads(json.dumps(original))
    for receipt in candidate["sources"]:
        if receipt["country"] not in claims:
            raise OfficialCaptureBlocked("SOURCE_COUNTRY_NOT_IN_CLAIMS")
        receipt["meetings"] = claims[receipt["country"]]
    candidate["capture_status"] = "REVIEWED_EXCERPT_CANDIDATES_NOT_COMPLETE_DAY"
    candidate["source_meeting_extract_reviewed"] = True
    candidate["independent_complete_day_denominator_verified"] = False
    candidate["independent_race_denominator_verified"] = False
    encoded = (json.dumps(candidate, ensure_ascii=False, sort_keys=True,
                          indent=2) + "\n").encode("utf-8")
    # A unique 0600 private temporary file lets the incumbent reader
    # validate source excerpts BEFORE exclusive final publication. Never
    # unlink a pre-existing path or a second reviewer's temp file.
    with tempfile.NamedTemporaryFile(
        mode="wb", dir=root, prefix=".official_review_",
        suffix=".json", delete=True,
    ) as provisional:
        provisional.write(encoded)
        provisional.flush()
        os.fsync(provisional.fileno())
        reviewed = read_official_bundle(Path(provisional.name), day=day)
        if reviewed["errors"] or reviewed["source_receipts_verified"] != 2:
            raise OfficialCaptureBlocked("REVIEWED_CANDIDATE_SOURCE_EXCERPT_INVALID")
    write_original_bytes_once(encoded, output_path, label="WRAPPER_JSON")
    return {
        "bundle_path": str(output_path),
        "status": candidate["capture_status"],
        "source_grounded_venue_candidates": len(reviewed["events"]),
        "independent_complete_day_denominator_verified": False,
        "independent_race_denominator_verified": False,
        "c6_pit_certified": False,
        "bet_authorized": False,
        "hq_accepted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    cap = sub.add_parser("capture", help="Opt-in live official HTTPS source fetch")
    cap.add_argument("--day", required=True)
    cap.add_argument("--private-root", type=Path, required=True)
    cap.add_argument("--no-url", default=DEFAULT_OFFICIAL_URLS["NO"])
    cap.add_argument("--se-url", default=DEFAULT_OFFICIAL_URLS["SE"])
    annotate = sub.add_parser("annotate", help="Attach reviewed excerpts offline")
    annotate.add_argument("--bundle", type=Path, required=True)
    annotate.add_argument("--claims", type=Path, required=True)
    annotate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "capture":
            result = capture_official_calendar(
                day=args.day, private_root=args.private_root,
                sources={"NO": args.no_url, "SE": args.se_url})
        else:
            result = attach_reviewed_calendar_claims(
                bundle_path=args.bundle,
                claims=json.loads(args.claims.read_text(encoding="utf-8")),
                output_path=args.output,
            )
    except (OfficialCaptureBlocked, ValueError, OSError) as exc:
        parser.error(type(exc).__name__ + ":" + str(exc)[:150])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

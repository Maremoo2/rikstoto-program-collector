"""Bounded public WIN/startlist response-body provenance (NOT source admission).

Hash the exact byte sequence returned by Playwright's response.body().
Playwright may decode HTTP content-encoding, so this is NOT a wire-level
packet hash. Do not emit or upload raw bodies from an Actions diagnostic.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from .pipeline import DOMAIN

SCHEMA = "phase_b_public_response_body_evidence_v1"
MAX_JSON_BYTES = 2_000_000
STARTLIST_PATH = re.compile(r"/api/racedays/[A-Z0-9_\-]{3,90}/starts\Z")
WIN_PATH = "/api/betdistribution/winodds"
SAFE_HEADER_KEYS = ("content-type", "date", "last-modified", "etag", "content-encoding")


class SourceBodyRejected(ValueError):
    """A source body could not be attributed to a permitted public endpoint."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    unique: dict[str, Any] = {}
    for key, value in pairs:
        if key in unique:
            raise SourceBodyRejected("DUPLICATE_JSON_KEYS")
        unique[key] = value
    return unique


def _forbid_non_json_number(value: str) -> Any:
    raise SourceBodyRejected("NON_STANDARD_JSON_NUMBER")


def decode_public_json_body(
    *, body: bytes, url: str, http_status: int, headers: dict[str, str],
    captured_utc: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return parsed public payload and strictly source-bound *unarchived* hash.

    Fail closed on ambiguous JSON, untrusted endpoint or missing source time.
    No source data is serialized to the provenance metadata.
    """
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_JSON_BYTES:
        raise SourceBodyRejected("EMPTY_OR_OVERSIZED_RESPONSE_BODY")
    parsed_url = urlsplit(url)
    path = parsed_url.path
    if (parsed_url.scheme != "https" or parsed_url.hostname != DOMAIN
            or parsed_url.port not in (None, 443)
            or parsed_url.username or parsed_url.password
            or parsed_url.fragment):
        raise SourceBodyRejected("UNTRUSTED_RESPONSE_ORIGIN")
    if path == WIN_PATH:
        source_kind = "WIN_ODDS"
    elif STARTLIST_PATH.fullmatch(path):
        source_kind = "OFFICIAL_STARTLIST"
    else:
        raise SourceBodyRejected("UNRECOGNIZED_SOURCE_ENDPOINT")
    if type(http_status) is not int or http_status != 200:
        raise SourceBodyRejected("SOURCE_HTTP_NOT_200")
    if not isinstance(headers, dict):
        raise SourceBodyRejected("SOURCE_HEADERS_MISSING")
    content_type = headers.get("content-type", "")
    if not isinstance(content_type, str) or "json" not in content_type.casefold():
        raise SourceBodyRejected("NON_JSON_RESPONSE_CONTENT_TYPE")
    try:
        captured = datetime.fromisoformat(captured_utc)
        if captured.tzinfo is None or captured.utcoffset() is None:
            raise ValueError("clock without offset")
        if captured.utcoffset().total_seconds() != 0:
            raise ValueError("capture time not UTC")
    except (ValueError, TypeError, AttributeError) as exc:
        raise SourceBodyRejected("SOURCE_CAPTURE_TIME_NOT_UTC") from exc

    try:
        decoded = body.decode("utf-8", errors="strict")
        payload = json.loads(
            decoded,
            object_pairs_hook=_unique_pairs,
            parse_constant=_forbid_non_json_number,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceBodyRejected("INVALID_UTF8_OR_JSON_RESPONSE") from exc
    if not isinstance(payload, dict):
        raise SourceBodyRejected("NON_OBJECT_SOURCE_PAYLOAD")

    safe_headers = {}
    for key in SAFE_HEADER_KEYS:
        value = headers.get(key)
        if isinstance(value, str):
            safe_headers[key] = value[:200].replace("\r", "").replace("\n", "")
    normalized_bytes = json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")

    evidence = {
        "schema": SCHEMA,
        "source_kind": source_kind,
        "source_path_no_query": path,
        "source_url_with_query_retained": False,
        "http_status": http_status,
        "safe_response_headers": safe_headers,
        "captured_utc": captured.isoformat(),
        "body_byte_length": len(body),
        "playwright_body_sha256": hashlib.sha256(body).hexdigest(),
        "normalized_json_sha256_distinct": hashlib.sha256(normalized_bytes).hexdigest(),
        "hash_scope": "PLAYWRIGHT_RESPONSE_BODY_BYTES_AFTER_BROWSER_TRANSPORT_DECODING",
        "body_bytes_archived_and_readback_verified": False,
        "raw_http_wire_bytes_verified": False,
        "source_authority_independently_verified": False,
        "bet_authorized": False,
    }
    return payload, evidence


async def inspect_public_response_body(
    response: Any, *, observed_utc: datetime | None = None,
    private_archive: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one Playwright response body; set capture time AFTER receipt.

    The injectable clock is only for isolated tests, never user-supplied by
    the live probe. No network requests are initiated here.
    """
    body = await response.body()
    now = datetime.now(UTC) if observed_utc is None else observed_utc
    payload, evidence = decode_public_json_body(
        body=body, url=response.url, http_status=response.status,
        headers=response.headers, captured_utc=now.isoformat(),
    )
    if private_archive is not None:
        # Only previously validated, explicitly public bytes reach the
        # private, owner-only archive. No raw bytes in returned diagnostics.
        verified = private_archive.write_body(body, evidence)
        evidence["body_bytes_archived_and_readback_verified"] = True
        evidence["private_archive_record_id"] = verified["record_id"]
        evidence["private_archive_manifest_sha256"] = verified["manifest_sha256"]
        evidence["immutable_or_signed_manifest_verified"] = False
        evidence["source_authority_independently_verified"] = False
    return payload, evidence

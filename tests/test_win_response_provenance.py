"""WIN/startlist source byte provenance: all fixtures are synthetic, no HTTP.

Uses EXACT bytes from mocked Playwright response.body(), never a re-encoded
parsed JSON string. This does not establish live source provenance.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collector.win_response_provenance import (
    SCHEMA,
    SourceBodyRejected,
    decode_public_json_body,
    inspect_public_response_body,
)

WIN = "https://www.rikstoto.no/api/betdistribution/winodds"
STARTS = "https://www.rikstoto.no/api/racedays/S2_NR_2026-10-20/starts"
NOW = "2026-10-20T12:00:00+00:00"
WIN_BYTES = b'{"success":true, "result":{"2":[{"startNumber":4,"odds":3.5}]}}'
HEADERS = {
    "content-type": "application/json; charset=utf-8",
    "date": "Tue, 20 Oct 2026 12:00:00 GMT",
    "set-cookie": "secret=never-recorded",
    "authorization": "Bearer never-recorded",
    "content-encoding": "gzip",
}


def _read(body=WIN_BYTES, *, url=WIN, headers=None, when=NOW, status=200):
    return decode_public_json_body(
        body=body, url=url, headers=HEADERS if headers is None else headers,
        http_status=status, captured_utc=when,
    )


def test_raw_playwright_bytes_hash_is_distinct_from_normalized_json_hash():
    data, proof = _read()
    assert data["success"] is True
    assert proof["schema"] == SCHEMA
    assert proof["source_kind"] == "WIN_ODDS"
    assert proof["source_path_no_query"] == "/api/betdistribution/winodds"
    assert proof["captured_utc"] == NOW
    assert proof["body_byte_length"] == len(WIN_BYTES)
    assert proof["playwright_body_sha256"] == hashlib.sha256(WIN_BYTES).hexdigest()
    assert proof["normalized_json_sha256_distinct"] != proof["playwright_body_sha256"]
    assert proof["hash_scope"] == (
        "PLAYWRIGHT_RESPONSE_BODY_BYTES_AFTER_BROWSER_TRANSPORT_DECODING"
    )
    assert proof["raw_http_wire_bytes_verified"] is False
    assert proof["body_bytes_archived_and_readback_verified"] is False
    assert proof["source_authority_independently_verified"] is False
    assert proof["bet_authorized"] is False
    assert "set-cookie" not in proof["safe_response_headers"]
    assert "authorization" not in proof["safe_response_headers"]
    assert "never-recorded" not in json.dumps(proof)


def test_differently_formatted_equal_json_has_distinct_body_hash():
    a = b'{"success":true,"result":{}}'
    b = b'{ "result":{}, "success":true }'
    _, first = _read(a)
    _, second = _read(b)
    assert first["playwright_body_sha256"] != second["playwright_body_sha256"]
    assert first["normalized_json_sha256_distinct"] == (
        second["normalized_json_sha256_distinct"]
    )


def test_official_startlist_has_separate_source_hash():
    original = b'{"success":true,"result":{"2":[{"startNumber":4,"isScratched":false}]}}'
    _, evidence = _read(original, url=STARTS)
    assert evidence["source_kind"] == "OFFICIAL_STARTLIST"
    assert evidence["playwright_body_sha256"] == hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize(("body", "expected"), [
    (b"", "EMPTY_OR_OVERSIZED_RESPONSE_BODY"),
    (b" " * 2_000_001, "EMPTY_OR_OVERSIZED_RESPONSE_BODY"),
    (b'{"success":true,"success":false}', "DUPLICATE_JSON_KEYS"),
    (b'{"x":{"a":1,"a":2}}', "DUPLICATE_JSON_KEYS"),
    (b'{"odds":NaN}', "NON_STANDARD_JSON_NUMBER"),
    (b'{"odds":Infinity}', "NON_STANDARD_JSON_NUMBER"),
    (b'{"invalid"', "INVALID_UTF8_OR_JSON_RESPONSE"),
    (b"\xff\xfe", "INVALID_UTF8_OR_JSON_RESPONSE"),
    (b"[]", "NON_OBJECT_SOURCE_PAYLOAD"),
])
def test_invalid_or_non_unambiguous_source_bytes_fail_closed(body, expected):
    with pytest.raises(SourceBodyRejected, match=expected):
        _read(body)


@pytest.mark.parametrize(("url", "expected"), [
    ("http://www.rikstoto.no/api/betdistribution/winodds", "UNTRUSTED_RESPONSE_ORIGIN"),
    ("https://attacker.example/api/betdistribution/winodds", "UNTRUSTED_RESPONSE_ORIGIN"),
    ("https://user:pass@www.rikstoto.no/api/betdistribution/winodds", "UNTRUSTED_RESPONSE_ORIGIN"),
    ("https://www.rikstoto.no:444/api/betdistribution/winodds", "UNTRUSTED_RESPONSE_ORIGIN"),
    ("https://www.rikstoto.no/api/customer/session", "UNRECOGNIZED_SOURCE_ENDPOINT"),
    ("https://www.rikstoto.no/api/racedays/../starts", "UNRECOGNIZED_SOURCE_ENDPOINT"),
])
def test_only_public_permitted_first_party_endpoints_accepted(url, expected):
    with pytest.raises(SourceBodyRejected, match=expected):
        _read(url=url)


def test_query_parameters_never_leak_into_evidence():
    _, report = _read(url=WIN + "?session=private&race=2")
    assert "session" not in json.dumps(report)
    assert report["source_url_with_query_retained"] is False


@pytest.mark.parametrize(("override", "reason"), [
    ({"status": 403}, "SOURCE_HTTP_NOT_200"),
    ({"status": True}, "SOURCE_HTTP_NOT_200"),
    ({"headers": {"content-type": "text/html"}}, "NON_JSON_RESPONSE_CONTENT_TYPE"),
    ({"when": "2026-10-20T12:00:00"}, "SOURCE_CAPTURE_TIME_NOT_UTC"),
    ({"when": "2026-10-20T13:00:00+01:00"}, "SOURCE_CAPTURE_TIME_NOT_UTC"),
])
def test_status_content_type_and_clock_are_strict(override, reason):
    with pytest.raises(SourceBodyRejected, match=reason):
        _read(**override)


class _FakeBrowserResponse:
    def __init__(self):
        self.url = WIN
        self.status = 200
        self.headers = HEADERS
        self.body_calls = 0

    async def body(self) -> bytes:
        self.body_calls += 1
        return WIN_BYTES


def test_async_browser_body_read_exactly_once_and_capture_after_read():
    response = _FakeBrowserResponse()
    payload, evidence = asyncio.run(
        inspect_public_response_body(
            response, observed_utc=datetime.fromisoformat(NOW),
        )
    )
    assert response.body_calls == 1
    assert payload["success"] is True
    assert evidence["captured_utc"] == NOW


def test_source_probe_uses_captured_win_body_time_not_navigation_start():
    # Source-level contract test; full browser integration depends on permitted
    # live public page or archived Playwright capture.
    source = (Path(__file__).parents[1] / "collector/win_source_probe.py").read_text()
    assert 'captured_utc=raw_winodds_evidence[-1]["captured_utc"]' in source
    assert 'captured_utc=report["captured_utc"]' not in source
    assert 'report["source_response_provenance"]' in source
    assert 'report["screen_captured_utc"]' in source

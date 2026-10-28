"""Offline browser-level source-provenance integration tests, no network.

The page, public WIN/startlist responses and clocks are synthetic.
Actual browser callback -> body digest -> WIN adapter -> screen parity is
exercised, rather than only checking source code strings.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from collector import win_response_provenance, win_source_probe

RACE_URL = "https://www.rikstoto.no/Spill/S2_NR_2026-10-20/V?race=2&p=2:0"
WIN_URL = "https://www.rikstoto.no/api/betdistribution/winodds"
STARTS_URL = "https://www.rikstoto.no/api/racedays/S2_NR_2026-10-20/starts"
PRESTART = datetime(2026, 10, 20, 11, 55, tzinfo=UTC)
BODY_CAPTURED = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
SCREEN_CAPTURED = datetime(2026, 10, 20, 12, 0, 10, tzinfo=UTC)

WIN_BODY = json.dumps({
    "success": True, "result": {"2": [
        {"startNumber": 4, "odds": 3.5, "lastUpdated": "2026-10-20T11:59:40Z"},
        {"startNumber": 7, "odds": 5.2, "lastUpdated": "2026-10-20T11:59:35Z"},
    ]},
}, separators=(",", ":")).encode("utf-8")

STARTS = [
    {"startNumber": 4, "horseName": "Alpha", "isScratched": False},
    {"startNumber": 7, "horseName": "Bravo", "isScratched": False},
]
SCREEN = (
    "Nr 4 Hest Alpha Kusk Jane Vinner 3,5 Plass 1,4\n"
    "Nr 7 Hest Bravo Kusk John Vinner 5,2 Plass 2,2\n"
)


class _PageResponse:
    def __init__(self, url: str, payload: bytes):
        self.url = url
        self.status = 200
        self.headers = {
            "content-type": "application/json; charset=utf-8",
            "set-cookie": "session-value-shall-never-be-exported",
        }
        self.request = SimpleNamespace(resource_type="xhr")
        self.payload = payload
        self.body_calls = 0

    async def body(self):
        self.body_calls += 1
        return self.payload


class _Page:
    def __init__(self, responses):
        self.responses = responses
        self.handler = None

    def on(self, name, handler):
        assert name == "response"
        self.handler = handler

    async def goto(self, url, **kwargs):
        assert url == RACE_URL
        assert self.handler is not None
        for response in self.responses:
            self.handler(response)
        return SimpleNamespace(status=200)

    async def wait_for_timeout(self, ms):
        assert ms == 5000

    def locator(self, css):
        assert css == "body"
        return SimpleNamespace(inner_text=AsyncMock(return_value=SCREEN))


class _ProbeClock:
    calls = 0

    @classmethod
    def now(cls, tz):
        cls.calls += 1
        return PRESTART if cls.calls == 1 else SCREEN_CAPTURED


class _ResponseClock:
    @staticmethod
    def now(tz):
        return BODY_CAPTURED

    @staticmethod
    def fromisoformat(value):
        return datetime.fromisoformat(value)


def _run_probe(start_rows=None, win_body=WIN_BODY):
    _ProbeClock.calls = 0
    start_rows = STARTS if start_rows is None else start_rows
    actual_starts = json.dumps(
        {"success": True, "result": {"2": start_rows}},
        separators=(",", ":"),
    ).encode("utf-8")
    candidates = [
        _PageResponse(WIN_URL, win_body),
        _PageResponse(STARTS_URL, actual_starts),
    ]
    page = _Page(candidates)
    request = SimpleNamespace(get=AsyncMock(side_effect=AssertionError(
        "Startlist response was already provided; do not make another request"
    )))
    context = SimpleNamespace(
        new_page=AsyncMock(return_value=page),
        request=request,
    )
    browser = SimpleNamespace(
        new_context=AsyncMock(return_value=context),
        close=AsyncMock(),
    )
    playwright = SimpleNamespace(chromium=SimpleNamespace(
        launch=AsyncMock(return_value=browser),
    ))
    # Python looks up async context-manager special methods on the TYPE,
    # not attributes of SimpleNamespace instances.
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=None)
    robots = SimpleNamespace(permits=lambda url: True)

    # Source-level browser integration: no actual HTTP or real race captured.
    with (
        patch("playwright.async_api.async_playwright", return_value=manager),
        patch("collector.win_source_probe.check_robots",
              new_callable=AsyncMock, return_value=robots),
        patch.object(win_source_probe, "datetime", _ProbeClock),
        patch.object(win_response_provenance, "datetime", _ResponseClock),
    ):
        result = asyncio.run(win_source_probe.probe(RACE_URL))
    return result, candidates, actual_starts


def test_win_probe_receipt_timestamp_tracks_exact_win_body_not_browser_start():
    result, candidates, starts_bytes = _run_probe()
    assert result["status"] == "DIAGNOSTIC_CAPTURED"
    assert result["probe_started_utc"] == PRESTART.isoformat()
    assert result["captured_utc"] == BODY_CAPTURED.isoformat()
    assert result["screen_captured_utc"] == SCREEN_CAPTURED.isoformat()
    assert result["source_capture_counts"] == {
        "winodds": 1, "official_starts": 1,
    }
    assert candidates[0].body_calls == 1
    assert candidates[1].body_calls == 1
    assert result["win_startlist_audit"]["status"] == (
        "STRUCTURE_VALID_UNVERIFIED"
    )
    assert result["win_startlist_audit"]["errors"] == []
    assert result["screen_parity"]["status"] == "MATCH"
    assert result["screen_parity"]["screen_api_capture_separation_seconds"] == 10.0

    source = result["source_response_provenance"]
    assert source["winodds"][0]["playwright_body_sha256"] == (
        hashlib.sha256(WIN_BODY).hexdigest()
    )
    assert source["official_starts"][0]["playwright_body_sha256"] == (
        hashlib.sha256(starts_bytes).hexdigest()
    )
    assert result["win_startlist_audit"]["source_win_body_sha256"] == (
        source["winodds"][0]["playwright_body_sha256"]
    )
    assert result["win_startlist_audit"][
        "source_official_startlist_body_sha256"
    ] == source["official_starts"][0]["playwright_body_sha256"]
    assert result["source_response_provenance_status"] == (
        "HASHED_BODIES_NOT_ARCHIVED_OR_INDEPENDENTLY_VERIFIED"
    )
    assert source["original_bodies_archived_and_readback_verified"] is False
    assert result["win_market_verified"] is False
    assert result["bet_authorized"] is False
    assert "session-value-shall-never-be-exported" not in json.dumps(result)


def test_duplicate_official_start_number_fails_closed_not_smaller_fake_field():
    duplicated = [
        {"startNumber": 4, "horseName": "Alpha", "isScratched": False},
        {"startNumber": 4, "horseName": "Bravo", "isScratched": False},
    ]
    result, _, _ = _run_probe(start_rows=duplicated)
    assert result["win_startlist_audit"] == {
        "status": "BLOCKED", "reason": "STARTLIST_FLAGS_OR_IDENTITIES_UNVERIFIED"
    }
    assert result.get("screen_parity") is None
    assert result["bet_authorized"] is False


def test_failed_exact_win_body_does_not_qualify_as_hashed_evidence():
    result, responses, _ = _run_probe(
        win_body=b'{"success":true,"result":{},"success":false}',
    )
    assert responses[0].body_calls == 1
    assert result["source_capture_counts"]["winodds"] == 0
    assert result["source_response_provenance_status"] == (
        "INCOMPLETE_OR_MISSING_SOURCE_BODY_HASHES"
    )
    assert result["win_startlist_audit"]["status"] == "BLOCKED"
    assert result["win_startlist_audit"]["reason"] == (
        "WIN_AND_OFFICIAL_STARTLIST_NOT_BOTH_CAPTURED"
    )
    assert any(
        "DUPLICATE_JSON_KEYS" in entry.get("reason", "")
        for entry in result["candidate_response_schemas"]
    )
    assert result["bet_authorized"] is False

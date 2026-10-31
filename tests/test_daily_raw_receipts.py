"""Offline request-level source archive tests without network or browser."""
import asyncio
import hashlib
import json
from pathlib import Path

from collector import daily


class Reply:
    status = 200
    headers = {"content-type": "application/json", "date": "Sat, 31 Oct 2026 06:00:00 GMT"}

    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    async def body(self):
        return self._body


class Request:
    def __init__(self, reply):
        self.reply = reply

    async def get(self, url, **kwargs):
        return self.reply


class Context:
    def __init__(self, reply):
        self.request = Request(reply)


class Robots:
    def permits(self, url):
        return True


def _run(body, tmp_path, monkeypatch, *, reply_status=200):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(daily.asyncio, "sleep", no_sleep)
    log = []
    path = tmp_path / "starts.json"
    result = asyncio.run(daily.request(
        Context(Reply(body, reply_status)), Robots(),
        "https://www.rikstoto.no/api/racedays/TEST_NR_2026-10-31/starts",
        path, log))
    return result, path, log


def test_real_request_layer_preserves_source_bytes_and_headers(tmp_path, monkeypatch):
    original = b'{ "result" : {"1": []}, "success": true }\n'
    result, formatted, log = _run(original, tmp_path, monkeypatch)
    assert result["result"] == {"1": []}
    assert formatted.exists()
    assert (tmp_path / "starts.raw.json").read_bytes() == original
    assert log[0]["status"] == "JSON_OK"
    assert log[0]["sha256"] == hashlib.sha256(original).hexdigest()
    assert log[0]["raw_readback_verified"] is True
    assert log[0]["response_headers"]["date"] == "Sat, 31 Oct 2026 06:00:00 GMT"
    assert log[0]["source_publication_time_attested"] is False
    assert json.loads(formatted.read_text())["response"] == result


def test_archive_write_failure_is_not_reported_as_network_or_success(tmp_path, monkeypatch):
    def blocked(*args, **kwargs):
        raise OSError("readback blocked")

    monkeypatch.setattr(daily, "archive_json_bytes", blocked)
    result, path, log = _run(b'{"result":[]}', tmp_path, monkeypatch)
    assert result is None
    assert log[0]["status"] == "ARCHIVE_READBACK_FAILED"
    assert not any(item["status"] == "JSON_OK" for item in log)


def test_invalid_json_does_not_issue_source_success_receipt(tmp_path, monkeypatch):
    result, path, log = _run(b'not json', tmp_path, monkeypatch)
    assert result is None
    assert log[0]["status"] == "NOT_JSON"
    assert not (tmp_path / "starts.raw.json").exists()


def test_provider_404_stays_http_failure_no_raw_archive(tmp_path, monkeypatch):
    result, path, log = _run(b'{"result":[]}', tmp_path, monkeypatch,
                             reply_status=404)
    assert result is None
    assert log[0]["status"] == "HTTP_404"
    assert not path.exists()

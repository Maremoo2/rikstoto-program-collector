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
        self.last_url = url
        self.last_kwargs = kwargs
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


def test_pdf_request_layer_preserves_original_and_provenance(tmp_path, monkeypatch):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(daily.asyncio, "sleep", no_sleep)
    pdf = b"%PDF-1.4\nsource bytes preserved\n"
    log = []
    target = tmp_path / "full_program.pdf"
    result = asyncio.run(daily.request(
        Context(Reply(pdf)), Robots(),
        "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/BJ_NR_2026-10-31",
        target, log, binary=True))
    assert result == pdf
    assert target.read_bytes() == pdf
    assert log[0]["status"] == "PDF_OK"
    assert log[0]["sha256"] == hashlib.sha256(pdf).hexdigest()
    assert log[0]["raw_readback_verified"] is True
    assert log[0]["response_headers"]["date"] == "Sat, 31 Oct 2026 06:00:00 GMT"
    assert log[0]["source_publication_time_attested"] is False


def test_pdf_readback_corruption_cannot_be_pdf_ok(tmp_path, monkeypatch):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(daily.asyncio, "sleep", no_sleep)
    original = Path.read_bytes

    def altered(path):
        if path.name == "full_program.pdf":
            return b"BAD"
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", altered)
    log = []
    target = tmp_path / "full_program.pdf"
    result = asyncio.run(daily.request(
        Context(Reply(b"%PDF-1.4\n")) , Robots(),
        "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/BJ_NR_2026-10-31",
        target, log, binary=True))
    assert result is None
    assert log[0]["status"] == "ARCHIVE_READBACK_FAILED"
    assert log[0]["source_type"] == "PDF"
    assert not any(x["status"] == "PDF_OK" for x in log)



def test_request_layer_second_json_get_fails_as_source_collision(tmp_path, monkeypatch):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(daily.asyncio, "sleep", no_sleep)
    path = tmp_path / "starts.json"
    url = "https://www.rikstoto.no/api/racedays/TEST_NR_2026-10-31/starts"
    first = b'{"success":true,"result":{"1":[]}}'
    second = b'{"success":false,"result":{}}'
    records = []
    initial = asyncio.run(daily.request(
        Context(Reply(first)), Robots(), url, path, records
    ))
    before = (path.read_bytes(), (tmp_path / "starts.raw.json").read_bytes())
    changed = asyncio.run(daily.request(
        Context(Reply(second)), Robots(), url, path, records
    ))
    assert initial is not None
    assert changed is None
    assert (path.read_bytes(), (tmp_path / "starts.raw.json").read_bytes()) == before
    assert [x["status"] for x in records] == ["JSON_OK", "SOURCE_ARCHIVE_COLLISION"]
    assert records[1]["source_type"] == "JSON"
    assert not records[1].get("raw_readback_verified")


def test_request_layer_second_pdf_get_preserves_first_original(tmp_path, monkeypatch):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(daily.asyncio, "sleep", no_sleep)
    url = "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/BJ_NR_2026-10-31"
    path = tmp_path / "program.pdf"
    records = []
    original = b"%PDF-1.4\nORIGINAL_DOCUMENT\n"
    revised = b"%PDF-1.4\nREVISED_DOCUMENT\n"
    assert asyncio.run(daily.request(
        Context(Reply(original)), Robots(), url, path, records, binary=True
    )) == original
    assert asyncio.run(daily.request(
        Context(Reply(revised)), Robots(), url, path, records, binary=True
    )) is None
    assert path.read_bytes() == original
    assert [x["status"] for x in records] == ["PDF_OK", "SOURCE_ARCHIVE_COLLISION"]
    assert records[1]["source_type"] == "PDF"
    assert "sha256" not in records[1]


def test_corrupt_first_pdf_write_never_creates_valid_original_receipt(tmp_path, monkeypatch):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(daily.asyncio, "sleep", no_sleep)
    original_read = Path.read_bytes

    def tamper(path):
        if path.name == "program.pdf":
            return b"BAD_BYTES"
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", tamper)
    path = tmp_path / "program.pdf"
    records = []
    result = asyncio.run(daily.request(
        Context(Reply(b"%PDF-1.4\nTEST\n")), Robots(),
        "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/BJ_NR_2026-10-31",
        path, records, binary=True,
    ))
    assert result is None
    assert records[0]["status"] == "ARCHIVE_READBACK_FAILED"
    assert "PDF_READBACK_SHA_MISMATCH" in records[0]["error"]
    assert not path.exists()



def test_official_source_get_refuses_redirect_before_body_or_receipt(tmp_path, monkeypatch):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(daily.asyncio, "sleep", no_sleep)
    url = "https://www.rikstoto.no/api/racedays/TEST_NR_2026-10-31/starts"
    for binary, suffix, payload in (
        (False, "starts.json", b'{"success":true,"result":{}}'),
        (True, "program.pdf", b"%PDF-1.4\nFAKE_REDIRECT_BODY"),
    ):
        context = Context(Reply(payload, status=302))
        messages = []
        path = tmp_path / suffix
        result = asyncio.run(daily.request(
            context, Robots(), url, path, messages, binary=binary,
        ))
        assert result is None
        assert context.request.last_url == url
        assert context.request.last_kwargs["max_redirects"] == 0
        assert messages[0]["status"] == "HTTP_302"
        assert not path.exists()
        assert not (tmp_path / "starts.raw.json").exists()
        assert not any(x["status"] in ("JSON_OK", "PDF_OK") for x in messages)


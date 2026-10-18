"""No-network tests for single-meeting PDF candidate fallback."""
from pathlib import Path

import pytest

from collector.pdf_probe import candidate_url, retrieve_pdf


def test_known_meeting_generates_only_one_candidate():
    url = "https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0"
    assert candidate_url(url) == (
        "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/OR_NR_2026-10-18")


@pytest.mark.parametrize("url", [
    "https://attacker.example/Spill/OR_NR_2026-10-18/V?race=6",
    "http://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6",
    "https://www.rikstoto.no/",
    "https://www.rikstoto.no/Spill/UNKNOWN/V?race=6",
])
def test_unknown_or_offdomain_does_not_generate_pdf_url(url):
    assert candidate_url(url) is None


def test_retrieve_pdf_404_is_reported_without_writing_pdf(monkeypatch, tmp_path):
    import urllib.error

    def fake_open(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("collector.pdf_probe.urllib.request.urlopen", fake_open)
    result = retrieve_pdf(
        "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/OR_NR_2026-10-18",
        tmp_path)
    assert result["ok"] is False
    assert result["code"] == "PDF_HTTP_404"
    assert not list(tmp_path.glob("*.pdf"))


def test_non_pdf_response_rejected(monkeypatch, tmp_path):
    class FakeResponse:
        status = 200
        headers = {"Content-Type": "text/html"}
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, length): return b"<html>browser error</html>" if not hasattr(self, "read_once") else b""

    def fake_open(request, timeout):
        result = FakeResponse()
        def read_once(length):
            if hasattr(result, "_done"): return b""
            result._done = True
            return b"<html>browser error</html>"
        result.read = read_once
        return result

    monkeypatch.setattr("collector.pdf_probe.urllib.request.urlopen", fake_open)
    result = retrieve_pdf(
        "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/OR_NR_2026-10-18",
        tmp_path)
    assert result["code"] == "PDF_RESPONSE_NOT_PDF"
    assert not list(tmp_path.glob("*.pdf"))

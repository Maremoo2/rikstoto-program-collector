"""Regression tests for robots policy and the staged diagnostic process (no network)."""
import json
import socket

import pytest

from collector import diagnose


TARGET = "https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0"


@pytest.mark.parametrize("http_status", [404, 410])
def test_robots_missing_is_not_disallow(http_status):
    allowed, code, _ = diagnose.robots_decision(
        {"status": http_status, "body": b""}, TARGET)
    assert allowed is True
    assert code == f"ROBOTS_MISSING_{http_status}"


@pytest.mark.parametrize("http_status", [403, 429, 500, 503])
def test_robots_blocked_or_unreachable_fails_closed(http_status):
    allowed, _, _ = diagnose.robots_decision(
        {"status": http_status, "body": b""}, TARGET)
    assert allowed is False


def test_robots_explicit_disallow_is_respected():
    allowed, code, _ = diagnose.robots_decision(
        {"status": 200, "body": b"User-agent: *\nDisallow: /Spill/\n"}, TARGET)
    assert not allowed
    assert code == "ROBOTS_DISALLOWED"


def test_robots_explicit_allow_is_respected():
    allowed, code, _ = diagnose.robots_decision(
        {"status": 200, "body": b"User-agent: *\nDisallow:\n"}, TARGET)
    assert allowed
    assert code == "ROBOTS_ALLOWED"


def test_robots_network_error_fails_closed():
    allowed, code, _ = diagnose.robots_decision(
        {"status": None, "error": "DNS failure"}, TARGET)
    assert not allowed
    assert code == "ROBOTS_UNVERIFIED"


@pytest.mark.parametrize("unsafe_url", [
    "http://www.rikstoto.no/",
    "https://www.rikstoto.no.evil.example/Spill/",
    "https://attacker@www.rikstoto.no/",
    "https://www.rikstoto.no:8080/",
    "https://rikstoto.no/",
])
def test_only_known_public_https_host(unsafe_url):
    with pytest.raises(ValueError):
        diagnose.safe_url(unsafe_url)


def test_site_unsupported_safari_message_is_detected():
    text = "Nettleseren din støttes ikke lenger. Du bruker en eldre versjon av Safari"
    assert diagnose.page_issue(text) == "UNSUPPORTED_BROWSER_PAGE"


def test_login_not_assumed_from_menu_link():
    assert diagnose.page_issue("Se alle løp. Logg inn. Vinner og odds.") is None
    assert diagnose.page_issue("Du må logge inn for å se dette") == "LOGIN_REQUIRED"


def test_dns_classification():
    assert diagnose.classify_error(socket.gaierror(-2, "Name or service not known")) == "DNS_RESOLUTION_FAILED"


def test_http_404_robot_gate_proceeds_but_page_error_remains_visible(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(diagnose, "diagnostic_dns", lambda stages: True)
    monkeypatch.setattr(diagnose, "diagnostic_tls", lambda stages: True)

    def fake_fetch(url):
        called.append(url)
        return {"status": 404, "body": b"", "url": url, "headers": {}}

    monkeypatch.setattr(diagnose, "fetch_http", fake_fetch)
    result = diagnose.run(TARGET, "http", str(tmp_path / "report.json"))
    data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert result == 1
    assert data["robots_allows_probe"] is True
    assert len(called) == 2  # robots.txt AND race page were checked
    assert data["stages"][-1]["code"] == "HTTP_404"


def test_blocked_robots_never_requests_race_page(monkeypatch, tmp_path):
    urls = []
    monkeypatch.setattr(diagnose, "diagnostic_dns", lambda stages: True)
    monkeypatch.setattr(diagnose, "diagnostic_tls", lambda stages: True)

    def fake_fetch(url):
        urls.append(url)
        return {"status": 503, "body": b"", "url": url, "headers": {}}

    monkeypatch.setattr(diagnose, "fetch_http", fake_fetch)
    assert diagnose.run(TARGET, "both", str(tmp_path / "report.json")) == 1
    assert len(urls) == 1  # Only robots.txt; protected race page never requested


def test_safari_banner_with_real_program_is_not_misdiagnosed():
    text = ("Nettleseren din støttes ikke lenger. " 
            "Spill og program. Løp 6. Hest 1 Vinner og odds. " 
            "Hest 2 Startliste. Hest 3.")
    assert diagnose.page_issue(text) is None

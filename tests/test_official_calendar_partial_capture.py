"""Partial C1 transport regressions; synthetic HTTP, no privacy attestation."""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collector import official_calendar_capture as capture
from collector.independent_day_window import read_official_bundle


@pytest.fixture
def local_root(tmp_path, monkeypatch):
    # Exercise transport/receipt behavior on Windows too. Production privacy
    # validation is unchanged and separately tested; this fixture attests none.
    monkeypatch.setattr(capture, "_private_root", lambda root: root)
    return tmp_path


def run_capture(root, *, denied=(), broken=(), allow_partial=True):
    calls = []

    def transport(url, *, max_bytes):
        calls.append(url)
        country = "NO" if "travsport.no" in url else "SE"
        if country in broken:
            raise capture.OfficialCaptureBlocked("HTTPS_ORIGIN_TRANSPORT_UNAVAILABLE")
        robots = url.endswith("/robots.txt")
        body = ((b"User-agent: *\nDisallow: /\n" if country in denied else
                 b"User-agent: *\nAllow: /\n") if robots else b"Original calendar")
        return capture.HTTPSReply(200, url, "text/plain", body)

    result = capture.capture_official_calendar(
        day="2026-11-01", private_root=root, transport=transport,
        clock=lambda: datetime(2026, 11, 1, 20, tzinfo=UTC),
        allow_partial=allow_partial)
    return result, calls


@pytest.mark.parametrize("country", ["NO", "SE"])
def test_allowed_country_survives_other_country_robots_denial(local_root, country):
    result, calls = run_capture(local_root, denied={country})
    assert result["status"] == "BLOCKED_PARTIAL_OFFICIAL_SOURCE_CAPTURE"
    assert capture.DEFAULT_OFFICIAL_URLS[country] not in calls
    assert len(result["source_sha256"]) == 1
    bundle = Path(result["bundle_path"])
    payload = json.loads(bundle.read_text())
    assert payload["captured_original_source_bodies"] == 1
    blocked = payload["blocked_sources"][0]
    robots = (local_root / blocked["robots_path"]).read_bytes()
    assert hashlib.sha256(robots).hexdigest() == blocked["robots_sha256"]
    assert blocked["network_https_response_observed"] is False
    assert blocked["reason"] == "ROBOTS_NOT_PERMITTED:" + country
    checked = read_official_bundle(bundle, day="2026-11-01")
    assert checked["source_receipts_verified"] == 1
    assert checked["errors"] == ["MISSING_NO_OR_SE_OFFICIAL_SOURCE_COPY"]
    for key in ("independent_complete_day_denominator_verified", "c6_pit_certified",
                "bet_authorized", "hq_accepted"):
        assert payload[key] is False
    with pytest.raises(capture.OfficialCaptureBlocked, match="INVALID|UNVERIFIED"):
        capture.attach_reviewed_calendar_claims(
            bundle_path=bundle, claims={"NO": [], "SE": []},
            output_path=local_root / "review.json")


def test_transport_failure_preserves_other_source_without_inventing_robots(local_root):
    result, calls = run_capture(local_root, broken={"NO"})
    blocked = result["blocked_sources"][0]
    assert blocked["robots_path"] is None
    assert blocked["robots_sha256"] is None
    assert capture.DEFAULT_OFFICIAL_URLS["NO"] not in calls
    assert set(result["source_sha256"]) == {"SE"}


def test_both_denied_is_negative_evidence_not_empty_calendar(local_root):
    result, calls = run_capture(local_root, denied={"NO", "SE"})
    assert all(url.endswith("/robots.txt") for url in calls)
    assert len(result["blocked_sources"]) == 2
    assert result["source_bytes"] == {}
    assert result["status"] == "BLOCKED_PARTIAL_OFFICIAL_SOURCE_CAPTURE"
    assert not list(local_root.glob("*.html"))


def test_default_remains_strict_and_partial_cannot_overwrite(local_root):
    with pytest.raises(capture.OfficialCaptureBlocked, match="ROBOTS_NOT_PERMITTED"):
        run_capture(local_root, denied={"SE"}, allow_partial=False)
    assert list(local_root.iterdir()) == []
    result, _ = run_capture(local_root, denied={"SE"})
    original = Path(result["bundle_path"]).read_bytes()
    with pytest.raises(FileExistsError):
        run_capture(local_root, denied={"SE"})
    assert Path(result["bundle_path"]).read_bytes() == original


def test_partial_flag_with_both_sources_retains_success_contract(local_root):
    result, _ = run_capture(local_root)
    assert result["blocked_sources"] == []
    assert result["status"] == "ORIGINAL_HTTPS_SOURCE_COPIES_REVIEW_REQUIRED"


def test_cli_prints_blocked_receipt_and_returns_nonzero(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(capture, "capture_official_calendar", lambda **kwargs: {
        "blocked_sources": [{"country": "SE"}], "bet_authorized": False})
    assert capture.main(["capture", "--day", "2026-11-01", "--private-root",
                         str(tmp_path), "--allow-partial"]) == 2
    assert json.loads(capsys.readouterr().out)["bet_authorized"] is False

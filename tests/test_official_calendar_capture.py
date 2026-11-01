"""C1 original official HTTPS acquisition and reviewable day+2 bundle tests."""
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from collector.official_calendar_integration import compare_original_three_day_sources

from collector.independent_day_window import (
    audit_official_day, audit_window, read_official_bundle,
)
from collector.official_calendar_capture import (
    DEFAULT_OFFICIAL_URLS, HTTPSReply, OfficialCaptureBlocked,
    _get_https, capture_official_calendar, attach_reviewed_calendar_claims,
)

DAY = "2026-11-01"
NOW = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
DATA = {
    "NO": b"01.11.2026 | Momarken Travbane\n",
    "SE": b"2026-11-01 | Solvalla\n",
}
ROBOTS = b"User-agent: *\nAllow: /\n"


def _fake_transport(*, denied=None, bad_redirect=None, oversized=None,
                    non_utf8=None, bad_robots=False, unexpected_status=None):
    calls = []

    def get(url, *, max_bytes):
        calls.append(url)
        if url.endswith("/robots.txt"):
            body = (b"User-agent: *\nDisallow: /\n" if bad_robots else ROBOTS)
            return HTTPSReply(
                200, url, "text/plain", body, "Sun, 01 Nov 2026 10:00:00 GMT")
        country = "NO" if "travsport.no" in url else "SE"
        body = DATA[country]
        if country == oversized:
            body = b"X" * (max_bytes + 1)
        if country == non_utf8:
            body = b"\xff\xfe"
        return HTTPSReply(
            500 if country == unexpected_status else 200,
            "https://evil.example.org/redirect" if country == bad_redirect else url,
            "text/html; charset=utf-8", body,
            "Sun, 01 Nov 2026 10:00:00 GMT",
        )

    return get, calls


def _capture(tmp_path, transport=None, **options):
    get = transport or _fake_transport(**options)[0]
    return capture_official_calendar(
        day=DAY, private_root=tmp_path,
        sources=DEFAULT_OFFICIAL_URLS,
        transport=get, clock=lambda: NOW,
    )


def _meeting_claims():
    return {
        "NO": [{
            "date": DAY, "venue": "Momarken Travbane",
            "evidence_excerpt": "01.11.2026 | Momarken Travbane",
        }],
        "SE": [{
            "date": DAY, "venue": "Solvalla",
            "evidence_excerpt": "2026-11-01 | Solvalla",
        }],
    }


def _collector_manifest():
    m1, m2 = "MO_NR_" + DAY, "S1_NR_" + DAY
    a = {"meeting_id": m1, "country": "NO", "sport_type": "T",
         "is_multi_track": False, "track": "Momarken"}
    b = {"meeting_id": m2, "country": "SE", "sport_type": "T",
         "is_multi_track": False, "track": "Solvalla"}
    return {
        "date_oslo": DAY, "automatically_discovered_meetings": [m1, m2],
        "manually_seeded_meetings": [],
        "public_racedays_api": {m1: a, m2: b},
        "homepage_spa_racedays": {"api_path": "/api/racedays", "meetings": {}},
        "calendar_racedays": {},
        "meetings": [
            {"meeting_id": m1, "listing_source": a,
             "program_pdf": "PDF_TEXT_OK",
             "pdf_race_numbers": [1],
             "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT"}},
            {"meeting_id": m2, "listing_source": b,
             "program_pdf": "PDF_TEXT_OK",
             "pdf_race_numbers": [1],
             "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT"}},
        ],
        "calendar_source_diagnostic": {"status": "EMPTY_RESULT_ARRAY"},
    }


def test_capture_original_http_bytes_both_sources_exclusive_and_readback(tmp_path):
    transport, calls = _fake_transport()
    report = _capture(tmp_path, transport)
    assert report["status"] == "ORIGINAL_HTTPS_SOURCE_COPIES_REVIEW_REQUIRED"
    assert report["source_bytes"] == {"NO": len(DATA["NO"]), "SE": len(DATA["SE"])}
    assert len(calls) == 4
    assert calls[0].endswith("/robots.txt")
    assert calls[1] == DEFAULT_OFFICIAL_URLS["NO"]
    assert calls[2].endswith("/robots.txt")
    assert calls[3] == DEFAULT_OFFICIAL_URLS["SE"]
    bundle_path = Path(report["bundle_path"])
    assert bundle_path.exists()
    original = json.loads(bundle_path.read_text())
    assert original["capture_method"] == "INJECTED_OFFLINE_TRANSPORT_TEST"
    assert original["source_meeting_extract_reviewed"] is False
    assert all(x["meetings"] == [] for x in original["sources"])
    assert all(x["network_https_response_observed"] is False
               for x in original["sources"])
    assert all(x["independent_transport_origin_attested"] is False
               for x in original["sources"])
    for source in original["sources"]:
        raw = (tmp_path / source["raw_path"]).read_bytes()
        robots = (tmp_path / source["robots_path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source["raw_sha256"]
        assert hashlib.sha256(robots).hexdigest() == source["robots_sha256"]
        assert (tmp_path / source["raw_path"]).stat().st_mode & 0o077 == 0
    source = read_official_bundle(bundle_path, day=DAY)
    assert source["source_receipts_verified"] == 2
    assert source["events"] == []
    assert source["independent_all_meetings_denominator_verified"] is False
    assert source["pit_certified"] is False


def test_full_c1_capture_attach_and_compare_is_still_not_coverage(tmp_path):
    captured = _capture(tmp_path)
    bundle = Path(captured["bundle_path"])
    saved_original_sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
    annotated = tmp_path / "reviewed.json"
    result = attach_reviewed_calendar_claims(
        bundle_path=bundle, claims=_meeting_claims(), output_path=annotated)
    assert result["source_grounded_venue_candidates"] == 2
    assert result["independent_complete_day_denominator_verified"] is False
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == saved_original_sha
    source = read_official_bundle(annotated, day=DAY)
    audit = audit_official_day(_collector_manifest(), source)
    assert len(audit["matched_venue_candidates"]) == 2
    assert audit["status"] == "BLOCKED_INDEPENDENT_FULL_DAY_DENOMINATOR"
    assert audit["coverage_percentage"] is None
    assert audit["race_denominator_independently_verified"] is False
    series = audit_window(
        DAY, {DAY: _collector_manifest()}, {DAY: source})
    assert len(series["days"]) == 3
    assert series["days"][1]["status"] == "BLOCKED_MISSING_EVIDENCE"
    assert series["c1_14_day_coverage_eligible"] is False
    assert series["pit_certified"] is False


@pytest.mark.parametrize("mode", [
    {"bad_redirect": "NO"},
    {"oversized": "NO"},
    {"non_utf8": "SE"},
    {"unexpected_status": "SE"},
    {"bad_robots": True},
])
def test_failing_http_or_robots_never_writes_a_positive_bundle(tmp_path, mode):
    with pytest.raises(OfficialCaptureBlocked):
        _capture(tmp_path, **mode)
    assert list(tmp_path.iterdir()) == []


def test_invalid_official_host_cannot_fetch_data(tmp_path):
    transport, calls = _fake_transport()
    with pytest.raises(OfficialCaptureBlocked, match="OFFICIAL_CALENDAR_HOST_REJECTED"):
        capture_official_calendar(
            day=DAY, private_root=tmp_path,
            sources={"NO": "https://example.org/official", "SE": DEFAULT_OFFICIAL_URLS["SE"]},
            transport=transport, clock=lambda: NOW)
    assert calls == []


def test_missing_country_cannot_produce_fake_complete_calendar(tmp_path):
    with pytest.raises(OfficialCaptureBlocked, match="REQUIRE_BOTH"):
        capture_official_calendar(
            day=DAY, private_root=tmp_path, sources={"NO": DEFAULT_OFFICIAL_URLS["NO"]},
            transport=_fake_transport()[0], clock=lambda: NOW)


@pytest.mark.parametrize("day", ["2026-02-30", "2026-11-1", "not-a-date"])
def test_invalid_day_never_sends_any_requests(tmp_path, day):
    transport, calls = _fake_transport()
    with pytest.raises(OfficialCaptureBlocked):
        capture_official_calendar(
            day=day, private_root=tmp_path, transport=transport, clock=lambda: NOW)
    assert calls == []


def test_repeat_capture_cannot_overwrite_first_original_bytes(tmp_path):
    old = _capture(tmp_path)
    body = Path(old["bundle_path"]).read_bytes()
    with pytest.raises(FileExistsError):
        _capture(tmp_path)
    assert Path(old["bundle_path"]).read_bytes() == body


def test_bad_human_claim_does_not_modify_or_publish_a_reviewed_bundle(tmp_path):
    old = Path(_capture(tmp_path)["bundle_path"])
    edited = _meeting_claims()
    edited["SE"][0]["evidence_excerpt"] = "invented by researcher"
    output = tmp_path / "reviewed.json"
    original_sha = hashlib.sha256(old.read_bytes()).hexdigest()
    with pytest.raises(OfficialCaptureBlocked, match="REVIEWED_CANDIDATE"):
        attach_reviewed_calendar_claims(
            bundle_path=old, claims=edited, output_path=output)
    assert not output.exists()
    assert not (tmp_path / "reviewed.json.pending").exists()
    assert hashlib.sha256(old.read_bytes()).hexdigest() == original_sha


def test_annotated_bundle_is_append_only_not_replaced(tmp_path):
    path = Path(_capture(tmp_path)["bundle_path"])
    output = tmp_path / "reviewed.json"
    attach_reviewed_calendar_claims(
        bundle_path=path, claims=_meeting_claims(), output_path=output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    with pytest.raises(OfficialCaptureBlocked):
        attach_reviewed_calendar_claims(
            bundle_path=path, claims=_meeting_claims(), output_path=output)
    assert hashlib.sha256(output.read_bytes()).hexdigest() == digest


def test_original_bundle_rejects_untrusted_symlink(tmp_path):
    bundle = Path(_capture(tmp_path)["bundle_path"])
    alias = tmp_path / "alias.json"
    alias.symlink_to(bundle)
    with pytest.raises(OfficialCaptureBlocked, match="MISSING_OR_SYMLINK"):
        attach_reviewed_calendar_claims(
            bundle_path=alias, claims=_meeting_claims(),
            output_path=tmp_path / "review.json")


def test_test_transport_cannot_accidentally_claim_live_origin(tmp_path):
    response = _capture(tmp_path)
    data = json.loads(Path(response["bundle_path"]).read_text())
    assert data["source_first_publication_time_attested"] is False
    assert data["independent_complete_day_denominator_verified"] is False
    assert data["bet_authorized"] is False
    assert data["hq_accepted"] is False
    assert all(not row["network_https_response_observed"] for row in data["sources"])


def test_robots_policy_checks_actual_requested_path(tmp_path):
    def get(url, *, max_bytes):
        if url.endswith("/robots.txt"):
            return HTTPSReply(200, url, "text/plain",
                              b"User-agent: *\nDisallow: /Sport/\n")
        return HTTPSReply(200, url, "text/html", DATA["NO"])
    with pytest.raises(OfficialCaptureBlocked, match="ROBOTS_NOT_PERMITTED:NO"):
        _capture(tmp_path, get)


def test_genuine_https_transport_requires_nonredirect_original_response(monkeypatch):
    # Validate the adapter itself offline: no live network traffic in tests.
    class Response:
        status = 200
        headers = {"Content-Type": "text/html", "Date": "Sun"}
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def geturl(self):
            return DEFAULT_OFFICIAL_URLS["NO"]
        def read(self, amount):
            assert amount == 101
            return DATA["NO"]

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == DEFAULT_OFFICIAL_URLS["NO"]
            assert request.get_method() == "GET"
            assert timeout == 16
            return Response()
    monkeypatch.setattr(
        "collector.official_calendar_capture.urllib.request.build_opener",
        lambda *_: Opener())
    reply = _get_https(DEFAULT_OFFICIAL_URLS["NO"], max_bytes=100)
    assert reply.body == DATA["NO"]
    assert reply.url == DEFAULT_OFFICIAL_URLS["NO"]



def _original_collector_archive(tmp_path, *, wrong_date=False,
                               tampered=False):
    run = "20261101T061915114528Z"
    root = f"output/daily/{DAY}/{run}/"
    meeting = "MO_NR_" + DAY
    raw_pdf = b"%PDF-1.4\nsynthetic source only\n"
    data = _collector_manifest()
    data.update({"run_id": run, "requests": [{
        "url": "https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/" +
        meeting, "status": "PDF_OK",
        "path": root + f"meetings/{meeting}/full_program.pdf",
        "sha256": hashlib.sha256(raw_pdf).hexdigest(),
        "at_utc": "2026-11-01T06:19:15Z",
    }], "counts": {}})
    if wrong_date:
        data["date_oslo"] = "2026-11-02"
    path = tmp_path / "original-collector.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(root + "manifest.json", json.dumps(data))
        archive.writestr(root + f"meetings/{meeting}/full_program.pdf",
                         b"tamper" if tampered else raw_pdf)
    return path


def test_integrated_c1_original_zip_and_human_source_excerpts_no_false_accept(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    result = capture_official_calendar(
        day=DAY, private_root=root, transport=_fake_transport()[0],
        clock=lambda: NOW)
    candidate = root / "reviewed.json"
    attach_reviewed_calendar_claims(
        bundle_path=Path(result["bundle_path"]), claims=_meeting_claims(),
        output_path=candidate,
    )
    original = _original_collector_archive(tmp_path)
    whole = compare_original_three_day_sources(
        DAY, {DAY: original}, {DAY: candidate})
    assert whole["status"] == "BLOCKED_INDEPENDENT_C1_DENOMINATOR"
    assert whole["original_source_days_with_valid_receipts"] == 1
    assert whole["official_source_days_with_two_hashed_copies"] == 1
    day0 = whole["calendar_candidate_comparison"]["days"][0]
    assert len(day0["matched_venue_candidates"]) == 2
    assert day0["coverage_percentage"] is None
    assert whole["source_evidence_by_day"][0]["original_archive_receipt_errors"] == []
    assert whole["source_evidence_by_day"][1]["archive_input_supplied"] is False
    assert whole["calendar_coverage_percentage"] is None
    assert whole["c6_tminus4_pit_certified"] is False
    assert whole["hq_accepted"] is False
    assert whole["bet_authorized"] is False


def test_original_pdf_tamper_blocks_c1_day_even_if_official_bundle_available(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    result = _capture(root)
    out = compare_original_three_day_sources(
        DAY, {DAY: _original_collector_archive(tmp_path, tampered=True)},
        {DAY: Path(result["bundle_path"])})
    assert out["original_source_days_with_valid_receipts"] == 0
    assert "PDF_SOURCE_SHA_MISMATCH" in out[
        "source_evidence_by_day"][0]["original_archive_receipt_errors"]
    assert out["calendar_candidate_comparison"]["days"][0]["missing_collector_manifest"]
    assert out["independent_race_denominator_verified"] is False


def test_original_archive_calendar_day_disagreement_fails_closed(tmp_path):
    result = compare_original_three_day_sources(
        DAY, {DAY: _original_collector_archive(tmp_path, wrong_date=True)}, {})
    assert result["original_source_days_with_valid_receipts"] == 0
    assert "ORIGINAL_ARCHIVE_DAY_DISAGREES" in result[
        "source_evidence_by_day"][0]["original_archive_receipt_errors"]
    assert result["c1_14_day_coverage_eligible"] is False


def test_out_of_window_original_inputs_never_silently_drop(tmp_path):
    with pytest.raises(ValueError, match="outside requested"):
        compare_original_three_day_sources(
            DAY, {"2026-11-10": tmp_path / "archive.zip"}, {})


def test_no_source_archive_and_no_bundle_is_explicit_blocked_not_no_races():
    result = compare_original_three_day_sources(DAY, {}, {})
    assert result["original_source_days_with_valid_receipts"] == 0
    assert result["official_source_days_with_two_hashed_copies"] == 0
    assert all(day["status"] == "BLOCKED_MISSING_EVIDENCE"
               for day in result["calendar_candidate_comparison"]["days"])
    assert result["calendar_coverage_percentage"] is None
    assert result["independent_meeting_denominator_verified"] is False

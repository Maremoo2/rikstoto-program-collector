"""Strict offline independent-calendar evidence and day+2 scope checks.

All fixtures are deliberately synthetic. These tests grant no live source,
all-day denominator, PIT or BET authority.
"""
import hashlib
import json

import pytest

from collector.independent_day_window import (
    SCHEMA, _trusted_official_url, audit_official_day, audit_window,
    read_official_bundle, window_dates,
)

DAY = "2026-11-01"


def _manifest(day=DAY):
    meeting_no = "MO_NR_" + day
    meeting_se = "S1_NR_" + day
    no_meta = {"meeting_id": meeting_no, "track": "Momarken", "country": "NO",
               "sport_type": "T", "is_multi_track": False}
    se_meta = {"meeting_id": meeting_se, "track": "Solvalla", "country": "SE",
               "sport_type": "T", "is_multi_track": False}
    return {"date_oslo": day, "automatically_discovered_meetings": [meeting_no, meeting_se],
            "manually_seeded_meetings": [],
            "homepage_spa_racedays": {"api_path": "/api/racedays",
                                       "meetings": {meeting_no: no_meta, meeting_se: se_meta}},
            "public_racedays_api": {meeting_no: no_meta, meeting_se: se_meta},
            "calendar_racedays": {},
            "calendar_source_diagnostic": {"status": "EMPTY_RESULT_ARRAY"},
            "meetings": [
                {"meeting_id": meeting_no, "listing_source": no_meta,
                 "program_pdf": "PDF_TEXT_OK", "pdf_race_numbers": [1, 2],
                 "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT"}},
                {"meeting_id": meeting_se, "listing_source": se_meta,
                 "program_pdf": "PDF_TEXT_OK", "pdf_race_numbers": [1, 2],
                 "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT"}},
            ]}


def _bundle(tmp_path, day=DAY, *, one_country=False, bad_sha=False,
            bad_url=False, unsafe_path=False, unmatched=False,
            duplicate=False, wrong_date=False, fake_excerpt=False,
            wrong_time=False, late_claim=False):
    dnt_line = f'{day[8:10]}.{day[5:7]}.{day[:4]} | Momarken Travbane'
    se_line = f'{day} | Solvalla'
    specs = [("NO", "https://old.travsport.no/Sport/Terminliste/", "no.txt", dnt_line,
              "Momarken Travbane"),
             ("SE", "https://www.travsport.se/kalender", "se.txt", se_line,
              "Solvalla")]
    if one_country:
        specs = specs[:1]
    sources = []
    for i, (country, url, name, line, venue) in enumerate(specs):
        raw = (line + "\n").encode("utf-8")
        (tmp_path / name).write_bytes(raw)
        source = {"country": country, "source_url": url if not bad_url else "https://rikstoto.no/",
                  "http_status": 200, "observed_at_utc": "2026-11-01T13:00:00Z" if not wrong_time else "2026-11-01T13:00:00",
                  "source_publication_time_attested": late_claim,
                  "raw_path": name if not unsafe_path else "../missing.txt",
                  "raw_sha256": hashlib.sha256(raw).hexdigest() if not bad_sha else "0" * 64,
                  "meetings": [{"date": day if not wrong_date else "2026-11-02",
                                "venue": ("Missing Venue" if unmatched else venue),
                                "evidence_excerpt": ("not in source" if fake_excerpt else line)}]}
        if duplicate and i == 0:
            source["meetings"].append(dict(source["meetings"][0]))
        sources.append(source)
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps({"schema": SCHEMA, "date_oslo": day,
                               "sources": sources}), encoding="utf-8")
    return path


def test_verifiable_local_official_page_copies_are_still_not_c1_proof(tmp_path):
    source = read_official_bundle(_bundle(tmp_path), day=DAY)
    assert source["source_receipts_verified"] == 2
    assert source["errors"] == []
    assert source["countries_with_source_copy"] == ["NO", "SE"]
    assert source["status"] == "SOURCE_COPIES_HASHED_CANDIDATE_LIST_ONLY"
    assert source["independent_transport_origin_attested"] is False
    assert source["independent_all_meetings_denominator_verified"] is False
    assert source["independent_all_races_denominator_verified"] is False
    result = audit_official_day(_manifest(), source)
    assert len(result["matched_venue_candidates"]) == 2
    assert result["independent_venues_unmatched_to_collector"] == []
    assert result["collector_candidates_not_correlated_to_official"] == []
    assert result["status"] == "BLOCKED_INDEPENDENT_FULL_DAY_DENOMINATOR"
    assert result["coverage_percentage"] is None
    assert result["c1_coverage_eligible"] is False
    assert result["pit_certified"] is False
    assert result["bet_authorized"] is False


@pytest.mark.parametrize("kwargs,error", [
    ({"one_country": True}, "MISSING_NO_OR_SE_OFFICIAL_SOURCE_COPY"),
    ({"bad_sha": True}, "RAW_SOURCE_SHA_MISMATCH"),
    ({"bad_url": True}, "UNTRUSTED_OFFICIAL_CALENDAR_ORIGIN"),
    ({"unsafe_path": True}, "UNSAFE_RAW_SOURCE_PATH"),
    ({"duplicate": True}, "DUPLICATE_OFFICIAL_VENUE"),
    ({"wrong_date": True}, "OFFICIAL_MEETING_DAY_OR_TEXT_INVALID"),
    ({"fake_excerpt": True}, "SOURCE_EVENT_EXCERPT_NOT_ATTESTED"),
    ({"wrong_time": True}, "UNSUPPORTED_SOURCE_RECEIPT_OR_TIME_CLAIM"),
    ({"late_claim": True}, "UNSUPPORTED_SOURCE_RECEIPT_OR_TIME_CLAIM"),
    ({"unmatched": True}, "SOURCE_EVENT_EXCERPT_NOT_ATTESTED"),
])
def test_invalid_source_bytes_and_claims_fail_closed(tmp_path, kwargs, error):
    result = read_official_bundle(_bundle(tmp_path, **kwargs), day=DAY)
    assert result["status"] == "BLOCKED"
    assert error in result["errors"]
    assert result["independent_all_races_denominator_verified"] is False


def test_unexpected_racing_date_in_bundle_fails_closed(tmp_path):
    result = read_official_bundle(_bundle(tmp_path), day="2026-11-02")
    assert "BUNDLE_SCHEMA_OR_DAY_MISMATCH" in result["errors"]


def test_no_automatic_c1_from_two_third_party_sites_even_when_matched(tmp_path):
    source = read_official_bundle(_bundle(tmp_path), day=DAY)
    manifest = _manifest()
    manifest["calendar_source_diagnostic"]["status"] = "TARGET_DAY_ENTRIES_PRESENT"
    manifest["calendar_racedays"] = manifest["public_racedays_api"]
    result = audit_official_day(manifest, source)
    assert len(result["matched_venue_candidates"]) == 2
    assert result["race_denominator_independently_verified"] is False
    assert result["meeting_denominator_independently_verified"] is False
    assert result["coverage_percentage"] is None


def test_independent_track_not_in_collector_remains_explicit(tmp_path):
    source = read_official_bundle(_bundle(tmp_path), day=DAY)
    m = _manifest()
    m["meetings"] = m["meetings"][:1]
    result = audit_official_day(m, source)
    assert result["independent_venues_unmatched_to_collector"] == [
        {"venue": "Solvalla", "country": "SE"}]
    assert result["collector_candidates_not_correlated_to_official"] == ["S1_NR_" + DAY]


def test_ambiguous_rikstoto_same_track_never_force_matched(tmp_path):
    source = read_official_bundle(_bundle(tmp_path), day=DAY)
    m = _manifest()
    extra_id = "S9_NR_" + DAY
    se = dict(m["public_racedays_api"]["S1_NR_" + DAY])
    se["meeting_id"] = extra_id
    m["public_racedays_api"][extra_id] = se
    m["homepage_spa_racedays"]["meetings"][extra_id] = se
    m["automatically_discovered_meetings"].append(extra_id)
    m["meetings"].append({"meeting_id": extra_id, "listing_source": se,
                          "program_pdf": "PDF_TEXT_OK", "pdf_race_numbers": [1],
                          "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT"}})
    result = audit_official_day(m, source)
    assert len(result["matched_venue_candidates"]) == 1
    assert len(result["ambiguous_venue_matches"]) == 1
    assert result["coverage_percentage"] is None


def test_three_day_window_crosses_year_boundary_and_marks_missing_evidence():
    assert window_dates("2026-12-31") == ["2026-12-31", "2027-01-01", "2027-01-02"]
    result = audit_window("2026-12-31", {}, {})
    assert len(result["days"]) == 3
    assert all(r["status"] == "BLOCKED_MISSING_EVIDENCE" for r in result["days"])
    assert all(r["missing_collector_manifest"] for r in result["days"])
    assert result["coverage_percentage"] is None
    assert result["c1_14_day_coverage_eligible"] is False
    assert result["pit_certified"] is False


def test_wrong_origin_with_user_info_or_ip_cannot_pass():
    assert _trusted_official_url("https://www.travsport.se/path", "SE")
    assert not _trusted_official_url("http://www.travsport.se/path", "SE")
    assert not _trusted_official_url("https://www.travsport.se.evil.com/path", "SE")
    assert not _trusted_official_url("https://user@www.travsport.se/path", "SE")
    assert not _trusted_official_url("https://www.travsport.se:444/path", "SE")
    assert not _trusted_official_url("https://www.travsport.se/path", "NO")


def test_unspecified_source_bundle_is_not_fabricated_as_no_races(tmp_path):
    result = audit_window(DAY, {DAY: _manifest()}, {})
    assert result["days"][0]["missing_official_bundle"] is True
    assert result["days"][0]["coverage_percentage"] is None
    assert result["days"][1]["missing_collector_manifest"] is True
    assert result["status"] == "BLOCKED_INDEPENDENT_FULL_DAY_DENOMINATOR"

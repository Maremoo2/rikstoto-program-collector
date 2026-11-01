"""C-DEV-02: candidate-only NO/SE trot audits; never fake a C1 denominator."""
import copy

from collector.calendar_audit import calendar_racedays
from collector.no_se_calendar import audit_no_se_trot_discovery, collection_order


DAY = "2026-10-29"


def row(code, country, sport="T", composite=False, races=(1, 2)):
    return {"raceDayKey": code, "raceDayName": code.split("_")[0],
            "countryIsoCode": country, "sportType": sport,
            "isMultiTrack": composite,
            "races": [{"raceNumber": n} for n in races]}


def sample(*, date_api_status="EMPTY_RESULT_ARRAY", max_meetings=None):
    keys = [
        row("BT_NR_" + DAY, "NO"),
        row("S1_NR_" + DAY, "SE"),
        row("S2_NR_" + DAY, "DK"),
        row("S3_NR_" + DAY, "SE", "G"),
        row("X1_NR_" + DAY, "", "T", True),
    ]
    typed = calendar_racedays({"success": True, "result": keys}, DAY)
    candidate_ids = sorted(typed)
    meetings = []
    for mid in candidate_ids[:max_meetings] if max_meetings is not None else candidate_ids:
        meetings.append({
            "meeting_id": mid, "program_pdf": "PDF_TEXT_OK",
            "pdf_race_numbers": [1, 2],
            "startlist_pdf_audit": {"status": "MATCHED_AS_OF_SNAPSHOT"},
            "listing_source": typed[mid],
            "is_multi_track_product": typed[mid]["is_multi_track"],
        })
    return {
        "date_oslo": DAY, "automatically_discovered_meetings": candidate_ids,
        "manually_seeded_meetings": [], "meetings": meetings,
        "homepage_spa_racedays": {"meetings": typed},
        "public_racedays_api": typed, "calendar_racedays": {},
        "calendar_source_diagnostic": {"status": date_api_status,
                                       "date_coverage_verified": False},
    }


def test_source_country_and_sport_not_meeting_prefix():
    m = sample()
    report = audit_no_se_trot_discovery(m)
    assert report["no_se_trot_physical_candidate_ids"] == [
        "BT_NR_" + DAY, "S1_NR_" + DAY]
    assert report["no_se_trot_candidate_count"] == 2
    assert report["no_se_trot_captured_count"] == 2
    assert report["no_se_trot_observed_pdf_race_count"] == 4
    assert "S2_NR_" + DAY in report["non_target_meeting_ids"]  # DK trot
    assert "S3_NR_" + DAY in report["non_target_meeting_ids"]  # SE gallop
    assert report["composite_product_ids_excluded"] == ["X1_NR_" + DAY]
    assert "DATE_API_NOT_VERIFIED:EMPTY_RESULT_ARRAY" in report["blockers"]
    assert report["c1_coverage_eligible"] is False
    assert report["independent_whole_day_denominator_verified"] is False
    assert report["pit_certified"] is False
    assert report["bet_authorized"] is False


def test_priority_queue_keeps_source_typed_no_se_trot_before_foreign_and_x1():
    m = sample()
    all_ids = set(m["automatically_discovered_meetings"])
    order = collection_order(DAY, m, all_ids)
    assert order[:2] == ["BT_NR_" + DAY, "S1_NR_" + DAY]
    assert order[-1] == "X1_NR_" + DAY
    m["meetings"] = [x for x in m["meetings"] if x["meeting_id"] in order[:1]]
    report = audit_no_se_trot_discovery(m)
    assert report["candidate_ids_not_collected"] == ["S1_NR_" + DAY]
    assert "SOURCE_CANDIDATES_NOT_CAPTURED" in report["blockers"]


def test_same_s_prefix_different_country_not_invented_as_sweden():
    m = sample()
    m["public_racedays_api"]["S2_NR_" + DAY]["country"] = "DK"
    r = audit_no_se_trot_discovery(m)
    assert "S2_NR_" + DAY not in r["no_se_trot_physical_candidate_ids"]


def test_country_conflict_blocks_without_guess_or_silent_last_wins():
    m = sample()
    m["public_racedays_api"] = copy.deepcopy(m["public_racedays_api"])
    m["public_racedays_api"]["S1_NR_" + DAY]["country"] = "DK"
    r = audit_no_se_trot_discovery(m)
    assert r["source_classification_conflicts"] == ["S1_NR_" + DAY]
    assert r["no_se_trot_physical_candidate_ids"] == ["BT_NR_" + DAY]
    assert "SOURCE_CLASSIFICATION_CONFLICT" in r["blockers"]
    assert r["status"] == "REVIEW_REQUIRED"


def test_sport_conflict_blocks_gallop_from_trot_count():
    m = sample()
    m["homepage_spa_racedays"]["meetings"] = copy.deepcopy(
        m["homepage_spa_racedays"]["meetings"])
    m["homepage_spa_racedays"]["meetings"]["S1_NR_" + DAY]["sport_type"] = "G"
    r = audit_no_se_trot_discovery(m)
    assert "S1_NR_" + DAY in r["source_classification_conflicts"]
    assert "S1_NR_" + DAY not in r["no_se_trot_physical_candidate_ids"]


def test_untyped_original_homepage_regex_id_cannot_get_inferred_country():
    m = sample()
    unknown = "S9_NR_" + DAY
    m["automatically_discovered_meetings"].append(unknown)
    m["meetings"].append({"meeting_id": unknown, "program_pdf": "PDF_TEXT_OK"})
    r = audit_no_se_trot_discovery(m)
    assert unknown in r["unknown_country_or_sport_ids"]
    assert unknown not in r["no_se_trot_physical_candidate_ids"]
    assert "UNKNOWN_COUNTRY_OR_SPORT" in r["blockers"]


def test_manual_seed_never_makes_independent_discovery():
    m = sample()
    m["manually_seeded_meetings"] = ["S1_NR_" + DAY]
    m["automatically_discovered_meetings"].remove("S1_NR_" + DAY)
    r = audit_no_se_trot_discovery(m)
    assert r["candidate_ids_manual_seeded"] == ["S1_NR_" + DAY]
    assert r["candidate_ids_not_auto_discovered"] == ["S1_NR_" + DAY]
    assert "CANDIDATES_NOT_AUTOMATICALLY_DISCOVERED" in r["blockers"]


def test_source_candidate_missing_pdf_or_unverified_startlist_is_not_ready():
    m = sample()
    m["meetings"][0]["program_pdf"] = "SOURCE_UNAVAILABLE"
    m["meetings"][1]["startlist_pdf_audit"]["status"] = "PARTIAL_OR_UNVERIFIED"
    r = audit_no_se_trot_discovery(m)
    assert r["candidate_ids_pdf_missing"] == ["BT_NR_" + DAY]
    assert r["candidate_ids_snapshot_unverified"] == ["S1_NR_" + DAY]
    assert "NO_SE_TROT_PDF_MISSING" in r["blockers"]
    assert "NO_SE_TROT_SNAPSHOT_UNVERIFIED" in r["blockers"]


def test_all_observed_sources_agree_still_no_full_day_or_pit_certification():
    m = sample(date_api_status="TARGET_DAY_ENTRIES_PRESENT")
    m["calendar_racedays"] = copy.deepcopy(m["public_racedays_api"])
    report = audit_no_se_trot_discovery(m)
    assert report["blockers"] == []
    assert report["status"] == "OBSERVED_CANDIDATES_RECONCILED_UNVERIFIED_DAY"
    assert report["independent_whole_day_denominator_verified"] is False
    assert report["c1_coverage_eligible"] is False
    assert report["pit_certified"] is False


def test_missing_date_and_no_typed_candidates_never_promotes_empty_day():
    m = {"date_oslo": DAY, "meetings": [], "automatically_discovered_meetings": [],
         "calendar_source_diagnostic": {"status": "EMPTY_RESULT_ARRAY"}}
    r = audit_no_se_trot_discovery(m)
    assert r["status"] == "REVIEW_REQUIRED"
    assert "NO_TYPED_NO_SE_TROT_CANDIDATES" in r["blockers"]
    assert r["no_se_trot_candidate_count"] == 0
    assert r["c1_coverage_eligible"] is False


def test_mismatched_meeting_identity_fails_closed():
    m = sample()
    m["public_racedays_api"] = copy.deepcopy(m["public_racedays_api"])
    m["public_racedays_api"]["BT_NR_" + DAY]["meeting_id"] = "S1_NR_" + DAY
    r = audit_no_se_trot_discovery(m)
    assert "BT_NR_" + DAY in r["source_classification_conflicts"]
    assert "BT_NR_" + DAY not in r["no_se_trot_physical_candidate_ids"]

"""Unit tests for exact PDF/startlist horse and scratch reconciliation."""
from collector.startlist_audit import normalized_horse_name, reconcile_startlist


def doc():
    return {"race": {"race_number": 6},
            "entrants": [
                {"program_number": 1, "name": "Skjetne Lara",
                 "scratched": False, "scratch_state": "UNVERIFIED"},
                {"program_number": 2, "name": "Lesja Loke",
                 "scratched": False, "scratch_state": "UNVERIFIED"},
            ],
            "scratches": [],
            "qa": {"warnings": ["SCRATCHES_UNVERIFIED", "PDF_SNAPSHOT_NOT_LIVE"],
                   "active_count": None, "scratched_count": None}}


def starts():
    return {"success": True, "result": {"6": [
        {"raceNumber": 6, "startNumber": 1, "horseName": "Skjetne Lara",
         "isScratched": False},
        {"raceNumber": 6, "startNumber": 2, "horseName": "Lesja Loke",
         "isScratched": True},
    ]}}


def test_exact_names_numbers_and_explicit_flags_verify_snapshot():
    race = doc()
    result = reconcile_startlist([race], starts(), captured_at="2026-10-18T05:00:00Z")
    assert result["status"] == "MATCHED_AS_OF_SNAPSHOT"
    assert result["horses_verified"] == 2
    assert result["confirmed_scratches"] == 1
    assert race["entrants"][0]["scratch_state"] == "ACTIVE_AS_OF_SNAPSHOT"
    assert race["entrants"][1]["scratch_state"] == "SCRATCHED_AS_OF_SNAPSHOT"
    assert race["qa"]["active_count"] == 1
    assert race["qa"]["scratched_count"] == 1
    assert "SCRATCHES_UNVERIFIED" not in race["qa"]["warnings"]
    assert "SCRATCH_STATUS_MAY_CHANGE" in race["qa"]["warnings"]


def test_missing_boolean_never_proves_any_horse_active():
    race = doc()
    response = starts()
    del response["result"]["6"][0]["isScratched"]
    output = reconcile_startlist([race], response)
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"
    assert all(h["scratch_state"] == "UNVERIFIED" for h in race["entrants"])


def test_number_collision_or_missing_runner_blocks_verification():
    race = doc()
    response = starts()
    response["result"]["6"][1]["startNumber"] = 1
    output = reconcile_startlist([race], response)
    assert output["race_matches"] == 0
    assert race["qa"]["active_count"] is None


def test_horse_name_mismatch_keeps_unverified_state():
    race = doc()
    response = starts()
    response["result"]["6"][1]["horseName"] = "Different Horse"
    output = reconcile_startlist([race], response)
    assert output["race_matches"] == 0
    assert not race["scratches"]


def test_one_pdf_race_missing_blocks_full_coverage():
    race = doc()
    response = starts()
    response["result"]["7"] = [{"raceNumber": 7, "startNumber": 1,
                                "horseName": "Extra Runner", "isScratched": False}]
    output = reconcile_startlist([race], response)
    assert output["race_matches"] == 1
    assert output["race_numbers_match"] is False
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"


def test_normalization_is_case_accent_insensitive():
    assert normalized_horse_name("Skjetne Lara") == normalized_horse_name("SKJETNE LARA")
    assert normalized_horse_name("Östra Häst") == normalized_horse_name("Ostra Hast")


def test_name_mismatch_diagnostics_identify_exact_runner():
    race = doc()
    response = starts()
    response["result"]["6"][1]["horseName"] = "Other Name"
    audit = reconcile_startlist([race], response)
    assert audit["status"] == "PARTIAL_OR_UNVERIFIED"
    assert audit["mismatches"][0]["differences"] == [
        {"number": 2, "pdf_name": "Lesja Loke", "startlist_name": "Other Name"}]
    assert race["entrants"][1]["scratch_state"] == "UNVERIFIED"


def test_number_mismatch_diagnostics_do_not_approve_race():
    race = doc()
    response = starts()
    response["result"]["6"][1]["startNumber"] = 3
    audit = reconcile_startlist([race], response)
    mismatch = audit["mismatches"][0]
    assert mismatch["missing_in_pdf"] == [3]
    assert mismatch["missing_in_startlist"] == [2]
    assert mismatch["missing_in_pdf_source_rows"] == [
        {"number": 3, "horse_name": "Lesja Loke", "isScratched": True}]
    assert audit["status"] == "PARTIAL_OR_UNVERIFIED"


def test_inferred_pdf_number_cannot_approve_physical_snapshot_or_scratch():
    race = doc()
    race["race"]["race_number_source"] = "pdf_order_inferred"
    result = reconcile_startlist([race], starts(), captured_at="2026-10-31T06:17:25Z")
    assert result["status"] == "PARTIAL_OR_UNVERIFIED"
    assert result["race_matches"] == 0
    assert result["race_numbers_match"] is True
    assert result["mismatches"] == [{
        "code": "PDF_PHYSICAL_RACE_NUMBER_INFERRED", "race": 6}]
    assert all(h["scratch_state"] == "UNVERIFIED" for h in race["entrants"])
    assert race["qa"]["active_count"] is None


def test_explicit_pdf_heading_remains_reconcilable():
    race = doc()
    race["race"]["race_number_source"] = "pdf_heading"
    result = reconcile_startlist([race], starts())
    assert result["status"] == "MATCHED_AS_OF_SNAPSHOT"
    assert result["race_matches"] == 1


def test_repeated_same_physical_pdf_race_number_is_blocked_even_when_names_match():
    a, b = doc(), doc()
    a["race"]["race_number_source"] = "pdf_heading"
    b["race"]["race_number_source"] = "pdf_heading"
    result = reconcile_startlist([a, b], starts())
    assert result["status"] == "UNVERIFIED"
    assert result["race_matches"] == 0
    assert result["mismatches"] == [{
        "code": "DUPLICATE_PHYSICAL_PDF_RACE_NUMBER",
        "pdf_race_rows": 2, "distinct_pdf_numbers": 1,
    }]
    assert all(h["scratch_state"] == "UNVERIFIED"
               for race in (a, b) for h in race["entrants"])

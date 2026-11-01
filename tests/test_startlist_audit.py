"""Unit tests for exact PDF/startlist horse and scratch reconciliation."""
from collector.startlist_audit import (
    normalized_horse_name, reconcile_startlist, unresolved_placeholder_name,
    stage_unverified_positive_scratch_signals, SCRATCH_STATUS_CONTRACT,
)


def doc():
    return {"race": {"race_number": 6, "race_number_source": "pdf_heading"},
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


def test_matching_generic_horse_name_is_not_a_verified_identity():
    race = doc()
    race["entrants"][0]["name"] = "Häst 1"
    api = starts()
    api["result"]["6"][0]["horseName"] = "Häst 1"
    audit = reconcile_startlist([race], api, captured_at="2026-11-01T06:20:00Z")
    assert audit["status"] == "PARTIAL_OR_UNVERIFIED"
    assert audit["race_numbers_match"] is True
    assert audit["race_matches"] == audit["horses_verified"] == 0
    assert audit["mismatches"][0] == {
        "code": "UNRESOLVED_PLACEHOLDER_HORSE_IDENTITY",
        "race": 6,
        "placeholders": [{"number": 1, "pdf_name": "Häst 1",
                          "startlist_name": "Häst 1"}],
    }
    assert race["qa"]["identity_verification"] == "UNVERIFIED_PLACEHOLDER_NAMES"
    assert "PLACEHOLDER_HORSE_IDENTITY_REVIEW" in race["qa"]["warnings"]
    assert all(x["scratch_state"] == "UNVERIFIED" for x in race["entrants"])


def test_generic_identity_audit_counts_blocked_race_and_horses():
    race = doc()
    race["entrants"][0]["name"] = "Häst 1"
    api = starts()
    api["result"]["6"][0]["horseName"] = "Häst 1"
    audit = reconcile_startlist([race], api)
    assert audit["verified_race_numbers"] == []
    assert audit["placeholder_race_numbers"] == [6]
    assert audit["placeholder_horses_unverified"] == 1
    assert audit["race_matches"] == audit["horses_verified"] == 0


def test_generic_placeholder_in_one_source_also_blocks_without_inferred_name():
    race = doc()
    api = starts()
    api["result"]["6"][1]["horseName"] = "Horse 2"
    output = reconcile_startlist([race], api)
    # Source disagreement alone blocks, never converts a generic value
    # into a verified identity through a matching program number.
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"
    assert output["race_matches"] == 0
    assert race["entrants"][1]["scratch_state"] == "UNVERIFIED"


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


def test_placeholder_grammar_is_narrow_and_normalized():
    assert unresolved_placeholder_name("HÄST 1")
    assert unresolved_placeholder_name("Häst 10")
    assert unresolved_placeholder_name("Horse 30")
    assert unresolved_placeholder_name("CAVALLO 4")
    assert not unresolved_placeholder_name("Horse Power")
    assert not unresolved_placeholder_name("Hästmann 1")
    assert not unresolved_placeholder_name("Champion Horse 1")
    assert not unresolved_placeholder_name("Häst 31")


def test_preliminary_positive_signal_never_confirms_scratch_or_active_state():
    race = doc()
    event = {
        "race_number": 6, "horse_number": 2, "horse_name": "Lesja Loke",
        "source_path": "$.races[0].starts[1]", "evidence": {"isScratched": True},
    }
    stage_unverified_positive_scratch_signals(race, [event])
    assert race["scratch_signal_candidates"] == [{
        **event, "verification": "UNVERIFIED_POSITIVE_SIGNAL",
    }]
    assert race["scratches"] == []
    assert all(h["scratched"] is None and h["scratch_state"] == "UNVERIFIED"
               for h in race["entrants"])
    assert race["qa"]["active_count"] is None
    assert race["qa"]["scratched_count"] is None
    assert race["qa"]["scratches_complete_as_of_snapshot"] is False
    assert race["qa"]["scratch_status_contract"] == SCRATCH_STATUS_CONTRACT


def test_missing_matching_startlist_cannot_promote_positive_signal():
    race = doc()
    event = {"race_number": 6, "horse_number": 2,
             "horse_name": "Lesja Loke", "evidence": {"isScratched": True}}
    stage_unverified_positive_scratch_signals(race, [event])
    source = starts()
    source["result"]["6"][1]["horseName"] = "Wrong Horse"
    result = reconcile_startlist([race], source)
    assert result["status"] == "PARTIAL_OR_UNVERIFIED"
    assert result["confirmed_scratches"] == 0
    assert all(h["scratched"] is None and h["scratch_state"] == "UNVERIFIED"
               for h in race["entrants"])
    assert race["scratches"] == []
    assert race["scratch_signal_candidates"][0]["verification"] == (
        "UNVERIFIED_POSITIVE_SIGNAL"
    )


def test_positive_signal_from_wrong_race_is_not_staged():
    race = doc()
    event = {"race_number": 7, "horse_number": 2, "horse_name": "Lesja Loke",
             "evidence": {"isScratched": True}}
    stage_unverified_positive_scratch_signals(race, [event])
    assert race["scratch_signal_candidates"] == []
    assert race["qa"]["scratch_verification"] == "UNVERIFIED_NO_POSITIVE_SIGNAL"
    assert all(h["scratched"] is None for h in race["entrants"])


def test_full_field_reconciliation_promotes_scratch_only_after_checks():
    race = doc()
    event = {"race_number": 6, "horse_number": 2,
             "horse_name": "Lesja Loke", "evidence": {"isScratched": True}}
    stage_unverified_positive_scratch_signals(race, [event])
    result = reconcile_startlist([race], starts(), captured_at="2026-11-01T06:19:20Z")
    assert result["status"] == "MATCHED_AS_OF_SNAPSHOT"
    assert result["horses_verified"] == 2
    assert result["confirmed_scratches"] == 1
    assert race["entrants"][0]["scratched"] is False
    assert race["entrants"][1]["scratched"] is True
    assert race["entrants"][1]["scratch_state"] == "SCRATCHED_AS_OF_SNAPSHOT"
    assert race["qa"]["scratches_complete_as_of_snapshot"] is True
    assert race["scratch_signal_candidates"][0]["verification"] == (
        "UNVERIFIED_POSITIVE_SIGNAL"
    )


def test_extra_malformed_startlist_race_cannot_disappear_from_denominator():
    race = doc()
    stage_unverified_positive_scratch_signals(race, [])
    source = starts()
    source["result"]["7"] = {"error": "unrecognized shape"}
    output = reconcile_startlist([race], source)
    assert output["status"] == "UNVERIFIED"
    assert output["verified_race_numbers"] == []
    assert output["mismatches"] == [{
        "code": "UNRECOGNIZED_STARTLIST_RACE_KEYS", "keys": ["7"],
    }]
    assert all(h["scratched"] is None for h in race["entrants"])


def test_alias_race_key_zero_padded_cannot_hide_second_api_race():
    race = doc()
    stage_unverified_positive_scratch_signals(race, [])
    source = starts()
    source["result"]["06"] = list(source["result"]["6"])
    output = reconcile_startlist([race], source)
    assert output["status"] == "UNVERIFIED"
    assert output["mismatches"] == [{
        "code": "UNRECOGNIZED_STARTLIST_RACE_KEYS", "keys": ["06"],
    }]
    assert all(h["scratch_state"] == "UNVERIFIED" for h in race["entrants"])


def test_row_declared_race_number_conflict_blocks_matching_program_number():
    race = doc()
    stage_unverified_positive_scratch_signals(race, [])
    source = starts()
    source["result"]["6"][1]["raceNumber"] = 7
    output = reconcile_startlist([race], source)
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"
    assert output["race_matches"] == 0
    assert output["mismatches"][0]["code"] == "HORSE_NUMBER_OR_FLAG_MISMATCH"
    assert output["mismatches"][0]["malformed_api_rows"] is True
    assert all(h["scratched"] is None for h in race["entrants"])


def test_row_declared_race_number_malformed_type_fails_closed():
    race = doc()
    stage_unverified_positive_scratch_signals(race, [])
    source = starts()
    source["result"]["6"][0]["raceNumber"] = "6"
    output = reconcile_startlist([race], source)
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"
    assert output["verified_race_numbers"] == []


def test_blank_name_in_startlist_not_matching_empty_identity():
    race = doc()
    race["entrants"][0]["name"] = "!!!"
    stage_unverified_positive_scratch_signals(race, [])
    source = starts()
    source["result"]["6"][0]["horseName"] = "!!!"
    output = reconcile_startlist([race], source)
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"
    assert output["horses_verified"] == 0
    assert all(h["scratched"] is None for h in race["entrants"])


def test_all_runner_scratched_anomaly_does_not_confirm_scratch():
    race = doc()
    event = {"race_number": 6, "horse_number": 2,
             "evidence": {"isScratched": True}}
    stage_unverified_positive_scratch_signals(race, [event])
    source = starts()
    source["result"]["6"][0]["isScratched"] = True
    output = reconcile_startlist([race], source)
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"
    assert output["confirmed_scratches"] == 0
    assert race["qa"]["scratch_verification"] == "UNVERIFIED_ALL_RUNNERS_FLAGGED"
    assert all(h["scratched"] is None for h in race["entrants"])


def test_unknown_pdf_race_number_source_blocks_full_field_identity():
    race = doc()
    race["race"].pop("race_number_source")
    stage_unverified_positive_scratch_signals(race, [])
    output = reconcile_startlist([race], starts())
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"
    assert output["verified_race_numbers"] == []
    assert output["mismatches"] == [{
        "code": "PDF_PHYSICAL_RACE_NUMBER_SOURCE_UNVERIFIED", "race": 6,
    }]
    assert all(h["scratched"] is None for h in race["entrants"])


def test_unrecognized_pdf_race_number_source_blocks_even_matching_field():
    race = doc()
    race["race"]["race_number_source"] = "from_api_not_pdf"
    stage_unverified_positive_scratch_signals(race, [])
    output = reconcile_startlist([race], starts())
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"
    assert output["race_matches"] == 0
    assert output["mismatches"][0]["code"] == "PDF_PHYSICAL_RACE_NUMBER_SOURCE_UNVERIFIED"


def test_duplicate_normalized_names_never_certify_unique_horse_identity():
    race = doc()
    race["entrants"][1]["name"] = "SKJETNE LARA"
    stage_unverified_positive_scratch_signals(race, [])
    source = starts()
    source["result"]["6"][1]["horseName"] = "Skjetne Lara"
    output = reconcile_startlist([race], source)
    assert output["status"] == "PARTIAL_OR_UNVERIFIED"
    assert output["verified_race_numbers"] == []
    assert output["confirmed_scratches"] == 0
    assert output["mismatches"] == [{
        "code": "AMBIGUOUS_DUPLICATE_HORSE_IDENTITY", "race": 6,
        "normalized_names": ["skjetnelara"],
    }]
    assert race["qa"]["identity_verification"] == "UNVERIFIED_DUPLICATE_HORSE_NAMES"
    assert all(h["scratched"] is None for h in race["entrants"])


def test_distinct_original_horse_names_continue_to_verify_snapshot():
    race = doc()
    stage_unverified_positive_scratch_signals(race, [])
    result = reconcile_startlist([race], starts())
    assert result["status"] == "MATCHED_AS_OF_SNAPSHOT"
    assert result["race_matches"] == 1

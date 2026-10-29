"""Composite X1/V4 regression tests; fail-closed and no BET promotion."""
from copy from collector.composite_audit import audit_composite_lineage


def _starts(meeting, races):
    return {"success": True, "result": {
        str(number): [
            {"raceNumber": number, "startNumber": n, "horseName": horse,
             "horseRegistrationNumber": f"REG-{number}-{n}",
             "isScratched": scratched, "raceKey": f"{meeting}#{number}"}
            for n, horse, scratched in rows]
        for number, rows in races.items()}}


def _pdf(races):
    return [{"race": {"race_number": number},
             "entrants": [{"program_number": n, "name": horse.upper()}
                          for n, horse, _ in rows]}
            for number, rows in races]


# Public archived 2026-10-29 X1 lineage: product 1/2/3/4 maps to
# Bergen 7 / Åby 9 / Bergen 8 / Åby 10. Entrant examples are grounded in
# the official captured source, but reduced to two per race for unit tests.
# Full historical 37-runner coverage is checked separately against the artifact.
X1 = "X1_NR_2026-10-29"
BT = "BT_NR_2026-10-29"
S2 = "S2_NR_2026-10-29"
PHYSICAL = {
    BT: {
        7: [(1, "Silkesvarta", False), (2, "Eldur", False)],
        8: [(1, "Mykle Kongen", False), (2, "Madla Lynet", False)],
    },
    S2: {
        9: [(1, "Here's Johnny", False), (5, "Fantasy Sensation", True)],
        10: [(1, "Quentin de Veluwe", False), (2, "Doyle Brunson", False)],
    },
}
COMPOSITE = {
    1: PHYSICAL[BT][7], 2: PHYSICAL[S2][9],
    3: PHYSICAL[BT][8], 4: PHYSICAL[S2][10],
}


def _sources():
    return {meeting: {"starts": _starts(meeting, races),
                      "pdf_audit_status": "MATCHED_AS_OF_SNAPSHOT"}
            for meeting, races in PHYSICAL.items()}


def test_exact_full_field_lineage_is_diagnostic_only():
    pdf_races = _pdf([(7, COMPOSITE[1]), (9, COMPOSITE[2]),
                      (8, COMPOSITE[3]), (10, COMPOSITE[4])])
    audit = audit_composite_lineage(X1, _starts(X1, COMPOSITE), pdf_races, _sources())
    assert audit["status"] == "MATCHED_TO_PHYSICAL_PDF_SNAPSHOTS"
    assert audit["reason"] is None
    assert [(a["product_leg"], a["physical_meeting_id"],
             a["physical_race_number"]) for a in audit["legs"]] == [
                 (1, BT, 7), (2, S2, 9), (3, BT, 8), (4, S2, 10)]
    assert audit["date_coverage_verified"] is False
    assert audit["win_market_verified"] is False
    assert audit["bet_authorized"] is False


def test_different_scratch_flag_is_not_approved():
    sources = _sources()
    sources[S2]["starts"]["result"]["9"][1]["isScratched"] = False
    audit = audit_composite_lineage(
        X1, _starts(X1, COMPOSITE), _pdf([(7, COMPOSITE[1]), (9, COMPOSITE[2]),
                                         (8, COMPOSITE[3]), (10, COMPOSITE[4])]),
        sources)
    assert audit["status"] == "BLOCKED"
    assert audit["legs"][1]["reason"] == "NO_EXACT_PHYSICAL_MATCH"


def test_partial_field_overlap_never_proves_full_field():
    sources = _sources()
    sources[BT]["starts"]["result"]["7"].pop()
    audit = audit_composite_lineage(
        X1, _starts(X1, COMPOSITE), _pdf([(7, COMPOSITE[1]), (9, COMPOSITE[2]),
                                         (8, COMPOSITE[3]), (10, COMPOSITE[4])]),
        sources)
    assert audit["status"] == "BLOCKED"
    assert audit["legs"][0]["reason"] == "NO_EXACT_PHYSICAL_MATCH"


def test_ambiguous_physical_match_is_blocked():
    sources = _sources()
    sources["OTHER_NR_2026-10-29"] = {
        "starts": _starts("OTHER_NR_2026-10-29", {7: COMPOSITE[1]}),
        "pdf_audit_status": "MATCHED_AS_OF_SNAPSHOT"}
    audit = audit_composite_lineage(
        X1, _starts(X1, COMPOSITE), _pdf([(7, COMPOSITE[1]), (9, COMPOSITE[2]),
                                         (8, COMPOSITE[3]), (10, COMPOSITE[4])]),
        sources)
    assert audit["status"] == "BLOCKED"
    assert audit["legs"][0]["reason"] == "AMBIGUOUS_PHYSICAL_MATCH"


def test_unreconciled_physical_pdf_is_not_evidence():
    sources = _sources()
    sources[BT]["pdf_audit_status"] = "COMPOSITE_OR_UNAVAILABLE"
    audit = audit_composite_lineage(
        X1, _starts(X1, COMPOSITE), _pdf([(7, COMPOSITE[1]), (9, COMPOSITE[2]),
                                         (8, COMPOSITE[3]), (10, COMPOSITE[4])]),
        sources)
    assert audit["status"] == "BLOCKED"
    assert audit["legs"][0]["reason"] == "NO_EXACT_PHYSICAL_MATCH"


def test_pdf_number_mismatch_blocks_even_when_fields_match():
    audit = audit_composite_lineage(
        X1, _starts(X1, COMPOSITE), _pdf([(3, COMPOSITE[1]), (9, COMPOSITE[2]),
                                         (8, COMPOSITE[3]), (10, COMPOSITE[4])]),
        _sources())
    assert audit["status"] == "BLOCKED"
    assert audit["legs"][0]["reason"] == "PDF_PHYSICAL_RACE_NUMBER_MISMATCH"


def test_duplicate_pdf_field_blocks_ambiguous_pdf_mapping():
    audit = audit_composite_lineage(
        X1, _starts(X1, COMPOSITE), _pdf([(7, COMPOSITE[1]), (7, COMPOSITE[1]),
                                         (9, COMPOSITE[2]), (8, COMPOSITE[3]),
                                         (10, COMPOSITE[4])]), _sources())
    assert audit["status"] == "BLOCKED"
    assert audit["legs"][0]["reason"] == "AMBIGUOUS_COMPOSITE_PDF_MATCH"


def test_missing_composite_leg_blocks_complete_mapping():
    audit = audit_composite_lineage(
        X1, _starts(X1, {1: COMPOSITE[1], 2: COMPOSITE[2]}),
        _pdf([(7, COMPOSITE[1]), (9, COMPOSITE[2]),
              (8, COMPOSITE[3]), (10, COMPOSITE[4])]),
        _sources())
    assert audit["status"] == "BLOCKED"
    assert audit["reason"] == "COMPOSITE_PDF_LEG_COVERAGE_MISMATCH"


def test_missing_explicit_scratch_boolean_fails_closed():
    starts = _starts(X1, COMPOSITE)
    del starts["result"]["1"][0]["isScratched"]
    audit = audit_composite_lineage(X1, starts, _pdf([(7, COMPOSITE[1])]), _sources())
    assert audit["status"] == "BLOCKED"
    assert audit["reason"] == "COMPOSITE_STARTLIST_UNVERIFIED"


def test_wrong_race_key_fails_closed():
    starts = _starts(X1, COMPOSITE)
    starts["result"]["1"][0]["raceKey"] = f"{BT}#7"
    audit = audit_composite_lineage(X1, starts, _pdf([(7, COMPOSITE[1])]), _sources())
    assert audit["status"] == "BLOCKED"
    assert audit["reason"] == "COMPOSITE_STARTLIST_UNVERIFIED"

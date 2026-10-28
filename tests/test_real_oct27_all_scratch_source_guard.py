"""Real archived 27 Oct Gelsenkirchen source anomaly, not simulated score data.

Original Collector daily run 40487116264 / artifact 12726250010.
Original PDF SHA256:
1cd2d2dee7dc29ca53c11d851bf09cac37a6ae95ebea5c0d37128707fb040797
Original /starts JSON SHA256:
a85d4cd711057bddc7f446b85df4571aee976fbaf6eec777d28f997044e6d71d

All API isScratched=true on 5/5 and 8/8 runners for races 6 and 7.
Independent public racing results show both races ran (not a 13-horse
confirmed withdrawal):
https://turfma.com/pmu-resultats-du-jour/gelsenkirchen-r2c6-27-10-2026/
https://www.geny.com/course/1693830-2026-10-27-gelsenkirchen-auf-wiedersehen-am-8-11-im-gelsentrabpark/arrivee-rapports

This regression reproduces exact archived public horse identities and flags
in a minimal fixture. It cannot independently certify the true per-horse
scratch state at the earlier archive time.
"""
from collector.startlist_audit import reconcile_startlist

ORIGINAL = {
    6: ["Messi Hazelaar", "Okura Greenwood", "Walkoffame Diamant",
        "Klaus Von Herten", "Purple Rain"],
    7: ["Ronettes Boko", "Jamy Chess", "Hela Br", "Isusa",
        "Nothello Tf", "Zampano", "Silberlowe", "Speedys Opaline"],
}


def _pdf_sections():
    return [
        {
            "race": {"race_number": race},
            "entrants": [
                {"program_number": i, "name": name.upper(),
                 "scratched": False, "scratch_state": "UNVERIFIED"}
                for i, name in enumerate(names, 1)
            ],
            "scratches": [],
            "qa": {"warnings": ["SCRATCHES_UNVERIFIED", "PDF_SNAPSHOT_NOT_LIVE"],
                   "scratched_count": None, "active_count": None},
        }
        for race, names in ORIGINAL.items()
    ]


def _archived_source_flags():
    return {
        "success": True,
        "result": {
            str(race): [
                {"raceNumber": race, "startNumber": i, "horseName": name,
                 "isScratched": True}
                for i, name in enumerate(names, 1)
            ]
            for race, names in ORIGINAL.items()
        },
    }


def test_real_gelsenkirchen_complete_field_true_flags_cannot_verify_scratches():
    docs = _pdf_sections()
    audit = reconcile_startlist(
        docs, _archived_source_flags(),
        captured_at="2026-10-27T10:17:19.154400+00:00",
    )
    assert audit["status"] == "PARTIAL_OR_UNVERIFIED"
    assert audit["race_numbers_match"] is True
    assert audit["race_matches"] == 0
    assert audit["horses_verified"] == 0
    assert audit["confirmed_scratches"] == 0
    assert sorted(m["race"] for m in audit["mismatches"]) == [6, 7]
    assert {m["code"] for m in audit["mismatches"]} == {
        "ALL_RUNNERS_SCRATCH_FLAG_REQUIRES_INDEPENDENT_CONFIRMATION",
    }
    assert sum(m["raw_flagged_runner_count"] for m in audit["mismatches"]) == 13
    for doc in docs:
        assert all(h["scratched"] is None for h in doc["entrants"])
        assert all(
            h["scratch_state"] == "UNKNOWN_ALL_RUNNERS_FLAGGED"
            for h in doc["entrants"]
        )
        assert len(doc["raw_scratch_flag_candidates"]) == len(doc["entrants"])
        assert all(x["isScratched_raw"] is True for x in doc["raw_scratch_flag_candidates"])
        assert doc["qa"]["scratch_verification"] == "UNVERIFIED_ALL_RUNNERS_FLAGGED"
        assert doc["qa"]["scratches_complete_as_of_snapshot"] is False
        assert doc["qa"]["active_count"] is None
        assert doc["qa"]["scratched_count"] is None
        assert "ALL_RUNNERS_SCRATCH_FLAG_REVIEW" in doc["qa"]["warnings"]
        assert doc["scratches"] == []


def test_a_real_race_with_one_active_and_one_positive_flag_still_verifies():
    # Negative control: conservative anomaly guard does not disable normal
    # source-backed mixed fields or change unrelated races.
    docs = _pdf_sections()
    race6 = docs[0]
    race6["entrants"] = race6["entrants"][:2]
    response = _archived_source_flags()
    response["result"] = {"6": response["result"]["6"][:2]}
    response["result"]["6"][0]["isScratched"] = False
    result = reconcile_startlist([race6], response)
    assert result["status"] == "MATCHED_AS_OF_SNAPSHOT"
    assert result["race_matches"] == 1
    assert result["confirmed_scratches"] == 1
    assert race6["entrants"][0]["scratch_state"] == "ACTIVE_AS_OF_SNAPSHOT"
    assert race6["entrants"][1]["scratch_state"] == "SCRATCHED_AS_OF_SNAPSHOT"

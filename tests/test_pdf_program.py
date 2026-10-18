"""Offline regression tests for dated extended program parsing."""
from collector.pdf_program import parse_extended_pdf


SAMPLE = """1
TRIPPEL TVILLING VINNER PLASS
2300m Voltestart Kaldblods. For 3-15-årige.
START KL. 17:53
1 FIRST HORSE, Per A. Eggan cc / Va
5-års brun h e Some Sire
Tr: Trainer Ei: Owner Op: Breeder
2026: 4-1-1-1 Tot: 4-1-1-1
Pe Egg OA 01.10.26-3|2 1 1 2300 30,0
Pe Egg OA 12.09.26-2|1 1 2 2300 30,1
2 SECOND HORSE, Tom H. Solberg cc / Va
6-års svart v e Sire
Tr: Another Trainer Ei: Owner
2026: 1-0-0-0 Tot: 1-0-0-0
Tom Sol OA 05.10.26-5|2 7 0 2300 31,0
Varig Orkla 18.10.2026 Utvidet - rikstoto.no Utskriftstidspunkt: 18.10.2026, 11:31 Side: 1 av 2

V65-1
TRIPPEL TVILLING VINNER PLASS
DELINGSLØP Løp 2
1720m Voltestart Kaldblods. Premier: 16000 kr.
START KL. 18:15
1 THIRD HORSE, Johan Driver cc / Va
4-års brun hp e Another Sire
Tr: Trainer Ei: Owner
2026: 1-1-0-0 Tot: 1-1-0-0
Joh D OA 07.10.26-6|1 1 1 1720 29,9
Varig Orkla 18.10.2026 Utvidet - rikstoto.no Utskriftstidspunkt: 18.10.2026, 11:31 Side: 2 av 2
"""


def parsed(text=SAMPLE):
    return parse_extended_pdf(
        text, meeting_id="OR_NR_2026-10-18", date="2026-10-18",
        url="https://www.rikstoto.no/api/programdownload/ProgramPdf/Utvidet/OR_NR_2026-10-18",
        captured_at="2026-10-18T09:00:00Z")


def test_full_program_two_races_and_three_horses():
    result = parsed()
    assert result["qa"]["race_numbers"] == [1, 2]
    assert result["qa"]["horses"] == 3
    assert result["qa"]["history_rows"] == 4
    assert [r["race"]["scheduled_time_local"] for r in result["races"]] == ["17:53", "18:15"]


def test_race_history_and_numbers_preserved():
    first = parsed()["races"][0]
    assert [h["program_number"] for h in first["entrants"]] == [1, 2]
    assert [h["name"] for h in first["entrants"]] == ["FIRST HORSE", "SECOND HORSE"]
    assert first["entrants"][0]["past_starts"][0]["date"] == "2026-10-01"
    assert len(first["entrants"][0]["past_starts"]) == 2
    assert first["race"]["distance_m"] == 2300


def test_scratchings_are_explicitly_unverified_by_pdf():
    docs = parsed()["races"]
    assert all("SCRATCHES_UNVERIFIED" in d["qa"]["warnings"] for d in docs)
    assert all(d["qa"]["active_count"] is None for d in docs)
    assert all(h["scratch_state"] == "UNVERIFIED" for d in docs for h in d["entrants"])


def test_wrong_date_is_rejected():
    output = parse_extended_pdf(SAMPLE, meeting_id="OR_NR_2026-10-19",
        date="2026-10-19", url="https://www.rikstoto.no/", captured_at="2026-10-18T09:00:00Z")
    assert output["races"] == []
    assert "PDF_DATE_MISMATCH" in output["qa"]["warnings"]

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
    assert result["races"][0]["race"]["race_number_source"] == "pdf_heading_number"
    assert result["races"][1]["race"]["race_number_source"] == "pdf_heading"
    assert "RACE_NUMBER_ORDER_INFERRED" not in result["qa"]["warnings"]


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


def test_swedish_appended_start_markers_do_not_lose_races():
    text = """1
Løp 1
2140m Voltestart Swedish program description Hederspris.START KL. 14:00
1 NORD SMARAGD, Christian Månsson cc / Va
3-års hp e Tekno Odin
Tr: Trainer Ei: Owner
2026: 1-0-0-0 Tot: 1-0-0-0
Lun Hu Ly 30.06.26-1|6 6 d 2140 ug
Skellefteå 18.10.2026 Utvidet - rikstoto.no Side: 1 av 2
2
Løp 2
1640m Autostart Trophy winner will receive.START KL. 14:22
1 TEST WINNER, Another Driver
4-års v e Some Horse
Tr: Trainer Ei: Owner
2026: 1-1-0-0 Tot: 1-1-0-0
Test Dr Ly 07.10.26-2|4 1 1 1640 12,0
Skellefteå 18.10.2026 Utvidet - rikstoto.no Side: 2 av 2
"""
    result = parsed(text)
    assert result["qa"]["race_sections"] == 2
    assert result["qa"]["race_numbers"] == [1, 2]
    assert result["qa"]["horses"] == 2
    assert result["qa"]["history_rows"] == 2


def test_gallop_prior_starts_do_not_require_pipe():
    text = """1
Prix De La Chapelle
1800m For fillies aged 2. AVERAGE TRACK.START KL. 15:15
1 SHOLPANA (FR), C.Demuro 58 Ft
2-års brun hp e Some Sire
Tr: M.Baratti Ei: Owner
2026: 4-0-0-1 Tot: 4-0-0-1
Ca Lop Du 02.01.26-7 3 1400 dt Rask 13-m
Ca Lop Jä 07.06.26-7 7 1730 dt God
Parislongchamp 18.10.2026 Utvidet - rikstoto.no Side: 1 av 1
"""
    result = parsed(text)
    assert result["qa"]["race_numbers"] == [1]
    assert result["qa"]["horses"] == 1
    assert result["qa"]["history_rows"] == 2
    assert result["races"][0]["entrants"][0]["past_starts"][0]["race_number"] == 7


def test_composite_program_preserves_actual_race_numbers_not_order():
    text = """V4-1
Jakt.se Løp 10
1640m Autostart Prize. START KL. 17:08
1 FRODO DE CASTELLA, Julian Cordeau
7-års brun v
Tr: Owner
2026: 1-1-0-0 Tot: 1-1-0-0
Cor Ju Ax 12.10.26-3|1 1 1 1640
V4-2
Løp 1
2300m Voltestart. START KL. 17:53
1 LANGLANDS SINDY, Per Arne Eggan
8-års brun hp
Tr: Owner
2026: 1-1-0-0 Tot: 1-1-0-0
Pe Egg OA 28.09.26-1|3 6 5 2300
V4 Xpress 18.10.2026 Utvidet - rikstoto.no Side: 1 av 1
"""
    result = parsed(text)
    assert result["qa"]["race_numbers"] == [1, 10]
    assert [race["race"]["race_number"] for race in result["races"]] == [10, 1]


def test_unlabeled_race_keeps_inferred_provenance():
    unlabeled = SAMPLE.replace("1\nTRIPPEL", "TRIPPEL", 1)
    result = parsed(unlabeled)
    assert result["races"][0]["race"]["race_number_source"] == "pdf_order_inferred"
    assert "RACE_NUMBER_ORDER_INFERRED" in result["qa"]["warnings"]

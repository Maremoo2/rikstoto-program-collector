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


def test_dotted_initials_horse_name_JC():
    text = ("Løp 4\n1640m Autostart START KL. 20:30\n"
            "5 FEARLESS FLIER, Gustav Johansson\n"
            "6 J.C., Thomas Dalborg\n"
            "7 ORACLE VIXI, Victor Rosleff\n"
            "Mantorp 19.10.2026 Utvidet - rikstoto.no Side: 1 av 1\n")
    parsed = parse_extended_pdf(text, meeting_id="S2_NR_2026-10-19", date="2026-10-19",
                                url="official-source", captured_at="2026-10-18T21:27:01Z")
    assert [(h["program_number"], h["name"]) for h in parsed["races"][0]["entrants"]] == [
        (5, "FEARLESS FLIER"), (6, "J.C."), (7, "ORACLE VIXI")]


# Source-anchored heading excerpts from ORIGINAL archived Rikstoto PDFs.
# 27 Oct X1: run 40487116264, PDF SHA256:
# 7663dc0fdcc01e8efd6e5a173dc052059c1ca70293075ce991a5da819d8ec452
# 31 Oct X1: run 41175937425, PDF SHA256:
# 7b9d6533a910b72a90f12bc6eb30f6c6fe87c741de181aac959ec46f109ad36e
# These are selected exact printed heading lines, not complete-PDF proof.
def test_original_xpress_bjerke_gavle_joined_race_12_not_ordinal_two():
    source_excerpt = """V4-1
AXEL JENSENS MINNELØP Løp 11
1609m Autostart Varmblods. AXEL JENSENS MINNELØP
START KL. 17:16
1 GOODBYE KISS* (IT), Christoffer Eriksson
4-års brun v e Nad Al Sheba
Tr: Linda Tovek
V4-2
STL STODIVISIONEN / RADIO METRO-LØPET - SPORTRAPP / GRUNNLAG - 15 BAK BILENLøp 12
2600m Autostart Varmblods. STL STODIVISIONEN
START KL. 17:38
1 EYE TO EYE* (S), Carl Johan Jepson
4-års brun hp e Readly Express
Tr: David Persson
Bjerke/Gävle 31.10.2026 Utvidet - rikstoto.no Side: 1 av 5
"""
    result = parse_extended_pdf(source_excerpt, meeting_id="X1_NR_2026-10-31",
                                date="2026-10-31", url="archive:41175937425",
                                captured_at="2026-10-31T06:17:30+00:00")
    assert [d["race"]["race_number"] for d in result["races"]] == [11, 12]
    assert all(d["race"]["race_number_source"] == "pdf_heading" for d in result["races"])
    assert "RACE_NUMBER_ORDER_INFERRED" not in result["qa"]["warnings"]
    assert "DUPLICATE_RACE_IDS" not in result["qa"]["warnings"]


def test_original_xpress_axevalla_joined_race_7_not_ordinal_two():
    source_excerpt = """V75-1
Løp 5
1609m Autostart Varmblods.
START KL. 20:25
1 FOLLOWTHATDREAM E.P., Driver Ab
4-års brun h e Example
Tr: Trainer
V75-2
B-tränarlopp - Ladugårdsinredes Lärlings-/Amatörserie - Omgång 15 - K150Løp 7
2140m Voltestart B-tränarlopp - Ladugårdsinredes Lärlings-/Amatörserie
Tillägg 20 m vid vunna 230.001 kr Pris: 40.000 kr START KL. 20:36
1 ASTON R.C., Isabelle Arvidsson
8-års brun v e Example
Tr: Isabelle Arvidsson
Bjerke/Axevalla 27.10.2026 Utvidet - rikstoto.no Side: 1 av 9
"""
    result = parse_extended_pdf(source_excerpt, meeting_id="X1_NR_2026-10-27",
                                date="2026-10-27", url="archive:40487116264",
                                captured_at="2026-10-27T10:16:30+00:00")
    assert [d["race"]["race_number"] for d in result["races"]] == [5, 7]
    assert all(d["race"]["race_number_source"] == "pdf_heading" for d in result["races"])
    assert "RACE_NUMBER_ORDER_INFERRED" not in result["qa"]["warnings"]

"""DATA-005: original PDF-layout gold regressions (not a random accuracy sample).

These independent expected values were read from 7 Nov Rikstoto expanded-PDF
source columns, NOT from existing Collector structured_program.json.
FR/DE joined dates remain deliberately unparsed beyond date/race.
"""
from collector.pdf_program import parse_extended_pdf


def parse(section: str, *, meeting: str = "S1_NR_2026-11-07"):
    return parse_extended_pdf(
        f"""Løp 5
1640m Autostart
START KL. 15:00
3 WARHOL, Mats Pettersson
2026: 12-2-0-1
{section}
Bergsåker 07.11.2026 Utvidet - rikstoto.no Side: 7 av 18
""",
        meeting_id=meeting, date="2026-11-07",
        url="official-pdf-source:2026-11-07",
        captured_at="2026-11-07T06:18:23+00:00",
    )["races"][0]["entrants"][0]["past_starts"]


def test_five_independently_read_swedish_history_rows():
    rows=parse("""Lil Ma
Ös 07.08.26-8|9 9
7
2140 14,8a
301
81' cc
Sve He
D
16.08.26-6|6 6
1
2140 13,7
34
27' ¢¢
Sve He
D
06.09.26-9|2 9
d
2160 p3g
36
27' ¢¢
Sve He
Sä 05.10.26-3|3 3
4
2140 14,0
144
38' ¢¢
Sve He
B
28.10.26-7|3 3
2
1640 11,2a
324
65' ¢¢""")
    assert len(rows)==5
    assert [(r["date"],r["race_number"]) for r in rows] == [
        ("2026-08-07",8),("2026-08-16",6),("2026-09-06",9),
        ("2026-10-05",3),("2026-10-28",7),
    ]
    assert [x["track"] for x in rows] == ["Ös","D","D","Sä","B"]
    assert [x["placing"] for x in rows] == ["7","1","d","4","2"]
    assert [x["distance_m"] for x in rows] == [2140,2140,2160,2140,1640]
    assert [x["kilometre_time"] for x in rows] == [
        "14,8a","13,7",None,"14,0","11,2a",
    ]
    assert rows[2]["disqualification_marker"] is True
    assert rows[0]["post"] is None
    assert rows[0]["cell_contract"]=="NORDIC_SOURCE_TEXT_PARTIAL_NOT_OFFICIAL_RESULT"


def test_norwegian_original_disqualification_trial_and_missing_place():
    rows=parse("""Es Sch
BI 10.06.26-20|14
P
2140 39,8
P
0' cc
Es Sch
AR 25.07.26-1|5 5
7
2100 36,5 g
191
0'
Es Sch
AR 02.08.26-1|5 5
-
1700 dg
49
0'
Kal PV
ST 21.08.25-21|22
1640 55,0 g
N
0' cc""",
       meeting="KL_NR_2026-11-07")
    assert len(rows)==4
    assert rows[0]["placing"]=="P"
    assert rows[1]["track"]=="AR"
    assert rows[1]["kilometre_time"]=="36,5g"
    assert rows[1]["gallop_marker"] is True
    assert rows[2]["placing"]=="-"
    assert rows[2]["distance_m"]==1700
    assert rows[2]["kilometre_time"] is None
    assert rows[2]["disqualification_marker"] is True
    assert rows[3]["placing"] is None
    assert rows[3]["distance_m"]==1640
    assert rows[3]["kilometre_time"]=="55,0g"


def test_compact_german_historic_row_does_not_shift_nordic_columns():
    rows=parse("""OPPOLI SARAD9519.07.26-6|7 7 2 2100 18,0a 36.8
BERGMANN JENSGEL26.08.26-5|5 5 5 2025 17,2""")
    assert len(rows)==2
    assert all(r["placing"] is None and r["kilometre_time"] is None for r in rows)
    assert all(r["distance_m"] is None for r in rows)


def test_missing_place_is_not_promoted_to_a_false_position():
    rows=parse("""Kal PV
ST 21.08.25-21|22
1640 55,0 g
N
0' cc""")
    assert len(rows)==1
    assert rows[0]["placing"] is None
    assert rows[0]["distance_m"]==1640
    assert rows[0]["disqualification_marker"] is None


def test_malformed_column_do_not_guess_distance_or_odds():
    rows=parse("""Vik Ma
B 28.10.26-7|3 3
n/a
abc nonsense
unknown
???""")
    assert len(rows)==1
    assert rows[0]["distance_m"] is None
    assert rows[0]["placing"] is None
    assert rows[0]["kilometre_time"] is None
    assert rows[0]["cell_contract"]=="NORDIC_PARTIAL_LAYOUT"

"""Original-PDF-anchored Odense L D regression (Collector P0, 23 Oct 2026).

Provenance: Daily Collector run #39904889503, artifact #12480651523,
S3_NR_2026-10-23/full_program.pdf, printed Odense page 9 of 11.
Full PDF SHA-256:
432e795e7ff3965804c26989ccb4f91e5fc6ef5da406415cc3b5dcf72b4e8d7c

The snippet is manually checked against that original page; it is not a
substitute for an independent full-card source-readiness check.
"""
from collector.pdf_program import parse_extended_pdf


ODENSE_SOURCE_EXCERPT = """9
Løp 9
2140m Voltestart
2-14-åriga högst 27.000 DKK.
START KL. 00:00
5 LEIKA TIME, Nicklas Korfitsen
4-års mörkbrun hp e Tobin Kronos - Aparte e Coktail Jet
Tr: Nicklas Korfitsen Ei: Stald Saltum Op: Stald Saltum
Ma Hen  Ål  20.10.25-2|7 10  0   2160  20,5g    85   11' cc  Va
Ni Kor   Ål  24.12.25-7|2 10  0   2160  18,7g   112   11' cc  Va
Ma Hen  Ål  13.08.26-7|5 8   0   2160  22,9g   109   15' cc  Va
Ni Kor   Ål  11.09.26-2|5 9   2   2160  17,9     85   15' cc  Va
Ni Kor   Ål  01.10.26-7|3 6   1   2160  17,7     19   15' cc  Va
6 L D, Mathias Jensen
4-års mörkbrun v e Gentle Tilly - Quite A Beauty e Earthquake
Tr: Kaj Jensen Ei: Jeanette H. Jensen Op: Kaj Jensen
Ma Jen  Aa 15.08.26-1|3 9   0   1820  19,1g  1310   15' c¢  Va
Ma Jen  Aa 12.09.26-1|2 5   2   1820  17,9    187   15' cc  Va
Ma Jen  Ål  24.09.26-2|3 3   1   2140 17,1ag   57     9' cc  Va
Ma Jen  Aa 03.10.26-7|6 6   2   1800  16,7a    37   23' cc  Va
Ma Jen  Aa 15.10.26-3|3 3   d   1800 ga      43   15' cc  Va
Odense 23.10.2026 Utvidet - rikstoto.no Side: 9 av 11
"""


def test_real_odense_ld_initials_preserve_five_history_rows_under_right_horse():
    report = parse_extended_pdf(
        ODENSE_SOURCE_EXCERPT,
        meeting_id="S3_NR_2026-10-23",
        date="2026-10-23",
        url="original-archive:12480651523/S3_NR_2026-10-23/full_program.pdf",
        captured_at="2026-10-23T05:20:00Z",
        track="Odense",
    )
    assert report["qa"]["race_sections"] == 1
    assert report["qa"]["history_rows"] == 10
    assert report["qa"]["horses"] == 2
    race = report["races"][0]
    assert race["race"]["race_number"] == 9
    assert race["race"]["scheduled_time_local"] == "00:00"
    assert race["race"]["start_method"] == "Voltestart"
    assert [(horse["program_number"], horse["name"]) for horse in race["entrants"]] == [
        (5, "LEIKA TIME"),
        (6, "L D"),
    ]
    assert len(race["entrants"][0]["past_starts"]) == 5
    ld = race["entrants"][1]
    assert ld["driver"].startswith("Mathias Jensen")
    assert len(ld["past_starts"]) == 5
    assert [item["date"] for item in ld["past_starts"]] == [
        "2026-08-15", "2026-09-12", "2026-09-24", "2026-10-03", "2026-10-15"
    ]
    assert any("17,1ag" in item["raw_text"] for item in ld["past_starts"])
    assert any("1800 ga" in item["raw_text"] for item in ld["past_starts"])
    # Program-text structural parsing cannot authorize unverified 00:00 start.
    assert report["qa"]["status"] == "REVIEW_REQUIRED"
    assert race["qa"]["status"] == "REVIEW_REQUIRED"

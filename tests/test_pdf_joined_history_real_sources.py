"""Original-PDF-anchored regression for track+date joined history starts.

27 Oct original F2 NRW-style program SHA-256:
1cd2d2dee7dc29ca53c11d851bf09cac37a6ae95ebea5c0d37128707fb040797
31 Oct original F1 Deauville PDF SHA-256:
1947bc302ab59c355c8da53d078f384345e06f453fbf9a71df2b7c90a0d28ce1
Only date/race are structured; position, odds and timing remain unknown.
"""
from collector.pdf_program import parse_extended_pdf


def _parse(excerpt, day, meeting):
    return parse_extended_pdf(excerpt, meeting_id=meeting, date=day,
                              url="original-archive:excerpt",
                              captured_at=day + "T06:20:00Z")


def test_original_german_harness_program_track_abbreviation_does_not_hide_starts():
    excerpt = """V4-1
Prix Bonjour Lyon Parilly Allemagne Løp 1
2000m Autostart.
START KL. 11:05
1 REMCO VL, Onderwater Kevin
6-års v e Brillantissime
Tr: J. Bergmann
OPPOLI SARAD9519.07.26-6|7 7 2 2100 18,0a 36.8
OPPOLI SARAD9509.08.26-4|2 2 2 2100 17,3a 8.9
BERGMANN JENSGEL26.08.26-5|5 5 5 2025 17,2
2 NADYHA, Will Ben
6-års he e Crazed
Tr: M. Schonlau
SCHONLAU MARCGEL18.09.25-9|4 4 2 2000 16,9a
HOLZSCHUH JOCHED9519.07.26-5|4 4 4 2100 17,5a
Gelsenkirchen 27.10.2026 Utvidet - rikstoto.no Side: 1 av 8
"""
    result = _parse(excerpt, "2026-10-27", "F2_NR_2026-10-27")
    assert result["qa"]["horses"] == 2
    assert result["qa"]["history_rows"] == 5
    first, second = result["races"][0]["entrants"]
    assert [s["date"] for s in first["past_starts"]] == [
        "2026-07-19", "2026-08-09", "2026-08-26"]
    assert [s["race_number"] for s in first["past_starts"]] == [6, 4, 5]
    assert [s["date"] for s in second["past_starts"]] == ["2025-09-18", "2026-07-19"]
    assert all(s["placing"] is None and s["distance_m"] is None
               for h in (first, second) for s in h["past_starts"])
    assert result["qa"]["status"] == "REVIEW_REQUIRED"


def test_original_french_gallop_attached_date_preserved_without_guessing_time():
    excerpt = """1
Prix Nonoalco
1300m For colts and geldings aged 2.
START KL. 00:00
1 OMARBEK (FR), S.Pasquier 58 Ft
2-års h e Golden Horde
Tr: Ha.Pantall
S.PASQUIERLYO02.09.26-3 11 1350 1:23,33 5 56.50
S.PASQUIERSAI 18.09.26-3 1 1200 1:15,13 8 58
S.PASQUIERCHA07.10.26-2 3 1400 1:25,74 3 58
Deauville 31.10.2026 Utvidet - rikstoto.no Side: 1 av 14
"""
    result = _parse(excerpt, "2026-10-31", "F1_NR_2026-10-31")
    h = result["races"][0]["entrants"][0]
    assert [(s["date"], s["race_number"]) for s in h["past_starts"]] == [
        ("2026-09-02", 3), ("2026-09-18", 3), ("2026-10-07", 2)]
    assert all(s["kilometre_time"] is None for s in h["past_starts"])
    assert "PDF_SNAPSHOT_NOT_LIVE" in result["races"][0]["qa"]["warnings"]


def test_invalid_date_stays_unknown_not_fabricated():
    excerpt = """Løp 1
2140m Voltestart
START KL. 15:05
1 TEST HORSE, Driver Person
4-års brun hp
Tr: Trainer
PERSONGEL99.99.26-4|1 1 1 2140
Gelsenkirchen 27.10.2026 Utvidet - rikstoto.no Side: 1 av 1
"""
    start = _parse(excerpt, "2026-10-27", "F2_NR_2026-10-27")["races"][0]["entrants"][0]["past_starts"]
    assert len(start) == 1
    assert start[0]["date"] is None
    assert "99.99.26" in start[0]["raw_text"]

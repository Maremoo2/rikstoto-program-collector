"""Conservative extraction from Rikstoto extended PDF program text.

PDF text is an auditable snapshot; scratches, live changes and schedule
completeness MUST be verified from separate, time-stamped sources.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

START = re.compile(r"START\s+KL\.?\s*(\d{1,2}:\d{2})", re.I)
RACE = re.compile(r"\bLøp\s+(\d{1,2})\b", re.I)
HORSE = re.compile(r"^\s*(\d{1,2})\s+([^,\n]{2,90}),\s+(.+)$")
# Official program PDFs may join the track abbreviation to the date (GEL26.08.26-5).
# A leading word boundary would silently discard these actual history rows.
HISTORY = re.compile(r"(\d{2}\.\d{2}\.\d{2})-(\d{1,2})(?=\||\s)")
FOOTER = re.compile(r"\bUtvidet\s*-\s*rikstoto\.no\b", re.I)
DISTANCE = re.compile(r"\b(\d{3,4})\s*m\s+(Voltestart|Autostart)\b", re.I)


def _pdf_date(text: str) -> str | None:
    m = re.search(r"\b(\d{2})\.(\d{2})\.(20\d{2})\s+Utvidet\s*-\s*rikstoto\.no", text)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _horse_header(line: str) -> tuple[int, str, str] | None:
    match = HORSE.match(line)
    if not match:
        return None
    number, name, driver = match.groups()
    letters = [c for c in name if c.isalpha()]
    short_initials = bool(re.fullmatch(r'(?:[A-Z]\.){2,}|[A-Z]\s+[A-Z]', name.strip()))
    if (not letters or (len(letters) < 3 and not short_initials)
            or sum(ch.isupper() for ch in letters) / len(letters) < .78):
        return None
    return int(number), name.strip(), driver.strip()


def parse_extended_pdf(text: str, *, meeting_id: str, date: str,
                       url: str, captured_at: str, track: str | None = None) -> dict[str, Any]:
    """Match collector's export schema, keeping uncertain facts unverified.

    Require document date to match requested day. First observed race can be
    headed by a standalone '1'; later races usually have an explicit 'Løp N'.
    """
    pdf_date = _pdf_date(text)
    if pdf_date != date:
        return {"races": [], "qa": {"status": "REVIEW_REQUIRED", "warnings": [
            "PDF_DATE_MISMATCH" if pdf_date else "PDF_DATE_UNVERIFIED"],
            "document_date": pdf_date, "race_sections": 0}}
    lines = text.splitlines()
    # Swedish and French programs append START KL to narrative text.
    indices = [(i, m.group(1), line[:m.start()]) for i, line in enumerate(lines)
               if (m := START.search(line))]
    tracks = re.search(r"^(.+?)\s+\d{2}\.\d{2}\.20\d{2}\s+Utvidet", text, re.M)
    track = track or (tracks.group(1) if tracks else None)
    docs = []
    race_numbers_seen = set()
    for ordinal, (start_index, time, marker_prefix) in enumerate(indices, 1):
        next_start = indices[ordinal][0] if ordinal < len(indices) else len(lines)
        # Source heading may identify race as 'Løp N' or standalone N.
        # Restrict to final header lines; exclude previous race history.
        heading = lines[max(0, start_index - 13):start_index] + [marker_prefix]
        found = [(int(m.group(1)), line) for line in heading
                 if (m := RACE.search(line))]
        if found:
            race_num = found[-1][0]
            number_source = "pdf_heading"
        else:
            standalone = [int(x.strip()) for x in heading
                          if re.fullmatch(r"\s*\d{1,2}\s*", x) and 1 <= int(x.strip()) <= 30]
            if standalone:
                race_num = standalone[-1]
                number_source = "pdf_heading_number"
            else:
                race_num = ordinal
                number_source = "pdf_order_inferred"
        headers = [(i, x) for i in range(start_index + 1, next_start)
                   if (x := _horse_header(lines[i])) is not None]
        entrants: list[dict[str, Any]] = []
        for h_i, (line_index, details) in enumerate(headers):
            end = headers[h_i + 1][0] if h_i + 1 < len(headers) else next_start
            block = [line for line in lines[line_index:end] if not FOOTER.search(line)]
            number, name, driver = details
            breeder = next((x for x in block if x.strip().startswith("Tr:")), None)
            starts = []
            for line in block:
                hist = HISTORY.search(line)
                if not hist:
                    continue
                previous_date, previous_race = hist.groups()
                try:
                    d = datetime.strptime(previous_date, "%d.%m.%y").date().isoformat()
                except ValueError:
                    d = None
                starts.append({"date": d, "race_number": int(previous_race),
                               "post": None, "track": None, "driver_abbrev": None,
                               "starter_number": None, "distance_m": None,
                               "placing": None, "kilometre_time": None,
                               "shoes": None, "wagon": None,
                               "odds_display": None, "prize_display": None,
                               "top_three": None, "raw_text": line, "comment": None})
            entrants.append({"program_number": number, "number_source": "official_pdf",
                             "name": name, "driver": driver, "scratched": False,
                             "scratch_state": "UNVERIFIED", "past_starts": starts,
                             "year_stats": {}, "total_stats": None,
                             "identity_text": next((x for x in block if "-års" in x), None),
                             "trainer_owner_breeder": breeder,
                             "header_text": block[0], "raw_section": "\n".join(block)})
        fmt = next((DISTANCE.search(line) for line in reversed(heading) if DISTANCE.search(line)), None)
        warnings = ["SCRATCHES_UNVERIFIED", "PDF_SNAPSHOT_NOT_LIVE"]
        if number_source == "pdf_order_inferred":
            warnings.append("RACE_NUMBER_INFERRED")
        if not entrants:
            warnings.append("NO_ENTRANTS_PARSED")
        if len({h["program_number"] for h in entrants}) != len(entrants):
            warnings.append("DUPLICATE_PROGRAM_NUMBERS")
        if race_num in race_numbers_seen:
            warnings.append("DUPLICATE_RACE_NUMBER")
        race_numbers_seen.add(race_num)
        if any(not h["past_starts"] for h in entrants):
            warnings.append("SOME_HORSES_NO_PRIOR_STARTS")
        docs.append({"race": {"meeting_id": meeting_id, "race_number": race_num,
                   "race_number_source": number_source, "source_url": url, "track": track,
                   "scheduled_time_local": time,
                   "distance_m": int(fmt.group(1)) if fmt else None,
                   "start_method": fmt.group(2) if fmt else None,
                   "captured_at_utc": captured_at},
                   "entrants": entrants, "scratches": [], "win_odds": [],
                   "qa": {"entrant_count": len(entrants), "active_count": None,
                          "scratched_count": None,
                          "past_start_rows": sum(len(h["past_starts"]) for h in entrants),
                          "warnings": warnings, "status": "REVIEW_REQUIRED"}})
    warnings = []
    if not indices:
        warnings.append("NO_RACE_HEADERS_IN_PDF")
    if len(docs) != len({d["race"]["race_number"] for d in docs}):
        warnings.append("DUPLICATE_RACE_IDS")
    if any(not doc["entrants"] for doc in docs):
        warnings.append("EMPTY_RACE_SECTIONS")
    if any(doc["race"]["race_number_source"] == "pdf_order_inferred" for doc in docs):
        warnings.append("RACE_NUMBER_ORDER_INFERRED")
    return {"races": docs, "qa": {"status": "REVIEW_REQUIRED",
            "warnings": warnings, "document_date": pdf_date, "race_sections": len(indices),
            "race_numbers": sorted(race_numbers_seen),
            "horses": sum(len(doc["entrants"]) for doc in docs),
            "history_rows": sum(doc["qa"]["past_start_rows"] for doc in docs)}}

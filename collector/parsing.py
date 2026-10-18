"""Conservative parsing of Rikstoto program text and HTML-derived odds.

A parsed record is an observation, not a completeness guarantee. Unknown fields
remain null; ambiguous text remains in raw_text for later audit.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse
from typing import Any

YEAR_RE = re.compile(r"^\s*(20\d{2})\s*:\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*,?\s*(.*)$")
TOTAL_RE = re.compile(r"^\s*Tot\s*:\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*$", re.I)
DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{2})\s*-\s*(\d+)(?:\|\s*(\d+[m]?))?", re.I)
ODDS_RE = re.compile(r"^(\d+)\s+(.+?)\s+(\d+[,.]\d+)\s+(\d+[,.]\d+)\s+(\d+[,.]\d+)\s*$")
START_RE = re.compile(r"\b(\d+)\s*(?:meter\s+)?(?:tillegg)\b", re.I)
RACE_LINK_RE = re.compile(r"^/Spill/([^/]+)/[^/?#]+", re.I)


def clean(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value or "").strip()


def number(value: str) -> float | None:
    try:
        return float(str(value).strip().replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def as_int(value: str) -> int | None:
    try:
        return int(str(value).replace(" ", ""))
    except (TypeError, ValueError):
        return None


def link_identity(url: str) -> dict[str, Any]:
    p = urlparse(url)
    m = RACE_LINK_RE.match(p.path)
    q = parse_qs(p.query)
    race = next(iter(q.get("race", [])), None)
    return {"meeting_id": m.group(1) if m else None,
            "race_number": as_int(race) if race else None, "source_url": url}


def odds_from_text(text: str) -> list[dict[str, Any]]:
    """Read WIN odds table, including two-line mobile/table layouts."""
    first = re.search(r"Odds\s*-\s*Vinner", text, re.I)
    if not first:
        return []
    remainder = text[first.end():]
    end = re.search(r"(?:\n\s*Vinner\s*\n|\n\s*Løp\s*\n|\n\s*Velg alle)", remainder, re.I)
    region = remainder[:end.start()] if end else remainder[:4000]
    lines = [clean(l.replace("checkbox", "")) for l in region.splitlines()]
    lines = [l for l in lines if l]
    result = []
    for i, line in enumerate(lines):
        match = ODDS_RE.match(line)
        if not match:
            head = re.match(r"^(\d+)\s+([A-Za-zÀ-ž][^\n]+)$", line)
            prices = re.match(r"^(\d+[,.]\d+)\s+(\d+[,.]\d+)\s+(\d+[,.]\d+)$", lines[i + 1]) if i + 1 < len(lines) else None
            if head and prices:
                groups = (*head.groups(), *prices.groups())
            else:
                continue
        else:
            groups = match.groups()
        no, horse, win, lo, hi = groups
        result.append({"horse_number": int(no), "horse_name": horse,
                       "win_odds": number(win), "place_min": number(lo),
                       "place_max": number(hi)})
    return result


def _identify_name(lines: list[str], year_idx: int) -> tuple[int | None, str | None, str | None]:
    """Find entry header near 2026 stats: horse, driver, quoted odds/earnings, record."""
    low = max(0, year_idx - 9)
    # Horse then driver then 1-2 numeric summary lines. Require nearby statistics.
    for i in range(year_idx - 3, low - 1, -1):
        if i + 2 >= year_idx:
            continue
        name = clean(lines[i]); driver = clean(lines[i + 1])
        if (not name or not driver or any(x in name.lower() for x in
                ("løp ", "tillegg", "vinner", "velg alle", "trener:", "kusk", "odds"))):
            continue
        if (not re.fullmatch(r"[A-Za-zÀ-žÆØÅæøå.'()\- ]{2,65}", name)
                or not re.fullmatch(r"[A-Za-zÀ-žÆØÅæøå.'()\- ]{4,65}", driver)):
            continue
        window = " ".join(lines[i + 2: year_idx])
        if not re.search(r"(?:Va|Ba|Am|31[,\.]\d|\d[ \d]{3,}|[-\d][,.]\d+)", window):
            continue
        return i, name, driver
    return None, None, None


def _year_stats(lines: list[str]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    years: dict[str, Any] = {}
    total = None
    for line in lines:
        m = YEAR_RE.match(line)
        if m:
            y, starts, wins, seconds, thirds, extra = m.groups()
            years[y] = {"starts": int(starts), "wins": int(wins),
                        "seconds": int(seconds), "thirds": int(thirds), "extra": clean(extra)}
        t = TOTAL_RE.match(line)
        if t:
            total = dict(zip(("starts", "wins", "seconds", "thirds"), map(int, t.groups())))
    return years, total


def _starts(block: list[str]) -> list[dict[str, Any]]:
    """Conservatively extract historic race details from displayed table rows."""
    header = next((i for i, line in enumerate(block) if "Dato" in line and "Kusk" in line), None)
    if header is None:
        return []
    tail = block[header + 1:]
    anchors: list[tuple[int, re.Match[str]]] = []
    for i, line in enumerate(tail):
        match = DATE_RE.search(line)
        if match:
            anchors.append((i, match))
    starts = []
    for j, (idx, match) in enumerate(anchors):
        stop = anchors[j + 1][0] if j + 1 < len(anchors) else len(tail)
        raw = "\n".join(tail[idx:stop]).strip()
        date, previous_race, previous_spot = match.groups()
        try:
            iso_date = datetime.strptime(date, "%d.%m.%y").date().isoformat()
        except ValueError:
            iso_date = None
        first = tail[idx]
        before = first[:match.start()].strip()
        if not before and idx > 0:
            before = clean(tail[idx - 1])
        tokens = before.split()
        track = tokens[-1] if len(tokens) >= 2 and len(tokens[-1]) <= 3 else None
        driver = " ".join(tokens[:-1]) if track else (before or None)
        cells = [clean(c) for c in first[match.end():].split("\t")]
        # Expected table columns after historical date/race/post:
        # runner no, distance, place, kilometre-time, shoes, wagon, odds, prize,
        # top-three. Empty cells are preserved to avoid column drift.
        # In some layouts the first visible separator is absent.
        if cells and not cells[0]: cells = cells[1:]
        def cell(i: int) -> str | None:
            return cells[i] if i < len(cells) and cells[i] else None
        distance = as_int(cell(1))
        if distance is not None and not 1000 <= distance <= 4000:
            distance = None
        # For heavily transformed text, exact cell offsets are untrustworthy;
        # store raw text and null ambiguous structured cells.
        trustworthy_cells = len(cells) >= 7 and distance is not None
        comment_lines = [clean(line) for line in tail[idx + 1:stop] if clean(line)]
        starts.append({"date": iso_date, "race_number": int(previous_race),
                       "post": previous_spot, "track": track, "driver_abbrev": driver,
                       "starter_number": as_int(cell(0)) if trustworthy_cells else None,
                       "distance_m": distance if trustworthy_cells else None,
                       "placing": cell(2) if trustworthy_cells else None,
                       "kilometre_time": cell(3) if trustworthy_cells else None,
                       "shoes": cell(4) if trustworthy_cells else None,
                       "wagon": cell(5) if trustworthy_cells else None,
                       "odds_display": cell(6) if trustworthy_cells else None,
                       "prize_display": cell(7) if trustworthy_cells else None,
                       "top_three": cell(8) if trustworthy_cells else None,
                       "raw_text": raw,
                       "comment": " ".join(comment_lines) if comment_lines else None})
    return starts


def extract_entrants(text: str) -> list[dict[str, Any]]:
    lines = [clean(line) for line in text.splitlines() if clean(line)]
    occurrences = []
    seen_heads: set[int] = set()
    for idx, line in enumerate(lines):
        if not YEAR_RE.match(line):
            continue
        start, name, driver = _identify_name(lines, idx)
        if start is not None and start not in seen_heads:
            seen_heads.add(start)
            occurrences.append((start, name, driver))
    result: list[dict[str, Any]] = []
    current_addition = 0
    for i, (begin, name, driver) in enumerate(occurrences):
        lower = occurrences[i - 1][0] if i else 0
        for preceding_line in lines[lower:begin]:
            m = START_RE.search(preceding_line)
            if m:
                current_addition = int(m.group(1))
        stop = occurrences[i + 1][0] if i + 1 < len(occurrences) else len(lines)
        section = lines[begin:stop]
        # Avoid absorbing footer into final entrant.
        footer = next((j for j, line in enumerate(section) if line in
                       ("Andre spill til løpet:", "Strykninger", "Åpningstider for nettspill")), None)
        if footer is not None:
            section = section[:footer]
        years, total = _year_stats(section)
        trainer = next((line for line in section if line.startswith("Trener:")), None)
        identity = next((line for line in section if re.search(r"\d+\s*-\s*års", line)), None)
        starts = _starts(section)
        head = " ".join(section[2: min(len(section), 5)])
        # Numbers inside a start-group repeat after handicap additions.
        result.append({"name": name, "driver": driver, "program_number": None,
                       "start_group_addition_m": current_addition,
                       "header_text": head, "identity_text": identity,
                       "trainer_owner_breeder": trainer, "year_stats": years,
                       "total_stats": total, "past_starts": starts,
                       "raw_section": "\n".join(section)})
    return result


def scratches_from_text(text: str, race_number: int | None) -> list[dict[str, Any]]:
    m = re.search(r"(?:^|\n)\s*Strykninger\s*(?:\n|$)", text, re.I)
    if not m:
        return []
    region = text[m.end():]
    end = re.search(r"Åpningstider for nettspill|Stiftelsen Norsk Rikstoto", region, re.I)
    if end:
        region = region[:end.start()]
    result = []
    # Lines may contain a bet-type description between 'Løp N' and horse id.
    for line in region.splitlines():
        mm = re.search(r"Løp\s+(\d+)\s+.*?\b(\d+)\s+([A-Za-zÀ-ž][^\n]+)$", clean(line))
        if mm and (race_number is None or int(mm.group(1)) == race_number):
            result.append({"horse_number": int(mm.group(2)), "horse_name": clean(mm.group(3)),
                           "race_number": int(mm.group(1))})
    return result


def parse_race(text: str, url: str, *, captured_at: str, html: str = "") -> dict[str, Any]:
    identity = link_identity(url)
    number_match = re.search(r"(?:^|\n)\s*Løp\s+(\d+)\s*(?:\n|$)", text, re.I)
    if number_match:
        identity["race_number"] = int(number_match.group(1))
    time_match = re.search(r"\bkl\.?\s*(\d{1,2}:\d{2})", text, re.I)
    distance = re.search(r"(?<!\d)(\d{3,4})\s*m\b", text)
    start_method = re.search(r"\b(Voltestart|Autostart)\b", text, re.I)
    track = None
    # In the displayed race panel: Vinner / Varig Orkla / Løp 6
    name_match = re.search(r"(?:^|\n)\s*Vinner\s*\n\s*([^\n]+)\s*\n\s*Løp\s+\d+", text, re.I)
    if name_match:
        track = clean(name_match.group(1))
    entrants = extract_entrants(text)
    odds = odds_from_text(text)
    scratches = scratches_from_text(text, identity["race_number"])
    odds_by_name = {o["horse_name"].casefold(): o["horse_number"] for o in odds}
    for entrant in entrants:
        # In the race header, the local position repeats after +20m; prefer
        # globally numbered odds/scratch tables for universal program number.
        entrant["program_number"] = odds_by_name.get(entrant["name"].casefold())
        entrant["number_source"] = "win_odds" if entrant["program_number"] else None
        entrant["scratched"] = any(s["horse_name"].casefold() == entrant["name"].casefold()
                                  for s in scratches)
        if entrant["scratched"] and entrant["program_number"] is None:
            entrant["program_number"] = next((s["horse_number"] for s in scratches
                                               if s["horse_name"].casefold() == entrant["name"].casefold()), None)
            entrant["number_source"] = "scratches"
    # If *every observed numbered runner* confirms the displayed entry order,
    # fill gaps but explicitly label the inferred provenance.
    observed = [(i, e["program_number"]) for i, e in enumerate(entrants, 1)
                if e["program_number"] is not None]
    if len(observed) >= 2 and all(i == n for i, n in observed):
        for i, entrant in enumerate(entrants, 1):
            if entrant["program_number"] is None:
                entrant["program_number"] = i
                entrant["number_source"] = "order_inferred_not_verified"
    warning = []
    if not entrants:
        warning.append("NO_ENTRANTS_PARSED")
    if any(e["program_number"] is None for e in entrants):
        warning.append("MISSING_PROGRAM_NUMBERS")
    if any(not e["past_starts"] for e in entrants):
        warning.append("MISSING_PAST_STARTS")
    if identity["race_number"] is None:
        warning.append("UNKNOWN_RACE_NUMBER")
    if not track:
        warning.append("UNKNOWN_TRACK")
    if not odds:
        warning.append("NO_WIN_ODDS_SNAPSHOT")
    if not scratches:
        warning.append("SCRATCHES_UNVERIFIED")
    if len(set(e["name"].casefold() for e in entrants)) != len(entrants):
        warning.append("DUPLICATE_HORSE_NAMES")
    return {"race": {**identity, "track": track,
                     "scheduled_time_local": time_match.group(1) if time_match else None,
                     "distance_m": int(distance.group(1)) if distance else None,
                     "start_method": start_method.group(1) if start_method else None,
                     "captured_at_utc": captured_at},
            "entrants": entrants, "scratches": scratches, "win_odds": odds,
            "qa": {"entrant_count": len(entrants),
                   "active_count": sum(not e["scratched"] for e in entrants),
                   "scratched_count": sum(e["scratched"] for e in entrants),
                   "past_start_rows": sum(len(e["past_starts"]) for e in entrants),
                   "warnings": warning,
                   "status": "REVIEW_REQUIRED" if warning else "STRUCTURED_UNVERIFIED"}}
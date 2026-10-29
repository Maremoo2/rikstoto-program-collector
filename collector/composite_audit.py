"""Read-only linkage of composite racing product legs to physical race snapshots.

A composite product such as X1/V4 may enumerate legs 1..4 while its PDF
lists the physical race numbers (e.g. Bergen 7, Åby 9, Bergen 8, Åby 10).
Never infer physical identity from product race number, position alone,
track label, overlapping runners, or PDF heading alone.

Every leg must exactly match all runner identities and explicit scratch
booleans in ONE physical race; the composite PDF must independently agree
on the complete field and physical race number. Physical race snapshots
must already be reconciled against their own official PDFs.

All sources are first-party, so even a MATCHED result is *not* an
independently verified market, complete daily schedule or BET approval.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

# Both product and physical race IDs must identify the SAME actual race date.
_MEETING_ID = re.compile(r"[A-Z0-9]{1,14}_[A-Z]{2,4}_(20\d{2}-\d{2}-\d{2})", re.I)
_EXPLICIT_PDF_NUMBER_SOURCES = frozenset(("pdf_heading", "pdf_heading_number"))


def _meeting_day(meeting_id):
    if not isinstance(meeting_id, str):
        return None
    match = _MEETING_ID.fullmatch(meeting_id)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None



def _normal_name(value):
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _race_lists(payload, meeting_id):
    """Require fully identified official startlists, never partial subsets."""
    if not isinstance(payload, dict) or payload.get("success") is False:
        return None
    result = payload.get("result")
    if not isinstance(result, dict) or not result:
        return None
    records = {}
    for key, runners in result.items():
        if not isinstance(key, str) or not key.isdigit() or int(key) < 1:
            return None
        race_no = int(key)
        if race_no in records or not isinstance(runners, list) or not runners:
            return None
        signatures = set()
        for item in runners:
            if not isinstance(item, dict):
                return None
            number, name, scratched = (item.get("startNumber"),
                                      _normal_name(item.get("horseName")),
                                      item.get("isScratched"))
            if (type(number) is not int or number < 1 or name is None
                    or type(scratched) is not bool
                    or item.get("raceNumber") != race_no):
                return None
            race_key = item.get("raceKey")
            if race_key is not None and race_key != f"{meeting_id}#{race_no}":
                return None
            signature = (number, name, scratched)
            if any(s[0] == number for s in signatures):
                return None
            signatures.add(signature)
        records[race_no] = signatures
    return records


def _pdf_races(races):
    """Extract full PDF field signatures; PDF scratch flags are not inferred."""
    if not isinstance(races, list) or not races:
        return None
    parsed = []
    for item in races:
        if not isinstance(item, dict) or not isinstance(item.get("race"), dict):
            return None
        number = item["race"].get("race_number")
        # Do not accept an ordinal fallback as physical race evidence.
        if item["race"].get("race_number_source") not in _EXPLICIT_PDF_NUMBER_SOURCES:
            return None
        entrants = item.get("entrants")
        if type(number) is not int or number < 1 or not isinstance(entrants, list) or not entrants:
            return None
        members = set()
        for horse in entrants:
            if not isinstance(horse, dict):
                return None
            n = horse.get("program_number")
            name = _normal_name(horse.get("name"))
            if type(n) is not int or n < 1 or name is None:
                return None
            if any(s[0] == n for s in members):
                return None
            members.add((n, name))
        parsed.append((number, members))
    return parsed


def audit_composite_lineage(composite_meeting_id, composite_starts,
                            composite_pdf_races, physical_sources):
    """Exact, unique full-field linkage. Pure and fail-closed.

    physical_sources maps a physical meeting ID to:
      {"starts": raw official starts response,
       "pdf_audit_status": "MATCHED_AS_OF_SNAPSHOT",
       "pdf_race_number_sources": {7: "pdf_heading", ...}}.
    A successfully linked product is still a distinct multi-track product.
    """
    result = {
        "status": "BLOCKED",
        "reason": None,
        "composite_meeting_id": composite_meeting_id,
        "legs": [],
        "date_coverage_verified": False,
        "win_market_verified": False,
        "bet_authorized": False,
        "source_scope": "FIRST_PARTY_SNAPSHOT_NOT_INDEPENDENT_MARKET_PROOF",
    }
    if not isinstance(composite_meeting_id, str) or not composite_meeting_id:
        result["reason"] = "COMPOSITE_ID_MISSING"
        return result
    composite_day = _meeting_day(composite_meeting_id)
    if composite_day is None:
        result["reason"] = "COMPOSITE_ID_INVALID_OR_DATE_UNKNOWN"
        return result
    legs = _race_lists(composite_starts, composite_meeting_id)
    if legs is None:
        result["reason"] = "COMPOSITE_STARTLIST_UNVERIFIED"
        return result
    pdf = _pdf_races(composite_pdf_races)
    if pdf is None:
        result["reason"] = "COMPOSITE_PDF_UNVERIFIED"
        return result
    if not isinstance(physical_sources, dict):
        result["reason"] = "PHYSICAL_SOURCES_UNVERIFIED"
        return result

    physical = {}
    for meeting_id, source in physical_sources.items():
        if (meeting_id == composite_meeting_id or not isinstance(source, dict)
                or _meeting_day(meeting_id) != composite_day
                or source.get("pdf_audit_status") != "MATCHED_AS_OF_SNAPSHOT"):
            continue
        pdf_number_sources = source.get("pdf_race_number_sources")
        if not isinstance(pdf_number_sources, dict):
            continue
        records = _race_lists(source.get("starts"), meeting_id)
        if records is not None:
            for race_number, signature in records.items():
                if pdf_number_sources.get(race_number) not in _EXPLICIT_PDF_NUMBER_SOURCES:
                    continue
                physical[(meeting_id, race_number)] = signature
    if not physical:
        result["reason"] = "NO_PDF_RECONCILED_PHYSICAL_RACES"
        return result

    used_pdf = set()
    used_physical = set()
    for leg, field in sorted(legs.items()):
        compact = {(n, name) for n, name, _ in field}
        candidates = [(meet, n) for (meet, n), v in physical.items() if v == field]
        matching_pdf = [(i, number) for i, (number, horses) in enumerate(pdf)
                        if horses == compact]
        entry = {"product_leg": leg, "runner_count": len(field),
                 "matching_physical_candidates": len(candidates),
                 "matching_pdf_candidates": len(matching_pdf),
                 "status": "BLOCKED"}
        if len(candidates) != 1:
            entry["reason"] = ("NO_EXACT_PHYSICAL_MATCH" if not candidates
                               else "AMBIGUOUS_PHYSICAL_MATCH")
        elif len(matching_pdf) != 1:
            entry["reason"] = ("NO_EXACT_COMPOSITE_PDF_MATCH" if not matching_pdf
                               else "AMBIGUOUS_COMPOSITE_PDF_MATCH")
        else:
            meeting_id, physical_number = candidates[0]
            pdf_idx, pdf_number = matching_pdf[0]
            if pdf_number != physical_number:
                entry["reason"] = "PDF_PHYSICAL_RACE_NUMBER_MISMATCH"
            elif (meeting_id, physical_number) in used_physical or pdf_idx in used_pdf:
                entry["reason"] = "DUPLICATE_LINEAGE_ASSIGNMENT"
            else:
                entry.update({"status": "MATCHED", "reason": None,
                              "physical_meeting_id": meeting_id,
                              "physical_race_number": physical_number,
                              "composite_pdf_race_number": pdf_number})
                used_physical.add((meeting_id, physical_number))
                used_pdf.add(pdf_idx)
        result["legs"].append(entry)

    if len(used_pdf) != len(pdf) or len(result["legs"]) != len(pdf):
        result["reason"] = "COMPOSITE_PDF_LEG_COVERAGE_MISMATCH"
    elif any(x["status"] != "MATCHED" for x in result["legs"]):
        result["reason"] = "COMPOSITE_LEG_LINKAGE_UNVERIFIED"
    else:
        result["status"] = "MATCHED_TO_PHYSICAL_PDF_SNAPSHOTS"
        result["reason"] = None
    return result

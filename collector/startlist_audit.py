"""Exact PDF-to-public-startlist reconciliation and time-stamped scratch states.

The verified 2026-10-18 /api/racedays/{id}/starts response uses:
{"result":{"6":[{"raceNumber":6,"startNumber":2,"horseName":"Lesja Loke",
                   "isScratched":true}, ...]}, "success":true}.
Missing/malformed flags stay unknown. Snapshot status is never final status.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalized_horse_name(value: str) -> str:
    """Identity check independent of case and accents, not of spelling."""
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.casefold())


def reconcile_startlist(pdf_races: list[dict[str, Any]], source: Any,
                        *, captured_at: str | None = None) -> dict[str, Any]:
    """Mutates verified race docs only if every number/name/flag matches.

    No correspondence by row index. No negative scratch inference from missing
    booleans. Distinct race numbers must match to claim PDF coverage.
    """
    audit: dict[str, Any] = {
        "status": "UNVERIFIED", "race_matches": 0, "horses_verified": 0,
        "confirmed_scratches": 0, "mismatches": [], "race_numbers_match": False,
        "snapshot_captured_utc": captured_at,
    }
    if not isinstance(source, dict) or source.get("success") is not True:
        audit["mismatches"].append("STARTLIST_RESPONSE_INVALID")
        return audit
    result = source.get("result")
    if not isinstance(result, dict):
        audit["mismatches"].append("STARTLIST_RESULT_UNRECOGNIZED")
        return audit

    known_races = {int(k) for k, value in result.items()
                   if isinstance(k, str) and k.isdigit()
                   and 1 <= int(k) <= 30 and isinstance(value, list)}
    pdf_race_numbers = {d["race"]["race_number"] for d in pdf_races}
    audit["race_numbers_match"] = bool(known_races and pdf_race_numbers == known_races)
    if not audit["race_numbers_match"]:
        audit["mismatches"].append({
            "code": "STARTLIST_PDF_RACE_SET_MISMATCH",
            "expected": sorted(known_races), "actual": sorted(pdf_race_numbers),
        })
    for doc in pdf_races:
        race_no = doc["race"]["race_number"]
        rows = result.get(str(race_no))
        if not isinstance(rows, list):
            audit["mismatches"].append({"code": "RACE_NOT_IN_STARTLIST", "race": race_no})
            continue
        if not rows or not doc["entrants"]:
            audit["mismatches"].append({"code": "EMPTY_RACE", "race": race_no})
            continue
        api_horses = {}
        malformed = False
        for item in rows:
            if not isinstance(item, dict) or type(item.get("startNumber")) is not int:
                malformed = True
                break
            number = item["startNumber"]
            if number in api_horses or not isinstance(item.get("horseName"), str) or type(item.get("isScratched")) is not bool:
                malformed = True
                break
            api_horses[number] = item
        pdf_horses = {h.get("program_number"): h for h in doc["entrants"]}
        if malformed or len(pdf_horses) != len(doc["entrants"]) or set(api_horses) != set(pdf_horses):
            audit["mismatches"].append({"code": "HORSE_NUMBER_OR_FLAG_MISMATCH", "race": race_no,
                                        "expected": sorted(api_horses), "actual": sorted(pdf_horses),
                                        "missing_in_pdf": sorted(set(api_horses) - set(pdf_horses)),
                                        "missing_in_startlist": sorted(set(pdf_horses) - set(api_horses)),
                                        "malformed_api_rows": malformed})
            continue
        if any(normalized_horse_name(pdf_horses[n]["name"]) !=
               normalized_horse_name(api_horses[n]["horseName"]) for n in api_horses):
            audit["mismatches"].append({"code": "HORSE_NAME_MISMATCH", "race": race_no,
                                        "differences": [
                                            {"number": n, "pdf_name": pdf_horses[n]["name"],
                                             "startlist_name": api_horses[n]["horseName"]}
                                            for n in sorted(api_horses)
                                            if normalized_horse_name(pdf_horses[n]["name"]) !=
                                               normalized_horse_name(api_horses[n]["horseName"])
                                        ]})
            continue

        # Only after FULL identity and schema agreement is scratch state set.
        scratches = []
        for number, entry in api_horses.items():
            horse = pdf_horses[number]
            scratched = entry["isScratched"]
            horse["scratched"] = scratched
            horse["scratch_state"] = ("SCRATCHED_AS_OF_SNAPSHOT" if scratched
                                      else "ACTIVE_AS_OF_SNAPSHOT")
            horse["scratch_source"] = "official_public_startlist_isScratched"
            horse["scratch_captured_utc"] = captured_at
            if scratched:
                scratches.append({"horse_number": number, "horse_name": horse["name"],
                                  "race_number": race_no, "source": "public_startlist_isScratched",
                                  "captured_utc": captured_at})
        doc["scratches"] = scratches
        qa = doc["qa"]
        qa["scratched_count"] = len(scratches)
        qa["active_count"] = len(doc["entrants"]) - len(scratches)
        qa["scratch_verification"] = "COMPLETE_AS_OF_SNAPSHOT"
        qa["scratches_complete_as_of_snapshot"] = True
        qa["warnings"] = [w for w in qa.get("warnings", []) if w != "SCRATCHES_UNVERIFIED"]
        if "SCRATCH_STATUS_MAY_CHANGE" not in qa["warnings"]:
            qa["warnings"].append("SCRATCH_STATUS_MAY_CHANGE")
        audit["race_matches"] += 1
        audit["horses_verified"] += len(doc["entrants"])
        audit["confirmed_scratches"] += len(scratches)

    audit["status"] = (
        "MATCHED_AS_OF_SNAPSHOT"
        if audit["race_numbers_match"] and audit["race_matches"] == len(pdf_races)
        else "PARTIAL_OR_UNVERIFIED"
    )
    return audit

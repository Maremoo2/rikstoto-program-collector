"""Source-only NO/SE trotting meeting audit; never certifies complete-day coverage.

A programme ID prefix (including S1/S2) is NOT a country or sport code.
Only observed, typed Rikstoto race-day metadata can classify a meeting.
All input sources are first-party snapshots: their agreement is not an
independent racing-calendar denominator, and never grants PIT/BET authority.
"""
from __future__ import annotations

from typing import Any

from .calendar_audit import DAY_KEY

SCHEMA = "collector_no_se_trot_discovery_audit_v1"
SOURCES = ("homepage_spa", "racedays_api", "date_api")


def _maps(manifest: dict) -> dict[str, dict]:
    homepage = manifest.get("homepage_spa_racedays")
    if not isinstance(homepage, dict):
        homepage = {}
    roots = (
        homepage.get("meetings") if homepage.get("api_path") == "/api/racedays"
        else {},
        manifest.get("public_racedays_api"),
        manifest.get("calendar_racedays"),
    )
    return {label: root if isinstance(root, dict) else {}
            for label, root in zip(SOURCES, roots)}


def _classify(day: str, manifest: dict) -> dict[str, Any]:
    source_maps = _maps(manifest)
    observed = set()
    auto = manifest.get("automatically_discovered_meetings")
    if isinstance(auto, list):
        observed.update(k for k in auto if isinstance(k, str))
    else:
        # Legacy manifest fallback; do not infer more source provenance.
        for item in manifest.get("discoveries", []):
            if isinstance(item, dict):
                observed.update(k for k in item.get("meeting_ids", [])
                                if isinstance(k, str))
    observed.update(k for source in source_maps.values() for k in source)
    observed = {mid for mid in observed if isinstance(mid, str)
                and DAY_KEY.fullmatch(mid) and mid.endswith("_" + day)}
    typed: dict[str, dict] = {}
    conflicts: set[str] = set()
    for source_name, source in source_maps.items():
        for mid, row in source.items():
            if not isinstance(mid, str) or not DAY_KEY.fullmatch(mid) or not mid.endswith("_" + day):
                continue
            if not isinstance(row, dict) or row.get("meeting_id") != mid:
                conflicts.add(mid)
                continue
            item = typed.setdefault(mid, {"countries": set(), "sports": set(),
                                          "composites": set(), "sources": set()})
            item["sources"].add(source_name)
            country, sport, composite = (row.get("country"), row.get("sport_type"),
                                         row.get("is_multi_track"))
            if isinstance(country, str) and country.strip():
                item["countries"].add(country.strip().upper())
            if isinstance(sport, str) and sport.strip():
                item["sports"].add(sport.strip().upper())
            if type(composite) is bool:
                item["composites"].add(composite)
    target, composite, other, unknown = set(), set(), set(), set()
    source_conflicts = set(conflicts)
    for mid, record in typed.items():
        if (len(record["countries"]) > 1 or len(record["sports"]) > 1
                or len(record["composites"]) > 1):
            source_conflicts.add(mid)
            continue
        if True in record["composites"]:
            composite.add(mid)
        elif len(record["countries"]) != 1 or len(record["sports"]) != 1:
            unknown.add(mid)
        elif (next(iter(record["countries"])) in {"NO", "SE"}
              and record["sports"] == {"T"}):
            target.add(mid)
        else:
            other.add(mid)
    untyped = observed - set(typed)
    unknown.update(untyped)
    return {
        "sources": source_maps,
        "target": target, "composite": composite, "other": other,
        "unknown": unknown, "conflicts": source_conflicts,
        "observed": observed, "typed": typed,
    }


def collection_order(day: str, manifest: dict, meeting_ids: set[str]) -> list[str]:
    """Prefer source-typed NO/SE physical trotting, never guess from IDs.

    A meeting cap can still prevent full capture. The audit reports every
    truncated target explicitly; it must never silently disappear.
    """
    classes = _classify(day, manifest)
    target = classes["target"] - classes["conflicts"]
    composites = classes["composite"]
    return sorted(meeting_ids, key=lambda mid:
                  (0 if mid in target else 2 if mid in composites else 1, mid))


def audit_no_se_trot_discovery(manifest: dict) -> dict[str, Any]:
    """Reconcile observed first-party candidates with captured meeting records.

    This is a candidate-level operational diagnostic, NOT an independent C1
    denominator, not source-publication-time or T-4 PIT attestation.
    """
    day = manifest.get("date_oslo")
    if not isinstance(day, str):
        raise ValueError("Manifest missing local calendar day")
    classes = _classify(day, manifest)
    candidates = classes["target"] - classes["conflicts"]
    captured_rows = {
        m["meeting_id"]: m for m in manifest.get("meetings", [])
        if isinstance(m, dict) and isinstance(m.get("meeting_id"), str)
    }
    captured = candidates & set(captured_rows)
    missing = candidates - captured
    manual = set(manifest.get("manually_seeded_meetings") or [])
    auto = set(manifest.get("automatically_discovered_meetings") or [])
    not_auto = candidates - auto
    pdf_missing = sorted(mid for mid in captured
                         if captured_rows[mid].get("program_pdf") != "PDF_TEXT_OK")
    snapshot_unverified = sorted(mid for mid in captured
                                 if captured_rows[mid].get(
                                     "startlist_pdf_audit", {}).get("status")
                                 != "MATCHED_AS_OF_SNAPSHOT")
    candidate_races = sum(
        len({n for n in captured_rows[mid].get("pdf_race_numbers", [])
             if type(n) is int and 1 <= n <= 30})
        for mid in captured)
    diagnostic = manifest.get("calendar_source_diagnostic")
    status = (diagnostic.get("status") if isinstance(diagnostic, dict)
              else "NOT_RECORDED")
    missing_from_date = (
        sorted(candidates - set(classes["sources"]["date_api"]))
        if status == "TARGET_DAY_ENTRIES_PRESENT" else []
    )
    # A date API whose results are empty/unknown MUST remain a coverage gap,
    # even if homepage and general racedays agree on all observed meetings.
    blockers = []
    if status != "TARGET_DAY_ENTRIES_PRESENT":
        blockers.append("DATE_API_NOT_VERIFIED:" + str(status))
    if missing:
        blockers.append("SOURCE_CANDIDATES_NOT_CAPTURED")
    if missing_from_date:
        blockers.append("SOURCE_CANDIDATES_ABSENT_FROM_DATE_API")
    if not_auto:
        blockers.append("CANDIDATES_NOT_AUTOMATICALLY_DISCOVERED")
    if classes["conflicts"]:
        blockers.append("SOURCE_CLASSIFICATION_CONFLICT")
    if classes["unknown"]:
        blockers.append("UNKNOWN_COUNTRY_OR_SPORT")
    if pdf_missing:
        blockers.append("NO_SE_TROT_PDF_MISSING")
    if snapshot_unverified:
        blockers.append("NO_SE_TROT_SNAPSHOT_UNVERIFIED")
    if not candidates:
        blockers.append("NO_TYPED_NO_SE_TROT_CANDIDATES")
    return {
        "schema": SCHEMA, "date_oslo": day,
        "scope": "OBSERVED_FIRST_PARTY_NO_SE_TROT_PHYSICAL_CANDIDATES",
        "status": ("REVIEW_REQUIRED" if blockers
                   else "OBSERVED_CANDIDATES_RECONCILED_UNVERIFIED_DAY"),
        "country_sport_from_typed_source_fields_only": True,
        "independent_whole_day_denominator_verified": False,
        "c1_coverage_eligible": False,
        "pit_certified": False, "bet_authorized": False,
        "date_api_status": status,
        "no_se_trot_physical_candidate_ids": sorted(candidates),
        "no_se_trot_candidate_count": len(candidates),
        "no_se_trot_captured_ids": sorted(captured),
        "no_se_trot_captured_count": len(captured),
        "no_se_trot_observed_pdf_race_count": candidate_races,
        "candidate_ids_not_collected": sorted(missing),
        "candidate_ids_absent_from_date_api": missing_from_date,
        "candidate_ids_not_auto_discovered": sorted(not_auto),
        "candidate_ids_manual_seeded": sorted(candidates & manual),
        "candidate_ids_pdf_missing": pdf_missing,
        "candidate_ids_snapshot_unverified": snapshot_unverified,
        "source_classification_conflicts": sorted(classes["conflicts"]),
        "unknown_country_or_sport_ids": sorted(classes["unknown"]),
        "composite_product_ids_excluded": sorted(classes["composite"]),
        "non_target_meeting_ids": sorted(classes["other"]),
        "sources_observed": {
            name: sorted(mid for mid in source if mid.endswith("_" + day))
            for name, source in classes["sources"].items()
        },
        "blockers": blockers,
        "notes": [
            "No inferred country/sport from S1, S2 or other meeting ID prefixes.",
            "All discovery sources are Rikstoto first-party observations, not an independent full-day schedule.",
            "Observed PDF race counts are not the independently expected race-day denominator.",
        ],
    }

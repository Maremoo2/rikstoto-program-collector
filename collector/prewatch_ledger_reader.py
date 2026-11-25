"""Read-only Phase A Ledger deduplication. No Sheet writes or betting authority."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import os
import re
import unicodedata

from .prewatch_ready import OSLO, digest, encoded, require, stamp

SPREADSHEET_ID_ENV = "PREWATCH_LEDGER_SPREADSHEET_ID"
SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
URL = "https://sheets.googleapis.com/v4/spreadsheets/{}/values:batchGet"
RANGES = ("RaceAssessments!A1:AG", "RaceFieldSnapshots!A1:U")
ASSESS = ("assessment_id race_id assessed_at_iso assessment_epoch_utc scheduled_start_epoch_utc "
          "non_scratched_horses horses_really_assessed fullfield_scratches_QA race_shape_documented "
          "data_score_25 shape_score_20 mispricing_score_30 liquidity_score_15 fit_score_10 total_score_formula "
          "score_bounds_QA_formula A_WATCH_GATE_formula FULL_RACE_QA_formula candidate_horse_no candidate_horse_name "
          "mispricing_hypothesis counterargument race_shape_summary source_url source_observed_at_iso "
          "assessment_status notes freeze_ref pilot_id STATUS_QA_consistent_formula assessment_ISO_epoch_QA "
          "field_snapshot_id strict_roster_qa_formula").split()
FIELD = ("field_snapshot_id race_id horse_no horse_name post distance_m scratch_state driver trainer "
         "source_uri observed_at_iso observed_epoch_utc scheduled_start_epoch_utc equipment_asof field_version "
         "source_kind member_key_formula unique_member_QA_formula official_prestart_QA_formula notes "
         "observed_ISO_epoch_QA").split()
COMPLETE = {"BELOW_THRESHOLD", "A_WATCH", "A-WATCH"}


def integer(v):
    require(not isinstance(v, bool) and re.fullmatch(r"[0-9]+(?:\.0+)?", str(v)), "LEDGER_INTEGER_INVALID")
    return int(str(v).split('.')[0])


def race_key(v):
    require(isinstance(v, str), "LEDGER_RACE_ID_INVALID")
    parts = v.split("|")
    require(len(parts) == 3 and parts[1].strip() == parts[1] and bool(parts[1])
            and re.fullmatch(r"[1-9]\d*", parts[2]), "LEDGER_RACE_ID_INVALID")
    require(date.fromisoformat(parts[0]).isoformat() == parts[0], "LEDGER_RACE_ID_INVALID")
    return unicodedata.normalize("NFC", v)


def table(values, header, *, field=False):
    require(isinstance(values, list) and values and values[0] == header, "LEDGER_SCHEMA_INVALID")
    result = []
    for row in values[1:]:
        require(isinstance(row, list) and len(row) <= len(header), "LEDGER_ROW_INVALID")
        row = row + [""] * (len(header) - len(row))
        if not row[0] and not row[1] and (not field or not row[2]):
            continue  # formula spill has no identity
        require(bool(row[0]) and bool(row[1]) and (not field or bool(row[2])), "LEDGER_ROW_ID_MISSING")
        d = dict(zip(header, row))
        d["race_id"] = race_key(d["race_id"])
        result.append(d)
    return result


def clock(iso, epoch):
    t = stamp(iso)
    require(t.microsecond == 0 and t.timestamp() == integer(epoch), "LEDGER_CLOCK_MISMATCH")
    return t


def complete(a, members, now):
    require(a["assessment_status"] in COMPLETE, "LEDGER_NOT_COMPLETE")
    flags = ("fullfield_scratches_QA", "race_shape_documented", "score_bounds_QA_formula",
             "FULL_RACE_QA_formula", "STATUS_QA_consistent_formula",
             "assessment_ISO_epoch_QA", "strict_roster_qa_formula")
    require(all(a[k] == "YES" for k in flags), "LEDGER_ASSESSMENT_QA_FAILED")
    require(bool(a["freeze_ref"]) and bool(a["field_snapshot_id"]), "LEDGER_FREEZE_OR_FIELD_MISSING")
    freeze = clock(a["assessed_at_iso"], a["assessment_epoch_utc"])
    start = datetime.fromtimestamp(integer(a["scheduled_start_epoch_utc"]), timezone.utc)
    require(freeze <= now and freeze < start and start.astimezone(OSLO).date().isoformat() == a["race_id"][:10],
            "LEDGER_PRESTART_INVALID")
    source_time = stamp(a["source_observed_at_iso"])
    require(timedelta(0) <= freeze - source_time <= timedelta(minutes=30), "LEDGER_ROSTER_AGE_INVALID")
    count = integer(a["non_scratched_horses"])
    require(count > 0 and count == integer(a["horses_really_assessed"]), "LEDGER_FIELD_COUNT_MISMATCH")
    require(members, "LEDGER_FIELD_MISSING")
    numbers = set()
    active = 0
    for m in members:
        require(m["race_id"] == a["race_id"] and m["source_kind"] == "OFFICIAL"
                and m["scratch_state"] in {"ACTIVE", "SCRATCHED"}
                and all(m[k] == "YES" for k in ("unique_member_QA_formula", "official_prestart_QA_formula",
                                                  "observed_ISO_epoch_QA")), "LEDGER_FIELD_QA_FAILED")
        number = integer(m["horse_no"])
        require(number > 0 and number not in numbers and bool(m["horse_name"]), "LEDGER_DUPLICATE_OR_INVALID_MEMBER")
        numbers.add(number)
        observed = clock(m["observed_at_iso"], m["observed_epoch_utc"])
        require(timedelta(0) <= freeze - observed <= timedelta(minutes=30)
                and observed < start and integer(m["scheduled_start_epoch_utc"]) == int(start.timestamp()),
                "LEDGER_FIELD_CLOCK_INVALID")
        if m["scratch_state"] == "ACTIVE":
            active += 1
    require(active == count, "LEDGER_FIELD_COUNT_MISMATCH")


def validate_values(assessments, fields, day, now):
    require(date.fromisoformat(day).isoformat() == day and now.tzinfo is not None, "LEDGER_REFERENCE_INVALID")
    arows, frows = table(assessments, ASSESS), table(fields, FIELD, field=True)
    require(len({a["assessment_id"] for a in arows}) == len(arows), "LEDGER_DUPLICATE_ASSESSMENT_ID")
    cohorts = defaultdict(list)
    for f in frows:
        cohorts[f["field_snapshot_id"]].append(f)
    accepted, rejected = [], []
    for a in arows:
        if not a["race_id"].startswith(day + "|"):
            continue
        try:
            complete(a, cohorts.get(a["field_snapshot_id"], []), now)
            accepted.append(a["race_id"])
        except (ValueError, TypeError, OverflowError, OSError) as e:
            rejected.append(str(e) if str(e).startswith("LEDGER_") else "LEDGER_VALUE_INVALID")
    require(len(set(accepted)) == len(accepted), "LEDGER_DUPLICATE_COMPLETED_RACE")
    return {"completed_ids": sorted(accepted), "rejected_counts": dict(sorted(Counter(rejected).items())),
            "assessment_rows": len(arows), "field_rows": len(frows),
            "values_sha256": digest(encoded([assessments, fields]))}


def read_live(day, *, session=None, clock_now=None):
    """Google ADC with read-only scope; injectable session only for offline tests."""
    now = clock_now or (lambda: datetime.now(timezone.utc))
    started = now()
    configured = os.environ.get(SPREADSHEET_ID_ENV, "")
    require(re.fullmatch(r"[A-Za-z0-9_-]{20,120}", configured), "LEDGER_ID_CONFIGURATION_MISSING")
    test_mode = session is not None or clock_now is not None
    if session is None:
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials, _ = google.auth.default(scopes=[SCOPE])
            session = AuthorizedSession(credentials)
        except Exception:
            raise ValueError("LEDGER_AUTH_UNAVAILABLE") from None
    params = [("ranges", r) for r in RANGES] + [
        ("valueRenderOption", "UNFORMATTED_VALUE"), ("dateTimeRenderOption", "FORMATTED_STRING"),
        ("majorDimension", "ROWS")]
    try:
        response = session.get(URL.format(configured), params=params, timeout=30)
        require(response.status_code == 200, f"LEDGER_HTTP_{response.status_code}")
        body = response.json()
    except ValueError:
        raise
    except Exception:
        raise ValueError("LEDGER_READ_UNAVAILABLE") from None
    finished = now()
    require(timedelta(0) <= finished - started <= timedelta(seconds=120)
            and finished.astimezone(OSLO).date().isoformat() == day, "LEDGER_READ_CLOCK_INVALID")
    require(isinstance(body, dict) and body.get("spreadsheetId") == configured, "LEDGER_ID_MISMATCH")
    v = body.get("valueRanges")
    require(isinstance(v, list) and len(v) == 2, "LEDGER_RANGES_MISSING")
    for item, requested in zip(v, RANGES):
        tab, cols = requested.split("!")
        require(re.fullmatch(re.escape(tab) + r"!A1:" + cols.split(":")[1] + r"\d*", item.get("range", ""))
                and item.get("majorDimension") == "ROWS", "LEDGER_RANGE_MISMATCH")
    result = validate_values(v[0].get("values"), v[1].get("values"), day, finished)
    result.update(read_started_utc=started.isoformat(), read_finished_utc=finished.isoformat(),
                  spreadsheet_id_sha256=digest(configured.encode()), scope=SCOPE,
                  evidence_kind="INJECTED_TEST_SESSION" if test_mode else "GOOGLE_API_READ")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.parse_args()
    day = datetime.now(OSLO).date().isoformat()
    result = read_live(day)
    # Public repository logs: aggregates only, never values, IDs or credentials.
    print(json.dumps({"status": "LEDGER_READ_CONFIRMED", "assessment_rows": result["assessment_rows"],
                      "field_rows": result["field_rows"], "completed_today": len(result["completed_ids"]),
                      "read_finished_utc": result["read_finished_utc"]}))


if __name__ == "__main__":
    main()

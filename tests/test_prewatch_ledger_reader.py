from copy import deepcopy
from datetime import datetime, timezone

import pytest

from collector.prewatch_ledger_reader import (
    ASSESS, FIELD, SPREADSHEET_ID_ENV, validate_values, read_live
)

SPREADSHEET_ID = "synthetic-spreadsheet-identity-12345"
DAY = "2026-11-25"
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
RACE = DAY + "|Example track|1"
FREEZE = "2026-11-25T10:00:00+00:00"
OBS = "2026-11-25T09:50:00+00:00"
START = "2026-11-25T19:00:00+00:00"


def ep(v):
    return int(datetime.fromisoformat(v).timestamp())


def row(keys, values):
    return [values.get(k, "") for k in keys]


def data():
    a = dict(assessment_id="assessment-1", race_id=RACE, assessed_at_iso=FREEZE,
             assessment_epoch_utc=ep(FREEZE), scheduled_start_epoch_utc=ep(START),
             non_scratched_horses=2, horses_really_assessed=2, assessment_status="BELOW_THRESHOLD",
             freeze_ref="freeze-1", field_snapshot_id="field-1", source_observed_at_iso=OBS)
    for k in ("fullfield_scratches_QA", "race_shape_documented", "score_bounds_QA_formula",
              "FULL_RACE_QA_formula", "STATUS_QA_consistent_formula", "assessment_ISO_epoch_QA",
              "strict_roster_qa_formula"):
        a[k] = "YES"
    f = dict(field_snapshot_id="field-1", race_id=RACE, horse_name="Example",
             scratch_state="ACTIVE", source_kind="OFFICIAL", observed_at_iso=OBS,
             observed_epoch_utc=ep(OBS), scheduled_start_epoch_utc=ep(START),
             unique_member_QA_formula="YES", official_prestart_QA_formula="YES", observed_ISO_epoch_QA="YES")
    return [ASSESS, row(ASSESS, a)], [FIELD, row(FIELD, dict(f, horse_no=1)), row(FIELD, dict(f, horse_no=2))]


def test_valid_and_empty_day():
    a, f = data()
    assert validate_values(a, f, DAY, NOW)["completed_ids"] == [RACE]
    assert validate_values(a, f, "2026-11-26", NOW)["completed_ids"] == []
    assert validate_values(a, f, DAY, NOW) == validate_values(a, f, DAY, NOW)


@pytest.mark.parametrize("key,value", [("assessment_status", "PARTIAL"), ("assessment_ISO_epoch_QA", "NO"),
    ("FULL_RACE_QA_formula", "NO"), ("strict_roster_qa_formula", "NO"), ("freeze_ref", ""),
    ("assessment_epoch_utc", 1), ("horses_really_assessed", 1), ("scheduled_start_epoch_utc", 1)])
def test_bad_assessment_not_excluded(key, value):
    a, f = data()
    a[1][ASSESS.index(key)] = value
    assert validate_values(a, f, DAY, NOW)["completed_ids"] == []


@pytest.mark.parametrize("key,value", [("horse_no", 1), ("observed_ISO_epoch_QA", "NO"),
    ("race_id", DAY + "|Example track|2"), ("observed_epoch_utc", 1), ("scratch_state", "UNKNOWN")])
def test_bad_field_not_excluded(key, value):
    a, f = data()
    f[2][FIELD.index(key)] = value
    assert validate_values(a, f, DAY, NOW)["completed_ids"] == []


def test_schema_duplicate_and_missing_field():
    a, f = data()
    with pytest.raises(ValueError, match="LEDGER_SCHEMA_INVALID"):
        validate_values([["bad"]], f, DAY, NOW)
    assert validate_values(a, f[:2], DAY, NOW)["completed_ids"] == []
    a.append(deepcopy(a[1]))
    with pytest.raises(ValueError, match="LEDGER_DUPLICATE_ASSESSMENT_ID"):
        validate_values(a, f, DAY, NOW)
    a[2][0] = "another-id"
    with pytest.raises(ValueError, match="LEDGER_DUPLICATE_COMPLETED_RACE"):
        validate_values(a, f, DAY, NOW)


class Response:
    def __init__(self, status=200):
        self.status_code = status

    def json(self):
        a, f = data()
        return {"spreadsheetId": SPREADSHEET_ID, "valueRanges": [
            {"range": "RaceAssessments!A1:AG1501", "majorDimension": "ROWS", "values": a},
            {"range": "RaceFieldSnapshots!A1:U1508", "majorDimension": "ROWS", "values": f}]}


class Session:
    def __init__(self, status=200):
        self.status = status

    def get(self, url, params, timeout):
        assert SPREADSHEET_ID in url and timeout == 30
        return Response(self.status)


def test_api_injected_not_live_and_failure(monkeypatch):
    monkeypatch.setenv(SPREADSHEET_ID_ENV, SPREADSHEET_ID)
    result = read_live(DAY, session=Session(), clock_now=lambda: NOW)
    assert result["completed_ids"] == [RACE]
    assert result["evidence_kind"] == "INJECTED_TEST_SESSION"
    with pytest.raises(ValueError, match="LEDGER_HTTP_403"):
        read_live(DAY, session=Session(403), clock_now=lambda: NOW)


def test_missing_configuration(monkeypatch):
    monkeypatch.delenv(SPREADSHEET_ID_ENV, raising=False)
    with pytest.raises(ValueError, match="LEDGER_ID_CONFIGURATION_MISSING"):
        read_live(DAY, session=Session(), clock_now=lambda: NOW)


def test_stale_roster_not_excluded():
    a, f = data()
    a[1][ASSESS.index("source_observed_at_iso")] = "2026-11-25T08:00:00Z"
    assert validate_values(a, f, DAY, NOW)["completed_ids"] == []

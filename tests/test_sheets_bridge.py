import json
from pathlib import Path

import pytest

from collector.sheets_bridge import HEADERS, extract_rows, sync


def test_extract_source_only(tmp_path):
    folder = tmp_path / "2026-10-18" / "20261018T115431185234Z"
    folder.mkdir(parents=True)
    manifest = {
        "date_oslo": "2026-10-18",
        "run_id": "20261018T115431185234Z",
        "status": "CAPTURED_UNVERIFIED",
        "meetings": [{"meeting_id": "OR_NR_2026-10-18",
                      "listing_source": {"country": "NO", "track": "Varig Orkla"}}]
    }
    doc = {"date": manifest["date_oslo"], "run_id": manifest["run_id"],
           "races": [{"race": {"meeting_id": "OR_NR_2026-10-18", "race_number": 5,
                               "captured_at_utc": "2026-10-18T11:55:08Z"},
                      "entrants": [{"past_starts": [{}, {}]}, {"past_starts": [{}]}],
                      "qa": {"scratch_verification": "COMPLETE_AS_OF_SNAPSHOT"}}]}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    (folder / "structured_program_day.json").write_text(json.dumps(doc))
    rows = extract_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0][0] == "2026-10-18|OR_NR_2026-10-18|5"
    assert rows[0][10:12] == [2, 3]
    assert rows[0][15] == "SOURCE_ONLY_NOT_SPORT_SCORED"


class Request:
    def __init__(self, result):
        self.result = result
    def execute(self):
        return self.result


class Values:
    def __init__(self, rows):
        self.rows = rows
    def get(self, **kwargs):
        a1 = kwargs["range"].split("!")[-1]
        if a1 == "A1:R10000":
            return Request({"values": self.rows})
        start = int(a1.split(":")[0].split("A")[-1])
        return Request({"values": [self.rows[start-1]]})
    def batchUpdate(self, **kwargs):
        for item in kwargs["body"]["data"]:
            start = int(item["range"].split(":")[0].split("A")[-1])
            while len(self.rows) < start:
                self.rows.append([])
            self.rows[start-1] = item["values"][0]
        return Request({})


class Sheets:
    def __init__(self, rows):
        self.values_api = Values(rows)
    def get(self, **kwargs):
        return Request({"sheets": [{"properties": {"title": "CrawlerSourceInbox"}}]})
    def values(self):
        return self.values_api


class Service:
    def __init__(self, rows):
        self.api = Sheets(rows)
    def spreadsheets(self):
        return self.api


def test_sync_deduplicates_same_run_and_appends_new_run():
    service = Service([HEADERS])
    row = ["race", "run1"] + [""] * (len(HEADERS)-2)
    first = sync(service, "sheet", [row])
    assert first["state"] == "VERIFIED"
    assert first["new_snapshots"] == 1
    second = sync(service, "sheet", [row])
    assert second["new_snapshots"] == 0
    next_run = row.copy()
    next_run[1] = "run2"
    third = sync(service, "sheet", [next_run])
    assert third["new_snapshots"] == 1
    assert len(service.api.values_api.rows) == 3

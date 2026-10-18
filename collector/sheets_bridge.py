"""Append-only Rikstoto source snapshots to a dedicated PreWatch Google Sheets inbox.

No sports scores, odds, bets, or existing PreWatch tabs are modified.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

TAB = "CrawlerSourceInbox"
HEADERS = ["race_id","snapshot_run_id","source_captured_utc","track","country",
           "meeting_id","race_no","scheduled_start_local","distance_m","start_method",
           "horses","past_starts","scratch_snapshot","official_program_url",
           "collector_status","evidence_state","source_archive_tag","imported_utc"]

def extract_rows(root):
    manifests = sorted(root.glob("*/*/manifest.json"))
    if not manifests:
        raise ValueError("No collector manifest")
    folder = manifests[-1].parent
    manifest = json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    data = json.loads((folder/"structured_program_day.json").read_text(encoding="utf-8"))
    day, run = manifest["date_oslo"], manifest["run_id"]
    if (data.get("date"),data.get("run_id")) != (day,run):
        raise ValueError("Collector manifest/data mismatch")
    if manifest.get("status") not in ("CAPTURED_UNVERIFIED","REVIEW_REQUIRED"):
        raise ValueError("Collector snapshot not importable")
    meetings = {m["meeting_id"]:m for m in manifest.get("meetings",[])
                if m.get("listing_source",{}).get("country") in ("NO","SE")
                and not m.get("is_multi_track_product")}
    rows = []
    for doc in data.get("races",[]):
        race = doc["race"]
        mid = race["meeting_id"]
        if mid not in meetings or not race.get("race_number") or not doc.get("entrants"):
            continue
        horses = doc["entrants"]
        meeting = meetings[mid]
        rows.append([
            f"{day}|{mid}|{race['race_number']}",run,race.get("captured_at_utc",""),
            race.get("track") or meeting.get("listing_source",{}).get("track",""),
            meeting["listing_source"]["country"],mid,race["race_number"],
            race.get("scheduled_time_local",""),race.get("distance_m",""),
            race.get("start_method",""),len(horses),
            sum(len(h.get("past_starts",[])) for h in horses),
            doc.get("qa",{}).get("scratch_verification","UNVERIFIED"),
            race.get("source_url",""),manifest["status"],
            "SOURCE_ONLY_NOT_SPORT_SCORED",f"rikstoto-program-{day}-{run}",
            datetime.now(timezone.utc).isoformat()])
    keys = [(r[0],r[1]) for r in rows]
    if len(keys)!=len(set(keys)):
        raise ValueError("Duplicate race/run keys in source")
    return rows

def sync(service,spreadsheet_id,rows,dry_run=False):
    api=service.spreadsheets()
    metadata=api.get(spreadsheetId=spreadsheet_id,fields="sheets(properties(sheetId,title))").execute()
    found=any(s["properties"]["title"]==TAB for s in metadata.get("sheets",[]))
    if not found:
        if dry_run:
            return {"state":"DRY_RUN_TAB_MISSING","candidate_rows":len(rows)}
        api.batchUpdate(spreadsheetId=spreadsheet_id,
                        body={"requests":[{"addSheet":{"properties":{"title":TAB}}}]}).execute()
    existing=api.values().get(spreadsheetId=spreadsheet_id,range=f"'{TAB}'!A1:R10000").execute().get("values",[])
    if existing and existing[0]!=HEADERS:
        raise ValueError("Inbox header mismatch: refusing to write")
    keys=set()
    for record in existing[1:]:
        if len(record)>1 and record[0]:
            key=(record[0],record[1])
            if key in keys:
                raise ValueError("Duplicate existing race/run key")
            keys.add(key)
    writes=[]
    if not existing:
        writes.append({"range":f"'{TAB}'!A1:R1","values":[HEADERS]})
    next_row=max(len(existing)+1,2)
    new=0
    for row in rows:
        if (row[0],row[1]) in keys:
            continue
        if next_row>10000:
            raise ValueError("Inbox capacity reached")
        writes.append({"range":f"'{TAB}'!A{next_row}:R{next_row}","values":[row]})
        next_row+=1
        new+=1
    if dry_run:
        return {"state":"DRY_RUN","new_snapshots":new,"already_present":len(rows)-new}
    if writes:
        api.values().batchUpdate(spreadsheetId=spreadsheet_id,
                                 body={"valueInputOption":"RAW","data":writes}).execute()
        for write in writes:
            observed=api.values().get(spreadsheetId=spreadsheet_id,
                                      range=write["range"]).execute().get("values",[])
            if not observed or [str(x) for x in observed[0]] != [str(x) for x in write["values"][0]]:
                raise RuntimeError("WRITE_READBACK_MISMATCH "+write["range"])
    return {"state":"VERIFIED","new_snapshots":new,"already_present":len(rows)-new}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=Path("output/daily"))
    parser.add_argument("--dry-run",action="store_true")
    args=parser.parse_args()
    rows=extract_rows(args.root)
    if args.dry_run and not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        print(json.dumps({"state":"LOCAL_SOURCE_VALIDATED","candidate_rows":len(rows)}))
        return
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info=json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    credentials=service_account.Credentials.from_service_account_info(
        info,scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service=build("sheets","v4",credentials=credentials,cache_discovery=False)
    print(json.dumps(sync(service,os.environ["PREWATCH_SPREADSHEET_ID"],rows,args.dry_run)))

if __name__=="__main__":
    main()

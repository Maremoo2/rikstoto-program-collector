"""DATA-005 one-time independent original-PDF 120-line replay; NO BET.

PDF source text is read independently of Collector's structured_program.json
BEFORE evaluating the repaired parser. This is a nonrepresentative, hand-
selected diagnostic slice across 24 horses and 15 physical races. Original
SHA-256 manifest and target race identity are mandatory. No betting/model use.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import fitz

from collector.pdf_program import parse_extended_pdf

SELECTION={
    "S1_NR_2026-11-07":[
        (5,3),(5,11),(6,3),(6,5),(7,3),(7,5),(8,9),(9,12),
        (10,3),(11,4),(12,3),(12,15),
    ],
    "KL_NR_2026-11-07":[
        (2,2),(2,5),(3,3),(3,2),(4,3),(4,6),(5,4),(5,10),
        (6,9),(6,4),(7,7),(8,10),
    ],
}
HEADER=re.compile(r"(?m)^([1-9]|1[0-9]) ([A-ZÅÄÖÆØÉÜÀÁÈÏŠČÐ][A-ZÅÄÖÆØÉÜÀÁÈÏŠČÐ.\-'\s()0-9]+), ([^\n]+)$")
DATE=re.compile(r"(\d\d\.\d\d\.\d\d)-(\d+)\|(.+)$")
DIST=re.compile(r"^([1-4]\d{3})\s+(.+)$")
PACE=re.compile(r"^(\d{1,2},\d)\s*([ag]{0,2})$")


def original_gold(pdf: bytes, meeting: str) -> tuple[list[dict], str]:
    doc=fitz.open(stream=pdf,filetype="pdf")
    pages=[p.get_text("text") for p in doc]
    page_labels=[];race=None
    for page in pages:
        m=re.search(r"(?m)^(?:Løp|Lopp) (\d+)$",page)
        if m:race=int(m.group(1))
        if race is None and meeting.startswith("KL_"):race=1
        page_labels.append(race)
    offsets=[];pos=0
    for page in pages:
        offsets.append(pos);pos+=len(page)+1
    full="\n".join(pages)
    headers=list(HEADER.finditer(full))
    sample={}
    for i,m in enumerate(headers):
        physical_page=max(k for k,x in enumerate(offsets) if x<=m.start())
        race=page_labels[physical_page]
        selection=(race,int(m.group(1)))
        if selection not in SELECTION[meeting]:continue
        block=full[m.end():headers[i+1].start() if i+1<len(headers) else len(full)]
        lines=block.splitlines()
        results=[]
        for j,line in enumerate(lines):
            match=DATE.search(line.strip())
            if match is None:continue
            track=line[:match.start()].strip() or (lines[j-1].strip() if j>=1 else "")
            driver=(lines[j-1].strip() if line[:match.start()].strip()
                    else lines[j-2].strip() if j>=2 else "")
            place=lines[j+1].strip() if j+1<len(lines) else ""
            dist=lines[j+2].strip() if j+2<len(lines) else ""
            if DIST.fullmatch(place) and not DIST.fullmatch(dist):
                dist,place=place,None
            if place=="MISSING":place=None
            m_dist=DIST.fullmatch(dist)
            distance=int(m_dist.group(1)) if m_dist else None
            kmtime=m_dist.group(2) if m_dist else None
            m_pace=PACE.fullmatch(kmtime or "")
            pace=m_pace.group(1)+m_pace.group(2) if m_pace else None
            d=datetime.strptime(match.group(1),"%d.%m.%y").date().isoformat()
            results.append({
                "meeting":meeting,"race":race,"number":selection[1],
                "horse":m.group(2),"date":d,"race_number":int(match.group(2)),
                "track":track,"driver_abbrev":driver,
                "placing":place,"distance_m":distance,
                "kilometre_time":pace,"raw_kmtime":kmtime,
            })
        if len(results)!=5:raise ValueError("INDEPENDENT_PDF_NOT_FIVE_LINES")
        if selection in sample:raise ValueError("INDEPENDENT_DUPLICATE_TARGET_HORSE")
        sample[selection]=results
    if set(sample)!=set(SELECTION[meeting]):
        raise ValueError("INDEPENDENT_PDF_TARGET_ROSTER_UNVERIFIED")
    return ([x for selection in SELECTION[meeting] for x in sample[selection]],
            full)


def replay(originals: Path, output: Path) -> dict:
    manifest=next(originals.glob("output/daily/2026-11-07/*/manifest.json"))
    data=json.loads(manifest.read_bytes())
    results=[]; fields=("date","race_number","track","driver_abbrev",
                        "placing","distance_m","kilometre_time")
    for meeting in SELECTION:
        receipt=[x for x in data["requests"]
                 if x.get("url","").endswith("/Utvidet/"+meeting)]
        if len(receipt)!=1:raise ValueError("COLLECTOR_MANIFEST_ORIGINAL_NOT_UNIQUE")
        r=receipt[0]
        pdf=originals/r["path"]
        raw=pdf.read_bytes()
        if (hashlib.sha256(raw).hexdigest()!=r["sha256"]
                or not raw.startswith(b"%PDF-")
                or datetime.fromisoformat(r["at_utc"])>=datetime.fromisoformat(
                    "2026-11-07T13:56:00+00:00")):
            raise ValueError("COLLECTOR_PDF_SHA_OR_PRESTART_CLOCK_INVALID")
        gold,text=original_gold(raw,meeting)
        parsed=parse_extended_pdf(
            text,meeting_id=meeting,date="2026-11-07",
            url=r["url"],captured_at=r["at_utc"],
        )
        races={r["race"]["race_number"]:r for r in parsed["races"]}
        for row in gold:
            entrants=[x for x in races[row["race"]]["entrants"]
                      if x["program_number"]==row["number"]
                      and x["name"].casefold()==row["horse"].casefold()]
            if len(entrants)!=1:
                raise ValueError("PARSED_TARGET_HORSE_IDENTITY_NOT_UNIQUE")
            prior=[x for x in entrants[0]["past_starts"]
                   if x.get("date")==row["date"]
                   and x.get("race_number")==row["race_number"]]
            if len(prior)!=1:
                raise ValueError("PARSED_PREVIOUS_EVENT_NOT_UNIQUE")
            for field in fields:
                expected=row[field]
                actual=prior[0].get(field)
                results.append({
                    "meeting":meeting,"race":row["race"],
                    "number":row["number"],"horse":row["horse"],
                    "date":row["date"],"field":field,
                    "gold":expected,"parsed":actual,
                    "status":("NOT_AVAILABLE" if expected is None
                              else "MISSING" if actual is None
                              else "CORRECT" if actual==expected else "WRONG"),
                    "original_sha256":r["sha256"],
                })
    if len(results)!=840:
        raise ValueError("EXPECTED_120_ROWS_X_7_FIELDS")
    counts={field:dict(collections.Counter(
        x["status"] for x in results if x["field"]==field))
        for field in fields}
    output.mkdir(parents=True,exist_ok=True)
    with (output/"DATA_005_ORIGINAL_GOLD_REPLAY.csv").open(
        "w",newline="",encoding="utf-8"
    ) as f:
        w=csv.DictWriter(f,fieldnames=list(results[0]))
        w.writeheader();w.writerows(results)
    report={
        "schema":"DATA005_ORIGINAL_PDF_GOLD_REPLAY_V1",
        "sample_rows":120,"both_meetings":2,"source":"ORIGINAL_PDF_SHA_VERIFIED",
        "sample_not_representative":True,
        "visual_manual_review_all_120":False,
        "exact_current_field_parser_replayed":True,
        "fields":counts,"bet_authority":False,
        "pit_certified":False,
        "acceptance":"ONLY_VERIFIED_PDF_CELL_VALUES_NOT_MODEL_FEATURES",
    }
    (output/"index.json").write_text(json.dumps(report,indent=2,ensure_ascii=False))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args()
    report=replay(args.source_root,args.output)
    print(json.dumps(report,ensure_ascii=False))
    # Only wrong accepted fields fail. Missing values are diagnosed separately
    # and must never be fabricated to obtain a green workflow.
    if any("WRONG" in scores for scores in report["fields"].values()):
        raise SystemExit("ORIGINAL_PDF_ACCEPTED_VALUE_WRONG")

"""Daily source-first Rikstoto archive: Oslo-local date, all discovered meetings.

The public race-day calendar and multiTracks endpoints were observed in an
actual Chromium network trace on 2026-10-18. Other endpoints similarly
observed include /api/racedays/{meeting}/starts, /api/game/program/{meeting}/
driverChanges, /formrowstrot and /api/programdownload/ProgramPdf/Utvidet/{id}.

The program makes no guesses about meeting IDs. It archives source JSON and
official PDFs with provenance, and NEVER claims completeness on partial data.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import re
import sys
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .pipeline import DOMAIN, USER_AGENT, check_robots, source_allowed

OSLO = ZoneInfo("Europe/Oslo")
MEETING_ID = re.compile(r"\b[A-Z0-9]{1,14}_[A-Z]{2,4}_(20\d{2}-\d{2}-\d{2})\b", re.I)
HORSE_RACE_KEYS = ("raceNumber", "raceNo", "raceNr", "race_number", "lopNr", "lopNummer")
SCRATCH_KEYS = ("scratched", "isScratched", "withdrawn", "isWithdrawn", "strøket", "stroket", "isScratch")
SCRATCH_STATUSES = {"SCRATCHED", "WITHDRAWN", "STRØKET", "STROKET"}
MAX_JSON_BYTES = 6_000_000
MAX_PDF_BYTES = 24_000_000


class StopCollection(RuntimeError):
    """Site explicitly refused a request or signalled rate limiting."""


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def oslo_date():
    return datetime.now(OSLO).date().isoformat()


def dump(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def meeting_ids(value, day: str):
    """Extract only concrete meeting IDs actually present in source material."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return sorted({m.group(0) for m in MEETING_ID.finditer(str(value))
                   if m.group(1) == day})


def race_numbers(value):
    """Conservative hint extraction; does not imply the program is complete."""
    numbers = set()
    def visit(obj):
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in HORSE_RACE_KEYS and type(val) in (str, int):
                    try:
                        n = int(val)
                        if 1 <= n <= 30:
                            numbers.add(n)
                    except (ValueError, TypeError):
                        pass
                if isinstance(val, (dict, list)):
                    visit(val)
        elif isinstance(obj, list):
            for item in obj:
                visit(item)
    visit(value)
    return sorted(numbers)


def _horse_info(obj):
    """Use only explicitly labeled fields; never infer horse number from order."""
    for key in ("horse", "horseInfo", "participant"):
        if isinstance(obj.get(key), dict):
            nested = obj[key]
            name = nested.get("name") or nested.get("horseName")
            num = (obj.get("startNumber") or obj.get("horseNumber") or
                   nested.get("startNumber") or nested.get("horseNumber"))
            return name, num
    return obj.get("horseName"), obj.get("startNumber") or obj.get("horseNumber")


def scratch_signals(value):
    """Only positive, explicit scratch flags; cannot verify a lack of scratches.

    The complete raw source is retained separately for human review. The
    scraper does not assume that an unrecognized schema means no scratches.
    """
    records = []
    seen = set()
    flags_seen = 0
    def visit(obj, path="$", race=None, in_scratch_list=False):
        nonlocal flags_seen
        if isinstance(obj, list):
            for i, item in enumerate(obj):
                visit(item, f"{path}[{i}]", race, in_scratch_list)
            return
        if not isinstance(obj, dict):
            return
        current_race = race
        for key in HORSE_RACE_KEYS:
            if key in obj:
                try:
                    current_race = int(obj[key])
                except (ValueError, TypeError):
                    pass
                break
        positive = in_scratch_list
        for key, val in obj.items():
            if key in SCRATCH_KEYS and isinstance(val, (bool, int, str)):
                flags_seen += 1
                positive |= val is True or str(val).strip().upper() in SCRATCH_STATUSES
            if key.lower() in ("status", "startstatus", "horsestatus") and isinstance(val, str):
                flags_seen += 1
                positive |= val.strip().upper() in SCRATCH_STATUSES
        if positive:
            horse_name, horse_number = _horse_info(obj)
            if horse_number is not None or horse_name:
                identity = (current_race, str(horse_number), str(horse_name))
                if identity not in seen:
                    seen.add(identity)
                    records.append({"race_number": current_race, "horse_number": horse_number,
                                    "horse_name": horse_name, "source_path": path,
                                    "evidence": {k: obj.get(k) for k in
                                                (*SCRATCH_KEYS, "status", "startStatus", "horseStatus")
                                                if k in obj}})
        for key, item in obj.items():
            if isinstance(item, (list, dict)):
                declared_list = key.casefold() in (
                    "scratches", "scratchings", "withdrawals", "strykninger", "strukne")
                visit(item, f"{path}.{key}", current_race, declared_list)
    visit(value)
    return {"positive_scratches": records, "explicit_status_fields_seen": flags_seen,
            "interpretation": "positive_only; absent or unrecognized status is UNKNOWN"}


async def request(ctx, robots, url, path: Path, log, *, binary=False):
    if not source_allowed(url) or not robots.permits(url):
        log.append({"url": url, "status": "ROBOTS_OR_HOST_BLOCKED", "at_utc": utcnow()})
        return None
    await asyncio.sleep(1.25)
    try:
        reply = await ctx.request.get(url, timeout=24000, max_redirects=3)
        status = reply.status
        ct = reply.headers.get("content-type", "")
        if status != 200:
            log.append({"url": url, "status": f"HTTP_{status}", "content_type": ct,
                        "at_utc": utcnow()})
            if status in (403, 429):
                raise StopCollection(f"Site returned HTTP {status}; stop further requests: {url}")
            return None
        raw = await reply.body()
        limit = MAX_PDF_BYTES if binary else MAX_JSON_BYTES
        if len(raw) > limit:
            log.append({"url": url, "status": "TOO_LARGE", "bytes": len(raw), "at_utc": utcnow()})
            return None
        if binary:
            if not raw.startswith(b"%PDF-"):
                log.append({"url": url, "status": "NOT_PDF", "content_type": ct, "at_utc": utcnow()})
                return None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            log.append({"url": url, "status": "PDF_OK", "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "path": str(path), "at_utc": utcnow()})
            return raw
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            log.append({"url": url, "status": "NOT_JSON", "content_type": ct,
                        "bytes": len(raw), "at_utc": utcnow()})
            return None
        dump(path, {"source_url": url, "fetched_utc": utcnow(), "response": value})
        log.append({"url": url, "status": "JSON_OK", "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "path": str(path), "at_utc": utcnow()})
        return value
    except StopCollection:
        raise
    except Exception as exc:
        log.append({"url": url, "status": "NETWORK_ERROR",
                    "error": f"{type(exc).__name__}: {str(exc)[:350]}",
                    "at_utc": utcnow()})
        return None


def extract_pdf(binary: bytes, folder: Path):
    try:
        from pypdf import PdfReader
        pdf = PdfReader(io.BytesIO(binary))
        text = "\n\n".join(page.extract_text() or "" for page in pdf.pages)
        (folder / "full_program.txt").write_text(text, encoding="utf-8")
        # All following counts are source-text heuristics, not an audited
        # guarantee that the PDF contains every horse or prior start.
        race_starts = len(re.findall(r"(?m)^START KL\.", text))
        horse_headers = len(re.findall(
            r"(?m)^\d{1,2}\s+[A-ZÆØÅ][A-ZÆØÅÀ-ÖØ-Þ0-9 .\-()]+,", text))
        history_rows = len(re.findall(
            r"(?m)^.{1,24}\s+[A-ZÆØÅ]{2,3}\s+\d\d\.\d\d\.\d\d-\d+", text))
        return {"pages": len(pdf.pages), "text_characters": len(text),
                "readable": bool(text.strip()),
                "race_heading_mentions": len(re.findall(r"\bLøp\s+\d+\b", text, re.I)),
                "heuristic_races": race_starts, "heuristic_horses": horse_headers,
                "heuristic_history_rows": history_rows,
                "counts_verified": False}
    except Exception as exc:
        return {"readable": False, "error": f"{type(exc).__name__}: {str(exc)[:250]}"}


async def archive_day(day, out, *, max_meetings=18, max_races=18):
    from playwright.async_api import async_playwright
    day = Date.fromisoformat(day).isoformat()
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = Path(out) / day / run
    folder.mkdir(parents=True, exist_ok=False)
    logs, warnings = [], []
    manifest = {
        "date_oslo": day, "created_utc": utcnow(), "run_id": run,
        "purpose": "public program and scratches morning snapshot",
        "discoveries": [], "meetings": [], "requests": logs, "warnings": warnings,
        "status": "REVIEW_REQUIRED", "completeness_verified": False,
        "note": "A 07:00 snapshot is not a final scratch list or closing-odds snapshot.",
    }
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(locale="nb-NO", timezone_id="Europe/Oslo")
            robots = await check_robots(ctx, "strict")
            manifest["robots"] = {"status": robots.status, "checked_utc": utcnow()}
            homepage = f"https://{DOMAIN}/?date={quote(day)}"
            if not robots.permits(homepage):
                warnings.append(f"ROBOTS_ACCESS_UNVERIFIED:{robots.status}")
            else:
                # The calendar endpoint is directly observed in a live site trace.
                start = (Date.fromisoformat(day) - timedelta(days=7)).isoformat()
                sources = [
                    (f"https://{DOMAIN}/api/racedays/dates/{start}/{day}", "calendar"),
                    (f"https://{DOMAIN}/api/racedays/multiTracks", "multitracks"),
                ]
                meeting_set = set()
                for url, label in sources:
                    data = await request(ctx, robots, url, folder / f"discovery_{label}.json", logs)
                    ids = meeting_ids(data, day) if data is not None else []
                    manifest["discoveries"].append({"source": label, "url": url,
                                                    "meeting_ids": ids, "received": data is not None})
                    meeting_set.update(ids)
                # Browser fallback discovers meeting IDs actually embedded in
                # current date-selected front page; it never fabricates IDs.
                page = await ctx.new_page()
                try:
                    response = await page.goto(homepage, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(3000)
                    html = await page.content()
                    body = await page.locator("body").inner_text(timeout=12000)
                    (folder / "frontpage.html").write_text(html, encoding="utf-8")
                    (folder / "frontpage.txt").write_text(body, encoding="utf-8")
                    found = meeting_ids(html, day)
                    meeting_set.update(found)
                    manifest["discoveries"].append({
                        "source": "frontpage_browser", "url": homepage,
                        "http_status": response.status if response else None,
                        "meeting_ids": found, "body_length": len(body)})
                except Exception as exc:
                    warnings.append(f"HOMEPAGE_BROWSER_FAILED:{type(exc).__name__}")
                finally:
                    await page.close()
                if not meeting_set:
                    warnings.append("NO_MEETING_IDS_DISCOVERED_FROM_OFFICIAL_SOURCES")
                if len(meeting_set) > max_meetings:
                    warnings.append(f"MEETING_LIMIT_EXCEEDED:{len(meeting_set)}>{max_meetings}")
                for meeting in sorted(meeting_set)[:max_meetings]:
                    record = {"meeting_id": meeting, "discovered_utc": utcnow(),
                              "source_date": day, "program_pdf": "unknown",
                              "scratching_status": "unknown", "race_numbers": []}
                    manifest["meetings"].append(record)
                    mdir = folder / "meetings" / meeting
                    mdir.mkdir(parents=True, exist_ok=True)
                    base = f"https://{DOMAIN}"
                    starts_url = f"{base}/api/racedays/{meeting}/starts"
                    starts = await request(ctx, robots, starts_url, mdir / "starts.json", logs)
                    if starts is None:
                        record["scratching_status"] = "SOURCE_UNAVAILABLE"
                        warnings.append(f"STARTS_UNAVAILABLE:{meeting}")
                    else:
                        scratch = scratch_signals(starts)
                        dump(mdir / "scratchings.json", {
                            "meeting_id": meeting, "captured_utc": utcnow(), **scratch})
                        record["scratching_status"] = (
                            "EXPLICIT_FLAGS_OBSERVED" if scratch["explicit_status_fields_seen"]
                            else "SCHEMA_UNVERIFIED")
                        record["positive_scratches"] = len(scratch["positive_scratches"])
                        record["race_numbers"] = race_numbers(starts)
                        if record["scratching_status"] != "EXPLICIT_FLAGS_OBSERVED":
                            warnings.append(f"SCRATCH_STATUS_UNVERIFIED:{meeting}")
                    pdf_url = f"{base}/api/programdownload/ProgramPdf/Utvidet/{meeting}"
                    raw_pdf = await request(ctx, robots, pdf_url, mdir / "full_program.pdf",
                                            logs, binary=True)
                    if raw_pdf is not None:
                        record["pdf_analysis"] = extract_pdf(raw_pdf, mdir)
                        record["program_pdf"] = (
                            "PDF_TEXT_OK" if record["pdf_analysis"]["readable"] else "PDF_UNREADABLE")
                    else:
                        record["program_pdf"] = "SOURCE_UNAVAILABLE"
                        warnings.append(f"FULL_PROGRAM_PDF_UNAVAILABLE:{meeting}")
                    # Once the source exposes actual race numbers, retain
                    # individually fetched public race program payloads too.
                    if record["race_numbers"]:
                        if len(record["race_numbers"]) > max_races:
                            warnings.append(f"RACE_LIMIT_EXCEEDED:{meeting}")
                        # The V/trot route is known from an observed Norwegian
                        # trotting race, not a documented universal gallop API.
                        is_trot = (record["program_pdf"] == "PDF_TEXT_OK"
                                   and "galopp" not in
                                   (mdir / "full_program.txt").read_text(encoding="utf-8")[:1000].casefold())
                        if is_trot:
                            for n in record["race_numbers"][:max_races]:
                                endpoint = f"{base}/api/game/program/{meeting}/V/trot/{n}"
                                await request(ctx, robots, endpoint, mdir / f"race_{n:02}.json", logs)
                    else:
                        warnings.append(f"RACE_NUMBERS_UNVERIFIED:{meeting}")
                    # Directly observed supplementary endpoint for actual
                    # driver change data. Scratches are never inferred from it.
                    await request(ctx, robots,
                                  f"{base}/api/game/program/{meeting}/driverChanges",
                                  mdir / "driver_changes.json", logs)
                    record["captured_utc"] = utcnow()
            if not manifest["meetings"]:
                warnings.append("NO_PROGRAMS_ARCHIVED")
            elif any(r["program_pdf"] != "PDF_TEXT_OK" for r in manifest["meetings"]):
                warnings.append("NOT_ALL_DISCOVERED_MEETINGS_HAVE_FULL_PDF")
            manifest["counts"] = {
                "meetings_discovered": len(manifest["meetings"]),
                "full_program_pdfs": sum(r["program_pdf"] == "PDF_TEXT_OK"
                                        for r in manifest["meetings"]),
                "scratches_positively_identified": sum(r.get("positive_scratches", 0)
                                                       for r in manifest["meetings"]),
                "scratch_status_sources_with_flags": sum(
                    r["scratching_status"] == "EXPLICIT_FLAGS_OBSERVED"
                    for r in manifest["meetings"]),
            }
            # Even a complete-looking snapshot remains unverified until the
            # official full daily schedule has been independently reconciled.
            manifest["status"] = (
                "CAPTURED_UNVERIFIED" if manifest["meetings"] and
                all(r["program_pdf"] == "PDF_TEXT_OK" for r in manifest["meetings"])
                else "REVIEW_REQUIRED")
            await ctx.close()
            await browser.close()
    except Exception as exc:
        warnings.append(f"FATAL:{type(exc).__name__}:{str(exc)[:350]}")
        manifest["status"] = "ERROR"
    finally:
        dump(folder / "manifest.json", manifest)
        print(f"DAILY_STATUS={manifest['status']} MEETINGS={len(manifest['meetings'])} "
              f"PDFS={manifest.get('counts',{}).get('full_program_pdfs',0)} "
              f"FOLDER={folder}", flush=True)
        for warning in warnings:
            print(f"WARNING {warning}", flush=True)
    return folder, manifest


def main():
    parser = argparse.ArgumentParser(description="Archive today's official Rikstoto programs at 07:00 Oslo time")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD; default today in Europe/Oslo")
    parser.add_argument("--out", default="output/daily")
    parser.add_argument("--max-meetings", type=int, default=18)
    parser.add_argument("--max-races", type=int, default=18)
    args = parser.parse_args()
    if not (1 <= args.max_meetings <= 25 and 1 <= args.max_races <= 25):
        parser.error("max-meetings and max-races must be between 1 and 25")
    day = args.date or oslo_date()
    folder, result = asyncio.run(archive_day(day, args.out,
                                              max_meetings=args.max_meetings,
                                              max_races=args.max_races))
    print(f"Manifest: {folder / 'manifest.json'}")
    return 0 if result["status"] == "CAPTURED_UNVERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())

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
from .pdf_program import parse_extended_pdf
from .calendar_audit import calendar_window, calendar_racedays, diagnose_calendar_response
from .startlist_audit import reconcile_startlist
from .composite_audit import audit_composite_lineage
from .homepage_schedule import homepage_racedays, schedule_comparison
from .source_integrity import archive_json_bytes

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
        # Race-level 'status' does not establish a horse scratch.
        # Count status/flag fields only on nodes that identify a horse.
        horse_name_here, horse_number_here = _horse_info(obj)
        has_horse_identity = bool(horse_name_here or horse_number_here is not None)
        positive = in_scratch_list
        for key, val in obj.items():
            if has_horse_identity and key in SCRATCH_KEYS and isinstance(val, (bool, int, str)):
                flags_seen += 1
                positive |= val is True or str(val).strip().upper() in SCRATCH_STATUSES
            if has_horse_identity and key.lower() in ("status", "startstatus", "horsestatus") and isinstance(val, str):
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
            if hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(raw).hexdigest():
                log.append({"url": url, "status": "ARCHIVE_READBACK_FAILED",
                            "source_type": "PDF", "at_utc": utcnow()})
                return None
            log.append({"url": url, "status": "PDF_OK", "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "path": str(path), "at_utc": utcnow(),
                        "content_type": ct,
                        "response_headers": {key: reply.headers[key]
                                             for key in ("date", "last-modified", "etag")
                                             if key in reply.headers},
                        "raw_readback_verified": True,
                        "source_publication_time_attested": False})
            return raw
        observed_at = utcnow()
        try:
            value, proof = archive_json_bytes(
                raw, path, url=url, observed_at_utc=observed_at)
        except (ValueError, UnicodeError):
            log.append({"url": url, "status": "NOT_JSON", "content_type": ct,
                        "bytes": len(raw), "at_utc": observed_at})
            return None
        except (OSError, TypeError) as exc:
            log.append({"url": url, "status": "ARCHIVE_READBACK_FAILED",
                        "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                        "at_utc": observed_at})
            return None
        log.append({"url": url, "status": "JSON_OK", "bytes": len(raw),
                    "path": str(path), "at_utc": observed_at,
                    "content_type": ct,
                    "response_headers": {key: reply.headers[key]
                                         for key in ("date", "last-modified", "etag")
                                         if key in reply.headers},
                    **proof})
        return value
    except StopCollection:
        raise
    except Exception as exc:
        log.append({"url": url, "status": "NETWORK_ERROR",
                    "error": f"{type(exc).__name__}: {str(exc)[:350]}",
                    "at_utc": utcnow()})
        return None


def calendar_source_evidence(response, day: str, url: str, request_log: list) -> dict:
    """Attach the archived request metadata to a non-authorizing diagnosis."""
    entry = next((item for item in reversed(request_log)
                  if item.get("url") == url), {})
    return {
        **diagnose_calendar_response(response, day),
        "source_url": url,
        "request_status": entry.get("status", "NOT_LOGGED"),
        "response_sha256": entry.get("sha256"),
        "raw_response_path": entry.get("raw_path"),
        "raw_readback_verified": entry.get("raw_readback_verified") is True,
        "source_publication_time_attested": False,
        "request_at_utc": entry.get("at_utc"),
    }


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


async def archive_day(day, out, *, max_meetings=18, max_races=18, seed_meetings=()):
    from playwright.async_api import async_playwright
    day = Date.fromisoformat(day).isoformat()
    seeds = []
    for seed in seed_meetings:
        seed = seed.strip().upper()
        match = MEETING_ID.fullmatch(seed)
        if not match or match.group(1) != day:
            raise ValueError(f'Seed meeting must contain exactly requested date {day}: {seed}')
        seeds.append(seed)
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = Path(out) / day / run
    folder.mkdir(parents=True, exist_ok=False)
    logs, warnings = [], []
    structured_races = []
    manifest = {
        "date_oslo": day, "created_utc": utcnow(), "run_id": run,
        "purpose": "public program and scratches morning snapshot",
        "discoveries": [], "meetings": [], "requests": logs, "warnings": warnings,
        "status": "REVIEW_REQUIRED", "completeness_verified": False,
        "calendar_source_diagnostic": {
            "status": "SOURCE_NOT_REQUESTED", "date_coverage_verified": False},
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
                # Observed date API uses an exclusive upper bound.
                # For 18 October, [18 Oct, 19 Oct) retrieves the target day,
                # while the previous [11 Oct, 18 Oct) accidentally omitted it.
                calendar_start, calendar_end = calendar_window(day)
                sources = [
                    (f"https://{DOMAIN}/api/racedays/dates/{calendar_start}/{calendar_end}", "calendar"),
                    (f"https://{DOMAIN}/api/racedays/multiTracks", "multitracks"),
                ]
                meeting_set = set()
                starts_by_meeting = {}
                calendar_entries = {}
                direct_racedays = {}
                embedded_home = {"status": "NOT_PRESENT", "meetings": {}, "api_path": None}
                # Initialize a real browser session first so its public
                # cookies and compatible headers are present for API requests.
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
                    embedded_home = homepage_racedays(html, day)
                    dump(folder / "discovery_spa_schedule.json", embedded_home)
                    # Meeting keys are read from actual first-party SPA data,
                    # not inferred from dates or generated by scanning codes.
                    meeting_set.update(found)
                    meeting_set.update(embedded_home["meetings"])
                    manifest["discoveries"].append({
                        "source": "frontpage_browser", "url": homepage,
                        "http_status": response.status if response else None,
                        "meeting_ids": found, "body_length": len(body),
                        "spa_status": embedded_home["status"],
                        "spa_meeting_ids": sorted(embedded_home["meetings"]),
                        "spa_observed_api": embedded_home["api_path"]})
                except Exception as exc:
                    warnings.append(f"HOMEPAGE_BROWSER_FAILED:{type(exc).__name__}")
                finally:
                    await page.close()
                if embedded_home["api_path"] == "/api/racedays":
                    # First-party URL is taken unchanged from SPA rehydration.
                    sources.append((f"https://{DOMAIN}/api/racedays", "racedays"))
                for url, label in sources:
                    data = await request(ctx, robots, url, folder / f"discovery_{label}.json", logs)
                    ids = meeting_ids(data, day) if data is not None else []
                    if label == "calendar":
                        calendar_entries = calendar_racedays(data, day)
                        manifest["calendar_source_diagnostic"] = calendar_source_evidence(
                            data, day, url, logs)
                    if label == "racedays" and data is not None:
                        direct_racedays = calendar_racedays(data, day)
                    manifest["discoveries"].append({"source": label, "url": url,
                                                    "meeting_ids": ids, "received": data is not None,
                                                    "typed_meetings": len(calendar_entries) if label == "calendar" else
                                                                      len(direct_racedays) if label == "racedays" else None})
                    meeting_set.update(ids)
                manifest["calendar_racedays"] = calendar_entries
                manifest["public_racedays_api"] = direct_racedays
                manifest["homepage_spa_racedays"] = embedded_home
                manifest["schedule_comparison"] = schedule_comparison(
                    set(meeting_set), embedded_home, direct_racedays, calendar_entries)
                if not calendar_entries:
                    # Keep the legacy warning for downstream readers while
                    # exposing the precise observed failure mode separately.
                    warnings.append("DATE_RANGE_API_NO_TARGET_MEETINGS")
                    warnings.append(
                        "DATE_RANGE_API_" + manifest["calendar_source_diagnostic"]["status"])
                if not embedded_home["meetings"] and not direct_racedays and not calendar_entries:
                    warnings.append("NO_STRUCTURED_RACEDAYS_BASELINE_AVAILABLE")
                if manifest["schedule_comparison"]["missing_from_collector"]:
                    warnings.append("SCHEDULE_SOURCE_MEETINGS_NOT_DISCOVERED")
                auto_discovered = sorted(meeting_set)
                for seed in seeds:
                    meeting_set.add(seed)
                manifest["automatically_discovered_meetings"] = auto_discovered
                manifest["manually_seeded_meetings"] = sorted(set(seeds))
                if seeds:
                    warnings.append("MANUAL_SEEDS_DO_NOT_VERIFY_COMPLETE_DATE_COVERAGE")
                if not meeting_set:
                    warnings.append("NO_MEETING_IDS_DISCOVERED_FROM_OFFICIAL_SOURCES")
                if len(meeting_set) > max_meetings:
                    warnings.append(f"MEETING_LIMIT_EXCEEDED:{len(meeting_set)}>{max_meetings}")
                for meeting in sorted(meeting_set)[:max_meetings]:
                    calendar_source = calendar_entries.get(meeting, {})
                    # SPA race array can contain only races offered for bet;
                    # do NOT compare its partial count to the full PDF.
                    listing_source = direct_racedays.get(meeting) or embedded_home["meetings"].get(meeting, {})
                    record = {"meeting_id": meeting, "discovered_utc": utcnow(),
                              "source_date": day, "program_pdf": "unknown",
                              "scratching_status": "unknown", "race_numbers": [],
                              "calendar_source": calendar_source,
                              "listing_source": listing_source,
                              "is_multi_track_product": bool(calendar_source.get("is_multi_track") or
                                                             listing_source.get("is_multi_track"))}
                    manifest["meetings"].append(record)
                    mdir = folder / "meetings" / meeting
                    mdir.mkdir(parents=True, exist_ok=True)
                    base = f"https://{DOMAIN}"
                    starts_url = f"{base}/api/racedays/{meeting}/starts"
                    starts = await request(ctx, robots, starts_url, mdir / "starts.json", logs)
                    if starts is not None:
                        starts_by_meeting[meeting] = starts
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
                        if record["pdf_analysis"]["readable"]:
                            parsed_program = parse_extended_pdf(
                                (mdir / "full_program.txt").read_text(encoding="utf-8"),
                                meeting_id=meeting, date=day,
                                url=pdf_url, captured_at=utcnow())
                            record["pdf_structure"] = parsed_program["qa"]
                            dump(mdir / "structured_program.json", parsed_program)
                            structured_races.extend(parsed_program["races"])
                            pdf_races = parsed_program["qa"].get("race_numbers", [])
                            record["pdf_race_numbers"] = pdf_races
                            # A composite Xpress PDF contains races from several
                            # physical venues, so IDs from its pooled startlist
                            # should NOT be compared as if it were an ordinary track.
                            if meeting.startswith("X1_") and "xpress" in (mdir / "full_program.txt").read_text(encoding="utf-8").casefold():
                                record["is_multi_track_product"] = True
                            if record["is_multi_track_product"]:
                                warnings.append(f"CROSS_MEETING_COMPOSITE_NOT_UNIQUE_TRACK:{meeting}")
                            record["parsed_horses"] = parsed_program["qa"].get("horses", 0)
                            record["parsed_history_rows"] = parsed_program["qa"].get("history_rows", 0)
                            if not pdf_races:
                                warnings.append(f"PDF_RACE_EXTRACTION_FAILED:{meeting}")
                            if (record["race_numbers"] and not record["is_multi_track_product"]
                                    and set(record["race_numbers"]) != set(pdf_races)):
                                warnings.append(f"STARTLIST_PDF_RACE_MISMATCH:{meeting}")
                            calendar_races = calendar_source.get("race_numbers", [])
                            if calendar_races and not record["is_multi_track_product"] and set(calendar_races) != set(pdf_races):
                                warnings.append(f"CALENDAR_PDF_RACE_MISMATCH:{meeting}")
                            if not record["race_numbers"]:
                                warnings.append(f"RACE_COUNT_UNVERIFIED_AGAINST_STARTLIST:{meeting}")
                            # Preserve explicit positive scratch events and avoid
                            # incorrectly declaring everyone else 'not scratched'.
                            scratch_events = scratch["positive_scratches"] if starts is not None else []
                            for doc in parsed_program["races"]:
                                assigned = []
                                for event in scratch_events:
                                    if str(event.get("race_number")) != str(doc["race"]["race_number"]):
                                        continue
                                    for horse in doc["entrants"]:
                                        if ((event.get("horse_number") is not None and
                                             str(horse["program_number"]) == str(event["horse_number"]))
                                                or (event.get("horse_name") and
                                                    horse["name"].casefold() == str(event["horse_name"]).casefold())):
                                            horse["scratched"] = True
                                            horse["scratch_state"] = "SCRATCHED_CONFIRMED_BY_STARTLIST"
                                            assigned.append({"horse_number": horse["program_number"],
                                                             "horse_name": horse["name"],
                                                             "race_number": doc["race"]["race_number"]})
                                            break
                                doc["scratches"] = assigned
                                doc["qa"]["scratched_count"] = len(assigned) if assigned else None
                                # Never infer all other runners are active from
                                # a positive-only scratch-status extraction.
                                doc["qa"]["active_count"] = None
                                doc["qa"]["scratch_verification"] = "positive_only"
                            # A verified starts response explicitly carries isScratched
                            # as a BOOLEAN for every horse. Cross-check exact PDF
                            # race/start numbers AND names before marking any horse
                            # ACTIVE or SCRATCHED as of this observation.
                            if starts is not None and not record["is_multi_track_product"]:
                                starts_at = next((item.get("at_utc") for item in reversed(logs)
                                                  if item.get("url") == starts_url), None)
                                audit = reconcile_startlist(
                                    parsed_program["races"], starts, captured_at=starts_at)
                                record["startlist_pdf_audit"] = audit
                                if audit["status"] != "MATCHED_AS_OF_SNAPSHOT":
                                    warnings.append(f"PDF_STARTLIST_HORSES_UNVERIFIED:{meeting}")
                            else:
                                record["startlist_pdf_audit"] = {
                                    "status": "COMPOSITE_OR_UNAVAILABLE",
                                    "note": "Do not validate pooled Xpress legs against physical race numbers"
                                }
                            dump(mdir / "structured_program.json", parsed_program)
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
            # Link X1 product legs to uniquely identified physical races
            # using full-field names, numbers and scratch flags; neither
            # same-provider agreement nor PDF matching authorizes BET.
            physical_sources = {}
            for item in manifest["meetings"]:
                if item["is_multi_track_product"]:
                    continue
                meeting = item["meeting_id"]
                pdf_number_sources = {}
                physical_pdf_file = folder / "meetings" / meeting / "structured_program.json"
                if physical_pdf_file.is_file():
                    try:
                        parsed_docs = json.loads(
                            physical_pdf_file.read_text(encoding="utf-8")).get("races", [])
                        for doc in parsed_docs:
                            number = doc["race"]["race_number"]
                            number_source = doc["race"].get("race_number_source")
                            # Duplicate physical race numbers invalidate
                            # their explicit-number evidence, not just one row.
                            if number in pdf_number_sources:
                                pdf_number_sources[number] = None
                            else:
                                pdf_number_sources[number] = number_source
                    except (OSError, ValueError, TypeError, KeyError):
                        pdf_number_sources = {}
                physical_sources[meeting] = {
                    "starts": starts_by_meeting.get(meeting),
                    "pdf_audit_status": item.get("startlist_pdf_audit", {}).get("status"),
                    "pdf_race_number_sources": pdf_number_sources,
                }
            for item in manifest["meetings"]:
                if not item["is_multi_track_product"]:
                    continue
                meeting = item["meeting_id"]
                composite_pdf_file = folder / "meetings" / meeting / "structured_program.json"
                composite_pdf_races = None
                if composite_pdf_file.is_file():
                    try:
                        composite_pdf_races = json.loads(
                            composite_pdf_file.read_text(encoding="utf-8")).get("races")
                    except (OSError, ValueError, TypeError):
                        pass
                audit = audit_composite_lineage(
                    meeting, starts_by_meeting.get(meeting),
                    composite_pdf_races, physical_sources)
                item["composite_physical_audit"] = audit
                dump(folder / "meetings" / meeting / "composite_physical_lineage.json", audit)
                if audit["status"] != "MATCHED_TO_PHYSICAL_PDF_SNAPSHOTS":
                    warnings.append(f"COMPOSITE_PHYSICAL_LINEAGE_UNVERIFIED:{meeting}")
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
                "pdf_races_parsed": len(structured_races),
                "pdf_horses_parsed": sum(len(doc["entrants"]) for doc in structured_races),
                "pdf_history_rows": sum(doc["qa"]["past_start_rows"] for doc in structured_races),
                "independent_tracks": sum(not r["is_multi_track_product"] for r in manifest["meetings"]),
                "unique_track_races": sum(len(r.get("pdf_race_numbers", [])) for r in manifest["meetings"]
                                          if not r["is_multi_track_product"]),
                "unique_track_horses": sum(r.get("parsed_horses", 0) for r in manifest["meetings"]
                                           if not r["is_multi_track_product"]),
                "unique_track_prior_starts": sum(r.get("parsed_history_rows", 0) for r in manifest["meetings"]
                                                if not r["is_multi_track_product"]),
                "verified_snapshot_horses": sum(
                    r.get("startlist_pdf_audit", {}).get("horses_verified", 0)
                    for r in manifest["meetings"] if not r["is_multi_track_product"]),
                "verified_snapshot_scratches": sum(
                    r.get("startlist_pdf_audit", {}).get("confirmed_scratches", 0)
                    for r in manifest["meetings"] if not r["is_multi_track_product"]),
                "fully_reconciled_independent_meetings": sum(
                    r.get("startlist_pdf_audit", {}).get("status") == "MATCHED_AS_OF_SNAPSHOT"
                    for r in manifest["meetings"] if not r["is_multi_track_product"]),
            }
            # Even a complete-looking snapshot remains unverified until the
            # official full daily schedule has been independently reconciled.
            # Captured-unverified requires all source-discovered meetings to
            # have been visited, and at least one structured dated schedule
            # source. A manual seed or an arbitrary homepage link list is not
            # an independently sufficient discovery baseline.
            coverage = (len(manifest["meetings"]) == len(meeting_set)
                        and bool(embedded_home["meetings"] or direct_racedays or calendar_entries)
                        and not manifest["schedule_comparison"]["missing_from_collector"])
            manifest["status"] = (
                "CAPTURED_UNVERIFIED" if manifest["meetings"] and coverage and
                all(r["program_pdf"] == "PDF_TEXT_OK"
                    and bool(r.get("pdf_race_numbers"))
                    and (r["is_multi_track_product"] or
                         r.get("startlist_pdf_audit", {}).get("status") == "MATCHED_AS_OF_SNAPSHOT")
                    and r["scratching_status"] == "EXPLICIT_FLAGS_OBSERVED"
                    and bool(r["race_numbers"])
                    and (r["is_multi_track_product"] or
                         set(r["race_numbers"]) == set(r["pdf_race_numbers"]))
                    and (r["is_multi_track_product"] or not r["calendar_source"].get("race_numbers") or
                         set(r["calendar_source"]["race_numbers"]) == set(r["pdf_race_numbers"]))
                    for r in manifest["meetings"])
                else "REVIEW_REQUIRED")
            await ctx.close()
            await browser.close()
    except Exception as exc:
        warnings.append(f"FATAL:{type(exc).__name__}:{str(exc)[:350]}")
        manifest["status"] = "ERROR"
    finally:
        dump(folder / "structured_program_day.json", {
            "date": day, "run_id": run, "source_type": "official_extended_pdf",
            "races": structured_races, "counts": {
                "races": len(structured_races),
                "horses": sum(len(doc["entrants"]) for doc in structured_races),
                "prior_starts": sum(doc["qa"]["past_start_rows"] for doc in structured_races)},
            "status": "UNVERIFIED",
            "limitations": ["Scratches and race-day changes may occur after snapshot.",
                            "Only discovered meetings; full date coverage unverified.",
                            "Past start fields retain raw official PDF text if ambiguous."]
        })
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
    parser.add_argument("--seed-meeting", action="append", default=[],
                        help="Optional independently known meeting ID for this date, not part of auto discovery")
    parser.add_argument("--max-meetings", type=int, default=18)
    parser.add_argument("--max-races", type=int, default=18)
    args = parser.parse_args()
    if not (1 <= args.max_meetings <= 25 and 1 <= args.max_races <= 25):
        parser.error("max-meetings and max-races must be between 1 and 25")
    day = args.date or oslo_date()
    folder, result = asyncio.run(archive_day(day, args.out,
                                              max_meetings=args.max_meetings,
                                              max_races=args.max_races,
                                              seed_meetings=args.seed_meeting))
    print(f"Manifest: {folder / 'manifest.json'}")
    return 0 if result["status"] == "CAPTURED_UNVERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())

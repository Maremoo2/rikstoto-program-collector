"""Polite, auditable capture of accessible Rikstoto pages with Playwright."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from typing import Any

from .exporting import finish_outputs, write_json
from .parsing import link_identity, parse_race

DOMAIN = "www.rikstoto.no"
USER_AGENT = "RikstotoProgramCollector/1.0 (research; respectful browser capture)"
RACE_URL = re.compile(r"/Spill/([^/?#]+)/[^/?#]+", re.I)
DATE_TAG = re.compile(r"20\d{2}-\d{2}-\d{2}")
PDF_MAX = 25_000_000


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_allowed(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and u.hostname == DOMAIN and not u.username and not u.password


def normal_url(url: str) -> str:
    """Strip fragments, tracking params, and return consistent ordered query fields."""
    u = urlparse(url)
    params = parse_qs(u.query)
    kept = {key: vals[0] for key, vals in params.items() if key in ("race", "p", "date") and vals}
    return urlunparse((u.scheme, u.netloc, u.path, "", urlencode(kept), ""))


def is_race_url(url: str, date: str) -> bool:
    return source_allowed(url) and bool(RACE_URL.search(urlparse(url).path)) and date in urlparse(url).path and bool(link_identity(url)["race_number"])


def race_url(template: str, race_number: int) -> str:
    parsed = urlparse(template)
    params = parse_qs(parsed.query)
    params["race"] = [str(race_number)]
    if "p" in params:
        params["p"] = [f"{race_number}:0"]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode({k:v[0] for k,v in params.items()}), ""))


def discover(html: str, current_url: str, date: str) -> list[str]:
    """HTML links and explicit in-page race URLs; never fabricate a meeting ID."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    found: set[str] = set()
    for tag in soup.select("[href], [data-href]"):
        for prop in ("href", "data-href"):
            target = tag.get(prop)
            if not target: continue
            url = urljoin(current_url, target)
            if is_race_url(url, date): found.add(normal_url(url))
    # Many SPA pages put navigable links in JSON script elements instead of anchors.
    for candidate in re.findall(r"(?:https?://www\.rikstoto\.no)?/Spill/[^\s\"'<>\\]+", html):
        url = urljoin(current_url, candidate.replace("&amp;", "&"))
        if is_race_url(url, date): found.add(normal_url(url))
    return sorted(found, key=lambda u: (link_identity(u)["meeting_id"] or "", link_identity(u)["race_number"] or 0))


class Robots:
    def __init__(self, parser: RobotFileParser | None, policy: str, status: str):
        self.parser, self.policy, self.status = parser, policy, status

    def permits(self, url: str) -> bool:
        # RFC 9309 2.3.1.3: a confirmed 404/410 robots.txt is unavailable,
        # not a Disallow rule. Network errors, 5xx and rate limits fail closed.
        # "warn" never bypasses explicit disallow or unresolved network errors.
        if self.status in ("missing_http_404", "missing_http_410"):
            return True
        return self.parser is not None and self.parser.can_fetch(USER_AGENT, url)


async def check_robots(context, policy: str) -> Robots:
    try:
        response = await context.request.get(f"https://{DOMAIN}/robots.txt", timeout=15000)
        if response.status in (404, 410):
            return Robots(None, policy, f"missing_http_{response.status}")
        if response.status != 200:
            return Robots(None, policy, f"robots_http_{response.status}")
        text = await response.text()
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        return Robots(parser, policy, "checked")
    except Exception as exc:
        return Robots(None, policy, f"robots_error: {type(exc).__name__}: {str(exc)[:300]}")


def html_tables(html: str) -> list[dict[str, Any]]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    output = []
    for table in soup.select("table"):
        rows = [[col.get_text(" ",strip=True) for col in tr.select("th,td")]
                for tr in table.select("tr")]
        output.append({"caption": table.caption.get_text(" ",strip=True) if table.caption else "",
                       "rows": rows})
    return output


async def capture(page, url: str, folder: Path, index: int, *, browser_pdf: bool) -> dict[str, Any]:
    record: dict[str, Any] = {"url": url, "captured_at_utc": now(), "status": "failed"}
    base = f"capture_{index:03}"
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)
        record["http_status"] = response.status if response else None
        record["title"] = await page.title()
        text = await page.locator("body").inner_text(timeout=15000)
        html = await page.content()
        record["text_path"] = base + ".txt"
        record["html_path"] = base + ".html"
        (folder / record["text_path"]).write_text(text, encoding="utf-8")
        (folder / record["html_path"]).write_text(html, encoding="utf-8")
        record["sha256"] = hashlib.sha256(html.encode("utf-8")).hexdigest()
        write_json(folder / (base + "_tables.json"), html_tables(html))
        record["status"] = "captured" if text.strip() and (response is None or response.ok) else "incomplete"
        if browser_pdf:
            pdf_path = base + "_browser_print.pdf"
            try:
                await page.pdf(path=str(folder / pdf_path), print_background=True)
                record["browser_pdf_path"] = pdf_path
            except Exception as exc:
                record["pdf_warning"] = str(exc)
        record["text"] = text
        record["html"] = html
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


async def official_pdfs(page, robots: Robots, folder: Path, *, max_files: int = 3) -> list[dict[str, Any]]:
    """Only follow explicitly linked public program PDFs, never synthesize a PDF URL."""
    anchors = await page.locator('a[href]').evaluate_all(
        '(items) => items.map(a => ({href: a.href, text: a.innerText || ""}))')
    files = []
    for item in anchors:
        href = item["href"]
        label = item["text"].casefold()
        if not source_allowed(href): continue
        if not (".pdf" in urlparse(href).path.casefold() or
                ("pdf" in label and ("program" in label or "løp" in label))):
            continue
        if not robots.permits(href):
            files.append({"url": href, "status": "robots_blocked"})
            continue
        try:
            response = await page.context.request.get(href, timeout=25000)
            if not response.ok:
                files.append({"url": href, "status": f"http_{response.status}"}); continue
            body = await response.body()
            if not body.startswith(b"%PDF") or len(body) > PDF_MAX:
                files.append({"url": href, "status": "invalid_or_large_pdf"}); continue
            name = f"official_program_{len(files)+1:02}.pdf"
            (folder/name).write_bytes(body)
            files.append({"url": href, "status": "downloaded", "path": name,
                          "sha256": hashlib.sha256(body).hexdigest()})
        except Exception as exc:
            files.append({"url": href, "status": f"error:{type(exc).__name__}"})
        if len(files) >= max_files: break
    return files


def summarize(payload: dict[str, Any], expected_races: int | None) -> dict[str, Any]:
    warnings = []
    races = payload["races"]
    if not races: warnings.append("NO_RACES_PARSED")
    if expected_races is not None and len(races) != expected_races:
        warnings.append(f"EXPECTED_{expected_races}_RACES_FOUND_{len(races)}")
    if any(doc["qa"]["warnings"] for doc in races):
        warnings.append("SOME_RACES_REQUIRE_MANUAL_REVIEW")
    if any(c["status"] != "captured" for c in payload["captures"]):
        warnings.append("SOME_CAPTURES_FAILED")
    if payload["discovery"]["status"] != "verified":
        warnings.append("RACE_DISCOVERY_UNVERIFIED")
    return {"races_parsed": len(races), "horses": sum(len(doc["entrants"]) for doc in races),
            "past_start_rows": sum(doc["qa"]["past_start_rows"] for doc in races),
            "warnings": warnings, "status": "REVIEW_REQUIRED" if warnings else "STRUCTURED_UNVERIFIED"}


async def collect(*, date: str, source_url: str, seed_urls: list[str],
                  out: Path, browser_pdf: bool, official_pdf: bool,
                  scan_races: int, expected_races: int | None,
                  delay_s: float, robots_policy: str,
                  browser_executable: str | None = None) -> Path:
    from playwright.async_api import async_playwright
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", date):
        raise ValueError("date must be YYYY-MM-DD")
    if not source_allowed(source_url) or any(not source_allowed(u) for u in seed_urls):
        raise ValueError("source and seeds must be public HTTPS www.rikstoto.no URLs")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = out/run_id
    folder.mkdir(parents=True, exist_ok=False)
    payload: dict[str, Any] = {"run_id": run_id, "created_utc": now(), "source_url": source_url,
        "date": date, "discovery": {"status": "unverified", "urls": [], "notes": []},
        "captures": [], "races": [], "official_pdf_files": [], "qa": {}}
    async with async_playwright() as playwright:
        launch_options = {"headless": True}
        if browser_executable:
            launch_options["executable_path"] = browser_executable
        browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context(locale="nb-NO", timezone_id="Europe/Oslo",
                                             accept_downloads=False)
        page = await context.new_page()
        robots = await check_robots(context, robots_policy)
        payload["robots"] = {"status": robots.status, "policy": robots_policy,
                             "access_decision": "proceed" if robots.permits(source_url) else "stop"}
        if robots.status.startswith("missing_http_"):
            payload["discovery"]["notes"].append(
                "robots.txt returned 404/410; treated as unavailable under RFC 9309, "
                "not as an explicit Disallow. Separate website terms still apply.")
        if not robots.permits(source_url):
            payload["captures"].append({"url": source_url, "status": "robots_blocked",
                                        "captured_at_utc": now(), "error": robots.status})
            payload["discovery"]["notes"].append(
                "No pages requested: robots policy denied or could not be verified. "
                "Check site permissions; do not bypass explicit disallow rules.")
            payload["qa"] = summarize(payload, expected_races)
            finish_outputs(folder, payload)
            await browser.close()
            return folder
        first = await capture(page, source_url, folder, 0, browser_pdf=browser_pdf)
        payload["captures"].append(first)
        links = discover(first.get("html", ""), source_url, date)
        if is_race_url(source_url, date): links.append(normal_url(source_url))
        for seed in seed_urls:
            if not is_race_url(seed, date):
                raise ValueError(f"Seed is not a race URL for {date}: {seed}")
            links.append(normal_url(seed))
        # When SPA route anchors cannot be discovered, explicitly probing races
        # from a user-provided valid seed gives a bounded candidate set.
        if scan_races:
            for seed in seed_urls + ([source_url] if is_race_url(source_url,date) else []):
                for index in range(1, scan_races + 1):
                    links.append(normal_url(race_url(seed, index)))
            payload["discovery"]["notes"].append("Bounded race-number probing; candidate set not verified by official schedule")
        links = sorted(set(links), key=lambda u: (link_identity(u)["meeting_id"] or "", link_identity(u)["race_number"] or 0))
        payload["discovery"]["urls"] = links
        payload["discovery"]["status"] = "candidate_only" if scan_races else "link_extracted"
        seen = set()
        for idx, url in enumerate(links, start=1):
            if url == source_url: rec = first
            else:
                if not robots.permits(url):
                    payload["captures"].append({"url": url,"status": "robots_blocked", "captured_at_utc": now()})
                    continue
                await asyncio.sleep(max(1.2,delay_s))
                rec = await capture(page, url, folder, idx, browser_pdf=browser_pdf)
                payload["captures"].append(rec)
            if rec["status"] != "captured": continue
            doc = parse_race(rec["text"], url, captured_at=rec["captured_at_utc"], html=rec["html"])
            race = doc["race"]
            identity = link_identity(url)
            # Reject SPA fallback/404/index pages posing as a race page.
            if not doc["entrants"] or race["race_number"] != identity["race_number"]:
                rec["status"] = "invalid_race_page"
                rec["error"] = "Race number mismatch or no horse data parsed"
                continue
            identity_key = (race["meeting_id"], race["race_number"])
            if identity_key in seen: continue
            seen.add(identity_key)
            payload["races"].append(doc)
            if official_pdf and len(payload["official_pdf_files"]) < 12:
                payload["official_pdf_files"].extend(await official_pdfs(page, robots, folder))
        await browser.close()
    for cap in payload["captures"]:
        cap.pop("text", None); cap.pop("html", None)
    payload["qa"] = summarize(payload, expected_races)
    finish_outputs(folder,payload)
    return folder


def parse_offline(path: Path, url: str, out: Path, *, expected_horses: int | None = None) -> Path:
    text = path.read_text(encoding="utf-8")
    run_id = datetime.now(timezone.utc).strftime("offline_%Y%m%dT%H%M%S%fZ")
    folder = out/run_id
    folder.mkdir(parents=True,exist_ok=False)
    filename = "capture_000.txt"
    (folder/filename).write_text(text,encoding="utf-8")
    rec = {"url":url,"captured_at_utc":now(),"status":"captured",
           "text_path":filename,"sha256":hashlib.sha256(text.encode()).hexdigest()}
    doc = parse_race(text,url,captured_at=rec["captured_at_utc"])
    if expected_horses is not None and len(doc["entrants"]) != expected_horses:
        doc["qa"]["warnings"].append(f"EXPECTED_{expected_horses}_HORSES_FOUND_{len(doc['entrants'])}")
        doc["qa"]["status"] = "REVIEW_REQUIRED"
    payload = {"run_id":run_id,"created_utc":now(),"source_url":url,
               "discovery":{"status":"offline_single_race","urls":[url]},
               "captures":[rec],"races":[doc],"official_pdf_files":[]}
    payload["qa"] = summarize(payload, 1)
    finish_outputs(folder,payload)
    return folder
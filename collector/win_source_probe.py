"""Read-only public WIN market source discovery. Diagnostic, NOT an odds feed.

Only explicitly supplied first-party race URL; robots and HTTP refusal fail closed.
Records metadata of observed same-host XHR/fetch requests, not private payloads.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .winodds_adapter import parse_public_winodds

CANDIDATE_PATH = re.compile(r"odds|vinner|winner|price|pool|market|betting", re.I)
SENSITIVE_KEY = re.compile(r"token|auth|session|cookie|email|password|secret|account|person", re.I)


def schema_outline(value, depth=0, max_depth=3):
    """Only public JSON structure and types, never values or credentials."""
    if depth >= max_depth:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(k): schema_outline(v, depth + 1, max_depth) for k, v in list(value.items())[:30]
                if not SENSITIVE_KEY.search(str(k))}
    if isinstance(value, list):
        return {"type": "array", "count": len(value),
                "item": schema_outline(value[0], depth + 1, max_depth) if value else None}
    return type(value).__name__


from .pipeline import DOMAIN, check_robots, source_allowed


def validate_probe_url(url: str) -> bool:
    parsed = urlparse(url)
    return (source_allowed(url) and parsed.port in (None, 443)
            and parsed.path.lower().startswith("/spill/")
            and "/api/" not in parsed.path.lower()
            and not parsed.username and not parsed.password)


async def probe(url: str, *, timeout_ms: int = 12000) -> dict:
    report = {"schema": "prewatch_win_source_probe_v1",
              "url": url, "captured_utc": datetime.now(timezone.utc).isoformat(),
              "status": "BLOCKED", "odds_captured": False,
              "win_market_verified": False, "bet_authorized": False,
              "observed_public_requests": []}
    if not validate_probe_url(url):
        report["reason"] = "URL_NOT_PUBLIC_FIRST_PARTY_RACE_PAGE"
        return report
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(locale="nb-NO", timezone_id="Europe/Oslo")
            robots = await check_robots(context, "strict")
            if not robots.permits(url):
                report["reason"] = "ROBOTS_UNVERIFIED_OR_DISALLOWED"
                return report
            page = await context.new_page()
            observed = []
            candidate_responses = []
            raw_winodds = []
            raw_startlists = []
            async def inspect_candidate(response):
                u = urlparse(response.url)
                if (u.scheme != "https" or u.hostname != DOMAIN or
                        response.status != 200 or not (CANDIDATE_PATH.search(u.path) or
                             (u.path.endswith("/starts") and "/api/racedays/" in u.path)) or
                        len(candidate_responses) >= 12):
                    return
                entry = {"path": u.path, "http_status": response.status}
                try:
                    content_type = response.headers.get("content-type", "")
                    if "json" not in content_type.lower():
                        entry["reason"] = "NOT_JSON"
                    else:
                        payload = await response.json()
                        if u.path.endswith("/betdistribution/winodds"):
                            raw_winodds.append(payload)
                        if u.path.endswith("/starts") and "/api/racedays/" in u.path:
                            raw_startlists.append(payload)
                        entry["schema_outline"] = schema_outline(payload, max_depth=7 if "/winodds" in u.path.lower() else 3)
                except Exception as exc:
                    entry["reason"] = f"UNREADABLE:{type(exc).__name__}"
                candidate_responses.append(entry)
            def capture_response(response):
                u = urlparse(response.url)
                if (u.scheme == "https" and u.hostname == DOMAIN
                        and response.request.resource_type in ("xhr", "fetch")
                        and len(observed) < 80):
                    observed.append({"path": u.path, "status": response.status,
                                     "resource_type": response.request.resource_type})
                    if CANDIDATE_PATH.search(u.path) or (u.path.endswith("/starts") and "/api/racedays/" in u.path):
                        tasks.append(asyncio.create_task(inspect_candidate(response)))
            tasks = []
            page.on("response", capture_response)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            report["page_http_status"] = response.status if response else None
            if response is None or response.status != 200:
                report["reason"] = "PAGE_HTTP_NOT_200"
                return report
            await page.wait_for_timeout(2000)
            body = await page.locator("body").inner_text(timeout=timeout_ms)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            report["candidate_response_schemas"] = candidate_responses
            # Read-only diagnostic: actual WIN values with exact startlist join.
            # Do not claim screen agreement or live trading authorization.
            match = re.search(r"/Spill/([^/]+)/", url, re.I)
            race_match = re.search(r"(?:^|[?&])race=(\d+)", url)
            # The odds page need not request starts itself. Query the observed
            # official first-party starts endpoint only when robots permits it.
            if match and raw_winodds and not raw_startlists:
                starts_url = f"https://{DOMAIN}/api/racedays/{match.group(1)}/starts"
                if robots.permits(starts_url):
                    try:
                        starts_response = await context.request.get(starts_url, timeout=timeout_ms)
                        if starts_response.status == 200 and "json" in starts_response.headers.get("content-type", "").lower():
                            raw_startlists.append(await starts_response.json())
                    except Exception:
                        pass
            report["source_capture_counts"] = {
                "winodds": len(raw_winodds), "official_starts": len(raw_startlists)}
            if match and race_match and raw_winodds and raw_startlists:
                race_number = int(race_match.group(1))
                start_rows = raw_startlists[-1].get("result", {}).get(str(race_number))
                if isinstance(start_rows, list) and start_rows and all(
                    isinstance(h, dict) and type(h.get("isScratched")) is bool
                    and type(h.get("startNumber")) is int
                    and isinstance(h.get("horseName"), str) for h in start_rows
                ):
                    expected = {h["startNumber"]: h["horseName"]
                                for h in start_rows if not h["isScratched"]}
                    audit = parse_public_winodds(
                        raw_winodds[-1], meeting_id=match.group(1),
                        race_number=race_number, captured_utc=report["captured_utc"],
                        expected_runners=expected, scratches_verified=True)
                    report["win_startlist_audit"] = {
                        "status": audit["status"], "errors": audit["errors"],
                        "runner_count": len(expected),
                        "api_odds": [{"number": row["number"], "odds": row["win_odds"]}
                                     for row in audit.get("snapshot", {}).get("runners", [])],
                        "market_last_updated": audit.get("market_last_updated", []),
                        "screen_comparison": "NOT_VERIFIED",
                        "bet_authorized": False}
                else:
                    report["win_startlist_audit"] = {"status": "BLOCKED",
                        "reason": "STARTLIST_FLAGS_OR_IDENTITIES_UNVERIFIED"}
            else:
                report["win_startlist_audit"] = {"status": "BLOCKED",
                    "reason": "WIN_AND_OFFICIAL_STARTLIST_NOT_BOTH_CAPTURED"}
            report["observed_public_requests"] = observed
            report["requested_race_number"] = int(race_match.group(1)) if race_match else None
            report["available_win_races"] = sorted(raw_winodds[-1].get("result", {}).keys()) if raw_winodds and isinstance(raw_winodds[-1].get("result"), dict) else []
            report["available_startlist_races"] = sorted(raw_startlists[-1].get("result", {}).keys()) if raw_startlists and isinstance(raw_startlists[-1].get("result"), dict) else []
            report["body_mentions_win"] = "vinner" in body.casefold()
            report["body_mentions_odds"] = "odds" in body.casefold()
            report["status"] = "DIAGNOSTIC_CAPTURED"
            report["reason"] = "REQUEST_METADATA_ONLY;WIN_SCHEMA_UNVERIFIED"
            return report
        except Exception as exc:
            report["reason"] = f"PROBE_ERROR:{type(exc).__name__}"
            return report
        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Explicit verified public race URL")
    parser.add_argument("--output", default="win_source_probe.json")
    args = parser.parse_args()
    result = asyncio.run(probe(args.url))
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

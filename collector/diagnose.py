"""Step-by-step public-site diagnostics. No login, credentials, or bypasses.

Stages: DNS -> TLS -> robots.txt -> plain HTTP -> Chromium -> public race-content QA.
A confirmed robots 404/410 permits an ordinary request per RFC 9309; network
failures, 5xx, 403, 429, and explicit Disallow rules remain fail-closed here.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

HOST = "www.rikstoto.no"
USER_AGENT = "RikstotoProgramCollector/1.0 (public-data diagnostics)"
DEFAULT_URL = "https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0"
TIMEOUT = 15
EXPLANATIONS = {
    "DNS_RESOLUTION_FAILED": "Name lookup failed; check runner DNS or outbound network.",
    "TCP_CONNECT_FAILED": "Could not connect to port 443.",
    "TLS_HANDSHAKE_FAILED": "HTTPS handshake or certificate validation failed.",
    "HTTP_TIMEOUT": "Request timed out.",
    "HTTP_403": "Server refused the request; do not circumvent.",
    "HTTP_429": "Rate limited; do not retry automatically.",
    "HTTP_5XX": "Remote server error; robots gate stays closed.",
    "ROBOTS_MISSING_404": "robots.txt absent (404); not a Disallow under RFC 9309.",
    "ROBOTS_MISSING_410": "robots.txt gone (410); not a Disallow under RFC 9309.",
    "ROBOTS_DISALLOWED": "robots.txt explicitly disallows target path.",
    "ROBOTS_UNVERIFIED": "Could not establish robots rules; no page request.",
    "UNSUPPORTED_BROWSER_PAGE": "Site returned an unsupported-browser message instead of race content.",
    "LOGIN_REQUIRED": "Target is a login page or explicitly demands authentication.",
    "BROWSER_LAUNCH_FAILED": "Chromium failed to launch; check Playwright installation.",
    "BROWSER_NAVIGATION_FAILED": "Chromium could not navigate to the URL.",
    "RACE_DATA_UNVERIFIED": "Page opened but no confidently identified race entries; parsing requires follow-up.",
    "HTTP_PAGE_FAILED": "Public race URL could not be opened via plain HTTP.",
}


def clock():
    return datetime.now(timezone.utc).isoformat()


def safe_url(raw):
    parsed = urlparse(raw)
    if (parsed.scheme != "https" or parsed.hostname != HOST or parsed.username
            or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Only public HTTPS www.rikstoto.no URLs may be tested")
    return raw


def classify_error(exc):
    message = str(exc).lower()
    if isinstance(exc, socket.gaierror) or "getaddrinfo" in message or "name or service not known" in message:
        return "DNS_RESOLUTION_FAILED"
    if isinstance(exc, (ssl.SSLError, ssl.CertificateError)) or "certificate verify" in message:
        return "TLS_HANDSHAKE_FAILED"
    if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in message or "timeout" in message:
        return "HTTP_TIMEOUT"
    return "TCP_CONNECT_FAILED"


def page_issue(text, final_url=""):
    preview = re.sub(r"\s+", " ", text).casefold()
    if ("nettleseren din støttes ikke" in preview
            or "browser is no longer supported" in preview
            or ("eldre versjon av safari" in preview and "oppdat" in preview)):
        return "UNSUPPORTED_BROWSER_PAGE"
    if (re.search(r"(du må logge inn|logg inn for å se|you must sign in|sign in to view)", preview)
            or "/login" in urlparse(final_url).path.casefold()
            or "/logginn" in urlparse(final_url).path.casefold()):
        return "LOGIN_REQUIRED"
    return None


def race_signals(text, html):
    """Weak indicators for diagnostics only, never proof of correct race extraction."""
    t = text.casefold()
    return {
        "html_bytes": len(html.encode("utf-8")),
        "body_characters": len(text),
        "table_tags": len(re.findall(r"<table\b", html, flags=re.I)),
        "race_route_mentions": len(re.findall(r"/spill/[^\"'\s<>]+", html, flags=re.I)),
        "mentions_start": "start" in t,
        "mentions_hest": "hest" in t,
        "mentions_odds": "odds" in t,
    }


def stamp(stages, name, state, code, detail="", **data):
    entry = {"at_utc": clock(), "stage": name, "state": state, "code": code,
             "detail": str(detail)[:1200], **data}
    stages.append(entry)
    print(f"[{state}] {name}: {code} {str(detail)[:240]}", flush=True)
    return entry


def fetch_http(url, *, timeout=TIMEOUT):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as result:
            return {"status": result.status, "url": result.url,
                    "headers": dict(result.headers.items()), "body": result.read(1_000_000)}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "url": exc.url, "headers": dict(exc.headers.items()),
                "body": exc.read(100_000)}
    except Exception as exc:
        return {"status": None, "error": str(exc), "exception": classify_error(exc),
                "url": url, "headers": {}, "body": b""}


def robots_decision(result, url):
    """Returns (may_request_target, decision_code, detail).

    RFC 9309 404/410 => unavailable (not explicitly disallowed).
    Conservative local policy blocks 403/429 and unknown responses as well
    as 5xx/connection failures. Independent website terms still apply.
    """
    status = result["status"]
    if status in (404, 410):
        return True, f"ROBOTS_MISSING_{status}", "Confirmed missing robots.txt; RFC 9309 2.3.1.3"
    if status == 200:
        content = result["body"].decode("utf-8", errors="replace")
        parser = RobotFileParser()
        parser.parse(content.splitlines())
        allow = parser.can_fetch(USER_AGENT, url)
        return allow, "ROBOTS_ALLOWED" if allow else "ROBOTS_DISALLOWED", "Parsed robots.txt for target"
    if status == 403:
        return False, "HTTP_403", "Conservative stop: robots.txt itself returns 403"
    if status == 429:
        return False, "HTTP_429", "Conservative stop: robots.txt rate limiting"
    if status is not None and status >= 500:
        return False, "HTTP_5XX", f"robots.txt returned {status}"
    return False, "ROBOTS_UNVERIFIED", result.get("error", f"robots HTTP {status}")


def diagnostic_dns(stages):
    try:
        addresses = sorted({info[4][0] for info in
                            socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)})
        stamp(stages, "dns", "PASS", "DNS_OK", f"{len(addresses)} addresses", addresses=addresses)
        return True
    except Exception as exc:
        stamp(stages, "dns", "FAIL", "DNS_RESOLUTION_FAILED", repr(exc))
        return False


def diagnostic_tls(stages):
    try:
        with socket.create_connection((HOST, 443), timeout=TIMEOUT) as conn:
            with ssl.create_default_context().wrap_socket(conn, server_hostname=HOST) as secure:
                stamp(stages, "tls", "PASS", "TLS_OK", f"TLS {secure.version()}")
        return True
    except Exception as exc:
        code = classify_error(exc)
        stamp(stages, "tls", "FAIL", code, repr(exc))
        return False


def diagnostic_http(stages, url):
    result = fetch_http(url)
    status = result["status"]
    if status is None:
        stamp(stages, "http", "FAIL", result.get("exception", "HTTP_PAGE_FAILED"),
              result.get("error", "Unknown HTTP error"))
        return False
    if status != 200:
        code = "HTTP_5XX" if status >= 500 else f"HTTP_{status}"
        stamp(stages, "http", "FAIL", code, f"status={status} final_url={result['url']}")
        return False
    text = result["body"].decode("utf-8", errors="replace")
    issue = page_issue(text, result["url"])
    if issue:
        stamp(stages, "http", "WARN", issue, f"HTTP 200 but likely non-program page; final URL={result['url']}",
              content_type=result["headers"].get("Content-Type", ""))
        return False
    stamp(stages, "http", "PASS", "HTTP_200", f"{len(result['body'])} bytes; final URL={result['url']}",
          signals=race_signals(text, text))
    return True


def diagnostic_browser(stages, url, out_folder):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        stamp(stages, "browser", "FAIL", "BROWSER_LAUNCH_FAILED", repr(exc))
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(locale="nb-NO", timezone_id="Europe/Oslo")
            page = context.new_page()
            js_errors, console_errors, requests = [], [], []
            page.on("pageerror", lambda exc: js_errors.append(str(exc)[:350]))
            page.on("console", lambda message: console_errors.append(message.text[:350])
                    if message.type == "error" and len(console_errors) < 15 else None)
            def track(response):
                if len(requests) >= 40 or response.request.resource_type not in ("xhr", "fetch"):
                    return
                parsed = urlparse(response.url)
                if parsed.hostname != HOST:
                    return
                requests.append({"url_without_query": urlunparse((parsed.scheme, parsed.netloc,
                                                                  parsed.path, "", "", "")),
                                 "status": response.status,
                                 "type": response.request.resource_type})
            page.on("response", track)
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3500)
                text = page.locator("body").inner_text(timeout=15000)
                html = page.content()
                status = response.status if response else None
                final_url = page.url
                title = page.title()
                screenshot = out_folder / "browser.png"
                page.screenshot(path=str(screenshot), full_page=False, timeout=15000)
                issue = page_issue(text, final_url)
                signals = race_signals(text, html)
                if status is not None and status >= 400:
                    state, code = "FAIL", ("HTTP_5XX" if status >= 500 else f"HTTP_{status}")
                elif issue:
                    state, code = "WARN", issue
                elif not text.strip():
                    state, code = "WARN", "RACE_DATA_UNVERIFIED"
                else:
                    state, code = "PASS", "BROWSER_PAGE_LOADED"
                stamp(stages, "browser", state, code,
                      f"status={status} title={title[:100]!r} body chars={len(text)}",
                      final_url=final_url, signals=signals,
                      text_preview=re.sub(r"\s+", " ", text)[:350],
                      javascript_errors=js_errors, console_errors=console_errors,
                      public_xhr_fetch=requests,
                      screenshot="browser.png")
                result = state == "PASS"
            except Exception as exc:
                stamp(stages, "browser", "FAIL", "BROWSER_NAVIGATION_FAILED", repr(exc),
                      javascript_errors=js_errors, public_xhr_fetch=requests)
                result = False
            context.close()
            browser.close()
            return result
    except Exception as exc:
        stamp(stages, "browser", "FAIL", "BROWSER_LAUNCH_FAILED", repr(exc))
        return False


def run(url, strategy, out):
    started = time.monotonic()
    out_folder = Path(out).parent
    out_folder.mkdir(parents=True, exist_ok=True)
    stages = []
    dns = diagnostic_dns(stages)
    if dns:
        diagnostic_tls(stages)
        robots_result = fetch_http(f"https://{HOST}/robots.txt")
        allowed, code, detail = robots_decision(robots_result, url)
        state = "WARN" if allowed and code.startswith("ROBOTS_MISSING") else ("PASS" if allowed else "FAIL")
        stamp(stages, "robots", state, code, detail, http_status=robots_result["status"])
    else:
        allowed = False
        stamp(stages, "robots", "SKIP", "ROBOTS_UNVERIFIED", "DNS failed")
    browser_ok = http_ok = pdf_ok = False
    if allowed:
        if strategy in ("http", "both", "all"):
            http_ok = diagnostic_http(stages, url)
        if strategy in ("browser", "both", "all"):
            # Do not change access method to get around explicit HTTP denials.
            last_http = next((e for e in reversed(stages) if e["stage"] == "http"), None)
            if last_http and last_http["code"] in ("HTTP_403", "HTTP_429"):
                stamp(stages, "browser", "SKIP", "HTTP_DENIAL", "Direct HTTP denied or rate-limited target")
            else:
                browser_ok = diagnostic_browser(stages, url, out_folder)
        if strategy in ("pdf", "all"):
            from .pdf_probe import candidate_url, retrieve_pdf
            pdf_url = candidate_url(url)
            if pdf_url is None:
                stamp(stages, "pdf", "SKIP", "PDF_SOURCE_UNKNOWN",
                      "Specify a known race URL including its meeting identifier.")
            else:
                pdf_allowed, pdf_gate_code, _ = robots_decision(robots_result, pdf_url)
                if not pdf_allowed:
                    stamp(stages, "pdf", "SKIP", "PDF_ROBOTS_BLOCKED",
                          f"PDF endpoint not permitted by robots gate: {pdf_gate_code}")
                else:
                    report = retrieve_pdf(pdf_url, out_folder)
                    pdf_ok = bool(report.get("ok") and report.get("text_verified"))
                    stamp(stages, "pdf", "PASS" if pdf_ok else "WARN",
                          report.get("code", "PDF_ERROR"),
                          "One inferred official PDF candidate checked; never proof of complete date coverage",
                          **{"pdf_" + str(k): v for k, v in report.items()})
    else:
        stamp(stages, "http", "SKIP", "ROBOTS_UNVERIFIED", "Access gate not passed")
        stamp(stages, "browser", "SKIP", "ROBOTS_UNVERIFIED", "Access gate not passed")
        stamp(stages, "pdf", "SKIP", "ROBOTS_UNVERIFIED", "Access gate not passed")
    status = "PAGE_REACHED" if (browser_ok or http_ok) else "NOT_REACHED"
    if browser_ok:
        status = "BROWSER_RENDERED_RACE_UNVERIFIED"
    if pdf_ok:
        status = "OFFICIAL_PDF_TEXT_AVAILABLE"
    output = {
        "created_utc": clock(), "target_url": url, "strategy": strategy, "status": status,
        "success": bool(browser_ok or http_ok or pdf_ok), "robots_allows_probe": allowed,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "runtime": {"python": sys.version.split()[0],
                    "github_actions": bool(os.environ.get("GITHUB_ACTIONS"))},
        "stages": stages, "explanations": EXPLANATIONS,
        "important": "A page response does not establish complete or accurate horse/race extraction.",
    }
    Path(out).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"STATUS={status} REPORT={out}", flush=True)
    return 0 if output["success"] else 1


def main():
    p = argparse.ArgumentParser(description="Public Rikstoto connectivity: DNS -> TLS -> robots -> HTTP -> browser")
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--strategy", choices=("http", "browser", "both", "pdf", "all"), default="all")
    p.add_argument("--out", default="diagnostics/report.json")
    # Backward-compatible alias for the original workflow.
    p.add_argument("--browser", action="store_true", help="Deprecated alias; equivalent to --strategy both")
    args = p.parse_args()
    safe_url(args.url)
    return run(args.url, "both" if args.browser else args.strategy, args.out)


if __name__ == "__main__":
    sys.exit(main())

"""Non-invasive connectivity diagnostics for public Rikstoto pages.

No login, proxy bypass, robots override, or scraping. Emits machine-readable
error codes and exits nonzero on an unresolved prerequisite.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse

HOST = "www.rikstoto.no"
USER_AGENT = "RikstotoProgramCollector/1.0 (research; respectful browser capture)"
ERRORS = {
    "DNS_RESOLUTION_FAILED": "Hostname could not be resolved. Check runner DNS and network egress.",
    "TCP_CONNECT_FAILED": "Cannot open TCP connection to port 443. Check firewall/network egress.",
    "TLS_HANDSHAKE_FAILED": "TLS certificate validation or handshake failed.",
    "HTTP_TIMEOUT": "Server did not respond before timeout.",
    "HTTP_403": "Server denied request. Do not bypass access controls.",
    "HTTP_429": "Rate limit. Stop and retry only according to site policy.",
    "HTTP_5XX": "Server error; no conclusion about parsing.",
    "ROBOTS_UNAVAILABLE": "Cannot verify robots.txt; do not crawl in strict mode.",
    "ROBOTS_DISALLOWED": "robots.txt forbids this path for the collector user agent.",
    "PLAYWRIGHT_BROWSER_MISSING": "Install browser with python -m playwright install chromium.",
    "PLAYWRIGHT_NAVIGATION_FAILED": "Browser navigation failed. Inspect Playwright error.",
    "HTML_NO_PROGRAM_DATA": "Page loaded but no program data found; inspect SPA/network and parser.",
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def event(events, stage, ok, code, detail="", **extra):
    item = {"timestamp_utc": utcnow(), "stage": stage, "ok": ok,
            "code": code, "detail": str(detail)[:1200], **extra}
    events.append(item)
    print(f"[{'OK' if ok else 'ERROR'}] {stage}: {code} {str(detail)[:250]}", flush=True)


def classify(exc):
    text = str(exc).lower()
    if isinstance(exc, socket.gaierror) or "name or service not known" in text or "getaddrinfo" in text or "dns" in text:
        return "DNS_RESOLUTION_FAILED"
    if isinstance(exc, (ssl.SSLError, ssl.CertificateError)) or "certificate" in text or "ssl" in text:
        return "TLS_HANDSHAKE_FAILED"
    if isinstance(exc, (TimeoutError, socket.timeout)) or "timeout" in text or "timed out" in text:
        return "HTTP_TIMEOUT"
    if "executable doesn't exist" in text or "browserType.launch" in str(exc) and "install" in text:
        return "PLAYWRIGHT_BROWSER_MISSING"
    return "TCP_CONNECT_FAILED"


def check_http(url, events, stage, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain,text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.status
            body = response.read(512_000)
            event(events, stage, 200 <= status < 400, f"HTTP_{status}",
                  f"{len(body)} bytes read", final_url=response.url,
                  content_type=response.headers.get("Content-Type", ""))
            return status, body
    except urllib.error.HTTPError as exc:
        code = "HTTP_5XX" if exc.code >= 500 else f"HTTP_{exc.code}"
        event(events, stage, False, code, str(exc))
    except Exception as exc:
        event(events, stage, False, classify(exc), repr(exc))
    return None, b""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://www.rikstoto.no/?date=2026-10-18")
    parser.add_argument("--out", default="diagnostics/report.json")
    parser.add_argument("--browser", action="store_true", help="Playwright navigation only if robots permits")
    args = parser.parse_args()
    if urlparse(args.url).scheme != "https" or urlparse(args.url).hostname != HOST:
        parser.error("Only HTTPS www.rikstoto.no is supported")
    events = []
    started = time.monotonic()
    try:
        infos = socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)
        event(events, "dns", True, "DNS_OK", f"{len(infos)} addresses", addresses=sorted(set(x[4][0] for x in infos)))
    except Exception as exc:
        event(events, "dns", False, "DNS_RESOLUTION_FAILED", repr(exc))
    status, body = check_http(f"https://{HOST}/robots.txt", events, "robots_http")
    allowed = False
    if status == 200:
        try:
            robots = RobotFileParser()
            robots.parse(body.decode("utf-8", errors="replace").splitlines())
            allowed = robots.can_fetch(USER_AGENT, args.url)
            event(events, "robots_policy", allowed, "ROBOTS_ALLOWED" if allowed else "ROBOTS_DISALLOWED", args.url)
        except Exception as exc:
            event(events, "robots_policy", False, "ROBOTS_UNAVAILABLE", repr(exc))
    else:
        event(events, "robots_policy", False, "ROBOTS_UNAVAILABLE", "robots.txt HTTP check unsuccessful")
    if allowed:
        status, body = check_http(args.url, events, "page_http")
        if status == 200:
            # No assumptions about JS-rendered content from this HTTP probe.
            event(events, "page_content", True, "RAW_HTML_RECEIVED", f"{len(body)} bytes; not proof of program parsing")
        if args.browser:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    response = page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2000)
                    text = page.locator("body").inner_text(timeout=10000)
                    event(events, "browser", bool(text.strip()), "BROWSER_LOADED" if text.strip() else "HTML_NO_PROGRAM_DATA",
                          f"HTTP {response.status if response else 'unknown'}, body chars={len(text)}",
                          title=page.title())
                    browser.close()
            except Exception as exc:
                event(events, "browser", False, classify(exc) if "install" in str(exc).lower() else "PLAYWRIGHT_NAVIGATION_FAILED", repr(exc))
    else:
        event(events, "page_http", False, "SKIPPED_ROBOTS_NOT_VERIFIED", "No program page request attempted")
    required = ("dns", "robots_http", "robots_policy", "page_http")
    success = all(any(e["stage"] == stage and e["ok"] for e in events) for stage in required)
    result = {"created_utc": utcnow(), "url": args.url, "success": success,
              "elapsed_seconds": round(time.monotonic()-started, 2),
              "runtime": {"python": sys.version.split()[0], "platform": platform.platform(),
                          "github_actions": bool(os.getenv("GITHUB_ACTIONS"))},
              "events": events, "error_explanations": ERRORS}
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Diagnostic JSON: {path}", flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

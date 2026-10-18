"""CLI entry-point. Run with: python -m collector --help"""
import argparse
import asyncio
from pathlib import Path

from .pipeline import collect, parse_offline


def main() -> None:
    p = argparse.ArgumentParser(description="Rikstoto program archive; no betting or account access")
    sub = p.add_subparsers(dest="command", required=True)
    live = sub.add_parser("collect", help="Capture a race day from the public site")
    live.add_argument("--date", required=True, help="YYYY-MM-DD")
    live.add_argument("--source-url", help="Race-day URL; defaults to ?date=YYYY-MM-DD")
    live.add_argument("--seed-url", action="append", default=[], help="Known race URL, repeat for each meeting")
    live.add_argument("--scan-races", type=int, default=15, help="Bounded race probes per seed meeting; 0 disables")
    live.add_argument("--expected-races", type=int, default=None, help="Optional explicit QA threshold")
    live.add_argument("--delay", type=float, default=2.5, help="Seconds between page visits (minimum 1.2)")
    live.add_argument("--out", type=Path, default=Path("output"))
    live.add_argument("--browser-pdf", action="store_true")
    live.add_argument("--browser-executable", help="Use an existing local Chromium binary")
    live.add_argument("--official-pdf", action="store_true")
    live.add_argument("--robots-policy", choices=["strict", "warn"], default="strict",
                      help="Warn allows proceeding only if robots.txt cannot be retrieved; denied paths stay denied")
    offline = sub.add_parser("parse", help="Offline parse a saved body text (.txt)")
    offline.add_argument("text_file", type=Path)
    offline.add_argument("--url", required=True, help="Original race URL for provenance")
    offline.add_argument("--expected-horses", type=int)
    offline.add_argument("--out", type=Path, default=Path("output"))
    args = p.parse_args()
    if args.command == "collect":
        if not 0 <= args.scan_races <= 30: p.error("--scan-races must be between 0 and 30")
        folder = asyncio.run(collect(
            date=args.date, source_url=args.source_url or f"https://www.rikstoto.no/?date={args.date}",
            seed_urls=args.seed_url, out=args.out, browser_pdf=args.browser_pdf,
            official_pdf=args.official_pdf, scan_races=args.scan_races,
            expected_races=args.expected_races, delay_s=args.delay, robots_policy=args.robots_policy,
            browser_executable=args.browser_executable))
    else:
        folder = parse_offline(args.text_file,args.url,args.out,expected_horses=args.expected_horses)
    print(f"Output: {folder}")
    print(f"QA: {folder / 'program.json'}")


if __name__ == "__main__":
    main()
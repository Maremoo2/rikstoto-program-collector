# Rikstoto Program Collector

A local, source-auditable collector for public Norsk Rikstoto race program pages. It **does not place bets**, use logins, or change Betting V3. No fabricated probability estimates.

## What it does

- Collects HTML, visible text and extracted HTML tables as timestamped evidence files, with SHA-256 checksums.
- Discovers race URLs from the race-day page and from user-supplied seed races, optionally probing a bounded set of race numbers in that same meeting.
- Extracts meeting/race metadata, entrants, drivers, year and career statistics, historical race rows with comments, scratchings and displayed WIN odds (snapshots only).
- Preserves unparsed history cells as **raw text**. Fields that cannot be parsed safely remain null; global horse numbers inferred from display order are clearly labeled.
- Creates a separate immutable output folder per run containing `program.json`, `program.sqlite`, `program.xlsx`, `program.pdf`, raw captures and QA warnings.
- Can optionally print HTML pages into browser-generated PDFs and download explicitly linked official PDF files where available and permitted.
- Explicit QA status `REVIEW_REQUIRED` vs `STRUCTURED_UNVERIFIED`; **never declares source completeness verified automatically**.

## Install

Python 3.11+ and Chromium required:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Collect 18 October 2026

Use the known Varig Orkla race as a meeting seed. `--scan-races 15` attempts race numbers 1–15 for that meeting, but does **not** prove that the day's complete schedule was discovered.

```bash
python -m collector collect \
  --date 2026-10-18 \
  --seed-url 'https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0' \
  --scan-races 15 --browser-pdf --official-pdf
```

Other tracks must also be discoverable from the day page, or supplied via additional `--seed-url` arguments. The tool does not invent unknown venue/meeting IDs. For local Linux Chromium installations, pass `--browser-executable /usr/bin/chromium` if the Playwright-managed browser is not installed. If the source's HTML or access policies change, the collector saves what it can and flags failed races. Never infer that `--scan-races 15` means the date contains exactly 15 races.

To limit the initial check to the supplied race:

```bash
python -m collector collect \
  --date 2026-10-18 \
  --source-url 'https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0' \
  --scan-races 0
```

Rikstoto is a dynamic site; browser captures may fail or omit data. Default robots policy is **strict**: if permission can't be established, no site pages are requested and an auditable `REVIEW_REQUIRED` output is generated. `--robots-policy warn` changes only handling of an unavailable robots file, not explicit disallow rules; first review the site's terms/permission. Do not evade site restrictions.

## Offline parsing and QA

When you have copied the page's full visible text into `race6.txt`:

```bash
python -m collector parse race6.txt \
  --url 'https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0' \
  --expected-horses 15
```

Expected reference checks from the supplied example:

| Reference | Value |
|---|---|
| Venue/race | Varig Orkla, race 6 |
| Listed entrants | 15 |
| Active entrants | 14 |
| Scratched | #2 Lesja Loke |
| Historical rows displayed | 75, five per entrant |

Reference data in automated tests are **synthetic examples** based on the submitted layout, not a live downloaded Rikstoto fixture. After a real capture, compare every horse and historical row manually with the program and inspect the `qa` warnings in `program.json`.

## Output

The output is written to `output/<UTC-run-id>/`. The `program.sqlite` file contains normalized `races`, `entrants`, `past_starts`, `scratches`, `win_odds` and `capture_evidence` with an explicit run ID. The Excel workbook has `Løp`, `Hester`, `Historikk`, `Strykninger`, `Odds VIN` and `Kilder` tabs. PDF contains race information and every parsed horse's historical raw rows.

Odds are **momentary displayed WIN prices**, not closing odds or calibrated market probabilities. There is no automatic V3 betting recommendation or Google Sheets write. Historical results are past-performance observations, not a verified separate post-race results feed. This requires a later validated source parser.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Limitations still requiring a live-site acceptance test

The site could not be retrieved from the development environment. Therefore: (1) the current parsing rules are tested against the layout you supplied, not a real fetched browser capture; (2) fully reliable discovery across **all meetings** on a day is unverified; (3) shoe/wagon data and some prior-start fields are retained in raw HTML/text when they cannot be safely assigned; (4) official PDF downloads depend on actual links and access permissions. Fixes should be made from saved captures and regression fixtures, never guesses.
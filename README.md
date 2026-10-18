# Rikstoto Program Collector — exploratory MVP

Captures publicly accessible Rikstoto pages as timestamped HTML and plain text, discovers linked `/Spill/` pages, optionally prints each page to PDF, and produces an Excel capture index, a PDF audit index and a JSON manifest. It **does not yet parse horse histories into structured rows**, guarantee full coverage, or download official program PDFs. Do not treat capture status as FULLY_ASSESSED.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python -m collector.main 'https://www.rikstoto.no/?date=2026-10-18' --discover --pdf
python -m collector.main 'https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0' --pdf
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

Output is in `output/<UTC timestamp>/`. Check `manifest.json` for errors and `discovered_links.json` for crawl candidates. Link discovery is exploratory: the site may use JS navigation, requiring a future documented adapter. Browser print PDFs are not the site's official PDF downloads. The collector does not authenticate, evade access restrictions, or send bets. Check the site's terms and robots rules before scheduled crawling; avoid aggressive request rates.

## First verification

Target date: **2026-10-18**; control race: **Varig Orkla, race 6**. Manually validate the **15 entrants**, **14 active**, scratched **#2 Lesja Loke**, and five prior runs per horse. The current implementation does not automate this verification.

## Next steps

1. Run against the supplied race and manually compare all 15 entrants, scratched #2, 14 active entrants and five past runs per horse.
2. Inspect actual HTML and network behavior to design a supported field-level parser; explicitly flag missing data.
3. Discover official program/PDF/Excel links if present and permitted, preserving their source URLs.
4. Add structured race/horse/start/history schemas, completeness gates and regression fixtures.
5. Separate pre-race snapshots from results and market snapshots; do not change V3 betting logic.

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

Rikstoto is a dynamic site; browser captures may fail or omit data. Robots behavior now follows RFC 9309: confirmed `robots.txt` HTTP 404/410 means unavailable (not an explicit Disallow) and permits an ordinary request, but an explicit Disallow, network error, 5xx, or uncertain policy still stops the collector. For caution, HTTP 403/429 on robots.txt also stops requests. The old `--robots-policy warn` argument no longer overrides those restrictions. Check applicable website terms separately and do not evade restrictions.

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

## Systematisk feilsøking på GitHub

**Utgangspunkt (18.10.2026):** GitHub-hostet Ubuntu løste DNS for Rikstoto,
men `robots.txt` svarte HTTP 404. Den gamle crawleren stoppet før den åpnet
løpsprogrammet. Denne håndteringen er rettet i både collector og diagnostics.

1. **Diagnose:** Åpne **Actions → Rikstoto connectivity diagnostics → Run workflow**.
   Standard `strategy=all` prøver etter tur DNS, TLS, robots-policy, HTTP,
   Chromium og ett mulig **offisielt utvidet PDF-program** for den kjente banen.
   Velg `http`, `browser` eller `pdf` for å isolere en metode.
2. **Les Job summary:** Feilkoder som `DNS_RESOLUTION_FAILED`,
   `HTTP_403`, `HTTP_429`, `ROBOTS_DISALLOWED`,
   `UNSUPPORTED_BROWSER_PAGE`, `BROWSER_NAVIGATION_FAILED`,
   `PDF_HTTP_404`, `PDF_RESPONSE_NOT_PDF` og
   `PDF_TEXT_EXTRACTION_FAILED` angir neste undersøkelse. `ROBOTS_MISSING_404`
   er en **advarsel**, ikke et blokkert tilsynsresultat.
3. **Last ned rikstoto-diagnostics:** `report.json`, konsoll-logg,
   eventuelt `browser.png` og `official_candidate.pdf/.txt`.
   Et 200-svar eller et skjermbilde betyr ikke at hestehistorikken er riktig.
4. **Hvis nettsiden fungerer:** Åpne **Actions → Rikstoto single-race smoke test
   → Run workflow**. Dette tester bare ett kjent løp og arkiverer faktisk
   `program.json`, SQLite, Excel, PDF, kildetekst og QA. Kontroller feltene
   opp mot det opprinnelige programmet før en full løpsdag forsøkes.
5. **Hvis nettsiden ikke fungerer, men den offisielle PDF-en gjør det:**
   Bruk PDF-en som kandidat for program/historikk. Den må få en egen,
   validerbar tabellparser før den kan levere normaliserte hester/starter.
   Nettstedet eller andre autoritative kilder trengs fortsatt for løpende odds
   og strykninger. At formatet virker historisk er ikke bevis for at enhver
   aktuell løpsdag har en tilgjengelig PDF.

### Beslutningsregler

| Funn | Betydning | Neste handling |
|---|---|---|
| DNS/TLS feiler | Miljø-/nettverksproblem | Test i et annet autorisert miljø |
| robots 404/410 | Fil mangler; ikke eksplisitt Disallow | Fortsett én kontrollert forespørsel |
| robots 5xx, nettfeil eller Disallow | Tilgang ikke verifisert eller ikke tillatt | Stopp. Ikke omgå begrensninger |
| HTTP 200, browser feiler | Ulik behandling av klient eller JS | Les browserfeil, screenshot og URL |
| Browser viser program, parser finner null hester | Parser/dataformatproblem | Sammenlign rå HTML/tekst før endring |
| PDF 200 og lesbar tekst | Mulig alternativt programgrunnlag | Valider hestene og historikken |
| PDF 404 eller ikke PDF | Den aktuelle PDF-kandidaten finnes ikke | Bruk HTML/Chromium eller manuelt program |
| Ingen metode virker | Årsaken gjenstår | Bevar logg og undersøk tilgangsvilkår/kildeendring |

Lokalt kan du kjøre:

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q
python -m collector.diagnose --strategy all \
  --url 'https://www.rikstoto.no/Spill/OR_NR_2026-10-18/V?race=6&p=6:0' \
  --out diagnostics/report.json
```

Rikstoto har offentlig indekserte PDF-er som
`/api/programdownload/ProgramPdf/Utvidet/OR_NR_2024-09-22`. Diagnosen
**avleder én kandidat** fra en konkret, brukeroppgitt møte-ID. Den verken
søker gjennom ukjente møte-ID-er eller påstår at PDF for 18.10.2026 finnes.
Automatiseringen bruker ikke innlogging, sesjonscookies eller spillkonto.



## Automatisk morgenarkiv kl. 07:00 norsk tid

Workflow: **Actions → Daily Rikstoto full programs – 07 Oslo**.
Den er konfigurert med `cron: 0 7 * * *` og
`timezone: Europe/Oslo` (sommer-/vintertid). GitHub-hostede planlagte
jobber kan bli forsinket eller enkelte ganger ikke startet ved stor
belastning. Den bruker standard **dagens dato i Oslo**, uavhengig av
GitHub-serverens tidssone, og kan også startes manuelt med `date`.

Collector:
```bash
python -m collector.daily
python -m collector.daily --date 2026-10-18
# Kontroll av ett kjent møte dersom automatisk oppdagelse ikke finner det:
python -m collector.daily --date 2026-10-18 --seed-meeting OR_NR_2026-10-18
```

Programmet henter en avgrenset løpskalender fra Rikstotos observerte
`/api/racedays/dates/<from>/<to>`-endepunkt og
`/api/racedays/multiTracks`, samt forsidelinker for valgt dato.
**Automatisk brukes bare faktiske møte-ID-er funnet i disse kildene.** Ved manuell feilsøking kan en kjent møte-ID også oppgis som `seed_meeting` i GitHub Actions. Manuelle møter logges separat og regnes aldri som bevis for komplett automatisk oppdagelse.
For hvert oppdaget møte lagres offentlig startliste-JSON, uttrekk av
eksplisitte strykningsmarkeringer, offisiell utvidet PDF og lesbar
PDF-tekst (når tilgjengelig), eventuelle løpsprogram-JSON og
kuskeendringer.

**Utgangsmaterialet er ikke garantert komplett**. Automatisk kalender-
oppdagelse på tvers av norske, svenske, franske og kanadiske løpsmøter
er ennå ikke verifisert mot en uavhengig fasit. Mangel på gjenkjente
strykninger betyr ikke nødvendigvis null strykninger. Kl. 07 gir et
tidlig øyeblikksbilde – strykninger kan skje senere. De fullstendige
PDF-ene har ofte fem tidligere starter, men parserens korrekthet må
kontrolleres mot faktisk data før en maskinlesbar historikk erklæres
verifisert.

Hver kjøring lager:
`output/daily/YYYY-MM-DD/<UTC-timestamp>/manifest.json`
og `meetings/<MEETING_ID>/full_program.pdf`,
`full_program.txt`, `starts.json`, `scratchings.json`, eventuelt
`race_XX.json` og `driver_changes.json`. Kildestatus, feil,
SHA-256 og tidspunkter lagres i manifest/kildelogger. Resultatet vises
i **Job summary** og lastes ned fra **Artifacts → rikstoto-morning-programs**.
GitHub-artefakten beholdes **90 dager**, ikke permanent. Jobben kan
være rød ved ufullstendig innsamling selv når noen filer er lagret;
last ned artefakten og se `manifest.json`.

Dette er separat fra Betting V3 og utfører aldri innlogging,
spillehandlinger, oddsvurderinger eller automatiske innsatser.


### Strukturert fullt program og kontroll mot startliste

Den nye PDF-parseren leser hvert faktisk `START KL.`-løp i offisielle
utvidede programmer, og lagrer hestenummer, hestenavn, kusk,
løpstid, distanse, startmetode og rå linjer fra tidligere starter.
**Ingenting oppdiktes** når et felt mangler. For møtet lagres
`meetings/<ID>/structured_program.json`, og alle innleste møter samles
i `structured_program_day.json`.

Kontroll mot ekte Orkla-program 18.10.2026 ga **11 løp, 106 hester og
529 historiske startlinjer**; i løp 6 var det **15 hester og 75 tidligere
starter**. Dette er en faktisk test av ett PDF-dokument, **ikke bevis på
at alle baner eller alle andre lands dokumentformater kan parses**.
Programmet sammenligner PDF-ens løpsnumre med startliste-API-ets
løpsnumre når begge finnes, og gir
`STARTLIST_PDF_RACE_MISMATCH:<ID>` ved avvik.

Strykninger lagres som positive, eksplisitte funn fra offentlige
startlister. Bare bekreftede treff merkes
`SCRATCHED_CONFIRMED_BY_STARTLIST`. For andre hester beholdes
`scratch_state=UNVERIFIED`; **0 funn betyr ikke nødvendigvis ingen
strykninger**. Spesielt klokken 07:00 kan strykninger endres senere.

`completeness_verified` holdes `false` til alle baner og løp er
avstemt mot uavhengig dagsprogram og strykningene er kontrollert.
`CAPTURED_UNVERIFIED` betyr bare at gjenkjente kilder kom inn,
ikke at hele dagen er fullstendig.

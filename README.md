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


### Kontrollkjøring 18.10.2026 – funn og rettelser (etter run 39119416534)

Denne kjøringen hadde **53/53 beståtte tester**, fant 8 program-PDF-er
og hentet offentlige startlister, men ble korrekt merket
`REVIEW_REQUIRED` fordi den gamle PDF-parseren overså svenske/finske
sammenkjedede `START KL.`-markører. Den opprinnelige parseren fant
bare 34 av programmets 67 løpsseksjoner.

En separat OFFLINE-krysskontroll av de faktisk nedlastede PDF-ene og
JSON-startlistene (ingen simulerte løpsdata) etter parserrettelsen fant:

- **7 selvstendige løpsmøter**, **63 løp**, **663 hester** og
  **2 689 historiske startlinjer**.
- **63/63 løp og 663/663 hester** hadde nøyaktig tilsvarende løpsnummer,
  startnummer og hestenavn i Rikstotos offentlige startlistekilder.
- **20 eksplisitte `isScratched=true`** blant de 663 hestene.
  `isScratched=false` for hver av de øvrige er nå mulig å verifisere
  **på tidspunktet** API-responsen ble lagret. Senere strykninger kan
  komme, og kl. 07:00 er ikke en sluttliste.
- Det åttende PDF-programmet, **X1 (Orkla/Årjäng V4 Xpress)**, er et
  sammensatt produkt med 4 allerede inngående løp; det skal arkiveres,
  men ikke legges til som en åttende selvstendig bane.

Den opprinnelige kalenderforespørselen brukte
`/api/racedays/dates/2026-10-11/2026-10-18`. Faktisk svar inneholdt
11.–17. oktober, **ikke 18. oktober**. Ny kode bruker derfor
`/api/racedays/dates/2026-10-18/2026-10-19`
og leser kalenderens egne `raceDayKey`, `raceNumber` og
`isMultiTrack`-felt for uavhengig kontroll.

**Viktig:** Tallene over er lokal offline-reanalyse av kildene fra
den gamle GitHub-kjøringen. De er **ikke bevis** på at den oppdaterte
GitHub Actions-jobben har bestått en ny dagshenting. `completeness_verified`
står fortsatt `false` inntil komplett dagskalender og alle løp er
kontrollert mot uavhengige, fullstendige kilder.


## Morgenarkiv: ny kildekontroll og GitHub Releases (18.10.2026)

**Første virkelige vellykkede innsamling:** GitHub Actions run
[`39120564330`](https://github.com/Maremoo2/rikstoto-program-collector/actions/runs/39120564330)
hadde **65/65 beståtte tester** og arkiverte 8 offisielle program-PDF-er.
7 selvstendige baner ga 63 løp, 663 hester og 20 bekreftede strykninger
ved kontrolltidspunktet. V4 Xpress er et sammensatt, separat program.

### Dokumentert oppdagelse av baner

Den offisielle datoperiode-API-en
`/api/racedays/dates/2026-10-18/2026-10-19` svarte med tom
`result`, selv om det var åtte møter på Rikstotos forside.
Nå benyttes først de **offisielle `raceDays`-dataene fra nettstedets
offentlig tilgjengelige `window.__spaRehydration`**, som på denne datoen
inneholdt de faktiske 8 `raceDayKey`-ene samt `isMultiTrack`.
Når nettstedet oppgir `raceDays.url=/api/racedays`, prøver
innsamleren dessuten dette direkte observerte endepunktet
for krysskontroll. Den lagrer `discovery_spa_schedule.json`,
`discovery_racedays.json` (hvis tilgjengelig) og
`manifest.json.schedule_comparison` med kildeavvik.

**Viktig:** Forsidens `raceDays[].races` viser av og til bare noen
løp som tilbys på forsiden. Parislongchamp hadde eksempelvis bare
løp 3 i forsidens `races`, mens offisiell full startliste viste
løp 1–8. Derfor brukes **startliste-API-et mot PDF-programmet**
for fullstendige løps- og hestetall. Vi setter aldri
`completeness_verified=true` bare fordi to nettstedsendepunkter er enige.

### Lagring som ikke er begrenset til Actions' 90 dager

På en **planlagt morgenkjøring**, eller en **manuell kjøring med
`persist_archive=true`**, laster et separat GitHub Actions-jobbtrinn
ned den fullførte innsamlingen, kontrollerer manifestet og bygger
`rikstoto-<DATE>-<UTC-RUN>.zip` pluss en egen SHA-256-fil.
Deretter opprettes et **utkast (draft) til GitHub Release per kjøring**
med taggen `rikstoto-program-<DATE>-<UTC-RUN>`. Utkastet er kun synlig
for kontoer med skrive-/administrasjonstilgang, selv om selve repoet
er offentlig. Original-PDF-er, startlister og strukturert data blir
**ikke publisert åpent**. Dagsfilene, metadataene og QA beholdes som
private-to-collaborators Release-assets. Vanlige `push`-smoke-tester
publiserer ikke arkiv; et eksplisitt bootstrap-merket commit kan brukes
ved innkjøring.

Du finner egne **draft Releases** under
[Releases](https://github.com/Maremoo2/rikstoto-program-collector/releases)
når du er logget inn som repo-eier. Ikke trykk «Publish release» uten å
ha kontrollert at du har rett til å distribuere kilde-PDF-ene offentlig.
En draft Release er **ikke** det samme som et vanlig Actions-artefakt og
har ikke den automatiske 90-dagers levetiden; arkivet kan fortsatt
fjernes av administrator eller fremtidige tjenesteregler.
GitHub krever en `GITHUB_TOKEN` med `contents:write` for denne
publiseringen. En eventuell avvist publisering vises med feilkode
i `persist`-jobben; da er ikke varig lagring bekreftet.

**Manuell første verifikasjon:** Åpne
[Daily Rikstoto full programs – 07 Oslo](https://github.com/Maremoo2/rikstoto-program-collector/actions/workflows/rikstoto-morning.yml),
velg `Run workflow`, sett `date=2026-10-18`, la møte-seed
stå tomt og behold `persist_archive=true`. Sjekk deretter at
`full-day` er grønn, `persist` er grønn og at Release finnes.
Automatiske tester sjekker også ZIP-integritet og SHA-256-beregning.

### Faktisk kontroll av 07:00

Jobben er tidssoneplanlagt med
`cron: '0 7 * * *'` og `timezone: Europe/Oslo`.
Hver kjøring rapporterer om hendelsen var `schedule`,
`workflow_dispatch` eller `push`, og klokkeslett i Oslo.
**07:00 er foreløpig konfigurert, men er ikke verifisert som en
faktisk tidsutløst kjøring før første `schedule`-event foreligger.**
GitHub kan forsinke planlagte jobber. I offentlige repoer kan
GitHub deaktivere planlagte workflows etter 60 dagers inaktivitet.

**Kvalitetsport:** `CAPTURED_UNVERIFIED` betyr at kjente
strukturerte dagskilder og alle oppdagede møte-programmer er behandlet
og avstemt. Det betyr *ikke* uavhengig bevis for alle løp i hele
markedet. Ved manglende dagskilde eller avkortet møteutvalg brukes
`REVIEW_REQUIRED`. `completeness_verified` forblir `false`.


## Automatisk Pre-Watch-kildebro fra 07:00-arkivet (18.10.2026)

Eksisterende planlagte **Pre-Watch V3.3.12 – Løpsvakt** (09–21 Oslo)
er oppdatert med en read-only kildebro. Den operasjonelle V3/V3.3.12-
modellen, scorer, gates, 25 NOK WIN, shadow-only, historiske frys og
spillebeslutninger er IKKE endret. Ingen ny ChatGPT-task ble opprettet.

GitHub morgenjobben bygger av offentlig PDF og startliste et eget
kildespeil: prewatch_source_v1. Det dekker fysiske norske/svenske møter
og inneholder alle løp og hester, opptil fem tidligere datostemplede
originalutdrag per hest, samt eksplisitt scratchstatus per timestamp.
Den tar ikke med Frankrike/Canada eller V4 Xpress som nye fysiske baner.

Hver kilde-bunt arkiveres som ikke-offentlig **draft GitHub Release** med
navn prewatch-src-YYYY-MM-DD-MEETING-pN-RUNID. Bunter er begrenset til
95 000 tegn og deles ved LØPSGRENSE, aldri midt i et hestefelt.
Det originale arkivets draft Release inneholder en datert indeks
med kildebunt-tagger, antall løp og eksakte løpsnumre per bunt.

Pre-Watch kjører kun lesing gjennom tilkoblet GitHub-connector:
- GET https://api.github.com/repos/Maremoo2/rikstoto-program-collector/releases?per_page=100
- Finn nyeste arkiv DATO = Europe/Oslo i dag, korrekt matching RUNID.
- For hver valgt kildebunt, hent GET /repos/Maremoo2/rikstoto-program-collector/releases/{numeric_id}
  og les release.body som ren UTF-8.
- For DRAFTS kan GET-by-tag gi HTTP 404 selv om Release finnes:
  identifiser alltid release ved numerisk ID fra listingen.
- Prioriter ett faktisk fremtidig, analyserbart NO/SE-løp om gangen.
  Hent ikke alle detaljer ukritisk hver time.
- Merk originalt datostempel og scratch_asof. Morgenens program er
  statisk historikk, aldri gjeldende WIN-odds eller endelige strykninger.
- Kryssjekk eventuelle nye strykninger og utstyr mot ferske offisielle
  kilder. Betfase trenger fortsatt brukerens ferske individuelle
  WIN-priser for alle hester, egen p(win), fair/minimum odds og positiv EV.
- Logg READ_OK / READ_PARTIAL / READ_UNAVAILABLE / STALE i eksisterende
  Google Sheet auditfelt bare hvis write og readback-gates faktisk fungerer.
- GitHub-verktøy utilgjengelig? Ærlig delstatus og ordinær Rikstoto-
  first fallback; aldri fabrikert data eller nye modellregler.

VERIFIKASJON: GitHub-run 39125075007 arkiverte 5 NO/SE-møter,
47 løp og 510 hester i draft-bunter, og connectoren leste både
indeksen og konkrete hestehistorikker fra release.body.
Denne interaktive tilgangen beviser IKKE at en reell planlagt Pre-Watch-
kjøring allerede har logget READ_OK. Det kontrolleres først ved en
faktisk 09–21-kjøring etter installasjonen.

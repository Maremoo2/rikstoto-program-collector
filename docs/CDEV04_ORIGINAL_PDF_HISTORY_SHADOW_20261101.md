# C-DEV-04 — Original-PDF history shadow diagnostics (NO production parser changes)

Date: 2026-11-01. Mode: source-only, offline, reviewable. Collector owns
original PDF bytes, source lineage and extraction diagnostics.
**The independent 390-field gold workflow already exists in Betting
(DATA-004E), and is NOT duplicated or bypassed here.**

## Pre-existing verified source contract

The existing Collector `collector/pdf_program.py` recognizes:
- dated prior-start signatures `DD.MM.YY-N`, including attached track/date
  on German/French source layouts;
- the short original horse name `L D` in Odense, where it must retain
  the full five historical source lines under the correct horse;
- source line `raw_text` for every candidate, date and race number,
  while leaving most other historical fields `None`.

This is a **candidate extraction**, not an independent original-PDF
adjudication of each previous race field.

Original PDF source candidates for immutable read-only E2E:
- Oct 23 Odense `S3_NR_2026-10-23`, artifact `12480651523`,
  official original PDF SHA-256
  `432e795e7ff3965804c26989ccb4f91e5fc6ef5da406415cc3b5dcf72b4e8d7c`.
- Oct 27 Gelsenkirchen `F2_NR_2026-10-27`, artifact `12726250010`,
  original PDF SHA-256
  `1cd2d2dee7dc29ca53c11d851bf09cac37a6ae95ebea5c0d37128707fb040797`.
- Oct 31 Deauville `F1_NR_2026-10-31`, artifact `13032657626`,
  original PDF SHA-256
  `1947bc302ab59c355c8da53d078f384345e06f453fbf9a71df2b7c90a0d28ce1`.

Original PDF bytes are checked against these pinned hashes on replay.
C-DEV-04 now additionally reproduces the Collector `extract_pdf` method
(default `pypdf.PdfReader(...).pages[].extract_text()`, joined with two
newlines) directly from the original PDF bytes and requires its **UTF-8
bytes to be identical** to archived `full_program.txt`. A mismatch is a
hard failure: `ARCHIVED_PDF_TEXT_PROJECTION_MISMATCH`. This validates
reproducibility under the documented installed `pypdf` version, not
independent physical PDF page/column ownership or visual gold.
The race-day and prior-start source dates are never backdated.

## Implemented C-DEV-04 source-only module

`collector/history_shadow.py`:
1. Reuses `parse_extended_pdf` exactly as shipped on Collector main,
   rather than writing a second production history parser.
2. Requires one original PDF and matching archived derived-text file
   for a physical meeting, verifies PDF SHA and text SHA, and rejects
   mismatched date/meeting, duplicate original PDF entries and missing text.
3. Preserves each original candidate line, normalized owner identity
   (meeting/race/horse program number), per-horse ordinal and SHA-256.
4. Adds *diagnostic* post-after-pipe and numeric distance tokens, with
   conspicuous `source_tokens_not_gold` status. No semantic field
   is upgraded by token shape alone.
5. Includes all **13** exact DATA-004C/004E field prompts per source row:
   `date, track, race_number, distance, start_method, result_category,
   placing, km_time, driver, shoes, wagon, gallop, dq`. Only the
   incumbent-conservatively extracted date/race fields can have
   `SOURCE_EXTRACTED_UNVERIFIED` status; all other fields abstain.
   **This is not a claim that the value is source-verified.**
6. Explicit `source_publication_time_attested=false`,
   `pit_certified=false`, `bet_authorized=false`,
   `data004e_holdout_verified=false`,
   `data004e_holdout_390_accepted=0`,
   `production_parser_changed=false` and
   `production_parser_approved=false`.
7. Source projection proof requires actual `pypdf` extraction parity
   against original PDF bytes; records `pdf_text_projection_reproduced_from_original_pdf`,
   extractor version, PDF page count and SHA-256. No assertion of
   visual source-page transcription or independently accepted labels.
8. CLI only reads an already-available ZIP. It prints summary by default,
   or writes an explicitly requested new private local diagnostic file
   with exclusive-create mode. It cannot replace original archive bytes.

Use example (private terminal, original archive already present):

```bash
python -m collector.history_shadow \
  --archive /private/oct27-original.zip \
  --meeting F2_NR_2026-10-27 --date 2026-10-27 \
  --pdf-sha256 1cd2d2dee7dc29ca53c11d851bf09cac37a6ae95ebea5c0d37128707fb040797 \
  --output /private/F2_history_shadow.json
```

The output is **unverified original-source candidate evidence**, not
independently verified gold. Do not publish original source rows or
private reviewer CSVs in a public repository.

## Relationship to the 390-cell independent holdout

Betting issue [#104](https://github.com/Maremoo2/Betting/issues/104),
`docs/DATA004C_BLIND_GOLD_REVIEW.md` and
`docs/DATA004E_DOUBLE_READ.md` are the sole authoritative research
workflow for the **frozen 30 × 13** holdout:
10 PARSED + 10 PARTIAL + 10 UNPARSEABLE rows across 24 original PDFs.
Current accepted source gold = **0/390**. The 60-row DATA-003B sample
has **780 development field evaluations**, not unseen holdout accuracy.

Still required, outside this automated engineering work:
1. Original PDFs for all 24 holdout programs rehashed and visually read
   by two independent actual reviewers.
2. Separately sealed per-cell source page rectangles and human
   status/value/code for all 390 cells, with explicit AMBIGUOUS/UNAVAILABLE.
   Never infer gallop=False or dq=False from missing printed symbols.
3. Third-party adjudication, accepted private gold manifest and
   reviewer-independence signoff.
4. Freeze old and candidate parser versions before any blind comparison,
   report stratified field precision/recall/abstentions/new wrong values.
5. Only after separate HQ approval, propose a future **production** parser
   PR based on accepted gold. No automatic merge or source reclassification.

## C0–C7 boundary

C1 independent complete NO/SE day/race denominator = BLOCKED;
C2 source originals = PARTIAL across history; C3 current exact
PDF/startlist snapshot cohort = PARTIAL (PR #47 separate);
C4 **390 gold accepted = 0**; C5 physical alias = PARTIAL;
C6 prospective immutable T−4 PIT = BLOCKED; C7 14 operational days = BLOCKED.
GitHub test success is not LIVE_VERIFIED or HQ_ACCEPTED.


## New regression boundary (C-DEV-04 original text parity)

The added test fixture contains a **genuine but wholly synthetic PDF**
generated with ReportLab and re-extracted with pypdf. Negative tests
tamper with archived text (horse name/date) while keeping the original
PDF SHA correct, and must fail without producing source-backed history.
The three immutable original Odense, Gelsenkirchen and Deauville archive
PDFs are replayed through the same byte-exact gate. Their output is
diagnostic only: no 390-field holdout gold, no human original-page review,
no prospective C6 timestamps and no betting-model promotion.

No PDF or JSON original archive is rewritten by this work. Because the
extractor library's behavior can change across versions, the exact
pypdf version is retained in each successful report. Version-dependent
mismatch fails closed until independently investigated; it must never be
silently corrected or counted as validated history.

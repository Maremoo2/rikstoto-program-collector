# C-DEV-04 P0 — 24 original PDF source receipts across seven Collector archives

**Scope:** read-only Collector *physical PDF source integrity*. No independent
history row/field gold, no Betting implementation, no production parser
change, no live data fetch or historical writeback.

## Frozen external reference, not a second Betting implementation

The public Betting repo already freezes a 30-row holdout (10 PARSED,
10 PARTIAL, 10 UNPARSEABLE) with **24 distinct original PDF programs
in seven original Collector GitHub Actions archives**. Its source index is
`research/data004-holdout-source-pdf-evidence-v1.json` at commit
`deec4e240293f43261d368c546faa6437f912472`; pinned Git blob
`e39363275abaffae4044b41e5c52f1765c26790e`.

Collector's new `holdout_pdf_source_replay.py` takes that **external,
immutable input**, with no copy of Betting gold/locators/selection code.
The referenced index contains a meeting, PDF SHA-256, physical page
count and original Collector artifact ID for each program. Each record
is a PDF **program**, not a source-confirmed sample horse or history
row. The 30 sample IDs, 390 prompts and human reviews remain wholly
within Betting's independent DATA-004E review workflow.

## Verification performed by Collector

The module reuses `archive_integrity_audit.audit_archive_zip` to
check original manifest receipts, unsafe/duplicate ZIP paths,
PDF/JSON raw integrity and legacy source limitations.

It then independently checks each of the **24 frozen program records**:
1. Original artifact identity and the **exact** manifest day/run
   directory; rejects same-SHA PDFs borrowed from a different run,
   duplicate ZIP entries, malformed indexes or mismatched source dates.
2. Full source PDF original bytes SHA-256 against the Betting index,
   with a conservative 64 MB per-PDF read-only bound.
3. Physical PDF page count via pypdf against the source index's
   previously recorded page count.
4. Presence and exact PDF SHA of the first-party Rikstoto
   `PDF_OK` HTTP request receipt for the correct meeting/URL/path.
   Missing/mismatched receipt is BLOCKED even if PDF bytes match.
5. Original JSON receipts lacking HTTP raw bytes remain explicitly
   counted as **legacy unverifiable**, not retroactively certified.
6. Whether paired derived PDF text is present. Byte-for-byte
   text/PDF extraction parity is **not** claimed by this PR:
   separate PR #51 implements that more demanding check.
7. The index itself is read and Git-blob checked against the
   frozen Betting commit; archive IDs are exact, no collection
   of newer replacement sources.

`ORIGINAL_PDF_COHORT_SOURCE_ONLY_VERIFIED` means only that the PDF
source corpus was present with original bytes, pages, capture
identity and corresponding first-party request receipts.
It does NOT certify the PDF's derived text fidelity, a source
publication time, a physical race/calendar denominator, an
individual horse history row, or any of the 390 DATA-004E gold cells.
If a source is unavailable or disagrees, status is
`BLOCKED_SOURCE_PROGRAM_COHORT` with explicit meeting-level errors.

## Original source artifacts

Original GitHub Actions artifact IDs (October 18–24 2026):
`12135567920`, `12152059609`, `12211357452`,
`12219187865`, `12218163952`, `12219320854`,
`12210589268`.

The read-only GitHub workflow downloads those exact seven archives.
It checks the public Betting source index at the pinned commit, pins
its Git blob SHA, then audits all original program PDFs. It does not
use Betting's CSV double-reader scripts, modify Betting or publish
raw PDF/page text or unverified private review labels.

## Data quality and C0–C7 acceptance boundary

- **C0:** A green source audit is not HQ acceptance. As of this work,
  `main.protected=false`, public repository rulesets `[]`
  and `HQ_REVIEWER_LOGINS` was missing. P0 issue #50 tracks
  governance bypasses. Authorized HQ must enforce branch protection
  and approve exact PR heads; DEV must not merge.
- **C1:** An archival set of PDF programs (including Xpress or foreign
  meetings) is *not* the complete authoritative calendar for physical
  NO/SE trotting races. 14-day >=95% remains BLOCKED.
- **C2:** Original PDF and legacy JSON raw provenance are reported
  separately. Legacy JSON cannot be backfilled.
- **C3/C5:** A valid program PDF is not independent proof of complete
  race/horse identity. The already-verified Nov 1 21/21 NO/SE
  observed race matches are **not** an independently sampled denominator.
- **C4:** `data004e_holdout_gold_pairs_accepted=0` out of 390
  until two independent visual reads, adjudication and sealed gold.
  Missing symbols never imply `gallop=False` or `dq=False`.
- **C6:** `source_first_publication_timestamp_attested=false`
  and `c6_t_minus_4_pit_certified=false`. HTTP capture time
  does not prove earliest source publication, nor T−4 PIT.
- **C7:** 14 verified consecutive operational days and HQ acceptance
  remain BLOCKED.

No production parser, betting model, scores, odds, staking, BET gates
or collector runtime endpoints are changed.

## How to run without changing source archives

Download the seven official artifacts privately and provide the
frozen Betting source JSON as a local file, then run:

```bash
python -m collector.holdout_pdf_source_replay \
  --source-index /private/data004-holdout-source-pdf-evidence-v1.json \
  --expected-index-blob-sha1 e39363275abaffae4044b41e5c52f1765c26790e \
  --archive 12135567920=/private/original-12135567920.zip \
  --archive 12152059609=/private/original-12152059609.zip \
  --archive 12211357452=/private/original-12211357452.zip \
  --archive 12219187865=/private/original-12219187865.zip \
  --archive 12218163952=/private/original-12218163952.zip \
  --archive 12219320854=/private/original-12219320854.zip \
  --archive 12210589268=/private/original-12210589268.zip \
  --output /private/CDEV04_original_24_PDF_source_replay.json
```

The output uses exclusive-create mode and cannot overwrite original
ZIPs or source-index input. A nonzero code is returned for missing
or invalid sources. The report is a source QA diagnostic, not
permission to promote any candidate or to merge.

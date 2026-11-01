# C-DEV-06 — original-PDF receipt timing vs PDF-derived T−4 clock (shadow only)

Date: 2026-11-01. Mode: offline, read-only original-source audit.
No Collector daily runtime, Betting V3.3.12, A-WATCH, risk/exposure,
model, stakes, settlement, original archives or historical records changed.

## Concrete missing quality check

Collector's original manifest contains retrieval completion `at_utc` for
successful first-party original PDF responses and their raw SHA-256;
its PDF text contains program start clocks. It previously had no
isolated, per-race diagnostic relating these two **different** timestamp
classes. A PDF receipt at or before the parsed T−4 clock is *not* a
prospective T−4 snapshot, and neither source time is independently
attested as the actual provider first-publication time.

New `collector/pit_source_snapshot.py` composes **existing**:
- `archive_integrity_audit.audit_archive_zip` (unaltered original
  manifests, PDF/JSON bytes, path and SHA readback);
- `no_se_calendar.audit_no_se_trot_discovery` (NO/SE **typed first-party**
  trotting candidates only; NEVER infer country/sport from ID);
- `history_shadow.replay_original_archive` (PDF source SHA + exact
  PDF→derived-text reproducibility with pypdf);
- `pdf_program.parse_extended_pdf` (existing conservative PDF race
  number and printed start clock; no new parser);
- `source_integrity.time_blocker` (midnight placeholder blocked).

A per-race observation is recorded only where an archived unique
original PDF request receipt matches the correct first-party source
URL, SHA, meeting path and explicit offset-aware **UTC**
retrieval-completion timestamp. The race must have a PDF-explicit
physical number, no duplicate, valid source-text start clock
and no local DST ambiguity/nonexistent time. The only possible
timing classifications are:

- `PDF_CAPTURE_EARLIER_THAN_UNVERIFIED_TMINUS4`
- `PDF_CAPTURE_AFTER_UNVERIFIED_TMINUS4`
- `RACE_SOURCE_CLOCK_OR_IDENTITY_UNVERIFIED`

**Do not interpret EARLIER as T−4 PIT success**: a morning PDF capture
can precede T−4 by hours, and a later scratch/start-time/source
revision may never have been collected. The original observation
timestamp is NOT the first publisher timestamp. An arbitrary
PDF-program start clock is NOT an independently witnessed actual
start. No market, pricing, horse field freshness or physical full-day
denominator is proven by this diagnostic.

## Original source test

GitHub Actions downloads the unchanged original 1 November 2026
Collector artifact ID `13072403701`. It SHA-verifies the manifest:
`9e3e5731e05b51b34593033d9a958faa5be10496f7423e32bc3a1ca788438751`.
The previous source replay observed 7 official PDFs, 73 original
JSON raw receipts, 2 typed NO/SE trotting physical meeting programs
(Momarken and Solvalla) and 21 source-observed PDF races. All 21
PDF/startlist fields reconciled on that sample, **but this is not an
independent C1/C3 all-race denominator**.

The new replay will record actual relative PDF capture timing
per PDF race using those exact original bytes, and will not fabricate
any missing timestamps or T−4 observations. It prints aggregate source
classification only; individual horse/history source rows are not
exported to GitHub Actions logs.

## Independently replayed original-source results, 1 November 2026

On exact development HEAD `8a4e0404f24019fef8ffc4028fbfd1fb475696c5`:

- Full Collector unit tests **606/606 PASS**
  ([run 41338819521](https://github.com/Maremoo2/rikstoto-program-collector/actions/runs/41338819521)).
- Ruff and **16 synthetic source-timing negative cases PASS**, plus
  original SHA-locked November 1 ZIP replay
  ([run 41338819554](https://github.com/Maremoo2/rikstoto-program-collector/actions/runs/41338819554)).
- Original archived ZIP SHA-256
  `ef500863ba372f81c19ab794a7ae5edb4d5b934069ffd0a37ef9f70e45f4f94e`.
- Original manifest SHA-256
  `9e3e5731e05b51b34593033d9a958faa5be10496f7423e32bc3a1ca788438751`.
- **2/2 first-party typed physical NO/SE trotting meeting PDF receipts**
  have their original SHA independently verified and PDF text reproduced.
- **21/21 source-observed PDF race sections** had an explicit PDF race
  number, parseable local race clock, and a PDF receipt observed
  at least four minutes before that **unverified PDF-derived clock**.
  There were 0 late-receipt observations and 0 unknown race clocks
  in this *captured* sample.
- One Xpress composite product was excluded.
- The original first-party date API result remained
  `EMPTY_RESULT_ARRAY`, so **C1's independent whole-day meeting
  and race denominators are not established**.

**This is NOT 21/21 PIT-qualified races.** In fact:
`history_pdf_source_pit_eligible_races=0`,
`c6_pit_certified=false`, `bet_authorized=false` and
`hq_accepted=false`, as verified by the actual source replay.
The 21 observations say only that an archived *morning* PDF
receipt preceded its own printed race clock by at least four minutes.
They neither prove what was published at T−4, nor actual start
timestamps, later changes, market completeness, or independent
coverage.

The HQ exact-head review workflow remained
`BLOCKED_HQ_REVIEW_CONFIGURATION_MISSING`
([run 41338819534](https://github.com/Maremoo2/rikstoto-program-collector/actions/runs/41338819534)).

## Hard blocked gates

- `source_first_publication_time_attested=false`
- `independent_race_start_time_verified=false`
- `independent_full_day_no_se_denominator_verified=false`
- `prospective_tminus4_snapshot_attested=false`
- `c6_pit_certified=false`
- `live_win_market_verified=false`
- `bet_authorized=false`
- `hq_accepted=false`
- `production_mutation=false`

**C1**: no independent official NO/SE calendar/race denominator or
14-day >=95% acceptance. **C4**: 390 independently labeled gold cells
still need Betting DATA-004E two-reader human review. **C6**:
true T−4 must use contemporaneously captured immutable source versions,
independently attested actual start time, complete horse/scratch/market
eligibility and source-publication timestamps, not a back-calculated
clock from an old PDF. **C7**: 14 operational days and HQ remain missing.

**C0**: independent HQ exact-head review remains separate; as observed
on 1 Nov 2026, main protection was false, ruleset list empty,
`HQ_REVIEWER_LOGINS` missing; P0 issue #50 tracks repeated merges
despite red HQ gate. DEV cannot install bypasses, self-approve or merge.

## Private local example

```bash
python -m collector.pit_source_snapshot \
  --archive /private/original-nov01.zip \
  --output /private/CDEV06_original_tminus4_receipt_diagnostic.json
```

Output is an exclusive newly created local report, not a revised
archive and not a source-of-truth PIT ledger. A nonzero exit on missing
or corrupt sources means BLOCKED; a zero exit only means this
diagnostic produced auditable observations, NOT C6 acceptance.

Status distinctions: IMPLEMENTED and TESTED require exact-head
CI evidence; MERGED, LIVE_VERIFIED and HQ_ACCEPTED must each
be established independently.

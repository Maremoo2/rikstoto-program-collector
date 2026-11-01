# C-DEV-04 P0 — Frozen 24-PDF derived-text reproducibility audit

**2026-11-01 · Source-only Collector code, no production writes.**

## Why this is the next source gate

C-DEV-04's independent DATA-004E gold is still **0/390 accepted
fields**. Collector PR #51 (merged into main without independent HQ
approval) can already verify that `full_program.txt` was reproduced
byte-for-byte from a single original, SHA-pinned `full_program.pdf`
using the incumbent `pypdf` extraction method. PR #52 (also merged
without HQ review) verifies the **24 locked original program PDFs** from
**seven immutable Collector archive artifacts** and the frozen
public Betting source-index Git blob. Neither PR alone measures
extraction parity over **all 24** of those archived original programs.

The new `collector.holdout_pdf_projection_audit` composes these two
existing Collector checks, without duplicating the Betting 390-field
gold validation or implementing a new historical parser.

## Source chain and exact inputs

The external public Betting reference is the **frozen** source index
`research/data004-holdout-source-pdf-evidence-v1.json` at commit
`deec4e240293f43261d368c546faa6437f912472`, Git blob
`e39363275abaffae4044b41e5c52f1765c26790e`.
It comprises 24 source programs across original Collector artifacts
`12135567920`, `12152059609`, `12211357452`,
`12219187865`, `12218163952`, `12219320854`,
`12210589268`.

First, the existing `audit_frozen_holdout_sources` requires **24/24**
original PDF source SHA-256, page count and Rikstoto first-party HTTP
PDF receipts, and exact index identity and seven original captures.
If that baseline fails, no text parity is evaluated or certified.

Then, for every *source-indexed* meeting, the existing
`history_shadow.replay_original_archive` requires the same
manifest day/run identity, re-reads original PDF bytes, reproduces
the original `pypdf` default `extract_text()` projection and
requires byte-for-byte identity with the archived `full_program.txt`.
Only then are its **unverified, source-derived** historical candidate
row counts allowed in this secondary diagnostic report.

Results explicitly partition all 24 programs into:
- `REPRODUCED_PDF_TEXT_SOURCE_ONLY`
- `PDF_TEXT_PROJECTION_BLOCKED` (with a reason, including missing
  text and byte mismatch)

The report gives one row per original PDF *program*, not one
DATA-004E gold label, and avoids publishing horse names, source
history lines, reviewer spreadsheets or field predictions.

## Important acceptance and fail-closed semantics

A technical replay can truthfully return
`COMPLETE_ORIGINAL_PDF_TEXT_PROJECTION_SOURCE_ONLY` only for
**all 24/24 original PDF→TXT byte-identical re-extractions**.
If any original source is unavailable, the frozen source cohort is
`BLOCKED_FROZEN_SOURCE_CORPUS`. If the original PDF provenance is
sound but one or more text projections mismatch, status must be
`PARTIAL_OR_BLOCKED_PDF_TEXT_PROJECTION`, with **every source program
counted in the denominator**.

The CI step runs in `--diagnostic-only` mode to preserve
an *honest negative report* when the projection is not fully
reproduced. Green workflow execution is **not** a green parity
or C4 gate; the explicit `status` and `projection_error_counts`
are authoritative. CLI normally exits nonzero on blocked
status unless explicitly run in diagnostic mode. No silent
override of source discrepancies is permitted.

The existing original source cohort check reported **24/24 original
PDF SHA, page-count and HTTP receipt correlations**, with source-typed
**21 physical / 3 composite** programs and **320 legacy JSON responses
without original raw HTTP bytes**. Those legacy JSON gaps
are not repaired by PDF re-extraction.

Reproducible pypdf text is not a visually verified original page
layout or horse/history row, and does not establish any of the
390 gold fields as correct. It also does not attest original
publication timestamps, full physical NO/SE daily calendars,
T−4 prospective PIT, WIN-market evidence, value-betting or
automated staking.

## Exact gates

- **C0:** source/pytest/Ruff success is not independent HQ review.
  `HQ_REVIEWER_LOGINS`/branch protection in P0 issue #50 remain
  necessary; DEV cannot approve/merge.
- **C1:** `independent_no_se_full_day_denominator_verified=false`
  and `c1_14day_coverage_verified=false`.
- **C2:** SHA and source receipt lineage inherited from existing
  original archive auditor; legacy missing JSON raws remain absent.
- **C3/C5:** derived text parity is not physical complete race/horse
  identity or calibrated >=98% startlist field coverage.
- **C4:** 30 x 13 = 390 independent labels are still 0 accepted.
  Betting DATA-004E independent two-reader gold process is the
  sole review pathway; no new gold, no negative gallop/DQ inference.
- **C6:** `source_first_publication_time_attested=false`,
  `c6_t_minus_4_pit_certified=false`, no as-of timestamp inferred.
- **C7:** no 14 consecutive independently verified days.

**IMPLEMENTED**: isolated development source-only code.
**TESTED**: only after exact-head pytest, Ruff, and seven-archive
source replay; record actual statuses and blocker counts.
**MERGED**, **LIVE_VERIFIED**, **HQ_ACCEPTED** remain false until
the relevant independent gates are actually met.

No Betting/production files, original PDF, JSON, model,
V3.3.12 score, gates, stakes or settlement are modified.

# Collector completion gates | 31 October 2026

**Source-audited research inventory, not a claim that the collector has reached 90% or 100%.**
This report refers to immutable original daily collector source ZIP artifacts, not
the Betting HBI 169-race multi-day archive or an independent official schedule.
No original timestamps, missing horses or P&L records were backfilled.

## Immutable source baseline

| Oslo date | Actions run | artifact | PDF bodies SHA pass | JSON exact HTTP body missing | physical meeting candidates | physical race candidates | horse rows | official PDF/startlist meeting snapshots matched |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-27 | 40487116264 | 12726250010 | 7/7 | 67/67 | 6 | 51 | 617 | 6/6 |
| 2026-10-29 | 40828821019 | 12877782643 | 5/5 | 51/51 | 4 | 34 | 379 | 4/4 |
| 2026-10-31 | 41175937425 | 13032657626 | 8/8 | 80/80 | 7 | 69 | 796 | 7/7 |
| **Total** | | | **20/20** | **198/198** | **17** | **154** | **1,792** | **17/17** |

Each day also contained one X1 multi-track product. These products are
**not** extra physical single-track racing meetings. The 154 denominator is
only source-discovered, non-composite race-reference candidates, not all races
that actually took place. All three collector manifests were
`CAPTURED_UNVERIFIED`, `completeness_verified=false`.
No archive delivers independent complete-day or PIT attestation.

### Confirmed reasons this is not complete

1. **Broken source on merged main:** PR #25 left literal backslash-n
   sequences in `collector/calendar_audit.py`; #26 repairs the import. The
   Oct 31 scheduled capture ran on the *previous* working main commit.
   Never cite that morning run as proof that the post-merge main is healthy.
2. **First-party date range discovery empty:** 27, 29 and 31 Oct
   `/api/racedays/dates/DATE/DATE+1` returned an empty result array despite
   documented meetings in other site sources. Do not infer zero scheduled
   races or independent all-day completeness from first-party overlap.
3. **Legacy original HTTP bytes unrecoverable:** JSON receipts contain a SHA
   of original HTTP bytes while the stored .json was rewritten as a wrapper;
   none of 198 exact raw JSON bodies can be hashed from the historic ZIP.
   All 20 original PDF bodies do verify. #28 preserves future raw JSON.
4. **Race start clocks and physical identities:** 29 of 154 physical race
   rows have `00:00` as a start time, which is unverified. The old parser
   also inferred printed physical race numbers in some PDFs, and X1 aliases
   must be linked by independent field/scratch/full-PDF agreement.
5. **Historical starts under-parsed:** German/French PDF exports join track
   and prior-start date (`GEL26.08.26-5`), causing missed starts. #29
   conservatively restores candidate date/race extraction. A higher count
   is NOT independent proof of accurate row-by-row interpretation.
6. **No historical source publication time:** observed HTTP/request time,
   HTTP Date, generated PDF time and a scheduled `START KL` are different
   concepts. Morning snapshots cannot retroactively prove data published
   before a physical race's canonical T−4 cut-off.
7. **A-WATCH selective WIN parity remains separate:** sources supplied to
   the collector alone do not authorize a score or BET.

## Objective acceptance rubric for 90–100% goal

The following thresholds are **targets to test**, not results achieved:

| Gate | Target | Current evidence | Terminal state |
|---|---|---|---|
| C0 merged main integrity | 3 subsequent main full-test CI passes, no import/runtime errors; no reduced suite | #25 main CI fails, #26 PR 401 green | **FAIL until merged/fresh main** |
| C1 independent whole-day discovery | For defined coverage geography, >=95% of independently enumerated physical races over 14 consecutive days; 100% missing reported, composites separated | Only source-discovered 154 candidates on 3 sampled days | **UNVERIFIED** |
| C2 immutable original capture | 100% successful NEW JSON/PDF responses have original bytes, direct SHA and independent readback (with counters for all failures) | Old 198 JSON absent; PDF 20/20; #28 staged, not deployed | **FAIL legacy; UNVERIFIED future** |
| C3 complete physical race/field | >=98% exact official PDF + same-instant starts matches on independently enumerated eligible race candidates; 100% unresolved flags explicit | 17/17 **meeting snapshot** matches inside discovered subset, not independent date | **UNVERIFIED external denominator** |
| C4 historical parser accuracy | Separate independent 30-row sealed holdout (10 PARSED/10 PARTIAL/10 UNPARSEABLE, 390 semantic fields) and preregistered parser comparison, beyond the developmental 60 rows; no false certainty for missing cells | Betting DATA-003B has 60 DEVELOPMENT rows/780 audited fields; DATA-004D localized 30/30 physical rows in 24 source PDFs, but 0/390 holdout semantic fields independently approved; #29 parser date recovery is not a row-level semantic truth | **BLOCKED independent sealed holdout** |
| C5 physical identity | 100% eligible cross-product references uniquely linked by full field + date + printed number; all ambiguous kept quarantined | X1 composite treated separately, linkage not completely proven | **BLOCKED** |
| C6 PIT certified | 90% of eligible predeclared races with attestable original provider publication clock, T−4 source lineage, complete as-of active field; 100% missing blocked | no independent published-at/T−4 source evidence in these ZIPs | **BLOCKED** |
| C7 prospective operations | 14 consecutive scheduled daily jobs, archived raw+manifest readback, no silent NOOP/coverage promotion | 3 historical sampled days; #30 pinned E2E verifies old gaps | **UNVERIFIED** |

`C1` and `C6` require genuine external evidence; code changes alone cannot
satisfy them. The final completion percentage is **not computable** until
the independently defined denominator and C0–C7 gates are established.
An observed 100% within discovered meetings is not a whole-day percentage.


### DATA-003B development sample versus independent holdout (cross-repo evidence)

The connected `Maremoo2/Betting/docs/DATA004_DIAGNOSTIC.md` records
an existing **DATA-003B development** set: 60 source rows split 20/20/20,
13 fields each = 780 assessments (407 correct, 216 missing, 2 wrong,
35 ambiguous gold, 94 unavailable gold and 26 unresolved parsed values).
These categories must **not** be collapsed into a naive accuracy percentage.
The sample was reused for diagnosis; it is **not an untouched validation set**.
The versioned CSV/checksum files are described as private Project/Library
materials, not guaranteed to be present in the Collector repository.

Betting `docs/DATA004D_GEOMETRY_EVIDENCE.md` and
`docs/DATA004E_DOUBLE_READ.md` document a separate frozen 30-row
holdout (10/10/10) and 24 original PDF digests. All 30 physical horse-row
locations were matched, but **0/390 semantic holdout cells have been
independently verified**; source geometry is not a gold-labelled placing,
time, gallop or DQ. The final 390-cell blinded double review/adjudication
must precede any claim of historical field accuracy. None of this expands
Collector's supported date/race/horse parsing into unverified result semantics.

## Implementation sequence without changing betting

- [#26](https://github.com/Maremoo2/rikstoto-program-collector/pull/26)
  restores import integrity. Must reach verified main CI before production.
- [#27](https://github.com/Maremoo2/rikstoto-program-collector/pull/27)
  fixes concatenated `Løp N` heading, with source-anchored + pinned-archive E2E.
- [#28](https://github.com/Maremoo2/rikstoto-program-collector/pull/28)
  records future original raw JSON bytes and source receipts.
- [#29](https://github.com/Maremoo2/rikstoto-program-collector/pull/29)
  fixes concatenated previous-start dates, no invented performance fields.
- [#30](https://github.com/Maremoo2/rikstoto-program-collector/pull/30)
  enables reproducible raw-source ZIP integrity audits.
- [#31](https://github.com/Maremoo2/rikstoto-program-collector/pull/31)
  introduces source-only daily count diagnostics.

No PR here is approved to merge, promote source-readiness or change betting
logic. After independent review and orderly integration, run source-allowed
prospective captures; only those future captures can prove new raw body
retention and before-start timing. Obtain the independent 60-row parser truth,
a source-attested official schedule and provider publication time rather than
relaxing the completeness gate.

# Phase B P0 — terminal receipts for selective WIN source probes

**Status: diagnostic-only.** This adds observable terminal states to the
existing manual `awatch-selective-win.yml` workflow; it changes neither the
A-WATCH scheduler nor the V3.3.12 decision thresholds.

## Observed incident and reason for the work

The 27 October Betting operational audit established 168 prospective
PreWatchFunnel race IDs for 15–27 October, 138 scored below threshold,
29 partial, 1 spreadsheet formula error, and **zero confirmed A-WATCH**.
The MarketSnapshots dashboard contains only 79 runner-level rows from
13–14 October, and no exact race/market join for these 168 race IDs.
This does **not** prove that real WIN pools were empty; it documents a
missing cross-system evidence bridge.

The existing Collector manual workflow printed only `probed_race_count`
and an unconditional `BET authorization: NO`. A green GitHub Actions
workflow with no qualifying/due races could therefore look similar to a
real completed source diagnostic. Further, the underlying
`win_source_probe.probe()` can return `DIAGNOSTIC_CAPTURED` when
`win_startlist_audit` or screen/API parity fails. That label means some
diagnostic content was retrieved, **not that the market passed**.

## Implementation

The read-only `collector.phase_b_receipts` postprocessor is now called by
the existing `collector.awatch_win_collector.collect()`, with the complete
source-only receipt embedded in the same archived JSON artifact.

Exact terminal states:

| Receipt status | Meaning |
| --- | --- |
| `NO_QUALIFIED_A_WATCH` | No manually submitted candidate satisfied existing frozen score/gate filters; zero legitimate Phase B source probes |
| `QUALIFIED_A_WATCH_NOT_DUE` | A candidate passed the manual-input syntactic gate, but no market collection event was due |
| `DUE_BUT_NO_SOURCE_PROBE` | At least one qualified race was due but source requests could not be scheduled/completed |
| `DUE_SOURCE_INCOMPLETE_OR_BLOCKED` | A due source probe was blocked, missing, contradictory or incomplete |
| `SOURCE_CANDIDATES_UNVERIFIED_NOT_BET` | Due sources had sufficient *reported diagnostic* evidence to merit external review; **not live or betting-approved** |

The report records the number of manually selected candidates, exact
due race IDs, due start timestamps derived from the planner, attempted
probes, immutable-to-report SHA-256 of the diagnostic envelope, explicit
blocker codes per race and a complete terminal count.

The code deliberately **does not equate `DIAGNOSTIC_CAPTURED` with
success**. To earn only `SOURCE_CANDIDATE_ONLY_UNVERIFIED`, a report
must state:

- The exact requested source URL and race number match.
- Both public WIN and official startlist were observed by the
  *diagnostic* (these observations are not independently validated).
- The existing `parse_public_winodds` audit reported
  `STRUCTURE_VALID_UNVERIFIED` with no errors.
- Rendered screen/API parity reported a MATCH for **every** active
  runner; missing/partial fields fail.
- Source capture and *each runner's* reported market update timestamp
  are parseable, prestart, correctly ordered and no older than
  180 seconds at capture.
- Source diagnostics themselves assert neither betting authorization
  nor independently verified live WIN.

The report **does not** verify source raw-byte hashes, a standalone WIN
pool, legal market source access, immutable pre-market calibration,
minimum price, real probability, the true manual Pre-Watch freeze or
actual successful Phase B. The existing public source probe does **not**
currently capture an independently verified standalone WIN pool, so
this receipt cannot make up one.

`manual_prewatch_score_independently_verified=false`,
`complete_operational_phase_b=false`, `bet_authorized=false`,
and `BET_BLOCKED=true` are fixed across every terminal state.

## Testing and integration

Regression tests in `tests/test_phase_b_receipts.py` mock only the
external source-probing function, then execute the unmodified
A-WATCH scoring/scheduling path and the real
`awatch_win_collector.collect()` wrapper. They cover:

- score 69: zero selected/due/probed;
- qualified score 70 but not due: explicit no-op;
- qualified and due with a structurally complete **fabricated**
  diagnostic: source-only candidate, not BET;
- blocked source, false generic `DIAGNOSTIC_CAPTURED`, wrong race/URL,
  missing market update, too-old market update, late/poststart capture,
  missing API/screen parity and improper `bet_authorized=true` claims;
- invalid/duplicate/unmatched probe entries;
- no source probe even when due;
- deterministic no-mutation report SHA-256.

The workflow summary now publishes receipt status and the due/attempted
counts. It does **not** change schedule, input authorization,
permissions, scraping scope or trigger time. The output remains a
seven-day GitHub Actions diagnostic artifact under the existing
workflow settings; even a successful job cannot claim a BET.

No source polling of currently unknown A-WATCH races was triggered to
verify this PR. **Tests are synthetic; real-source acceptance remains
unverified.** The separate live provider failures for French/ Norwegian
full-field admission continue to block production.

## Follow-up acceptance

1. Obtain one real, **prospectively frozen**, official A-WATCH in the
   original Pre-Watch V3.3.12 source and score ledger, not a newly
   manufactured manually supplied score. Preserve its immutable source
   and time.
2. Within a permitted prestart window, receive a full field, verified
   scratches, source/update times, matching WIN API/screen odds, and an
   independently observed **standalone WIN pool** (not V-series pool).
3. Produce a stable source receipt with full original provenance, and
   verify the same exact race across Collector and Betting without
   source-leakage or retrospectively changed scores.
4. Separately produce calibrated, frozen full-field p(win), fair odds,
   conservative minimum price and EV; only the Betting runtime can
   govern BET/WATCH/PASS. Real-money automation is explicitly excluded.

This PR is a small, reversible instrumentation change:
`phase_b_receipts.py`, existing source-only Collector wrapper, tests
and existing workflow summary. Revert it to restore prior behavior.

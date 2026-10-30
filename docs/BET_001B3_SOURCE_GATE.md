# BET-001B3 — Disabled-by-default WIN source evidence gate

## Authority

This is a stand-alone, **offline** diagnostic: `collector.bet001b3_source_gate.audit_source_claim`.
It does not alter any existing `awatch_win_collector`, `win_source_probe`,
Phase B receipt, existing 180-second collector default, workflows or Betting
strategy. No run triggers network collection, production writes or bets.

The original hash-frozen HBI Research V3.2 `HBI_EXECUTABLE_PRICE_CAPTURE_V1`
package is NOT verified in this repository. Its exact five-second clock
definition, source uncertainty, and cache semantics MUST be recovered before
a real checkpoint may be qualified. The 5s setting in this file is the old
**local BET-001A/B diagnostic**, not a reconstructed contract.

## Fail-closed logic

The source claim must carry meeting/race keys, verified official active
roster with one boolean scratch state per runner, a matching public WIN
response (one valid quote per active horse), isolated WIN pool and currency,
receipt and scheduled clocks. Additional evidence requires:
- request start, response receipt (UTC), source update and actual start with
  independent source;
- HTTP status, Date, Age, Cache-Control, source version, clock offset and
  uncertainty with sync reference;
- original raw WIN body paired byte-for-byte with its SHA-256;
- official roster + scratch + pool body digests, source URIs, versions,
  independent field confirmation and checkpoint identity.

Missing, conflicting or implausible evidence => `BLOCKED`.
Even all internally consistent synthetic evidence => `UNVERIFIED` with
`FROZEN_HBI_CAPTURE_CONTRACT_NOT_VERIFIED`. `hbi_live_qualified` and
`bet_authorized` are always false. Hash-shaped strings, flags and HTTP
200 alone are **not** independently authenticated provider evidence.

## Future authorized integration (NOT IMPLEMENTED)

Only after HQ verifies the frozen contract and permitted provider
source access: place this check *after* selective WIN probe and
official scratch/field reconciliation, *before* Phase B source
receipt/Betting handoff. Preserve raw body hashes and split metadata,
keep individual WIN turnover separate from V75/V85, and write a
source-only traceable receipt. Do not open BET-001C/pFund/closing until
separate HQ gates are cleared.

## Regression

`python -m pytest -q tests/test_bet001b3_source_gate.py`

Full collector repository: `python -m pytest -q`. All fixtures are
synthetic and may NOT count toward the 2,000-live-observation research gate.

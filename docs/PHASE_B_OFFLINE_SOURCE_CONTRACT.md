# Phase B P0 — isolated A-WATCH → WIN source contract

**Mode:** synthetic, offline, read-only test fixture. **Not a bet or live source acceptance.**

## Why this is the next binding link

The 27 October prospective Betting V3.3.12 dashboard was independently
read: 168 unique frozen races from 15–27 October, 138
`SCREENED_BELOW_THRESHOLD`, 29 `PARTIAL`, one `#REF!` formula error.
There are 42 scores of 65–69 and no A-WATCH. The 79
`MarketSnapshots` rows in that dashboard cover only 13–14 October
(two distinct races), i.e. there are zero exact-race-market joins for
the 168 sampled races. Absence in that dashboard is **not** proof
the provider could not furnish market odds.

The existing `awatch-selective-win.yml` requires **manually provided**
pre-scored Pre-Watch JSON and `workflow_dispatch`. No automatic BET
or odds decision is emitted. The collector is a **source supplier**,
not the calibrated probability/pricing engine. Promoting a synthetic
source test into a BET would be an architecture and temporal-integrity
violation.

## Minimal deterministic code path

`collector.phase_b_contract` calls the existing:

1. `eligible_race_urls()` + `plan_awatch_market_checks()` with one
   explicitly synthetic score-70 A-WATCH candidate at T-3.
2. An explicit, independently provided *fixture* of the same race's
   official startlist with individual boolean scratching flags.
3. `parse_public_winodds()`, enforcing fresh per-runner odds, complete
   active-field identity, positive decimal WIN prices and source clocks.
4. Printed WIN screen rows matched **for every active starter**
   on number, normalized name, odds and comparable timestamps.
5. A standalone `market_type=WIN` pool fixture with exact race
   identity, positive amount, currency and prestart source times.

The synthetic positive fixture has two active runners and one
explicitly scratched runner, whose quote is **not** used. All horse
names, odds, pot sizes and times in the fixture are fictional
integration examples. They are **not** reconstructed or observed
20 October prices, not calibrated p(win), and not betting advice.

Run locally after installing the repo's dev requirements:

```bash
python -m pytest -q tests/test_phase_b_contract.py
python -m collector.phase_b_contract \
  --input tests/fixtures/phase_b_source_synthetic_v1.json \
  --output /tmp/phase_b_synthetic_contract.json
```

The output file is created exclusively (refuses overwrite), includes
the canonical JSON input SHA-256 and lists each contract error.
The fixture is explicit; real-source input **is refused**. None of
the code performs network requests, GitHub Action dispatch, Sheets
writes, bets or probability estimation.

### A green synthetic report still means BLOCKED for real betting

Even when `technical_source_contract_passed_synthetic=true`,
the report always says:

```json
{
  "fixture_only": true,
  "real_A_WATCH_frozen_evidence_verified": false,
  "actual_source_provenance_verified": false,
  "real_live_WIN_pool_verified": false,
  "calibrated_probability_evidence_verified": false,
  "minimum_price_and_EV_verified": false,
  "full_phase_b_operationally_verified": false,
  "bet_authorized": false,
  "BET_BLOCKED": true
}
```

Do **not** count it as an actual A-WATCH, BET, live WIN pool,
executed trade, realized CLV or empirical predictive observation.

### Negative acceptance tests

The new suite tests: score 69, false A-WATCH gates, changed status,
missing score, late/not-due target, wrong meeting/race/date, missing
scratch verification, duplicate or incomplete runners, scratched
runner in WIN prices, missing WIN quote, stale/future quote clocks,
asynchronous API/screen captures, wrong visible price, V75/V85
pool substituted for WIN, missing/old/future pool, poststart source,
naive clocks and attempted source-to-strategy-field injection.
All must block; no premarket probability or price can be made up.

## P0 empirical next steps (no gate relaxation)

A fully functioning operational chain requires **separate** evidence:

- A real, prospectively frozen Pre-Watch V3.3.12 `A-WATCH` that
  qualifies under the unchanged 70 and subscore gates; source
  citations, runner roster/scratches, historical data and freeze
  timestamp, not a manually invented score.
- A real 2–4-minute-before-start collection on the **same exact race**:
  complete active-field WIN quotes with per-runner source update
  timestamps <=180 seconds, screenshot/API parity, independently
  time-stamped standalone WIN pool and corroborated scratch state.
- An immutable, calibrated **full-field** p(win) snapshot created
  before comparing WIN prices, with a conservative interval,
  independently locked minimum odds, position sizing governance,
  liquidity/market scope, and fully traceable BET/WATCH/PASS decision.
  This must be implemented and controlled by **Betting**, not Collector.
- Actual prospectively verified workflow Actions runs and output
  artifacts. No production promotion on `SUCCESS` without a valid
  event and complete source/probability chain.

As of this handoff: 0 real A-WATCH/BET chain runs verified and 0
new calibrated probability snapshots for the sampled cohort.
`BET_BLOCKED` remains unchanged; do not modify the frozen
V3.3.12 scoring, stakes (25 NOK WIN baseline), Champion, schedule or
production model.

## Rollback and scope

This delivery adds only a separate offline module, fictional JSON
fixture, adversarial tests and documentation. There is **no**
change to the existing market planner, Odds adapter, workflow,
schedules or Betting runtime. Revert its PR to remove the
diagnostic without altering production ingestion.

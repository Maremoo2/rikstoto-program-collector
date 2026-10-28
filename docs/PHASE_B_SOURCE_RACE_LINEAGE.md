# Phase B P0 — exact race lineage across Pre-Watch, Collector and WIN

**Diagnostic-only; no independent prospective A-WATCH attestation or BET.**

## Why this check is required

Collector [PR #14](https://github.com/Maremoo2/rikstoto-program-collector/pull/14)
added terminal market-only source receipts and [PR #15](https://github.com/Maremoo2/rikstoto-program-collector/pull/15)
added per-response Playwright-body SHA-256 and clocks. A receipt with
\`SOURCE_CANDIDATE_ONLY_UNVERIFIED\` still does not show whether the same
race was present in the independently archived morning race queue,
selected by the manually scored A-WATCH submission, had the same
scheduled start, and was quoted in the correct local race-date window.

This new read-only tool **never constructs a new A-WATCH score**. It
joins three *existing* artefacts by **exact meeting ID and race number**:

1. \`scored_prewatch.json\`: the same manually submitted \`meetings/races\`
   format already accepted by Collector, with an additional
   \`frozen_at_utc\` field per race **if supplied** (self-reported
   timestamp, not independent immutable proof).
2. \`prewatch_source_index.json\`: exact original morning Collector
   \`prewatch_source_v1\` index including the per-race
   \`source_ready_snapshot\`, \`source_blockers\`, \`race_key\`,
   \`runner_count\`, \`date_oslo\` and \`created_utc\`.
3. \`awatch_win_diagnostic.json\`: the actual existing Phase B
   \`B_MARKET_ONLY\` response envelope, with original per-race
   \`diagnostic\`, \`receipt\`, and source provenance metadata.

No file is changed in place. The tool re-derives the existing receipt
using \`receipt_from_selective_collection()\` and rejects any
inconsistency rather than trusting a supplied \`BET\` claim.

## Exact checks

For every due race, verify:

- exact \`meeting_id\`, \`race_number\` and \`race_key\` across sources;
- no duplicate race keys in manual or morning records;
- same Oslo calendar date as the dated meeting ID and morning index;
- the original morning source was available before the manually
  supplied Pre-Watch freeze timestamp and before the market probe;
- the manually asserted freeze is before scheduling/start;
- collector due-event start equals exact submitted prestart \`start_utc\`;
- an actual source probe exists with the **exact canonical public race
  URL** and matching source request race number;
- terminal receipt says only \`SOURCE_CANDIDATE_ONLY_UNVERIFIED\`,
  with no source blockers (never a production approval);
- one unambiguous WIN source body digest and one official startlist
  digest, both same source paths, HTTP 200 and prestart UTC clocks;
- WIN adapter's recorded digests match the same two browser response
  digests, with valid reported screen/WIN receipt ordering and no
  more than 90 seconds between captures;
- morning race source QA remains ready; incomplete PDF/startlist
  reconciliation cannot be filled retroactively by later odds.

An earlier or current score **is never re-scored**. A pool (V75/V85)
is never reinterpreted as standalone WIN. The input's
\`frozen_at_utc\` is a **manual assertion**, not a signed preregistration;
and the morning index is still a morning source-quality snapshot,
not current scratch evidence.

## Offline usage

The CLI can be run on a private copy of already created, non-sensitive
diagnostic metadata and source records; it does **not** access a website:

\`\`\`bash
python -m collector.phase_b_race_lineage \
  --prewatch /private/scored_prewatch.json \
  --source-index /private/prewatch_source_index.json \
  --collection /private/awatch_win_diagnostic.json \
  --output /private/phase_b_lineage_diagnostic.json
\`\`\`

Output is created **only when the path is new**. It includes normalized
JSON input digests, explicit per-race reasons, and original body hashes
as recorded in the diagnostic; it contains no raw source bytes or
betting model output. It reports either \`NO_QUALIFIED_AWATCH\`,
\`A_WATCH_SELECTED_BUT_NOT_DUE\`,
\`SOURCE_LINEAGE_BLOCKED\`, or
\`CLAIMED_LINEAGE_MATCHES_BUT_OPERATIONALLY_BLOCKED\`.

Even the best apparent match has:

\`\`\`json
{
  "source_body_hashes_replayed_from_original_bytes": false,
  "manual_prewatch_frozen_prospectively_authenticated": false,
  "original_source_publisher_authority_verified": false,
  "isolated_win_pool_verified": false,
  "full_phase_b_completed": false,
  "real_betting_authorized": false,
  "BET_BLOCKED": true
}
\`\`\`

These false values are **not user-overridable options**. The tool does
not read the optional raw archive from PR #17 and does not turn a SHA
reported by Collector into independent source authentication.

## Synthetic integration tests

\`tests/test_phase_b_race_lineage.py\` generates a sample manual
Pre-Watch payload, an independently mocked morning source index,
and a real output envelope produced by the existing
\`awatch_win_collector.collect()\` with only the HTTP probe replaced
by a fake. Tests include incorrect race/start/day, incomplete
morning readiness, changed and missing source-body SHA metadata,
improper source-authority claims, altered terminal receipts,
wrong screen/WIN timing, missing asserted freeze time,
duplicate source rows, score 69 substitution and overwritten output.

The successful *structural* example is deliberately
\`CLAIMED_LINEAGE_MATCHES_BUT_OPERATIONALLY_BLOCKED\`, not a real
A-WATCH or BET. No source was contacted and no actual probabilities
or market values were used.

## Outstanding operational P0

A complete prospective Phase B needs **independent timestamp-bound
freeze evidence** for the original V3.3.12 decision; a full and
fresh independently verified active race field; private readback
of the actual source bytes with admission policy; a **separate
standalone WIN pool** and exact source time; and a separately calibrated
and frozen **full-field** p(win), fair odds and minimum price under
the existing Betting review contract.

A passing source lineage or generic green Actions run does not satisfy
any of these. No betting, new score weights, V3.3.12 changes, thresholds,
new schedules, source permission bypass or settlement writes are allowed.

## Dependencies and review

This PR targets **main directly** and depends only on the already
merged Collector #14 and #15 source diagnostics. It does *not* depend
on the private-archive recovery PR #17, so there is no stacked merge
risk. Review both PRs independently, require CI on the exact
\`main\`-based branch, and stop before merge.

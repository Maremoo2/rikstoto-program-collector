# C-DEV-02 — original NO/SE trot calendar candidate audit (2026-11-01)

**Status:** Development / source-only diagnostic. **Not C1-certified**.
**Base dependency:** C-DEV-01 draft PR #42 (unmerged).
**Scope:** Collector source discovery only, never Betting p(win)/EV/BET.

## Grounded source evidence

Six immutable GitHub Actions morning ZIP archives (27 Oct–1 Nov 2026) were
read offline. The date-API `/api/racedays/dates/{start}/{end}` had no
usable dated meeting set, while public homepage rehydration and the general
racedays endpoint each displayed concrete meeting keys. Their agreement is
**not** an independent complete-day calendar.

| Date | Archived manifest SHA-256 | Observed NO/SE trot physical meetings | Observed PDF race numbers |
|---|---|---:|---:|
| 2026-10-27 | `afc398eae7bc0b7cb73845432449c0f86f337d3449347e074dcb0cf86b3f355c` | 3 | 28 |
| 2026-10-28 | `6283f7695f9fba5aa5609f882bfedda02b0a4b2f046962c72c5b26a480d25543` | 2 | 19 |
| 2026-10-29 | `0936848546deada25938d8f6e61c4cfe9c41d726137ec2a71863c5022cb76267` | 3 | 26 |
| 2026-10-30 | `49e465224528392b53889f5ce5c17e5f540675a12d96c756ef4f1ca5cf2b745a` | 3 | 26 |
| 2026-10-31 | `17932ad46ef9d96977ff251a144dec097f8b83051f3670005e730f53be1629b2` | 2 | 22 |
| 2026-11-01 | `9e3e5731e05b51b34593033d9a958faa5be10496f7423e32bc3a1ca788438751` | 2 | 21 |
| **Observed total** | — | **15** | **142** |

Those are **observed first-party candidate counts**, not independently
enumerated racing-day denominators. Historical JSON raw bytes are absent in
the pre-Nov-1 legacy archives and cannot be reconstructed.

### Concrete country/sport classification hazards

- `S1_NR_2026-10-28` = SE **gallop**, not Swedish trotting.
- `S2_NR_2026-10-30` = DK **trotting**, not Swedish racing.
- `OV_NR_2026-11-01` = NO **gallop**, not Norwegian trotting.
- `X1_NR_...` and some `S5_NR_...` are composite multi-track
  **products**, not independent physical race meetings.
- No source publication time, complete-day denominator, future-date
  verification, or T−4 qualification is inferred from these archives.

## Additive Collector contract

`manifest.no_se_trot_discovery_audit` exposes:
- Source-typed physical NO/SE trotting candidates, captured IDs, and
  observed PDF race count.
- Missing discovered/collected candidates and manual-seed limitations.
- Conflict/quarantine for differing country, sport, composite flags,
  or a mismatched source meeting ID.
- Unclassified IDs without typed country/sport (no prefix inference).
- Excluded composite products and non-target racing meetings.
- Separate date-API availability and source-disagreement blockers.
- Hard `independent_whole_day_denominator_verified=false`,
  `c1_coverage_eligible=false`, `pit_certified=false`,
  `bet_authorized=false`, irrespective of first-party agreement.

With a `max_meetings` cap, known typed NO/SE physical trot meetings are
prioritized ahead of foreign races and composite products; the full
collection queue and truncated candidates are retained. All other provider
capture and source-response behavior is otherwise unchanged.

## Verification and follow-up

`.github/workflows/no-se-calendar-original-e2e.yml` downloads all six
pinned original artifacts read-only, verifies each original manifest SHA,
replays the added candidate audit, and asserts that neither C1 nor PIT
is ever promoted.

**Still blocked:** independently authoritative physical NO/SE
calendar for today plus the next two days; C1 >=95% over 14 prospective
days; C3/C5 complete per-race runner identity; C6 prospective T-4;
C7 scheduled-run evidence and HQ review. This PR neither initiates
additional live requests nor manufactures independent dates/race counts.

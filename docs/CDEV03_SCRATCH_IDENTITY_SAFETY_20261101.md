# C-DEV-03 P0 — do not promote positive-only scratches before full-field reconciliation

**Source-only code contract, 2026-11-01.** Collector remains responsible
for PDF/startlist identity and temporal source receipts, not betting scores,
p(win), EV, staking or race selection.

## Source-grounded defect in code before this change

- `collector/pdf_program.py` created every entrant with `scratched=False`
  while `scratch_state=UNVERIFIED`. That is a contradictory consumer field:
  a PDF program cannot establish that the runner will start.
- `collector/daily.py` walked the positive-only output of
  `scratch_signals(starts)` and immediately set
  `horse["scratched"]=True` and
  `scratch_state="SCRATCHED_CONFIRMED_BY_STARTLIST"`, using a
  program number **OR** a matching name. The full-field reconciliation
  happened only **after** those side effects.
- When subsequent `reconcile_startlist` returned
  `PARTIAL_OR_UNVERIFIED`, several rejection branches did not undo
  the prematurely confirmed horse flag. This can export a false
  verified scratch even though the PDF/startlist field is not proved.
- `reconcile_startlist` also counted only well-shaped numeric API
  race lists. An *additional* malformed race entry could disappear
  from the known-race denominator. An API runner row whose explicit
  `raceNumber` disagreed with its enclosing race key was not blocked.

These are code-path defects and risks, not evidence that any specific
historic bet was affected. No archived source bytes or prior decisions
are rewritten.

## Narrow behavioral changes

1. `parse_extended_pdf`: raw PDF entrants begin with
   `scratched=null` and `scratch_state=UNVERIFIED`.
2. `stage_unverified_positive_scratch_signals`: retain positive
   source flags as `scratch_signal_candidates` with source path,
   number, name and source evidence. Their verification is explicitly
   `UNVERIFIED_POSITIVE_SIGNAL`. Leave all horse scratched flags
   unknown and no confirmed scratches. Events outside the physical
   race number never get attached to that race.
3. `daily.archive_day` calls the staging helper **before**
   `reconcile_startlist`. Only exact full-field number/name/boolean
   agreement can set an observed active/scratched state. Conflicts
   remain unknown and the complete original starts/PDF source is kept.
4. `reconcile_startlist`: reject a malformed/extra/aliased race-key
   shape instead of silently ignoring it, and reject contradictory
   row-level `raceNumber` when explicitly supplied. Empty or
   synthetic normalized names are not verified identities.
5. Existing all-runners-scratched, inferred physical race number,
   duplicate PDF race and placeholder-name quarantine stays intact.

## Original capture evidence

Original GitHub Actions artifact **13072403701** on 2026-11-01 has
manifest SHA-256
`9e3e5731e05b51b34593033d9a958faa5be10496f7423e32bc3a1ca788438751`,
**7/7** original PDFs and **73/73** original JSON raw HTTP receipts
previously SHA-readback verified. This original capture is
`REVIEW_REQUIRED`, not complete day/PIT certified.

`.github/workflows/cdev03-original-field-scratch-e2e.yml`
read-only downloads the original immutable artifact, checks original
PDF/JSON receipts, reparses archived PDF-derived text, stages observed
positive flags without claim of verification, and replays the archived
official `starts.json` response against each physical meeting. All
unverified races must have `scratched=null` and no confirmed scratches.
The job prints real parsed/reconciled/blocked counts without substituting
any retrospective source-time or complete-day denominator.

## Strict remaining acceptance gates

- **C1:** independent physical racing calendar for NO/SE, 95% over
  14 consecutive days, NOT obtained by this patch.
- **C2:** original new source raw bytes and immutability still required.
- **C3:** at least 98% source-verified exact PDF/startlist field matches
  across the qualified independently enumerated cohort; this replay
  alone does NOT meet the denominator or prospective sampling protocol.
- **C4:** DATA-004 independent gold holdout not promoted here.
- **C5:** independent complete physical-race/runner identity required.
- **C6:** prospective T-4 PIT snapshots; no time inferred from
  source existence in an archive.
- **C0/C7:** full main CI, HQ exact-head review, consecutive scheduled
  operational days and observed failures remain separate gates.

Do not merge before independent HQ acceptance. No betting-side changes,
new provider requests, automated collection or release promotion.

# C-DEV-02 P0 — independent official calendar source intake, Oslo day + 2

**Repository scope:** Collector, read-only/offline diagnostics only.
**Dependency:** PR #44 restores PR #43 onto the real main branch. This
follow-up must target PR #44; both require separate HQ review.
**No live collection, original archival rewrites or Betting changes.**

## Verified source situation: 2026-11-01

The Rikstoto original Nov 1 archive is immutable and identified by
GitHub Actions artifact 13072403701, manifest SHA-256
`9e3e5731e05b51b34593033d9a958faa5be10496f7423e32bc3a1ca788438751`.
It contains 7 meeting records, 6 physical and 1 composite, with 56
observed physical race sections and 605 observed horses. It is **NOT**
an independently verified full race day.

From its *first-party* source metadata, the physically typed NO/SE trot
meetings are `MO_NR_2026-11-01` (Momarken; 9 original-PDF race
numbers) and `S1_NR_2026-11-01` (Solvalla; 12 original-PDF race
numbers): 2 physical venues and 21 observed PDF race numbers. The
Rikstoto `OV_NR_...` meeting is NO **gallop**, and `X1_NR_...` is
a multi-track composite product; neither is a new physical trot venue.

### Separate published-calendar findings (not original-HTTP receipts)

- Norway: Det Norske Travselskap (DNT) official schedule
  https://old.travsport.no/Sport/Terminliste/
  lists Momarken on Nov 1, Varig Orkla Arena on Nov 2 and Bjerke
  on Nov 3. This is a **meeting-level** schedule.
- Sweden: Svensk Travsport official front page
  https://www.travsport.se/ displayed Solvalla on Nov 1.
- Swedish Nov 2/3 venue lists (Årjäng, Halmstad, Mantorp;
  Axevalla, Eskilstuna) appear in third-party schedule results,
  e.g. https://ryttaravenyn.se/tavlingar?from=2026-11-01&kategori=TRAVSPORT&sida=1&to=2026-11-30
  and https://www.travkoll.se/Kalender . These are research leads,
  **not** an independent authoritative source ledger. Site listings
  differ in product/scope; Mantorp appears in one venue list but not
  the other. No inferred complete SE source list.

None of these website views was captured with authenticated original
source HTTP bytes in the Collector environment. A search result or
rendered HTML snippet MUST NOT be converted into a fabricated raw-byte
receipt or claimed official first-published timestamp.

## Implemented contract: independent_official_calendar_evidence_v1

`python -m collector.independent_day_window` accepts archived Collector
manifest files and **locally retained official source-page copies** for
the explicit Oslo date and the next two dates.

Example diagnostic invocation:

```bash
python -m collector.independent_day_window \
  --today 2026-11-01 \
  --manifest 2026-11-01=/private/2026-11-01/manifest.json \
  --source-bundle 2026-11-01=/private/2026-11-01/official-index.json \
  --output /private/no-se-day-plus-two-diagnostic.json
```

The independent index must already exist; this command NEVER fetches
sites or creates first-party dates, odds or races. The source bundle
is a JSON object with `schema`, `date_oslo` and a nonempty `sources`
array. Each source item requires:
- `country` exactly NO or SE and HTTPS URL from that country's
  DNT/Svensk Travsport official hostname allowlist.
- `http_status=200`, `observed_at_utc` as UTC with offset,
  `raw_path` relative to index directory and `raw_sha256` for its
  original file bytes. A claimed publication-time attestation is
  rejected rather than manufactured.
- `meetings`: each row has `date`, `venue`, and `evidence_excerpt`
  that must be contained in the verified local source-page bytes and
  must include both venue text and an explicit unambiguous ISO
  (`YYYY-MM-DD`) or Norwegian `DD.MM.YYYY` date.

This hash+text verification establishes only consistency between the
**local claimed source copy** and its declared schedule entries.
A caller-controlled URL is NOT authenticated transport/provenance.
No official source bytes are invented or committed to the repository.

The per-day report explicitly distinguishes:
- Official venue-name excerpt candidates matched to source-typed
  physical NO/SE trot Rikstoto meeting IDs (not a numeric ID guess).
- Official venues not matched by the Collector, conflicting/ambiguous
  matches, and Collector candidates not independently corroborated.
- Missing country snapshots, missing complete three-day manifests,
  invalid source hashes/excerpts and missing physical race counts.

For avoidance of doubt:
`independent_meeting_denominator_verified=false`;
`independent_race_denominator_verified=false`;
`coverage_percentage=null`;
`c1_14_day_coverage_eligible=false`;
`pit_certified=false`;
`bet_authorized=false`.

The parser does not infer full official race numbers from a
meeting-level season/terminliste or turn two first-party Rikstoto
schedules into independent proof.

## Exit criteria still open

1. Obtain independently authorized original official NO/SE daily
   schedule *and* full physical race program source bodies for today+2.
2. Capture raw page HTTP response/provenance with authorized transport
   and verify immutability, scope, date and meeting/race enumeration.
3. Reconcile venue aliases and all physical race numbers. No silent
   alias inference from X1 products or ID prefixes.
4. Independently validate 14 consecutive complete days and verify
   C1 >=95% with full denominators; run C3/C5 full-field gates.
5. Require HQ exact-head review/approval, main CI and live prospective
   evidence before operational or PIT readiness.

This PR is a safe **dependency bridge** for real source-intake work,
not a claim that the sources or the 14-day acceptance series exist.

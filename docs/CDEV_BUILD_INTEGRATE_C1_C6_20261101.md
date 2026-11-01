# MASTER ROADMAP V5.0 – BUILD/INTEGRATE C1 original official source intake

2026-11-01. Development only. No production changes, external writes,
scheduled network jobs, Betting score/gate changes, source backfills or merges.

## Why code was missing

The incumbent C-DEV-02 independent-day-window comparer already validates
locally supplied NO/SE official calendar page copies, reviewable date/venue
excerpts and SHA hashes. It cannot itself obtain original official HTTP
responses, so actual future C1 source acquisition lacked a complete intake.
A PDF from Rikstoto is not an independent Norwegian/Swedish race calendar.

This implementation builds the missing input workflow; it REUSES existing
source readback and comparison rather than creating another calendar matcher.

## Code now available

- collector/official_calendar_capture.py: opt-in CLI that GETs BOTH NO
  and SE approved first-party calendar sources with default OS TLS
  verification, redirect rejection, bounded response bytes and
  robots.txt checked for the exact URL. HTTP 403/429/non-200,
  non-UTF8, missing robots, disallow, changed URL or incorrect
  content type BLOCK source capture. It does not enumerate race IDs
  from arbitrary HTML or silently claim that a page shows every race.
- Original response and robots bytes go to an existing private,
  user-owned 0700 directory *outside the repo*, using the incumbent
  append-only exclusive writer, file mode 0600, full SHA readback,
  and no overwrite. A new source bundle conforms to the incumbent
  independent_official_calendar_evidence_v1 input. Its meetings list
  starts EMPTY deliberately.
- The annotate command accepts an explicitly reviewed JSON of
  source excerpts/venue/date claims, checks each excerpt against its
  original retained page using the EXISTING read_official_bundle,
  then creates a NEW bundle with original raw source untouched.
  This is SOURCE-GROUNDED MANUAL CANDIDATE RECONCILIATION, not a
  declaration of independently complete official meeting/race counts.
- collector/official_calendar_integration.py accepts the existing
  original Collector ZIP(s) and independent source bundle(s) over
  Oslo day/day+1/day+2. It uses the incumbent archive_integrity_audit
  and independent_day_window.audit_window; it fails closed on missing
  captures, corrupt originals, mismatched day, absent official pages.
  No source row is counted as independently complete.

## Local opt-in source acquisition (never automatic)

Prepare a private directory with mode 0700 outside the repository,
review access terms and robots, then run only when explicitly authorized:

    python -m collector.official_calendar_capture capture \
      --day 2026-11-02 --private-root /private/c1-sources \
      --no-url https://old.travsport.no/Sport/Terminliste/ \
      --se-url https://www.travsport.se/

If either provider blocks robots/network or the page is not UTF-8,
the attempt blocks. A successful original-byte capture is still not
the official full-day event count, first publication time, source
transport signature or a C1 acceptance.

For a HUMAN-REVIEWED, source-attached candidate list, create a private
claims JSON with NO and SE lists. Each item has date, venue and an
evidence_excerpt copied verbatim from the captured source; the
existing C1 reader checks the excerpt really appears in the raw page.
Save the reviewed candidate bundle to a NEW filename:

    python -m collector.official_calendar_capture annotate \
      --bundle /private/c1-sources/<capture>.json \
      --claims /private/reviewed-claims.json \
      --output /private/c1-sources/<capture>.reviewed.json

Then the existing source comparator can be run directly with source
bundles and Collector manifest JSON, or the new integration CLI can
accept original Collector ZIP archives:

    python -m collector.official_calendar_integration \
      --start-day 2026-11-01 \
      --original-archive 2026-11-01=/private/nov01-original.zip \
      --official-bundle 2026-11-01=/private/c1-sources/reviewed.json \
      --output /private/c1-source-comparison.json

The integration command returns exit code 2 intentionally because
matching venue candidates is NOT a complete-day source denominator.
Missing next-day captures are explicit BLOCKED, never zero races.

## C6 – second implementation: multi-capture source revision chain

New collector/pit_revision_chain.py uses the EXISTING
pit_source_snapshot.audit_original_pdf_capture_tminus4 per immutable
original ZIP. It orders individual race receipt timestamps rather than
assuming the input ZIP order and identifies:
- original PDF SHA changes between independent Collector runs;
- changes to the PDF-printed racing clock across versions;
- missing races, duplicate archives, invalid source timestamps and
  inconsistent capture identities (all fail closed);
- whether source observations occur around or bracket an *unverified*
  PDF T−4 clock.

This closes the code gap for a future longitudinal source version
record. It does NOT create actual new capture archives and must never
be interpreted as first-publication evidence, an independent actual
start clock, a prospective as-of market/field snapshot or C6 PIT
authorization. Every report carries tminus4_pit_certified=false.
The original November 1 archive supplies only ONE historical morning
source capture: C6 version-chain status must therefore be
BLOCKED_INSUFFICIENT_SOURCE_CAPTURES, not an invented T−4 pass.

The corresponding tests use independently varied synthetic receipt
and PDF SHA evidence, and the integration CI checks the actual original
Nov 1 archive against both the C1 calendar negative and C6 single-
capture negative. No production collection is scheduled or edited.

Private replay, if multiple ORIGINAL collector ZIP captures for the
same Oslo race day exist:

    python -m collector.pit_revision_chain --day 2026-11-01 \
      --archive /private/run-1.zip --archive /private/run-2.zip \
      --output /private/pit_source_version_chain.json

A green source revision chain is still SOURCE_REVISION_SEQUENCE_DIAGNOSTIC_ONLY,
not PIT certification. Independent actual start time, complete race/horse
scope, point-in-time market and source publication still require separate
prospective evidence.

## Evidence and unreached acceptance

The synthetic negative suite tests source URL and robots protection,
real code-path HTTPS adapter with mocked transport, UTF-8 validation,
SHA readback, collision prevention, human excerpt source matching,
original Collector ZIP source tamper and day+2 missing days.
These are OFFLINE simulations and cannot be treated as the actual
DNT/Svensk Travsport original HTTP capture. Test-injected transports
explicitly mark network_https_response_observed=false.

The original 1 Nov 2026 Collector capture has 7 SHA-valid PDF and 73
raw JSON receipts; its date API said EMPTY_RESULT_ARRAY. It contains
NO independent original DNT/Swedish calendar HTTP page bytes.
Those specific missing sources and Nov 2/3 archives cannot be
retroactively fabricated by capturing new pages later.

Acceptance:
- C0: technical CI alone is not authorized human HQ approval.
  main protected=false/rulesets empty at implementation; issue #50 P0.
- C1: still BLOCKED until genuine independent official calendar
  source provenance, ALL physical meetings and ALL races,
  14-day >=95% sample are actually verified.
- C2: source captures are immutable local original-byte evidence,
  not historic corrections; legacy missing raw responses remain.
- C3/C5: parsed PDF/startlist matches and source venue excerpts do
  not establish independent complete race and horse identity.
- C4: DATA-004E 30 rows / 390 independent fields remain 0 accepted.
  Betting owns independent gold; no duplicate validation here.
- C6: no independent source publication time, T-4 snapshot, or
  actual start-time verification. Existing C-DEV-06 historical
  PDF time diagnostic remains candidate-only.
- C7: 14 approved operational days still missing.

IMPLEMENTED, TESTED, MERGED, LIVE_VERIFIED and HQ_ACCEPTED must be
reported separately for the exact branch HEAD. No automatic merge.

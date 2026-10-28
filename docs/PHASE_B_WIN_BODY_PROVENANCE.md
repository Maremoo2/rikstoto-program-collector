# Phase B P0 — WIN and official startlist byte provenance (28 October 2026)

**Research / diagnostic only; no independent live WIN verification and no BET.**

## Verified gap and bounded correction

Before this change the source probe recorded `captured_utc` when the
browser procedure **began, before navigating to the race page**. It later
passed that same earlier clock to `parse_public_winodds()`. The time
could differ materially from the receipt of the response bytes, causing
wrong market-age judgments and undermining Pre/POST isolation.

The probe now records a distinct `probe_started_utc`, the
`screen_captured_utc` immediately after reading the rendered page,
and a separate **UTC timestamp after actual body receipt** for each
captured first-party WIN and official startlist JSON body. The odds
adapter receives the timestamp of the **specific WIN body** it parsed.

Every permitted public response gets:

- an allowlisted first-party response endpoint path, no query/cookies;
- exact HTTP response status (200 only), limited safe response headers,
  observed UTC, and response byte count;
- **SHA-256 of the original byte string returned by Playwright
  `response.body()`**, with no JSON reserialization;
- a separate SHA-256 of a canonical JSON serialization strictly
  marked as **not the original source body**.

The bytes returned by Playwright may have been decoded from HTTP
`Content-Encoding`; the hash is **not** a cryptographic attestation
of wire-compressed packets. The live diagnostic currently **does not
archive those original returned bytes** and therefore does not claim
independent readback verification. It does not expose the raw body,
cookies, credentials, untrusted URL queries, user data or an
authentication workflow in public GitHub Actions artifacts.

Only source-response types used by the WIN audit are admitted:
`/api/betdistribution/winodds` and explicitly recognized
`/api/racedays/<meeting-id>/starts` on the genuine first-party
host. All other XHR/fetch candidates remain metadata-only. Wrong
host/protocol, non-200, non-JSON MIME, invalid UTC, oversized or empty
body, duplicate JSON keys, NaN, malformed UTF-8/JSON and non-object
payloads are rejected instead of being silently parsed as evidence.

For the displayed screen/API comparison, the probe now records the
source-to-screen capture-time separation and refuses `MATCH`
if it exceeds 90 seconds. Earlier screen and API parity assertions
remain source diagnostics, not independent admission.

## Exact operational limitation

- Positive `playwright_body_sha256` means bytes were locally read
  and hashed by the diagnostic. It does **not** prove original source
  archiving, source-host trust at the betting layer, unaltered collection,
  independent replay, current scratches, standalone WIN pool or betting
  eligibility. Status is
  `HASHED_BODIES_NOT_ARCHIVED_OR_INDEPENDENTLY_VERIFIED`.
- Incomplete or rejected source bodies give
  `INCOMPLETE_OR_MISSING_SOURCE_BODY_HASHES`. No synthetic
  negative scratch, zero pool or stand-in V-series liquidity is inferred.
- The source probe still uses a presumed `Europe/Oslo` source timezone
  for timezone-naive provider price timestamps. This assumption
  **remains explicitly unverified** and cannot silently authorize a
  fresh source or BET.
- Provider country completeness/identity blockers from the existing
  live smoke (NO/FR) are **not** bypassed.
- Manual selective `A-WATCH` input is not a verified frozen model
  decision. The previous terminal receipt PR #14 is separate and
  may remain unmerged when this patch is reviewed.

## Tests and acceptance boundary

```bash
python -m pytest -q tests/test_win_response_provenance.py
python -m pytest -q
```

All test bodies are **synthetic**. Tests check direct Playwright-body
hashes vs normalized JSON, different byte representations of equivalent
JSON, official startlist source identity, safe headers/query redaction,
duplicate JSON keys (also nested), invalid JSON, wrong endpoint, wrong
host, clock offset/naive timestamps, wrong HTTP response and body size,
and a mocked async Playwright response read exactly once.

These tests do **not** constitute a completed live Phase B. To reach
real reproducible source provenance, the next separately authorized
step must add a **private** original-byte archive with byte-level
readback hashes, content trust/permission checks, a source timestamp
paired to frozen A-WATCH race ID, and a signed/immutable manifest
before an operational pilot. No public repository commit or open
Actions artifact should silently expose unreviewed raw source data.

**No changes** to Pre-Watch V3.3.12 model weights, A-WATCH gates,
Betting probability or minimum-odds logic, scheduling, WAGER, betting
execution or staking. `bet_authorized=false` and `BET_BLOCKED`
remain the only valid operational decision states.

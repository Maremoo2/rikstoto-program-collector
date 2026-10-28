# Phase B P0 — private original-body readback (opt-in only)

**Status:** offline implementation and synthetic tests. **No live-source attestation, no real A-WATCH, no betting.**

## Dependency and why this is separate

This is a *stacked* draft on top of Collector
[PR #15](https://github.com/Maremoo2/rikstoto-program-collector/pull/15),
which adds true Playwright body-time stamping and SHA-256. PR #15 has
not yet merged to `main`; do not merge or rebase this follow-on without
first verifying that prerequisite.

PR #15's hash alone cannot prove that the originally captured byte
sequence was retained. The present change offers a **local-only,
explicitly opted-in** storage path, so an authorized researcher can
compare saved exact bytes to the digest after reopening the file.
No archive is created by default, by the scheduled collector, or by
GitHub Actions.

## Private local usage (after the dependency is reviewed and merged)

Use only with source access that is explicitly permitted by the
provider's public access conditions and robots controls.

```bash
mkdir -m 700 /secure/private-racing-archive
python -m collector.win_source_probe \
  --url 'https://www.rikstoto.no/Spill/VERIFIED_MEETING/V?race=2' \
  --private-archive-root /secure/private-racing-archive \
  --output /secure/private-racing-archive/diagnostic.json
```

The URL is a **placeholder**, not an invitation to test against an
unverified live provider; the tool will still check same-host public
URLs and robots permissions. `--private-archive-root` must be an
**already existing absolute non-symlink directory, owned by the
executing user with no group/world permissions**, located outside the
repository and Actions workspace. GitHub Actions explicit opt-in is
rejected. No private archive option exists in
`awatch-selective-win.yml`.

Each successful, accepted first-party public JSON body is written once
as a unique, random-ID `.body` file (owner-only 0600) and receives a
separate 0600 manifest **only after the body is reopened and compared
byte-for-byte**. The manifest holds the original body SHA-256, length,
actual post-read UTC capture timestamp, source endpoint path (no query),
claimed meeting/race identity and an explicit record schema. It does
not hold raw response bodies, user tokens, cookies, credentials or
private URLs. An incomplete or inconsistent archive attempt rejects
that source body; the source probe cannot promote it as valid evidence.

The public diagnostic JSON carries only the random archive record ID,
verified manifest digest and source metadata. It never includes
private archive absolute paths or raw body bytes. Status
`PRIVATE_BODY_READBACK_VERIFIED_SOURCE_STILL_UNVERIFIED` means **only**
the local `response.body()` bytes were written and reread accurately;
it does not mean that a live market, standalone WIN pot, whole field,
odds screen, or BET was independently verified. No P(win), fair odds,
minimum price, EV, betting signals or stakes are created.

### Independent offline recheck

```python
from pathlib import Path
from collector.private_source_archive import verify_private_source_record

receipt = verify_private_source_record(
    Path("/secure/private-racing-archive"), "<32-char-private-record-id>"
)
assert receipt["private_readback_sha256_verified"]
assert not receipt["bet_authorized"]
```

The comparison covers SHA-256 and exact byte length; it also rejects
manifest/body filename mismatch, unknown record IDs, symlinked files,
unsafe permissions or local tampering. A researcher who controls the
entire directory can modify **both** manifest and body; therefore the
manifest is **not signed or immutable** and this is **not** independent
publisher authenticity. Playwright may have decompressed the response:
the hash is not wire-level capture. The provider's response may include
all races, and the claimed meeting/race context still requires a
separate exact-key parser/official-startlist reconciliation.

## Tests and fail-closed policy

```bash
python -m pytest -q tests/test_private_source_archive.py
python -m pytest -q tests/test_win_source_browser_provenance.py
python -m pytest -q
```

All tests run on **synthetic bytes** with the actual validation/readback
implementation and a fake browser, never against Rikstoto. They cover
original byte checksums, tampering and mutated manifests, second
capture without overwriting the first, symlink/permission/unsafe path
refusals, pre-existing race identity, no credentials in metadata,
default-disabled archiving, and explicit rejection when an Actions
environment attempts to enable raw-body archiving.

This branch deliberately does **not** change the manual/automatic
schedules, grant access to new URLs, bypass robots, relax stale quotes,
change V3.3.12 models, create a private cloud store, publish raw data,
merge prior PRs or place wagers. Production always remains
`bet_authorized=false` and `BET_BLOCKED`.

## Outstanding P0 before any live Phase B success

1. Merge/test PR #15 independently and review this stacked change.
2. Decide private retention, deletion, encryption/backup and
   access governance; local 0600/0700 permissions do not replace
   organizational storage policy.
3. Obtain a **real, prospectively frozen A-WATCH** with immutable race
   identity and documented source timestamps; no manual synthetic
   substitution.
4. Verify complete official runner/scratch identity, rendered WIN
   prices, an independently time-stamped **standalone WIN pool** and
   genuine raw source/replay provenance for the same exact race.
5. Freeze and calibrate full-field p(win) and independent minimum BET
   prices within Betting's unchanged gate framework, *before* market
   comparison. Only then could a future governed betting decision be
   evaluated. A passing source test is never BET authorization.

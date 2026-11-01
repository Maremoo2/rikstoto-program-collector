# P0 – Append-only original response capture (no source overwrite)

**Scope:** \`collector/source_integrity.py\` and the daily collector's original
JSON/PDF HTTP body persistence. This is an engineering integrity guard for
prospective CORE-003 / longitudinal source archives; it is not a PIT certificate
or a betting permission.

## Original failure mode

Previously, \`archive_json_bytes\` used \`Path.write_bytes\` for both
\`*.raw.json\` (the actual response bytes) and \`*.json\` (a formatted
collector wrapper), while \`daily.request(binary=True)\` used \`Path.write_bytes\`
for original PDF response bytes. A second GET in the same run with the same
archive path could overwrite the first response silently. The receipt from
the first GET could then point to a *different* current file body. This
undermines original-source lineage and retrospective PIT claims.

## Enforced original-source contract

* Byte-for-byte JSON and PDF response files are created with OS-level
  \`O_CREAT|O_EXCL|O_WRONLY\`, and \`O_NOFOLLOW\` where supported. The writer
  cannot overwrite an existing original body or formatted wrapper, **even
  if identical**.
* Writes are flushed and fsynced, followed by an independent SHA-256
  readback. The original JSON wrapper SHA is tracked separately from
  the original HTTP body SHA; the latter is never computed over a
  re-serialized object.
* If either JSON output path exists (including a symlink), no source bytes
  are changed. If the new wrapper fails after new raw creation, only the
  raw file from **that call** is removed. A broken readback produces no
  successful source receipt. The original raw and wrapper collision
  status is \`SOURCE_ARCHIVE_COLLISION\` in daily collector request logs.
* The same no-overwrite rule now holds for original PDF bytes.
* No old archive is regenerated. Original HTTP Date/Last-Modified/ETag
  headers remain **observations, not authenticated first-publication
  timestamps**. Normal filesystem ownership alone is not independent
  trusted timestamp attestation or tamper-proof storage.

## Validation

\`pytest tests/test_json_raw_archive.py tests/test_daily_raw_receipts.py\`
contains negative collision tests for duplicate identical and different
original JSON bodies, pre-existing wrapper/raw files, symlinks, repeated
PDF fetches and corruption/readback mismatch. Full Collector unit CI
must also PASS on exact PR head.

\`.github/workflows/archive-integrity-original-e2e.yml\` rechecks the
**existing, unchanged actual** pinned 27/29/31 October and 1 November
collector archival source artifacts, including 73 original JSON source
bodies plus 7 original PDFs on 1 November. Existing October legacy JSON
wrappers without original raw HTTP bytes **remain unverifiable**.

Archive immutability is a prerequisite for source attribution, **not**
verification of all available meetings, independent prospective roster,
publisher publication-before-T−4, predictive EV, or permission to trade.
Existing 14-day, PIT, V3.3.12 and BET hardgates remain fail-closed.

**Governance:** merge only after independent designated HQ approval on exact
PR HEAD and appropriate enforced branch protection, never by DEV automation.

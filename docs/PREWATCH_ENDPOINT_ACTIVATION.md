# CORE-STABILITY-001 — merge versus activation boundary

PR #63 adds diagnostic-only modules and offline tests. The scheduled Collector,
refresh pilot and Pre-Watch automation are unchanged. The approved manual
diagnostic from PRs #64–66 remains unchanged and pins the live-verified
candidate bce63739a2493537aeec4d30693cb6c4f9e61c92.

## Existing evidence
- Numeric marker-only draft 458013574, tag prewatch-ready-v1, is already
  provisioned; no bootstrap writer is needed in this merge.
- Run 45639694382 verified source archive and roster digests, draft readback,
  Google WIF read-only Ledger (31 assessment / 264 field rows) and a nonempty
  SOURCE_READY packet (19 eligible). Zero completed IDs that day; positive
  live exclusion remains unproved, while synthetic tests cover exclusion.
- No public artifact contains the Ready Packet or Ledger cells. Receipt metadata
  (Release IDs, hashes, timestamps, asset metadata) appears in diagnostic logs;
  it is not a secret credential. See PREWATCH_RELEASE_ACCESS_DIAGNOSTIC.md.

## Before any separate activation
1. Obtain explicit HQ/owner approval. Publication is hard-disabled in both
   integration output and mailbox CLI; --apply fails before network access.
2. Maintain dedicated Viewer-only Google identity, exact repository/ref/workflow
   WIF condition and short-lived read-only Sheets token. Never create keys.
3. Design and prove a single serialized writer and final prestart rechecks of
   newest archive, roster and Ledger. A same-run readback receipt is a point-in-
   time observation, not an atomic guarantee against concurrent new archives.
4. Validate private draft identity, full packet readback, expiry, positive live
   deduplication, prospective Phase A and shadow operation. Never publish the
   private draft or allow betting authority in a source packet.
5. Separate activation PR and approval required. No schedule, production,
   mailbox or Ledger mutation is authorized by the code merge.

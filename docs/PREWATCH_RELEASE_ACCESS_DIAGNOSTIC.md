# CORE-STABILITY-001C – draft Release visibility boundary

GitHub REST List releases only exposes drafts to principals with push access:
https://docs.github.com/en/rest/releases/releases#list-releases

Run 45613561139 verified full Google Ledger read and failed at RELEASE_TAG_NOT_UNIQUE.
The original code used the same error for zero or multiple matching tags.
The new release_probe mode checks a known numeric draft and a bounded listing using
the unchanged contents:read token. This is the direct runtime proof of visibility.

GitHub has no draft-only read scope. The proposed manual full_integration uses a
separate, short-lived contents:write token only in draft-readback. This is a
permission expansion, NOT a read-only credential, and requires explicit owner
approval before merge and the approve_draft_readback switch on dispatch.
No Google credentials, OIDC, external action, candidate code execution or mutation
API is used in that job. It reads trusted main code at the workflow commit,
validates the existing Collector run and reads its index as data, then performs
only fixed-repository GET calls with no redirect. The only output is a compact
same-run receipt of IDs, hashes, timestamps and asset digests, not Release bodies.
The integration job retains contents:read/actions:read and read-only Sheets WIF;
it consumes the trusted workflow receipt and rechecks archive bytes, bodies by
hash, source packs, roster freshness, Ledger exclusion and expiry.

No source packet, raw body or Ledger content is uploaded as a public artifact.
Receipt metadata is workflow output, not an independent signature; trust rests
on this exact main workflow and same-run job boundary. A stale, absent, ambiguous
or malformed receipt fails closed. A no-eligible-race result fails acceptance.
No scheduled/production workflow change, no writes to releases or Ledger.
Do not merge PR #63 or enable mailbox publication.

Owner may reject elevated permissions; in that case run only release_probe and
leave full integration blocked. No PAT or permanent secret is requested.

# CORE-STABILITY-002 — manual shadow mailbox protocol

This proposal adds three manually dispatched modes to the existing WIF-authorized
workflow. Existing auth_only, release_probe, full_integration, scheduled Collector
and active ChatGPT Pre-Watch are not changed. No automatic activation.

The existing private draft 458013574 is the only writable target. Root envelope
status SHADOW_ONLY, no root selected race, phase_a_completed=false,
bet_authority=false, operational_publication_allowed=false. The nested
diagnostic packet retains its original false publication flag. The envelope
contains a canonical packet SHA-256; authenticated GET after a PATCH verifies
the entire canonical body and numeric draft identity. No public artifacts or
raw packet outputs. Same-run hash only is not a signature.

Permissions proposal: a short-lived, isolated manual job needs contents:write
because GitHub blocks read-only tokens from draft GET, actions:read for the
existing artifact, and id-token:write for the existing Google Viewer WIF.
Unlike 001C, these capabilities coexist in this job to permit immediate
revalidation without handing raw source/Ledger data between jobs. This is an
explicit security trade-off requiring owner review before merge. No additional
Google role, keys or permanent secrets. Only the approved main modules execute.
The only PATCH target is fixed and the only field written is body.

Sequence after approval and merge:
1. Run normal Collector on new main, verify success. Run shadow_preflight using
   newest successful run ID, approve_draft_readback=true, approval blank.
2. Verify active Pre-Watch does not interpret SHADOW_ONLY as operational input.
   This requires separate live automation review; a failed automation connector
   is not proof. Do not authorize publication until verified.
3. Separately authorize shadow_publish, same fresh source or new fresh source,
   approve_draft_readback=true, exact approval PUBLISH_SHADOW_ONLY_458013574.
4. Run shadow_consume immediately against same source ID; packet and existing
   Ledger evidence expire quickly (120 seconds; original roster max 30 min).
   This is a Python transport consumer, NOT proof of actual ChatGPT Pre-Watch
   consumption or Phase A. No active automation modification in this PR.
5. Separate owner-approved shadow Pre-Watch consumer session and prospective
   QA/Phase A validation remain required. Ledger writes remain prohibited.

The writer and consumer use a dedicated concurrency group, no cancellation of
running jobs. All supported writers must use this group; UI/API changes outside
the group remain forbidden during the pilot. GitHub PATCH has no atomic CAS.
A newer archive can appear after the final list; check again before operational
use. Do not claim atomicity across external producers. Recheck selected race
official starts and driver changes via direct HTTPS GET, comparing archived
JSON payload; changed, unavailable or volatile responses block and require a
new Collector run. This does not extend the original 30-minute clock. Start
time check is against verified scheduled start, not an independent live race
status endpoint. Require final roster/archive/Ledger rechecks within 30 sec
and existing analysis window. If PATCH result is uncertain, do not retry
blindly; inspect numeric draft readback. A post-write expired packet remains
SHADOW_ONLY and must not be consumed. No automatic rollback mutation.

No Phase A completion or BET alerts. Positive live deduplication, independent
full-field QA, actual Pre-Watch consumption, and Ledger registration/readback
require separate evidence and authorization. No production activation.

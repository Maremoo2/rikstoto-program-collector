# C-DEV-02 / C1: retain permitted original sources when another country blocks

Base inspected: Collector `db50ad9530f0388f36a9e394445b5a89af3d30f2`,
which already contains PR #55 (`fc5253041625ab34aa720c200e942800bccb5a0e`).
The supplied continuation text's open-draft status for #55 is therefore stale.
No HQ acceptance is inferred from that merge. Betting is unchanged.

## Concrete source finding and priority

Manual, bounded OS-verified HTTPS probe on 2026-11-01 used the existing
`_get_https`, `_robots_url`, `_robots_permits` and default official URLs:

| Country | Robots response | Page request |
| --- | --- | --- |
| NO | 200, text/plain, 42 bytes, permitted | 200, text/html; charset=utf-8, 46,475 bytes |
| SE | 200, text/plain, 1,000 bytes, not permitted | NOT REQUESTED |

These observations were printed in the development terminal. They are **not**
archived authenticated calendar evidence, do not establish dated meeting/race
coverage, and do not certify the new end-to-end capture command as live verified.
Do not bypass Swedish robots restrictions or treat the Norwegian HTML response
as an independently reviewed schedule.

C0 remains an administrator/HQ dependency. The actionable C1 defect is that
strict capture discarded an already obtained permitted country response when
the other country blocked. This delivery adds an explicit opt-in partial mode
to the existing capture implementation, rather than a duplicate crawler.

## Behavior

On a supported POSIX host, with an existing user-owned 0700 directory outside
the repository:

```sh
python -m collector.official_calendar_capture capture --day 2026-11-01 \
  --private-root /absolute/private/evidence --allow-partial
```

Only permitted pages are requested. Each country's expected transport/policy
failure is recorded separately. Successfully obtained page bytes and valid
robots bytes (including a denial) are exclusively archived with SHA readback.
Unknown or invalid robots responses are never recorded as verified originals.
The other country is still attempted under its own robots check.

Partial/zero-source output has `BLOCKED_PARTIAL_OFFICIAL_SOURCE_CAPTURE` and
CLI exit **2**, prints the bundle path and country blockers, and contains only
actually obtained successful page receipts in `sources`. No placeholder page,
empty calendar or zero-race inference is created. The incumbent C1 reader
continues to block partial bundles; annotation still requires two verified
country sources. The default command retains strict all-or-nothing behavior.
Existing original files are never replaced. New evidence requires a new run.

## Validation and limits

Seven added synthetic transport tests cover either country's robots denial,
transport failure, both countries denied, strict default, repeat-write
collision, two-country success, and CLI nonzero output. They explicitly replace
the private-root guard only within test fixtures, so transport behavior can be
tested on Windows without claiming Windows privacy validation.

Local baseline full suite: 599 passed, 38 failed, 2 errors. The existing private
archive implementation uses POSIX `os.geteuid` and file permissions unsupported
on this Windows host; a focused original capture test reproduces AttributeError
at that unchanged guard. No production privacy guard has been weakened.
Full Ubuntu CI and original pinned Nov 1 ZIP replay are required on the PR head.

## Acceptance remains distinct

IMPLEMENTED: isolated branch. TESTED: local synthetic regressions; Ubuntu CI
must be checked separately. MERGED: no. LIVE_VERIFIED: no (transport probe only).
HQ_ACCEPTED: no. C1 full-day/14-day denominator, C4 independent 390-cell gold,
C6 prospective T-minus-4 and C7 accepted 14-day operation remain unproven.
No percentage completion is inferred from test counts. No production schedule,
Betting behavior, model, stakes or historical source archive is changed.

Rollback: close this draft; no deployment or source migration is involved.

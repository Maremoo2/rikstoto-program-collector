# AGENTS.md — Maremoo2/rikstoto-program-collector 

## Scope and authority
This repository is the public racing-data **supplier**, not the betting decision engine. Its outputs are source snapshots, source-readiness audits and handoff data; they do **not** authorize `p(win)`, fair odds, EV, BET or real wagers. `Maremoo2/Betting` owns the future analysis runtime. ChatGPT Pre-Watch V3.3.12 remains a separately frozen comparator.

Read `README.md`, relevant `collector/` code and `tests/`, `.github/workflows/tests.yml`, `.github/workflows/rikstoto-morning.yml` and `collector/prewatch_handoff.py` before proposing duplicate capture or parser code. The common cross-repository DEV procedure is kept in `Maremoo2/Betting/docs/DEV_WORKFLOW.md` (pin the version/commit you actually read); this file remains sufficient for safe local work if that document is unavailable.

## Source contract
- Preserve source URL, actual observed UTC, HTTP status/headers when obtained, original response bytes and direct SHA-256 where available; verify archive bytes after readback. Pretty-printed/normalized JSON has **a separate hash** and is not the raw HTTP response.
- Match PDF and official startlist before treating an observed field as complete; never infer unseen participants, scratches, results, horse IDs or actual start time from scheduled time.
- Keep `CAPTURED_UNVERIFIED`, `REVIEW_REQUIRED`, `MATCHED_AS_OF_SNAPSHOT`, `UNKNOWN` and terminal source blocks distinct. A green workflow or HTTP 200 does not establish actual data completeness.
- Use only permitted public requests. Do not evade robots directives, authentication, CAPTCHA, paywalls or provider restrictions. Preserve PRE/POST isolation.

## Local development and tests
Identify a specific source artifact or failing Actions run, reproduce with existing fixtures, make the minimal explicitly authorized **local** change, then focused tests, log-driven correction, full `python -m pytest -q`, and one archived-race/manifest/hash regression. Tests must cover missing rows, malformed meeting IDs, race/horse reconciliation, bad hashes, unknown timestamps and fail-closed states. State whether the test uses real archived bytes or synthetic fixtures. Do not fabricate access to a blocked network.

## Authorization and stopping
Without express HQ scope, do not create GitHub branches/commits/PRs, run workflows, change schedules, write Sheets, merge, change model decisions or publish production data. Even an approved PR is **not** approved for merge. Stop at the authorization boundary; report exact tests, run/artifact IDs, source coverage, unresolved gaps and rollback. Missing permission or credible source evidence => `BLOCKED`, not invented completion.
# P0 – Independent HQ exact-head review in Collector

This repository has the same HQ-only governance contract as \`Maremoo2/Betting/docs/DEV_WORKFLOW.md\`: **DEV cannot merge**, and GitHub Actions is not sufficient to enforce independent review unless the authorized HQ administrator installs required branch rules.

An authorized admin must:
1. Configure the comma-separated GitHub **repository variable** \`HQ_REVIEWER_LOGINS\` with approved real HQ human reviewer logins, excluding PR authors, bots and agents.
2. Install and independently verify a required branch ruleset/branch protection on \`main\` that requires the PR review, dismisses stale approvals, forbids routine bypass, and requires exact PR-head status check \`independent-hq-review-evidence\` plus other mandatory CI checks. Do the same independently in \`Maremoo2/Betting\`.
3. Test a disposable PR with no reviewer and another with a wrong/stale exact SHA; record GitHub's **rejected merge** evidence, not just a red workflow job.
4. After an independent designated HQ **APPROVED** review on the exact current PR head, the same reviewer must post the exact later comment:

\`\`\`
APPROVED_FOR_MERGE: Maremoo2/rikstoto-program-collector PR #<n> HEAD <full-lowercase-40-character-SHA>
\`\`\`

5. Re-review and re-sign after any commit changes.

The workflow \`.github/workflows/hq-independent-review-gate.yml\` uses read-only official GitHub API responses for pull-request metadata, all reviews and issue comments. The Python script \`scripts/hq_exact_head_review_gate.py\` verifies exact-head, reviewer allowlist and an explicit later signoff, and produces a fail-closed status when reviewers have not been configured. Passing the evidence check still reports \`branch_ruleset_required_check_verified=false\`, \`merge_authority=false\` and \`model_or_bet_authority=false\`. The workflow **cannot** install branch protection, merge PRs, attest model PIT, or change staking rules.

Offline negative tests:

\`\`\`bash
python -m pytest -q tests/test_hq_exact_head_review_gate.py
\`\`\`

Existing historic merges with \`[]\` approval reviews must not be backdated or described as approved. The \`/rulesets\` endpoint returning \`[]\` does not prove that classic branch protection is absent; independently inspect protection with admin permissions.

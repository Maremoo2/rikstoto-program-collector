"""Read-only independent HQ reviewer and exact PR-head signoff gate.

This gate cannot enforce itself until a repository/organization branch ruleset
requires the corresponding check, configured by a *separate* authorized HQ
administrator. It never approves, merges, edits code, or grants model/BET
authority. Inspect immutable GitHub REST review and issue-comment metadata.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return timestamp if timestamp.utcoffset() is not None else None


def _pages(value: object) -> list[dict[str, Any]]:
    """GitHub API --paginate --slurp produces a list of JSON-array pages."""
    if not isinstance(value, list):
        raise TypeError("Expected GitHub API page list")
    if all(isinstance(x, dict) for x in value):
        return value
    if all(isinstance(chunk, list) for chunk in value):
        result = []
        for chunk in value:
            if any(not isinstance(x, dict) for x in chunk):
                raise ValueError("Non-object review or comment")
            result.extend(chunk)
        return result
    raise ValueError("Unexpected paginated GitHub API response")


def evaluate(
    pr: dict[str, Any],
    reviews: object,
    comments: object,
    *,
    repository: str,
    reviewer_logins: str,
) -> dict[str, Any]:
    """No fuzzy approval matching, no inferred HQ identity, no stale reviews."""
    if "/" not in repository or len(repository.split("/")) != 2:
        raise ValueError("Explicit owner/repo required")
    number = pr.get("number")
    head = pr.get("head") or {}
    user = pr.get("user") or {}
    sha = head.get("sha")
    author = user.get("login")
    if (
        type(number) is not int
        or not isinstance(sha, str)
        or len(sha) != 40
        or any(char not in "0123456789abcdef" for char in sha)
        or not isinstance(author, str)
    ):
        raise ValueError("Incomplete PR identity or original head SHA")
    base_repo = (pr.get("base") or {}).get("repo") or {}
    if not isinstance(base_repo, dict) or base_repo.get("full_name") != repository:
        raise ValueError("PR does not belong to requested repository")
    names = {
        name.strip().casefold() for name in reviewer_logins.split(",")
        if name.strip()
    }
    if names and any(not name or not all(ch.isalnum() or ch == "-" for ch in name)
                     for name in names):
        raise ValueError("Invalid configured HQ reviewer login")
    expected = f"APPROVED_FOR_MERGE: {repository} PR #{number} HEAD {sha}"

    answer = {
        "schema": "HQ_INDEPENDENT_EXACT_HEAD_REVIEW_V1",
        "repository": repository,
        "pr_number": number,
        "pr_head_sha": sha,
        "pr_author": author,
        "reviewer_allowlist_explicitly_configured": bool(names),
        "status": "BLOCKED_HQ_REVIEW_CONFIGURATION_MISSING",
        "independent_approving_reviewers": [],
        "exact_head_signoff_present": False,
        "branch_ruleset_required_check_verified": False,
        "branch_protection_enforced_by_this_script": False,
        "merge_authority": False,
        "model_or_bet_authority": False,
    }
    if not names:
        return answer
    if pr.get("state") != "open" or pr.get("draft") is not False:
        answer["status"] = "BLOCKED_PR_NOT_OPEN_AND_REVIEWABLE"
        return answer
    latest_decisive: dict[str, dict] = {}
    for item in _pages(reviews):
        reviewer = item.get("user")
        if not isinstance(reviewer, dict) or reviewer.get("type") != "User":
            continue
        login = reviewer.get("login")
        if not isinstance(login, str) or login.casefold() not in names:
            continue
        if login.casefold() == author.casefold():
            continue
        state = item.get("state")
        if state not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            continue
        stamp = _instant(item.get("submitted_at"))
        if stamp is None:
            continue
        prior = latest_decisive.get(login.casefold())
        if prior is None or stamp >= prior["when"]:
            latest_decisive[login.casefold()] = {
                "when": stamp, "state": state,
                "head": item.get("commit_id"),
            }
    approved = {
        login: detail for login, detail in latest_decisive.items()
        if detail["state"] == "APPROVED" and detail["head"] == sha
    }
    answer["independent_approving_reviewers"] = sorted(approved)
    if not approved:
        answer["status"] = "BLOCKED_NO_INDEPENDENT_EXACT_HEAD_APPROVING_REVIEW"
        return answer

    for item in _pages(comments):
        reviewer = item.get("user")
        login = reviewer.get("login") if isinstance(reviewer, dict) else None
        if not isinstance(login, str):
            continue
        approval = approved.get(login.casefold())
        if approval is None or reviewer.get("type") != "User":
            continue
        when = _instant(item.get("created_at"))
        if when is None or when < approval["when"]:
            continue
        if isinstance(item.get("body"), str) and item["body"].strip() == expected:
            answer["exact_head_signoff_present"] = True
            answer["status"] = "HQ_REVIEW_EVIDENCE_PRESENT_RULESET_ENFORCEMENT_UNVERIFIED"
            return answer
    answer["status"] = "BLOCKED_MISSING_POST_REVIEW_EXACT_HEAD_HQ_SIGNOFF"
    return answer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--comments", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--reviewer-logins", default="")
    args = parser.parse_args()
    report = evaluate(
        json.loads(args.pr.read_text(encoding="utf-8")),
        json.loads(args.reviews.read_text(encoding="utf-8")),
        json.loads(args.comments.read_text(encoding="utf-8")),
        repository=args.repository,
        reviewer_logins=args.reviewer_logins,
    )
    print(json.dumps(report, sort_keys=True, indent=2))
    # Even a PASS here is only evidence suitable for requiring via *HQ-installed*
    # GitHub branch protection; the script cannot prove the ruleset enforces it.
    if report["status"] != "HQ_REVIEW_EVIDENCE_PRESENT_RULESET_ENFORCEMENT_UNVERIFIED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

"""Offline HQ gate negatives. Not a substitute for real GitHub HQ approval."""
from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[1] / "scripts/hq_exact_head_review_gate.py"
SPEC = importlib.util.spec_from_file_location("hq_exact_head_review_gate", FILE)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

SHA = "0123456789abcdef" * 2 + "01234567"
OLD = "abcdef0123456789" * 2 + "abcdef01"
REPO = "Maremoo2/rikstoto-program-collector"
PR_NUMBER = 111
TOKEN = f"APPROVED_FOR_MERGE: {REPO} PR #{PR_NUMBER} HEAD {SHA}"


def fixture():
    pr = {
        "number": PR_NUMBER, "state": "open", "draft": False,
        "user": {"login": "pr-author", "type": "User"},
        "head": {"sha": SHA}, "base": {"repo": {"full_name": REPO}},
    }
    reviews = [{
        "user": {"login": "hq-human", "type": "User"},
        "commit_id": SHA, "state": "APPROVED",
        "submitted_at": "2026-11-01T10:12:00Z",
    }]
    comments = [{
        "user": {"login": "hq-human", "type": "User"}, "body": TOKEN,
        "created_at": "2026-11-01T10:14:00Z",
    }]
    return pr, reviews, comments


def run(pr=None, reviews=None, comments=None, config="hq-human"):
    base_pr, base_reviews, base_comments = fixture()
    return module.evaluate(
        pr if pr is not None else base_pr,
        reviews if reviews is not None else base_reviews,
        comments if comments is not None else base_comments,
        repository=REPO, reviewer_logins=config,
    )


def test_exact_independent_hq_evidence_is_not_ruleset_or_bet_authority():
    result = run()
    assert result["status"] == "HQ_REVIEW_EVIDENCE_PRESENT_RULESET_ENFORCEMENT_UNVERIFIED"
    assert result["independent_approving_reviewers"] == ["hq-human"]
    assert result["exact_head_signoff_present"] is True
    assert result["branch_ruleset_required_check_verified"] is False
    assert result["branch_protection_enforced_by_this_script"] is False
    assert result["merge_authority"] is False
    assert result["model_or_bet_authority"] is False


def test_missing_allowlist_fails_closed_even_with_valid_approval_and_comment():
    result = run(config="")
    assert result["status"] == "BLOCKED_HQ_REVIEW_CONFIGURATION_MISSING"
    assert not result["independent_approving_reviewers"]


@pytest.mark.parametrize("broken", [
    "unapproved", "outdated_review", "bot", "self_review", "reviewer_not_hq",
    "dismissed", "changes_requested", "stale_after_change_request",
    "missing_comment", "other_user_comment", "old_comment", "other_pr",
    "other_repo", "old_sha_comment", "draft", "closed", "wrong_repo",
])
def test_unverifiable_or_stale_git_hub_approval_fails_closed(broken):
    pr, reviews, comments = fixture()
    if broken == "unapproved":
        reviews[0]["state"] = "COMMENTED"
    elif broken == "outdated_review":
        reviews[0]["commit_id"] = OLD
    elif broken == "bot":
        reviews[0]["user"]["type"] = "Bot"
    elif broken == "self_review":
        reviews[0]["user"]["login"] = "pr-author"
    elif broken == "reviewer_not_hq":
        reviews[0]["user"]["login"] = "someone-else"
    elif broken == "dismissed":
        reviews[0]["state"] = "DISMISSED"
    elif broken == "changes_requested":
        reviews[0]["state"] = "CHANGES_REQUESTED"
    elif broken == "stale_after_change_request":
        reviews.append({
            "user": {"login": "hq-human", "type": "User"},
            "commit_id": SHA, "state": "CHANGES_REQUESTED",
            "submitted_at": "2026-11-01T10:14:59Z",
        })
    elif broken == "missing_comment":
        comments.clear()
    elif broken == "other_user_comment":
        comments[0]["user"]["login"] = "pr-author"
    elif broken == "old_comment":
        comments[0]["created_at"] = "2026-11-01T10:11:59Z"
    elif broken == "other_pr":
        comments[0]["body"] = TOKEN.replace(f"#{PR_NUMBER}", "#112")
    elif broken == "other_repo":
        comments[0]["body"] = TOKEN.replace(REPO, "other/repository")
    elif broken == "old_sha_comment":
        comments[0]["body"] = TOKEN.replace(SHA, OLD)
    elif broken == "draft":
        pr["draft"] = True
    elif broken == "closed":
        pr["state"] = "closed"
    elif broken == "wrong_repo":
        pr["base"]["repo"]["full_name"] = "different/repo"
    if broken == "wrong_repo":
        with pytest.raises(ValueError, match="requested repository"):
            run(pr, reviews, comments)
    else:
        assert not run(pr, reviews, comments)["status"].startswith("HQ_REVIEW_EVIDENCE_PRESENT")


def test_pagination_does_not_miss_second_page_and_disallows_newer_decisive_block():
    pr, reviews, comments = fixture()
    paginated_reviews = [[{
        "user": {"login": "random", "type": "User"},
        "state": "APPROVED", "commit_id": SHA,
        "submitted_at": "2026-11-01T10:00:00Z",
    }], reviews]
    paginated_comments = [[], comments]
    assert run(pr, paginated_reviews, paginated_comments)[
        "status"
    ] == "HQ_REVIEW_EVIDENCE_PRESENT_RULESET_ENFORCEMENT_UNVERIFIED"
    paginated_reviews[1].append({
        "user": {"login": "hq-human", "type": "User"},
        "state": "DISMISSED", "commit_id": SHA,
        "submitted_at": "2026-11-01T11:00:00Z",
    })
    assert run(pr, paginated_reviews, paginated_comments)[
        "status"
    ] == "BLOCKED_NO_INDEPENDENT_EXACT_HEAD_APPROVING_REVIEW"


def test_missing_both_evidence_types_blocks():
    pr, _, _ = fixture()
    assert run(pr, [], [])["status"] == "BLOCKED_NO_INDEPENDENT_EXACT_HEAD_APPROVING_REVIEW"


@pytest.mark.parametrize("bad", [None, {}, "not-list", [None], [[None]], [[{}], "bad"]])
def test_corrupt_api_review_or_comment_pages_rejected(bad):
    if bad is None:
        return
    pr, reviews, comments = fixture()
    with pytest.raises((TypeError, ValueError)):
        run(pr, bad, comments)
    with pytest.raises((TypeError, ValueError)):
        run(pr, reviews, bad)


def test_non_name_author_and_invalid_sha_rejected():
    pr, reviews, comments = fixture()
    pr["head"]["sha"] = "something-other-than-a-full-sha"
    with pytest.raises(ValueError, match="Incomplete PR identity"):
        run(pr, reviews, comments)


def test_function_never_mutates_input_reviews_comments():
    pr, reviews, comments = fixture()
    before = deepcopy((pr, reviews, comments))
    run(pr, reviews, comments)
    assert (pr, reviews, comments) == before

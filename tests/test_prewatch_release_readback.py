from copy import deepcopy
import json
import pytest

from collector import prewatch_release_readback as r
DAY = "2026-11-25"
RUN = "20261125T075221791585Z"
ARCH = f"rikstoto-program-{DAY}-{RUN}"
TAG = f"prewatch-src-{DAY}-S2_NR_{DAY}-p1-{RUN}"
NOW = r.stamp("2026-11-25T08:10:03Z")

INDEX = {"date_oslo": DAY, "run_id": RUN, "meeting_feeds": [{"release_tag": TAG}]}
MARKER = {"id": r.MARKER_ID, "tag_name": r.MARKER_TAG, "draft": True, "published_at": None}
ARCHIVE = {"id": 1, "tag_name": ARCH, "draft": True, "published_at": None,
           "body": "SNAPSHOT_OBSERVED_UTC=2026-11-25T07:53:01Z | SOURCE_CLOCK=LATEST_OFFICIAL_ROSTER_RECEIPT",
           "assets": [{"name": "archive.zip", "digest": "sha256:" + "a"*64}]}
MEETING = {"id": 2, "tag_name": TAG, "draft": True, "published_at": None, "body": "private body"}


def getter(rows=None, overrides=None):
    rows = [MARKER, ARCHIVE, MEETING] if rows is None else rows
    numeric = {x["id"]: x for x in rows}
    numeric[r.MARKER_ID] = MARKER
    numeric.update(overrides or {})
    def get(path):
        if "?" in path:
            return rows if path.endswith("page=1") else []
        value = numeric[int(path.split("/")[-1])]
        if isinstance(value, Exception):
            raise value
        return value
    return get


def receipt(**kwargs):
    return r.readback(INDEX, "123", "456", getter=getter(**kwargs), clock=lambda: NOW)


def test_readback_receipt_contains_no_body_or_token():
    data = receipt()
    assert len(data["records"]) == 2
    assert "private body" not in json.dumps(data)
    assert all("body" not in x for x in data["records"])
    assert data["records"][0]["body_sha256"] == r.sha(MEETING["body"])


@pytest.mark.parametrize("rows,code", [
    ([MARKER, ARCHIVE], "RELEASE_TAG_MISSING"),
    ([MARKER, ARCHIVE, MEETING, dict(MEETING, id=3)], "RELEASE_TAG_DUPLICATE"),
    ([MARKER, ARCHIVE, MEETING, MEETING], "RELEASE_PAGINATION_DUPLICATE_ID"),
    ([ARCHIVE, MEETING], "RELEASE_DRAFT_LIST_VISIBILITY_UNCONFIRMED"),
])
def test_list_fail_closed(rows, code):
    with pytest.raises(ValueError, match=code):
        receipt(rows=rows)


def test_missing_numeric_marker_is_access_unconfirmed():
    with pytest.raises(ValueError, match="RELEASE_DRAFT_VISIBILITY_UNCONFIRMED"):
        receipt(overrides={r.MARKER_ID: ValueError("RELEASE_HTTP_404")})


def test_numeric_identity_and_public_rejected():
    with pytest.raises(ValueError, match="RELEASE_IDENTITY_MISMATCH"):
        receipt(overrides={2: dict(MEETING, id=4)})
    with pytest.raises(ValueError, match="RELEASE_NOT_PRIVATE_DRAFT"):
        receipt(overrides={2: dict(MEETING, draft=False)})


def test_second_page_and_duplicate_across_pages():
    filler = [{"id": i+100, "tag_name": "old-"+str(i)} for i in range(100)]
    def fetch(path):
        return filler if path.endswith("page=1") else [MARKER, ARCHIVE, MEETING]
    assert len(r.list_rows(fetch)) == 103
    def shifted(path):
        return filler if path.endswith("page=1") else [filler[0]]
    with pytest.raises(ValueError, match="RELEASE_PAGINATION_DUPLICATE_ID"):
        r.list_rows(shifted)


def test_same_run_context_and_expiry():
    from datetime import timedelta
    data = receipt()
    env = {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY_ID": str(r.REPO_ID),
           "GITHUB_JOB": "integration", "GITHUB_WORKFLOW_REF": r.REPO+"/.github/workflows/prewatch-ledger-read-diagnostic.yml@refs/heads/main",
           "COLLECTOR_RUN_ID": "123", "GITHUB_RUN_ID": "456"}
    assert r.validate_receipt(data, INDEX, env, NOW) == data["records"]
    with pytest.raises(ValueError, match="RELEASE_RECEIPT_STALE"):
        r.validate_receipt(data, INDEX, env, NOW+timedelta(seconds=181))
    with pytest.raises(ValueError, match="RELEASE_RECEIPT_CONTEXT_INVALID"):
        r.validate_receipt(data, INDEX, dict(env, GITHUB_JOB="other"), NOW)
    with pytest.raises(ValueError, match="RELEASE_RECEIPT_IDENTITY_INVALID"):
        r.validate_receipt(data, INDEX, dict(env, GITHUB_RUN_ID="789"), NOW)

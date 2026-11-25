"""GET-only draft Release readback, with compact intra-workflow receipts.

Run this trusted module in an isolated manually approved job. It never writes
to GitHub, never handles Google credentials and never emits raw release bodies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = "Maremoo2/rikstoto-program-collector"
REPO_ID = 1424144324
MARKER_ID = 458013574
MARKER_TAG = "prewatch-ready-v1"
SCHEMA = "prewatch_release_receipt_v1"
MAX_PAGES = 100
MAX_BYTES = 32 * 1024 * 1024
MAX_RECEIPT_AGE = 180
OBS = re.compile(r"^SNAPSHOT_OBSERVED_UTC=([^ |\n]+) \| SOURCE_CLOCK=LATEST_OFFICIAL_ROSTER_RECEIPT$", re.M)


def need(value, code):
    if not value:
        raise ValueError(code)


def now():
    return datetime.now(timezone.utc)


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stamp(text):
    d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    need(d.tzinfo is not None, "RELEASE_CLOCK_INVALID")
    return d.astimezone(timezone.utc)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get(path):
    """The only network primitive. No redirects, no mutation, fixed repo."""
    need(bool(re.fullmatch(r"releases(?:/\d+|\?per_page=100&page=\d+)?", path)), "RELEASE_PATH_INVALID")
    token = os.environ.get("GH_TOKEN", "")
    need(bool(token), "RELEASE_TOKEN_MISSING")
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/{path}", method="GET",
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "prewatch-draft-readback"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=20) as res:
            need(res.status == 200, "RELEASE_API_STATUS_INVALID")
            raw = res.read(MAX_BYTES + 1)
            need(len(raw) <= MAX_BYTES, "RELEASE_RESPONSE_TOO_LARGE")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"RELEASE_HTTP_{exc.code}") from None
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("RELEASE_API_RESPONSE_INVALID") from None


def marker(getter=get):
    r = getter(f"releases/{MARKER_ID}")
    need(isinstance(r, dict) and r.get("id") == MARKER_ID and r.get("tag_name") == MARKER_TAG,
         "RELEASE_MARKER_IDENTITY_INVALID")
    need(r.get("draft") is True and r.get("published_at") is None, "RELEASE_MARKER_NOT_DRAFT")
    return r


def list_rows(getter=get):
    rows, ids = [], set()
    for page in range(1, MAX_PAGES + 1):
        items = getter(f"releases?per_page=100&page={page}")
        need(isinstance(items, list) and len(items) <= 100, "RELEASE_LIST_SHAPE_INVALID")
        for r in items:
            need(isinstance(r, dict) and type(r.get("id")) is int and r["id"] > 0
                 and isinstance(r.get("tag_name"), str), "RELEASE_LIST_ROW_INVALID")
            need(r["id"] not in ids, "RELEASE_PAGINATION_DUPLICATE_ID")
            ids.add(r["id"])
            rows.append({k: r.get(k) for k in ("id", "tag_name", "draft")})
        if len(items) < 100:
            return rows
    raise ValueError("RELEASE_PAGINATION_LIMIT")


def index_tags(index):
    day, run = index["date_oslo"], index["run_id"]
    need(re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and re.fullmatch(r"\d{8}T\d{12}Z", run)
         and run.startswith(day.replace("-", "")), "RELEASE_SOURCE_ID_INVALID")
    archive = f"rikstoto-program-{day}-{run}"
    tags = [m["release_tag"] for m in index["meeting_feeds"]]
    need(0 < len(tags) <= 100 and len(set(tags)) == len(tags), "RELEASE_EXPECTED_TAGS_INVALID")
    pattern = rf"prewatch-src-{re.escape(day)}-[A-Za-z0-9_-]+-p[1-9]\d*-{re.escape(run)}"
    need(all(isinstance(t, str) and re.fullmatch(pattern, t) for t in tags), "RELEASE_EXPECTED_TAGS_INVALID")
    return day, run, archive, set(tags)


def readback(index, collector_run_id, diagnostic_run_id, *, getter=get, clock=now):
    start = clock()
    day, run, archive, wanted = index_tags(index)
    need(start.astimezone(ZoneInfo("Europe/Oslo")).date().isoformat() == day, "RELEASE_SOURCE_DATE_NOT_TODAY")
    need(all(re.fullmatch(r"[0-9]{1,20}", str(x)) for x in (collector_run_id, diagnostic_run_id)),
         "RELEASE_RUN_ID_INVALID")
    try:
        marker(getter)
    except ValueError as exc:
        if str(exc) in {"RELEASE_HTTP_403", "RELEASE_HTTP_404"}:
            raise ValueError("RELEASE_DRAFT_VISIBILITY_UNCONFIRMED") from None
        raise
    rows = list_rows(getter)
    need(any(r["id"] == MARKER_ID and r["tag_name"] == MARKER_TAG and r["draft"] is True for r in rows),
         "RELEASE_DRAFT_LIST_VISIBILITY_UNCONFIRMED")
    prefix = f"rikstoto-program-{day}-"
    tags = wanted | {archive} | {r["tag_name"] for r in rows if r["tag_name"].startswith(prefix)}
    need(len(tags) <= 300, "RELEASE_DAILY_TAG_LIMIT")
    records = []
    for tag in sorted(tags):
        matches = [r for r in rows if r["tag_name"] == tag]
        need(matches, "RELEASE_TAG_MISSING")
        need(len(matches) == 1, "RELEASE_TAG_DUPLICATE")
        rid = matches[0]["id"]
        r = getter(f"releases/{rid}")
        need(isinstance(r, dict) and r.get("id") == rid and r.get("tag_name") == tag, "RELEASE_IDENTITY_MISMATCH")
        need(r.get("draft") is True and r.get("published_at") is None, "RELEASE_NOT_PRIVATE_DRAFT")
        body = r.get("body")
        need(isinstance(body, str), "RELEASE_BODY_MISSING")
        record = {"id": rid, "tag_name": tag, "draft": True, "published_at": None,
                  "body_sha256": sha(body), "assets": []}
        if tag not in wanted:
            obs = OBS.findall(body)
            need(len(obs) == 1, "ARCHIVE_OBSERVATION_INVALID")
            record["observed_utc"] = stamp(obs[0]).isoformat()
            if tag == archive:
                assets = r.get("assets")
                need(isinstance(assets, list), "RELEASE_ASSETS_INVALID")
                for a in assets:
                    need(isinstance(a, dict) and isinstance(a.get("name"), str), "RELEASE_ASSETS_INVALID")
                    record["assets"].append({"name": a["name"], "digest": a.get("digest")})
        records.append(record)
    finish = clock()
    need(0 <= (finish - start).total_seconds() <= 240, "RELEASE_READBACK_DURATION_INVALID")
    return {"schema": SCHEMA, "repository_id": REPO_ID, "source_run_id": run,
            "collector_run_id": str(collector_run_id), "diagnostic_run_id": str(diagnostic_run_id),
            "read_started_utc": start.isoformat(), "read_finished_utc": finish.isoformat(), "records": records}


def validate_receipt(receipt, index, env, clock):
    """Accept live evidence only from the approved workflow's same-run job output.

    This is a trusted workflow boundary, not an externally signed receipt.
    Offline input remains replay-only in the integration CLI.
    """
    need(env.get("GITHUB_ACTIONS") == "true" and env.get("GITHUB_REF") == "refs/heads/main"
         and env.get("GITHUB_REPOSITORY_ID") == str(REPO_ID) and env.get("GITHUB_JOB") == "integration"
         and env.get("GITHUB_WORKFLOW_REF") == REPO + "/.github/workflows/prewatch-ledger-read-diagnostic.yml@refs/heads/main",
         "RELEASE_RECEIPT_CONTEXT_INVALID")
    _, run, _, _ = index_tags(index)
    need(isinstance(receipt, dict) and receipt.get("schema") == SCHEMA and receipt.get("repository_id") == REPO_ID
         and receipt.get("source_run_id") == run and receipt.get("collector_run_id") == env.get("COLLECTOR_RUN_ID")
         and receipt.get("diagnostic_run_id") == env.get("GITHUB_RUN_ID"), "RELEASE_RECEIPT_IDENTITY_INVALID")
    start, finish = stamp(receipt["read_started_utc"]), stamp(receipt["read_finished_utc"])
    need(0 <= (finish - start).total_seconds() <= 240 and 0 <= (clock - finish).total_seconds() <= MAX_RECEIPT_AGE,
         "RELEASE_RECEIPT_STALE")
    records = receipt.get("records")
    need(isinstance(records, list) and 0 < len(records) <= 300, "RELEASE_RECEIPT_RECORDS_INVALID")
    need(all(isinstance(r, dict) and re.fullmatch(r"[a-f0-9]{64}", r.get("body_sha256", "")) for r in records),
         "RELEASE_RECEIPT_RECORDS_INVALID")
    return records


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--index", type=Path)
    p.add_argument("--probe", action="store_true")
    a = p.parse_args()
    try:
        if a.probe:
            # Compare a known numeric draft with a bounded first-page listing.
            try:
                marker()
                print("RELEASE_PROBE_NUMERIC_DRAFT_VISIBLE")
            except ValueError as exc:
                print("RELEASE_PROBE_NUMERIC_" + str(exc))
            rows = get("releases?per_page=100&page=1")
            need(isinstance(rows, list), "RELEASE_LIST_SHAPE_INVALID")
            print("RELEASE_PROBE_FIRST_PAGE_COUNT=" + str(len(rows)))
            print("RELEASE_PROBE_FIRST_PAGE_DRAFT_COUNT=" + str(sum(r.get("draft") is True for r in rows)))
            return
        need(a.index is not None, "RELEASE_INDEX_MISSING")
        index = json.loads(a.index.read_bytes())
        receipt = readback(index, os.environ["COLLECTOR_RUN_ID"], os.environ["GITHUB_RUN_ID"])
        raw = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        need(len(raw.encode("utf-8")) <= 100_000, "RELEASE_RECEIPT_TOO_LARGE")
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write("receipt=" + raw + "\n")
        print("RELEASE_NUMERIC_READBACK_PASS")
        print("RELEASE_RECORDS_VERIFIED=" + str(len(receipt["records"])))
    except Exception as exc:
        code = str(exc)
        print(code if re.fullmatch(r"[A-Z][A-Z0-9_]{2,90}", code) else "RELEASE_DIAGNOSTIC_FAILED")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

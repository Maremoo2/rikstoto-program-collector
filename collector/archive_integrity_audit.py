"""Read-only audit of collector day ZIP artifacts and original HTTP body receipts.

Supports GitHub Actions ZIP layout (output/daily/day/run/...) and a draft
release ZIP layout (day/run/...). Does not extract files or infer absent
source timestamps, independent full-day coverage, PIT or betting eligibility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

_RUN = re.compile(r"\d{8}T\d{12}Z\Z")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _archive_name(name: str, names: set[str], prefix: str) -> str | None:
    """Resolve only the two collector-owned documented ZIP layouts."""
    if not isinstance(name, str) or not name:
        return None
    if name in names:
        return name
    if name.startswith("output/daily/"):
        candidate = name[len("output/daily/"):]
        if candidate.startswith(prefix) and candidate in names:
            return candidate
    return None


def audit_archive_zip(archive: Path | str) -> dict:
    """Return proof counts, not coverage certification. Never mutate the ZIP."""
    report = {
        "status": "BLOCKED", "manifest": None,
        "pdf_raw_sha_verified": 0, "json_raw_sha_verified": 0,
        "json_wrapper_sha_verified": 0, "json_raw_unavailable_legacy": 0,
        "requests_observed": 0, "raw_provenance_complete": False,
        "completeness_verified": False, "pit_certified": False,
        "errors": [],
    }
    try:
        with zipfile.ZipFile(archive) as zipped:
            names = zipped.namelist()
            if len(names) != len(set(names)):
                report["errors"].append("DUPLICATE_ZIP_PATH")
                return report
            for name in names:
                parts = PurePosixPath(name).parts
                if (not name or name.startswith("/") or "\\" in name
                        or ".." in parts):
                    report["errors"].append("UNSAFE_ZIP_PATH")
                    return report
            file_names = set(names)
            manifests = [n for n in names if n.endswith("/manifest.json")]
            if len(manifests) != 1:
                report["errors"].append("NOT_EXACTLY_ONE_DAILY_MANIFEST")
                return report
            manifest_path = manifests[0]
            report["manifest"] = manifest_path
            data = json.loads(zipped.read(manifest_path))
            day, run = data.get("date_oslo"), data.get("run_id")
            prefix = "/".join(PurePosixPath(manifest_path).parts[-3:-1]) + "/"
            if (not isinstance(day, str) or not isinstance(run, str)
                    or not _RUN.fullmatch(run)
                    or prefix != f"{day}/{run}/"):
                report["errors"].append("MANIFEST_IDENTITY_MISMATCH")
                return report
            requests = data.get("requests")
            if not isinstance(requests, list):
                report["errors"].append("REQUEST_MANIFEST_UNRECOGNIZED")
                return report
            report["date_oslo"] = day
            report["run_id"] = run
            report["requests_observed"] = len(requests)
            report["meeting_refs"] = len(data.get("meetings", []))
            report["physical_meeting_candidates"] = sum(
                m.get("is_multi_track_product") is False
                for m in data.get("meetings", []) if isinstance(m, dict))
            report["composite_meeting_refs"] = sum(
                m.get("is_multi_track_product") is True
                for m in data.get("meetings", []) if isinstance(m, dict))
            report["reported_unique_track_races"] = data.get("counts", {}).get(
                "unique_track_races")
            report["reported_unique_track_horses"] = data.get("counts", {}).get(
                "unique_track_horses")
            report["calendar_status"] = data.get(
                "calendar_source_diagnostic", {}).get("status", "NOT_RECORDED")
            report["collector_status"] = data.get("status")
            report["source_coverage_certified_by_collector"] = (
                data.get("completeness_verified") is True)
            # Even a source-declared flag is not independent full-day proof.
            report["completeness_verified"] = False

            for entry in requests:
                if not isinstance(entry, dict):
                    report["errors"].append("MALFORMED_REQUEST_RECEIPT")
                    continue
                status = entry.get("status")
                if status not in ("PDF_OK", "JSON_OK"):
                    continue
                recorded = entry.get("sha256")
                if not isinstance(recorded, str) or not re.fullmatch(
                        r"[0-9a-f]{64}", recorded):
                    report["errors"].append("MISSING_OR_INVALID_SOURCE_SHA")
                    continue
                if status == "PDF_OK":
                    resolved = _archive_name(entry.get("path"), file_names, prefix)
                    if not resolved:
                        report["errors"].append("PDF_ARCHIVE_PATH_MISSING")
                    elif _sha(zipped.read(resolved)) != recorded:
                        report["errors"].append("PDF_SOURCE_SHA_MISMATCH")
                    else:
                        report["pdf_raw_sha_verified"] += 1
                    continue

                formatted = _archive_name(entry.get("path"), file_names, prefix)
                raw_path = entry.get("raw_path")
                if not raw_path:
                    # Legacy collector deliberately stored a pretty wrapper,
                    # not original HTTP bytes. It cannot be retro-certified.
                    report["json_raw_unavailable_legacy"] += 1
                    continue
                raw_name = _archive_name(raw_path, file_names, prefix)
                if not raw_name or not formatted:
                    report["errors"].append("JSON_ORIGINAL_OR_WRAPPER_NOT_ARCHIVED")
                    continue
                raw_bytes = zipped.read(raw_name)
                wrapper_bytes = zipped.read(formatted)
                if _sha(raw_bytes) != recorded:
                    report["errors"].append("JSON_ORIGINAL_SHA_MISMATCH")
                    continue
                wrapper_sha = entry.get("wrapper_sha256")
                if not isinstance(wrapper_sha, str) or _sha(wrapper_bytes) != wrapper_sha:
                    report["errors"].append("JSON_WRAPPER_SHA_MISMATCH")
                    continue
                try:
                    if json.loads(raw_bytes) != json.loads(wrapper_bytes)["response"]:
                        report["errors"].append("JSON_WRAPPER_RESPONSE_DISAGREES")
                        continue
                except (TypeError, ValueError, KeyError):
                    report["errors"].append("JSON_WRAPPER_RESPONSE_UNREADABLE")
                    continue
                report["json_raw_sha_verified"] += 1
                report["json_wrapper_sha_verified"] += 1

            report["raw_provenance_complete"] = (
                not report["errors"]
                and report["json_raw_unavailable_legacy"] == 0
                and report["pdf_raw_sha_verified"] +
                report["json_raw_sha_verified"] ==
                sum(r.get("status") in ("PDF_OK", "JSON_OK")
                    for r in requests if isinstance(r, dict)))
            report["status"] = ("BLOCKED" if report["errors"] else
                                "AUDITED_SOURCE_BYTES_UNVERIFIED_DAY")
            return report
    except (OSError, zipfile.BadZipFile, UnicodeError, ValueError, TypeError) as exc:
        report["errors"].append("ARCHIVE_UNREADABLE:" + type(exc).__name__)
        return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only source ZIP integrity audit")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    report = audit_archive_zip(args.archive)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

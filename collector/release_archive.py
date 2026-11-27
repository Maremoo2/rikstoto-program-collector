"""Package one immutable Rikstoto daily source snapshot for GitHub Releases.

Actions artifacts expire; the release ZIP and its SHA-256 checksum are stored
as repository release assets and remain available until deleted or service
policy changes. Never publish any authenticated content or betting credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

MAX_UNCOMPRESSED_BYTES = 800_000_000
MAX_ZIP_BYTES = 1_900_000_000
RUN_ID = re.compile(r"^\d{8}T\d{12}Z$")
CAPTURE_STATUSES = {"CAPTURED_UNVERIFIED", "REVIEW_REQUIRED"}


def find_latest_run(root: Path) -> tuple[Path, dict]:
    candidates = sorted(root.glob("*/*/manifest.json"))
    if not candidates:
        raise ValueError(f"No daily manifest found under {root}; cannot persist an empty archive")
    manifest = candidates[-1]
    data = json.loads(manifest.read_text(encoding="utf-8"))
    day = data.get("date_oslo")
    run = data.get("run_id")
    if (not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
            or not isinstance(run, str) or not RUN_ID.fullmatch(run)
            or manifest.parent.name != run or manifest.parent.parent.name != day):
        raise ValueError("Daily manifest date/run ID does not match the archive path")
    return manifest.parent, data


def build_release_archive(root: Path, dest: Path) -> dict:
    folder, manifest = find_latest_run(root)
    day = manifest["date_oslo"]
    run_id = manifest["run_id"]
    dest.mkdir(parents=True, exist_ok=True)
    name = f"rikstoto-{day}-{run_id}.zip"
    archive = dest / name
    files = sorted(f for f in folder.rglob("*") if f.is_file() and not f.is_symlink())
    if not files or not any(f.name == "manifest.json" for f in files):
        raise ValueError("No manifest in archive source")
    total = sum(p.stat().st_size for p in files)
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("Archive exceeds allowed source size; check the GitHub Actions artifact")
    with zipfile.ZipFile(archive, mode="x", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as zipped:
        for file in files:
            # Preserve date/run prefix in ZIP, no absolute paths.
            zipped.write(file, arcname=f"{day}/{run_id}/{file.relative_to(folder).as_posix()}")
    if archive.stat().st_size > MAX_ZIP_BYTES:
        archive.unlink(missing_ok=True)
        raise ValueError("ZIP exceeds GitHub Release asset size limit")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum = dest / f"{name}.sha256"
    checksum.write_text(f"{digest.hexdigest()}  {name}\n", encoding="utf-8")
    notes = dest / "release_notes.md"
    notes.write_text(
        f"# Rikstoto offentlige løpsprogrammer – {day}\n\n"
        f"**Kjøring:** {run_id}\n\n"
        f"**Status:** {manifest.get('status', 'UNKNOWN')}\n\n"
        f"**Møter i arkivet:** {len(manifest.get('meetings', []))}\n\n"
        "Arkivet inneholder originalfiler fra offentlig tilgjengelige kilder, "
        "tidsstempler, kontrollrapport og uverifisert programstruktur. "
        "Det garanterer ikke alle dagens løp, endelige strykninger eller odds.\n\n"
        "Hver ZIP-fil er en separat, uendret kjøring. "
        "Sammenlign SHA-256 med tilhørende .sha256-fil.\n",
        encoding="utf-8",
    )
    return {
        "tag": f"rikstoto-program-{day}-{run_id}",
        "archive": str(archive),
        "checksum": str(checksum),
        "notes": str(notes),
        "date": day,
        "run_id": run_id,
        "files": len(files),
        "uncompressed_bytes": total,
        "zip_bytes": archive.stat().st_size,
        "sha256": digest.hexdigest(),
        "collection_status": manifest.get("status", "UNKNOWN"),
    }


def prepare_publication(root: Path, feed: Path, dest: Path, capture_date: str,
                        capture_status: str) -> dict:
    """Validate the workflow artifact before granting any publishing step access."""
    from .prewatch_handoff import build_handoff

    if len(list(root.glob("*/*/manifest.json"))) != 1:
        raise ValueError("Expected exactly one daily manifest")
    folder, manifest = find_latest_run(root)
    run = manifest["run_id"]
    if (capture_status not in CAPTURE_STATUSES or manifest["status"] != capture_status
            or manifest["date_oslo"] != capture_date
            or not run.startswith(capture_date.replace("-", ""))):
        raise ValueError("Capture status or date/run binding mismatch")
    if any(path.is_symlink() for path in folder.rglob("*")):
        raise ValueError("Unexpected symlink in original snapshot")
    prefix = f"output/daily/{capture_date}/{run}/"
    verified_originals = set()

    def verify(path, expected, size):
        if not isinstance(path, str) or not path.startswith(prefix):
            raise ValueError("Source receipt path outside captured run")
        relative = path.removeprefix(prefix)
        file = folder / relative
        if (file.resolve() != file or folder not in file.parents or not file.is_file()
                or type(size) is not int or file.stat().st_size != size):
            raise ValueError("Source receipt missing file or size mismatch")
        with file.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("Source receipt hash mismatch")
        return file

    folder = folder.resolve()
    for receipt in manifest["requests"]:
        status = receipt["status"]
        if status in {"SOURCE_ARCHIVE_COLLISION", "ARCHIVE_READBACK_FAILED"}:
            raise ValueError("Collector reported an integrity failure")
        if status not in {"PDF_OK", "JSON_OK"}:
            continue
        if receipt["raw_readback_verified"] is not True:
            raise ValueError("Original source readback missing")
        if status == "JSON_OK":
            verify(receipt["path"], receipt["wrapper_sha256"], receipt["wrapper_bytes"])
            original = verify(receipt["raw_path"], receipt["sha256"], receipt["bytes"])
        else:
            original = verify(receipt["path"], receipt["sha256"], receipt["bytes"])
        if original in verified_originals:
            raise ValueError("Duplicate original source receipt")
        verified_originals.add(original)
    if verified_originals != {*folder.rglob("*.raw.json"), *folder.rglob("*.pdf")}:
        raise ValueError("Missing original source receipt")

    build_handoff(root, feed)
    index = json.loads((feed / "index.json").read_bytes())
    qualified = sum(
        row["source_ready_snapshot"] is True and not row["source_blockers"]
        and row["official_roster_handoff_status"] == "VERIFIED_AS_OF_SOURCE_CAPTURE"
        for row in index["race_queue"]
    )
    if not qualified:
        raise ValueError("No individually verified NO/SE races")
    data = build_release_archive(root, dest)
    with zipfile.ZipFile(data["archive"]) as archive:
        if archive.testzip() is not None:
            raise ValueError("Packaged archive failed ZIP integrity verification")
    return {**data, "qualified_no_se_races": qualified}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Immutable daily program ZIP with checksum for release")
    p.add_argument("--root", type=Path, default=Path("output/daily"))
    p.add_argument("--dest", type=Path, default=Path("release_assets"))
    p.add_argument("--github-output", type=Path, default=None)
    p.add_argument("--publication-feed", type=Path)
    p.add_argument("--capture-date")
    p.add_argument("--capture-status")
    args = p.parse_args(argv)
    if args.publication_feed is not None:
        data = prepare_publication(
            args.root, args.publication_feed, args.dest, args.capture_date, args.capture_status,
        )
    else:
        data = build_release_archive(args.root, args.dest)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key in ("tag", "archive", "checksum", "notes", "date", "run_id"):
                output.write(f"{key}={data[key]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

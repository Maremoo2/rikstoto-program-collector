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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Immutable daily program ZIP with checksum for release")
    p.add_argument("--root", type=Path, default=Path("output/daily"))
    p.add_argument("--dest", type=Path, default=Path("release_assets"))
    p.add_argument("--github-output", type=Path, default=None)
    args = p.parse_args(argv)
    data = build_release_archive(args.root, args.dest)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key in ("tag", "archive", "checksum", "notes", "date", "run_id"):
                output.write(f"{key}={data[key]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Offline C-DEV-04 shadow evidence for historical rows from original PDFs.

Reuses the existing Collector PDF parser solely to index source line ownership.
Does not write accepted past-start fields, source gold, production exports,
PIT clocks or betting inputs. The Betting DATA-004E double-review workflow
owns independent 390-field gold acceptance; it is not implemented here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

from .pdf_program import parse_extended_pdf

HISTORY_GOLD_FIELDS = (
    "date", "track", "race_number", "distance", "start_method",
    "result_category", "placing", "km_time", "driver", "shoes",
    "wagon", "gallop", "dq",
)
SCHEMA = "collector_cdev04_original_history_shadow_v1"
MEETING = re.compile(r"[A-Z0-9]{1,14}_[A-Z]{2,4}_(20\d{2}-\d{2}-\d{2})\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
POST = re.compile(r"\|\s*(\d{1,2})(?=\s|$)")
DISTANCE = re.compile(r"(?<!\d)([12]\d{3}|3\d{3}|4[0-5]\d{2})(?!\d)")
MAX_ARCHIVED_TEXT_BYTES = 12_000_000


def _abstentions(start: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Source tokens are candidates, never independently accepted gold.

    Only date and race number are returned from the incumbent conservative
    Collector parser, with a distinct source-observed, not gold, status.
    We must never infer negatives for gallop or disqualification.
    """
    result = {
        key: {"status": "ABSTAIN_INDEPENDENT_GOLD_PENDING", "value": None}
        for key in HISTORY_GOLD_FIELDS
    }
    for key in ("date", "race_number"):
        value = start.get(key)
        if value is not None:
            result[key] = {"status": "SOURCE_EXTRACTED_UNVERIFIED", "value": value}
    return result


def build_history_shadow(
    pdf_text: str,
    *,
    meeting_id: str,
    racing_date: str,
    source_archive_sha256: str,
    source_pdf_sha256: str,
    pdf_text_sha256: str,
) -> dict[str, Any]:
    """Index original-program text rows with explicit provenance and abstentions.

    The PDF bytes may be integrity-verified separately. The derived .txt
    projection is not *cryptographically* proven to have originated from the
    PDF merely because both appeared in an archived ZIP.
    """
    if (not MEETING.fullmatch(meeting_id)
            or not meeting_id.endswith("_" + racing_date)
            or date.fromisoformat(racing_date).isoformat() != racing_date
            or any(not HEX.fullmatch(value) for value in (
                source_archive_sha256, source_pdf_sha256, pdf_text_sha256))):
        raise ValueError("Invalid source identity, date or source SHA")
    expected_text = hashlib.sha256(pdf_text.encode("utf-8")).hexdigest()
    if expected_text != pdf_text_sha256:
        raise ValueError("Derived PDF text SHA mismatch")
    parsed = parse_extended_pdf(
        pdf_text, meeting_id=meeting_id, date=racing_date,
        url="offline-original-archive-sha256:" + source_archive_sha256,
        captured_at="UNATTESTED_ARCHIVE_ORIGIN_TIME",
    )
    entries = []
    diagnostics: dict[str, int] = {}
    for doc in parsed["races"]:
        race = doc["race"]
        for horse in doc["entrants"]:
            for index, start in enumerate(horse["past_starts"], 1):
                raw = start["raw_text"]
                # The old source parser may spot date/race in a joined row;
                # neither an ordinal row number nor a parsed snippet is gold.
                row_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                status = "SOURCE_ROW_CANDIDATE_NOT_GOLD"
                if start["date"] is None:
                    status = "INVALID_HISTORY_DATE_ABSTAIN"
                elif start["date"] > racing_date:
                    status = "HISTORY_DATE_AFTER_RACEDAY_ABSTAIN"
                diagnostics[status] = diagnostics.get(status, 0) + 1
                pipe_tail = raw.split("|", 1)[1] if "|" in raw else ""
                post = POST.search(raw)
                possible_distances = sorted({
                    int(m.group(1)) for m in DISTANCE.finditer(pipe_tail)
                })
                entries.append({
                    "source": {
                        "meeting_id": meeting_id,
                        "racing_date": racing_date,
                        "physical_pdf_sha256": source_pdf_sha256,
                        "derived_text_sha256": pdf_text_sha256,
                        "race_number": race["race_number"],
                        "race_number_source": race["race_number_source"],
                        "horse_program_number": horse["program_number"],
                        "horse_name": horse["name"],
                        "history_ordinal_within_horse": index,
                        "source_line_sha256": row_sha,
                        "raw_text": raw,
                    },
                    "status": status,
                    "source_tokens_not_gold": {
                        "post_after_pipe": int(post.group(1)) if post else None,
                        "distance_tokens_after_pipe": possible_distances,
                        "contains_pipe": bool(pipe_tail),
                    },
                    "gold_field_candidates": _abstentions(start),
                    "source_text_projection_is_official_pdf_attested": False,
                    "source_publication_time_attested": False,
                    "pit_certified": False,
                })
    return {
        "schema": SCHEMA,
        "source_archive_sha256": source_archive_sha256,
        "source_pdf_sha256": source_pdf_sha256,
        "pdf_text_sha256": pdf_text_sha256,
        "meeting_id": meeting_id,
        "racing_date": racing_date,
        "source_scope": "IMMUTABLE_ARCHIVED_PDF_BYTES_PLUS_UNATTESTED_TEXT_PROJECTION",
        "parse_status": parsed["qa"]["status"],
        "original_pdf_date_status": parsed["qa"]["warnings"],
        "pdf_race_sections": parsed["qa"]["race_sections"],
        "pdf_horse_headers": parsed["qa"].get("horses", 0),
        "history_source_rows_indexed": len(entries),
        "source_row_diagnostics": diagnostics,
        "history_rows": entries,
        "gold_fields_per_row": len(HISTORY_GOLD_FIELDS),
        "independent_gold_field_pairs_accepted": 0,
        "data004e_holdout_390_accepted": 0,
        "data004e_holdout_verified": False,
        "production_parser_changed": False,
        "production_parser_approved": False,
        "source_publication_time_attested": False,
        "pit_certified": False,
        "bet_authorized": False,
        "notes": [
            "A source row candidate is not a visually verified horse/history owner or gold field.",
            "Unambiguous-looking tokens remain unverified until independent two-reader gold.",
            "No gallop=False or dq=False inferred from absent markers.",
            "Use existing Betting DATA-004E independent double-review for 390 gold cells.",
        ],
    }


def replay_original_archive(
    archive_path: Path,
    *,
    meeting_id: str,
    date_oslo: str,
    expected_pdf_sha256: str,
) -> dict[str, Any]:
    """Check archived original PDF SHA and paired text, without any HTTP."""
    if not HEX.fullmatch(expected_pdf_sha256):
        raise ValueError("Expected immutable PDF SHA256 required")
    if not MEETING.fullmatch(meeting_id) or not meeting_id.endswith("_" + date_oslo):
        raise ValueError("Meeting identity must match date")
    archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive_path) as archive:
        paths = archive.namelist()
        pdf_paths = [name for name in paths
                     if name.endswith("/meetings/" + meeting_id + "/full_program.pdf")]
        if len(pdf_paths) != 1:
            raise ValueError("Missing or duplicate original physical PDF member")
        pdf_path = pdf_paths[0]
        txt_path = pdf_path[:-4] + ".txt"
        if txt_path not in paths:
            raise ValueError("Missing paired PDF text member")
        original_pdf = archive.read(pdf_path)
        if hashlib.sha256(original_pdf).hexdigest() != expected_pdf_sha256:
            raise ValueError("Original PDF SHA mismatch")
        raw_text = archive.read(txt_path)
        if len(raw_text) > MAX_ARCHIVED_TEXT_BYTES:
            raise ValueError("Derived PDF text exceeds read-only limit")
        source_text = raw_text.decode("utf-8")
        # Original PDF bytes are checksum-attested. This source projection
        # does not become independently attested original PDF page geometry.
        shadow = build_history_shadow(
            source_text, meeting_id=meeting_id, racing_date=date_oslo,
            source_archive_sha256=archive_sha,
            source_pdf_sha256=expected_pdf_sha256,
            pdf_text_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        )
        shadow["source_members"] = {"original_pdf": pdf_path, "derived_text": txt_path}
        shadow["source_bytes_sha256_verified"] = True
        return shadow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--meeting", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--pdf-sha256", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = replay_original_archive(
        args.archive, meeting_id=args.meeting,
        date_oslo=args.date, expected_pdf_sha256=args.pdf_sha256,
    )
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        # Explicit local diagnostic output only; never write to source
        # archive, prospective ledger, public GitHub or Betting.
        if args.output.resolve() == args.archive.resolve():
            raise ValueError("Refusing overwrite of original source archive")
        with args.output.open("x", encoding="utf-8") as target:
            target.write(output + "\n")
    else:
        # Avoid default terminal dumping of thousands of private source rows.
        summary = {key: value for key, value in report.items()
                   if key != "history_rows"}
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["source_bytes_sha256_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

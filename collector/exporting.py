"""Versioned snapshots and human-readable exports. Never rewrite earlier runs."""
from __future__ import annotations

import json
import sqlite3
from html import escape
from pathlib import Path
from typing import Any


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def store_sqlite(path: Path, payload: dict[str, Any]) -> None:
    """Persist one immutable collection run; raw evidence is retained as files."""
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    with db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
          run_id TEXT PRIMARY KEY, created_utc TEXT, source_url TEXT,
          discovery_status TEXT, qa_json TEXT);
        CREATE TABLE IF NOT EXISTS races (
          run_id TEXT, race_key TEXT, meeting_id TEXT, race_number INTEGER,
          track TEXT, scheduled_time_local TEXT, distance_m INTEGER,
          start_method TEXT, url TEXT, status TEXT, qa_json TEXT,
          PRIMARY KEY(run_id, race_key),
          FOREIGN KEY(run_id) REFERENCES runs(run_id));
        CREATE TABLE IF NOT EXISTS entrants (
          run_id TEXT, race_key TEXT, ordinal INTEGER, program_number INTEGER,
          horse_name TEXT, driver TEXT, scratched INTEGER, stats_json TEXT,
          identity_text TEXT, trainer_owner_breeder TEXT, raw_text TEXT,
          PRIMARY KEY(run_id, race_key, ordinal));
        CREATE TABLE IF NOT EXISTS past_starts (
          run_id TEXT, race_key TEXT, entrant_ordinal INTEGER, start_ordinal INTEGER,
          raced_on TEXT, track TEXT, previous_race INTEGER, distance_m INTEGER,
          driver_abbrev TEXT, comment TEXT, raw_text TEXT,
          PRIMARY KEY(run_id, race_key, entrant_ordinal, start_ordinal));
        CREATE TABLE IF NOT EXISTS scratches (
          run_id TEXT, race_key TEXT, horse_number INTEGER, horse_name TEXT);
        CREATE TABLE IF NOT EXISTS win_odds (
          run_id TEXT, race_key TEXT, horse_number INTEGER, horse_name TEXT,
          win_odds REAL, place_min REAL, place_max REAL, captured_utc TEXT);
        CREATE TABLE IF NOT EXISTS capture_evidence (
          run_id TEXT, ordinal INTEGER, url TEXT, status TEXT, captured_utc TEXT,
          http_status INTEGER, html_path TEXT, text_path TEXT, sha256 TEXT, error TEXT,
          PRIMARY KEY(run_id, ordinal));
        """)
        run_id = payload["run_id"]
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (run_id, payload["created_utc"],
                   payload["source_url"], payload["discovery"]["status"],
                   json.dumps(payload["qa"], ensure_ascii=False)))
        for ordinal, evidence in enumerate(payload["captures"]):
            db.execute("INSERT INTO capture_evidence VALUES(?,?,?,?,?,?,?,?,?,?)", (
                run_id, ordinal, evidence.get("url"), evidence.get("status"),
                evidence.get("captured_at_utc"), evidence.get("http_status"),
                evidence.get("html_path"), evidence.get("text_path"),
                evidence.get("sha256"), evidence.get("error")))
        for i, doc in enumerate(payload["races"]):
            race = doc["race"]
            race_key = f'{race.get("meeting_id") or "unknown"}:{race.get("race_number") or i}'
            db.execute("INSERT INTO races VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                run_id, race_key, race.get("meeting_id"), race.get("race_number"),
                race.get("track"), race.get("scheduled_time_local"),
                race.get("distance_m"), race.get("start_method"), race.get("source_url"),
                doc["qa"]["status"], json.dumps(doc["qa"], ensure_ascii=False)))
            for j, entrant in enumerate(doc["entrants"]):
                db.execute("INSERT INTO entrants VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    run_id, race_key, j, entrant.get("program_number"), entrant["name"],
                    entrant.get("driver"), int(entrant.get("scratched", False)),
                    json.dumps({"years":entrant.get("year_stats"),
                                "total":entrant.get("total_stats")}, ensure_ascii=False),
                    entrant.get("identity_text"), entrant.get("trainer_owner_breeder"),
                    entrant.get("raw_section")))
                for k, start in enumerate(entrant["past_starts"]):
                    db.execute("INSERT INTO past_starts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                        run_id, race_key, j, k, start.get("date"), start.get("track"),
                        start.get("race_number"), start.get("distance_m"),
                        start.get("driver_abbrev"), start.get("comment"), start.get("raw_text")))
            for s in doc["scratches"]:
                db.execute("INSERT INTO scratches VALUES(?,?,?,?)", (
                    run_id, race_key, s["horse_number"], s["horse_name"]))
            for o in doc["win_odds"]:
                db.execute("INSERT INTO win_odds VALUES(?,?,?,?,?,?,?,?)", (
                    run_id, race_key, o["horse_number"], o["horse_name"],
                    o["win_odds"], o["place_min"], o["place_max"],
                    race["captured_at_utc"]))
    db.close()


def export_xlsx(path: Path, payload: dict[str, Any]) -> None:
    """Review-friendly workbook. No spreadsheet calculation is used for model probabilities."""
    import xlsxwriter
    book = xlsxwriter.Workbook(str(path), {"strings_to_urls": False})
    head = book.add_format({"bold": True, "font_color": "white", "bg_color": "#183153",
                            "text_wrap": True, "valign": "top"})
    txt = book.add_format({"text_wrap": True, "valign": "top"})
    fmtwarn = book.add_format({"font_color": "#9C2E25"})
    data: dict[str, tuple[list[str], list[list[Any]]]] = {
        "Løp": (["Meeting", "Løp", "Bane", "Starttid", "Distanse", "Start", "Hester",
                 "Aktive", "Strøket", "Tidligere starter", "Kvalitetsstatus", "Advarsler", "Kilde"], []),
        "Hester": (["Meeting", "Løp", "Nummer", "Hest", "Kusk", "Strøket",
                    "Antall tidligere starter", "Tot starter", "Tot seier", "Identitet", "Trener/eier", "Kilde"], []),
        "Historikk": (["Meeting", "Løp", "Hest", "Dato", "Bane", "Historisk løp", "Spor",
                      "Distanse", "Kusk", "Kommentar", "Rå rad"], []),
        "Strykninger": (["Meeting", "Løp", "Nummer", "Hest"], []),
        "Odds VIN": (["Meeting", "Løp", "Hest nr", "Hest", "Vinner", "Plass min",
                      "Plass maks", "Observer tidspunkt UTC"], []),
        "Kilder": (["URL", "Status", "HTTP", "Tid UTC", "SHA256", "Tekstfil", "HTML-fil", "Feil"], []),
    }
    for doc in payload["races"]:
        race = doc["race"]; qa = doc["qa"]
        rid = [race.get("meeting_id"), race.get("race_number")]
        data["Løp"][1].append(rid + [race.get("track"), race.get("scheduled_time_local"),
            race.get("distance_m"), race.get("start_method"), qa["entrant_count"],
            qa["active_count"], qa["scratched_count"], qa["past_start_rows"],
            qa["status"], "; ".join(qa["warnings"]), race["source_url"]])
        for h in doc["entrants"]:
            stats = h.get("total_stats") or {}
            data["Hester"][1].append(rid + [h.get("program_number"), h["name"],
              h.get("driver"), "JA" if h.get("scratched") else "NEI", len(h["past_starts"]),
              stats.get("starts"), stats.get("wins"), h.get("identity_text"),
              h.get("trainer_owner_breeder"), race["source_url"]])
            for start in h["past_starts"]:
                data["Historikk"][1].append(rid + [h["name"], start.get("date"),
                    start.get("track"), start.get("race_number"), start.get("post"),
                    start.get("distance_m"), start.get("driver_abbrev"),
                    start.get("comment"), start.get("raw_text")])
        for s in doc["scratches"]:
            data["Strykninger"][1].append(rid + [s.get("horse_number"), s.get("horse_name")])
        for o in doc["win_odds"]:
            data["Odds VIN"][1].append(rid + [o.get("horse_number"), o.get("horse_name"),
                o.get("win_odds"), o.get("place_min"), o.get("place_max"),
                race["captured_at_utc"]])
    for e in payload["captures"]:
        data["Kilder"][1].append([e.get("url"), e.get("status"), e.get("http_status"),
            e.get("captured_at_utc"), e.get("sha256"), e.get("text_path"),
            e.get("html_path"), e.get("error")])
    for name, (cols, rows) in data.items():
        sheet = book.add_worksheet(name)
        sheet.freeze_panes(1, 0)
        sheet.set_row(0, 32)
        sheet.set_column(0, min(7,len(cols)-1), 16)
        if name in ("Historikk", "Hester"):
            sheet.set_column(len(cols)-2, len(cols)-1, 43)
        if name == "Løp":
            sheet.set_column(11, 12, 50)
        if name == "Kilder":
            sheet.set_column(0, 0, 55)
        for c, key in enumerate(cols):
            sheet.write(0, c, key, head)
        for r, values in enumerate(rows, 1):
            for c, val in enumerate(values):
                if val is None: continue
                sheet.write(r, c, val, fmtwarn if val == "REVIEW_REQUIRED" else txt)
        if rows:
            sheet.autofilter(0, 0, len(rows), len(cols)-1)
    book.close()


def export_pdf(path: Path, payload: dict[str, Any]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether
    font = "Helvetica"
    from pathlib import Path as _Path
    font_file = _Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if font_file.exists():
        pdfmetrics.registerFont(TTFont("DejaVuSans-Collector", str(font_file)))
        font = "DejaVuSans-Collector"
    styles = getSampleStyleSheet()
    for name in ("Normal", "Title", "Heading1", "Heading2"):
        styles[name].fontName = font
    small = ParagraphStyle("smallCollector", parent=styles["Normal"], fontName=font,
                           fontSize=8, leading=12, spaceAfter=5)
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=34, leftMargin=34,
                            topMargin=37, bottomMargin=35)
    story = [Paragraph("Rikstoto – lagret løpsprogram", styles["Title"]),
             Paragraph(f"Run: {escape(payload['run_id'])}", small),
             Paragraph("Data er avlest fra kilde. Ingen bettinganalyse eller garantert kompletthet.",small)]
    for r_i, entry in enumerate(payload["races"]):
        race = entry["race"]; qa = entry["qa"]
        if r_i: story.append(PageBreak())
        story.append(Paragraph(f"{escape(str(race.get('track') or 'Ukjent bane'))} – løp {race.get('race_number')}", styles["Heading1"]))
        story.append(Paragraph(escape(f"{race.get('scheduled_time_local') or '?'} | {race.get('distance_m') or '?'} m | {race.get('start_method') or '?'} | {qa['entrant_count']} oppførte / {qa['active_count']} aktive"), small))
        story.append(Paragraph(f"Kvalitet: {escape(qa['status'])} | {escape(', '.join(qa['warnings']) or 'Ingen parser-advarsler')}", small))
        story.append(Paragraph(f"Kilde: {escape(race['source_url'])}", small))
        for h in entry["entrants"]:
            head = f"#{h.get('program_number') or '?'} {h['name']}"
            if h.get("scratched"): head += " (STRØKET)"
            details = [Paragraph(escape(head),styles["Heading2"]),
                       Paragraph(escape(f"Kusk: {h.get('driver') or '?'} | Tidligere starter: {len(h['past_starts'])}"), small)]
            if h.get("identity_text"):
                details.append(Paragraph(escape(h["identity_text"]), small))
            if h.get("trainer_owner_breeder"):
                details.append(Paragraph(escape(h["trainer_owner_breeder"]),small))
            story.append(KeepTogether(details))
            for s in h["past_starts"]:
                raw = escape(s.get("raw_text") or "").replace("\n", "<br/>")
                story.append(Paragraph(f"<b>{escape(str(s.get('date') or '?'))}</b> | {raw}",small))
    if not payload["races"]:
        story.append(Paragraph("Ingen gyldige løpsprogrammer ble hentet. Se manifest og logg.", small))
    doc.build(story)


def finish_outputs(directory: Path, payload: dict[str, Any]) -> None:
    write_json(directory / "program.json", payload)
    store_sqlite(directory / "program.sqlite", payload)
    export_xlsx(directory / "program.xlsx", payload)
    export_pdf(directory / "program.pdf", payload)
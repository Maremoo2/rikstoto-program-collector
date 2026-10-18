"""Single-meeting probe for Rikstoto's publicly observed expanded PDF format.

The endpoint format is documented by independently observed historical PDFs,
but the existence of a PDF for a NEW meeting is never assumed. No URL sweeps.
"""
from __future__ import annotations

import hashlib
import io
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

DOMAIN = "www.rikstoto.no"
MAX_BYTES = 20_000_000
MEETING = re.compile(r"^/Spill/([A-Z0-9]+_NR_20\d{2}-\d{2}-\d{2})(?:/|$)", re.I)


def candidate_url(race_url: str) -> str | None:
    parsed = urlparse(race_url)
    if parsed.scheme != "https" or parsed.hostname != DOMAIN:
        return None
    match = MEETING.match(parsed.path)
    if not match:
        return None
    return f"https://{DOMAIN}/api/programdownload/ProgramPdf/Utvidet/{match.group(1)}"


def retrieve_pdf(pdf_url: str, directory: Path) -> dict:
    """Check exactly one inferred candidate, enforce limit/type, preserve source."""
    directory.mkdir(parents=True, exist_ok=True)
    if not pdf_url.startswith(f"https://{DOMAIN}/api/programdownload/ProgramPdf/Utvidet/"):
        return {"code": "PDF_URL_UNEXPECTED", "ok": False}
    request = urllib.request.Request(
        pdf_url, headers={"User-Agent": "RikstotoProgramCollector/1.0 (public-data diagnostics)",
                          "Accept": "application/pdf"})
    try:
        with urllib.request.urlopen(request, timeout=25) as reply:
            status = reply.status
            if status != 200:
                return {"ok": False, "code": f"PDF_HTTP_{status}", "http_status": status}
            chunks, total = [], 0
            while True:
                chunk = reply.read(min(1024 * 1024, MAX_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_BYTES:
                    return {"ok": False, "code": "PDF_TOO_LARGE", "downloaded_bytes": total}
            binary = b"".join(chunks)
            if not binary.startswith(b"%PDF-"):
                return {"ok": False, "code": "PDF_RESPONSE_NOT_PDF",
                        "http_status": status, "bytes": len(binary),
                        "content_type": reply.headers.get("Content-Type", "")}
            pdfpath = directory / "official_candidate.pdf"
            pdfpath.write_bytes(binary)
            result = {"ok": True, "code": "PDF_DOWNLOADED", "bytes": total,
                      "sha256": hashlib.sha256(binary).hexdigest(),
                      "pdf_path": pdfpath.name, "http_status": status,
                      "pdf_url": pdf_url, "text_verified": False}
            try:
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(binary))
                pages = len(reader.pages)
                extracted = "\n\n".join(page.extract_text() or "" for page in reader.pages)
                (directory / "official_candidate.txt").write_text(extracted, encoding="utf-8")
                result.update(pages=pages, text_characters=len(extracted),
                              text_path="official_candidate.txt",
                              text_verified=bool(extracted.strip()),
                              text_preview=re.sub(r"\s+", " ", extracted)[:180])
                if not extracted.strip():
                    result["code"] = "PDF_TEXT_EMPTY"
            except ImportError:
                result["code"] = "PDF_DOWNLOADED_TEXT_TOOL_MISSING"
            except Exception as exc:
                result["code"] = "PDF_TEXT_EXTRACTION_FAILED"
                result["text_error"] = f"{type(exc).__name__}: {str(exc)[:350]}"
            return result
    except urllib.error.HTTPError as exc:
        return {"ok": False, "code": f"PDF_HTTP_{exc.code}", "http_status": exc.code,
                "pdf_url": pdf_url}
    except Exception as exc:
        return {"ok": False, "code": "PDF_NETWORK_ERROR",
                "detail": f"{type(exc).__name__}: {str(exc)[:350]}", "pdf_url": pdf_url}

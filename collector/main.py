"""Rikstoto program collector: auditable capture, no undocumented API assumptions."""
import argparse
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright
from openpyxl import Workbook
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

HOST = 'www.rikstoto.no'
RACE_RE = re.compile(r'/Spill/[^?#]+(?:\?[^#]*)?', re.I)


def allowed(url):
    p = urlparse(url)
    return p.scheme == 'https' and p.hostname == HOST


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def export(run_dir, records):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Pages'
    ws.append(['url', 'captured_at_utc', 'title', 'status', 'text_sha256', 'text_file', 'html_file', 'pdf_file'])
    for r in records:
        ws.append([r.get(k) for k in ('url','captured_at_utc','title','status','text_sha256','text_file','html_file','pdf_file')])
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    wb.save(run_dir / 'program_capture.xlsx')
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(run_dir / 'program_capture.pdf'))
    story = [Paragraph('Rikstoto program capture – source audit', styles['Title']), Spacer(1,12)]
    for r in records:
        story.append(Paragraph(str(r.get('title') or 'Untitled'), styles['Heading2']))
        for k in ('url','captured_at_utc','status','text_sha256'):
            story.append(Paragraph(f'{k}: {r.get(k)}', styles['BodyText']))
        story.append(Spacer(1,10))
    doc.build(story)


async def capture(url, page, run_dir, index, print_pdf):
    record = {'url': url, 'captured_at_utc': utcnow(), 'status': 'error'}
    try:
        response = await page.goto(url, wait_until='domcontentloaded', timeout=45000)
        await page.wait_for_timeout(1800)
        record['http_status'] = response.status if response else None
        record['title'] = await page.title()
        text = await page.locator('body').inner_text(timeout=12000)
        html = await page.content()
        prefix = f'page_{index:03}'
        (run_dir / f'{prefix}.txt').write_text(text, encoding='utf-8')
        (run_dir / f'{prefix}.html').write_text(html, encoding='utf-8')
        record.update(text_file=f'{prefix}.txt', html_file=f'{prefix}.html',
                      text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                      status='captured' if text.strip() and (not response or response.ok) else 'incomplete')
        if print_pdf:
            await page.pdf(path=str(run_dir / f'{prefix}.pdf'), print_background=True)
            record['pdf_file'] = f'{prefix}.pdf'
        record['links'] = await page.locator('a[href]').evaluate_all('(els) => els.map(e => e.href)')
    except Exception as exc:
        record['error'] = str(exc)
    return record


async def run(args):
    if not allowed(args.url):
        raise SystemExit('Only HTTPS www.rikstoto.no URLs are permitted')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    run_dir = out / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run_dir.mkdir()
    records = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale='nb-NO', timezone_id='Europe/Oslo', accept_downloads=False)
        page = await context.new_page()
        first = await capture(args.url, page, run_dir, 0, args.pdf)
        records.append(first)
        candidates = sorted({u for u in first.get('links', []) if allowed(u) and RACE_RE.search(urlparse(u).path)})
        (run_dir / 'discovered_links.json').write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding='utf-8')
        if args.discover:
            for i, link in enumerate(candidates[:args.max_pages], start=1):
                await page.wait_for_timeout(args.delay_ms)
                records.append(await capture(link, page, run_dir, i, args.pdf))
        await browser.close()
    for r in records:
        r.pop('links', None)
    (run_dir / 'manifest.json').write_text(json.dumps({'source':args.url, 'records':records,
      'note':'Raw page capture only. Horse-level completeness and official program download NOT validated.'}, ensure_ascii=False, indent=2), encoding='utf-8')
    export(run_dir, records)
    print(run_dir)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('--out', default='output')
    parser.add_argument('--discover', action='store_true')
    parser.add_argument('--max-pages', type=int, default=30)
    parser.add_argument('--delay-ms', type=int, default=2500)
    parser.add_argument('--pdf', action='store_true', help='Browser print PDF (not official downloadable program)')
    args = parser.parse_args()
    asyncio.run(run(args))

if __name__ == '__main__':
    main()

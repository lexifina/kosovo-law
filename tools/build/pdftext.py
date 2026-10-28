"""Read the text layer of a gazette PDF from gzk.rks-gov.net into lines with their position (PyMuPDF).

    extract(path) -> {'pages': [{'height', 'width', 'scanned', 'lines': [[x0, y0, x1, y1, size, bold, text, block]]}]}

A page whose text layer holds fewer than 40 letters while it carries an image is a scan (the annexed agreements of
many ratification laws): it is marked `scanned` and its few words (stamps, page numbers) are dropped. Cached as
.cache/pdftext/<act>-<lang>.json, keyed by the PDF's sha256 and EXTRACTOR.
"""
import hashlib
import json
import re
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
CACHE = HERE / '.cache'
OUT = CACHE / 'pdftext'
EXTRACTOR = '2'
LETTER = re.compile(r'[^\W\d_]', re.U)


def extract(path: Path) -> dict:
    doc = pymupdf.open(path)
    pages = []
    for p in doc:
        lines = []
        d = p.get_text('dict', flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)
        for bi, b in enumerate(d['blocks']):
            if b.get('type'):
                continue
            for ln in b['lines']:
                spans = [s for s in ln['spans'] if s['text']]
                if not spans:
                    continue
                text = ''.join(s['text'] for s in spans)
                if not text.strip():
                    continue
                size = max(s['size'] for s in spans)
                bold = all(('Bold' in s['font'] or s['flags'] & 16) for s in spans if s['text'].strip())
                x0, y0, x1, y1 = ln['bbox']
                lines.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1), round(size, 1), bool(bold),
                              text, bi])
        letters = sum(len(LETTER.findall(l[6])) for l in lines)
        scanned = letters < 40 and bool(p.get_images())
        pages.append({'height': round(p.rect.height, 1), 'width': round(p.rect.width, 1), 'scanned': scanned,
                      'lines': [] if scanned else lines})
    return {'pages': pages}


def cached(act: int, lang: str) -> dict | None:
    pdf = CACHE / 'act' / str(act) / f'pdf-{lang}.pdf'
    if not pdf.exists():
        return None
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    out = OUT / f'{act}-{lang}.json'
    if out.exists():
        try:
            d = json.loads(out.read_text('utf-8'))
            if d.get('sha256') == sha and d.get('extractor') == EXTRACTOR:
                return d
        except (OSError, json.JSONDecodeError):
            pass
    d = extract(pdf)
    d['sha256'], d['extractor'] = sha, EXTRACTOR
    OUT.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, ensure_ascii=False), 'utf-8')
    return d

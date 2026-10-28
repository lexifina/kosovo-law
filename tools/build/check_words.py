"""Independent check: the letters and digits of every act in the built repo against the RAW source.

    python check_words.py <built repo> [--show 5]

The source side is read here with its own minimal extractor, not with the builder's parser (text.py):
- a text-layer page: the `MainContent_txtDocument` span, every tag removed, entities unescaped;
- a PDF: PyMuPDF `page.get_text('rawdict')`, its characters joined line by line (not the builder's span text); a page with fewer than 40 letters that carries an image is a scan and is skipped (the builder skips
  the same pages);
then these lines are removed, by this script's own rules: the gazette's header lines ("GAZETA ZYRTARE ...",
"OFFICIAL GAZETTE ...", with a "PRISTINA" line right under one), lines that hold only a number (page numbers), and, in PDFs, the band under the gazette
header (down to 24 pt below it, positions to 0.1 pt) where the running title is printed, and any line of 12 or more characters in
the top 90 pt that recurs there on two or more pages.
The repo side is every file the act's commit added, in reading order, with the `#`/`##` heading marks dropped.
Both sides are casefolded and cut into runs of letters and digits, and compared with git diff (Myers). A difference that
involves letters is a MISMATCH; one that involves only numbers is counted apart (page numbers kept in tables).
"""
import argparse
import gzip
import json
import html
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pymupdf

HERE = Path(__file__).parent
CACHE = HERE / '.cache' / 'act'
TOKEN = re.compile(r'[^\W_]+', re.U)
HEADER = re.compile(r'^\s*(gazeta\s+zyrtare\b|official\s+gazette\b|slu[žz]beni\s+list\b)', re.I)
NUMBER = re.compile(r'^[\s\-–]*[0-9]+[\s\-–]*$|^\s*[-–]\s*[ivxlc]+\s*[-–]\s*$', re.I)
CITY = re.compile(r'^\s*(prishtin[ëe]|pristina|priština)\s*$', re.I)
LETTER = re.compile(r'[^\W\d_]', re.U)


def tokens(s: str) -> list[str]:
    return TOKEN.findall(s.casefold())


def raw_html(act: int, lang: str) -> list[str] | None:
    p = CACHE / str(act) / f'doc-{lang}.html.gz'
    if not p.exists():
        return None
    page = gzip.decompress(p.read_bytes()).decode('utf-8')
    m = re.search(r'<span id="MainContent_txtDocument">(.*?)</span>\s*</p>', page, re.S)
    if not m or not re.sub(r'<[^>]+>|\s|&nbsp;', '', m.group(1)):
        return None
    # tags are removed line by line (between <br>s): OCR text layers hold stray "<" and ">" characters
    t = '\n'.join(html.unescape(re.sub(r'<[^>]+>', '', part)).replace('\n', ' ')
                  for part in re.split(r'<br\s*/?>', m.group(1)))
    out, after_header = [], False
    for l in t.split('\n'):
        if HEADER.match(l) or NUMBER.match(l) or (after_header and CITY.match(l)):
            after_header = bool(HEADER.match(l))
            continue
        after_header = False
        out.append(l)
    return out


def raw_pdf(act: int, lang: str) -> list[str] | None:
    p = CACHE / str(act) / f'pdf-{lang}.pdf'
    if not p.exists():
        return None
    pages = []
    for pg in pymupdf.open(p):
        if len(LETTER.findall(pg.get_text('text'))) < 40 and pg.get_images():
            continue
        rows = []
        for b in pg.get_text('rawdict')['blocks']:
            for ln in b.get('lines', []):
                t = ' '.join(''.join(ch['c'] for sp in ln['spans'] for ch in sp['chars']).split())
                if t:
                    rows.append((round(ln['bbox'][1], 1), round(ln['bbox'][3], 1), t))   # positions to 0.1 pt
        pages.append(rows)
    top = Counter(t for rows in pages for t in {t for _, y1, t in rows if y1 < 90 and len(t) >= 12})
    out = []
    for rows in pages:
        heads = [y1 for y0, y1, t in rows if HEADER.match(t) and y0 < 90]
        band = max(heads) + 24 if heads else None
        for y0, y1, t in rows:
            if HEADER.match(t) or NUMBER.match(t) or (band is not None and y1 <= band) or (y1 < 90 and top[t] >= 2):
                continue
            out.append(t)
    return out


def hunks(a: list[str], b: list[str]) -> list[tuple[list[str], list[str]]]:
    """The differing runs of two token lists, by git's own (Myers) diff over one token per line: difflib's matcher
    is quadratic on long acts."""
    if a == b:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        pa, pb = Path(tmp) / 'a', Path(tmp) / 'b'
        pa.write_text('\n'.join(a) + '\n', 'utf-8')
        pb.write_text('\n'.join(b) + '\n', 'utf-8')
        out = subprocess.run(['git', 'diff', '--no-index', '--no-color', '-U0', str(pa), str(pb)],
                             capture_output=True).stdout.decode('utf-8')
    res = []
    for h in out.split('\n@@')[1:]:
        lines = h.split('\n')[1:]
        res.append(([l[1:] for l in lines if l.startswith('-')], [l[1:] for l in lines if l.startswith('+')]))
    return res


def order(path: str) -> tuple:
    stem = path.rsplit('/', 1)[-1][:-3]
    rank = {'hyrje': 0, 'preamble': 0, 'teksti': 1, 'text': 1, 'nenshkrimi': 3, 'signature': 3}.get(stem, 2)
    m = re.search(r'(\d+)$', stem)
    return rank, int(m.group(1)) if m else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('repo')
    ap.add_argument('--show', type=int, default=5)
    ap.add_argument('--only', help='comma-separated ActIDs (testing)')
    a = ap.parse_args()
    git = lambda *x: subprocess.run(['git', '-C', a.repo, *x], capture_output=True, check=True).stdout  # noqa: E731
    log = git('log', '--format=%H%x1f%(trailers:key=Act,valueonly)%x1f%(trailers:key=Text-sq,valueonly)%x1f'
                     '%(trailers:key=Text-en,valueonly)%x1e', '--branches').decode('utf-8')
    commits = [r.strip('\n').split('\x1f') for r in log.split('\x1e') if r.strip()]
    cat = subprocess.Popen(['git', '-C', a.repo, 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def blob(spec: str) -> str:
        cat.stdin.write(spec.encode('utf-8') + b'\n')
        cat.stdin.flush()
        head = cat.stdout.readline().split()
        data = cat.stdout.read(int(head[2]))
        cat.stdout.read(1)
        return data.decode('utf-8')

    checked = mism = num_only = reordered = spacing = 0
    bad = []
    numbers = 0
    for h, act, src_sq, src_en in commits:
        act = act.strip()
        if not act or (a.only and act not in a.only.split(',')):
            continue
        added = git('diff-tree', '--no-commit-id', '-r', '--root', '--diff-filter=A', '--name-only', h).decode(
            'utf-8').split('\n')
        for lang, src in (('sq', src_sq), ('en', src_en)):
            src = src.strip()
            if src.startswith('none'):
                continue
            files = sorted((p for p in added if p and ((lang == 'en') == p.startswith('en/'))), key=order)
            if not files:
                continue
            mine = tokens(' '.join(re.sub(r'^#+ ', '', blob(f'{h}:{p}'), flags=re.M) for p in files))
            raw = raw_html(int(act), lang) if src.startswith('text layer') else raw_pdf(int(act), lang)
            if raw is None:
                bad.append((act, lang, 'raw source missing'))
                mism += 1
                continue
            theirs = tokens('\n'.join(raw))
            checked += 1
            letters = []
            nums = sp = 0
            for old, new in hunks(theirs, mine):
                seg = old + new
                if all(t.isdigit() for t in seg):
                    nums += 1
                elif ''.join(old) == ''.join(new):
                    sp += 1      # the same letters, split into words differently (letter-spaced PDF text)
                else:
                    letters.append((' '.join(old)[:120], ' '.join(new)[:120]))
            numbers += nums
            if nums and not letters and not sp:
                num_only += 1
            if sp and not letters:
                spacing += 1
            if letters:
                # the same words, letter for letter, in another order (table cells and OCR layers, read in a
                # different order by the two extractors): counted apart, with the words that differ in number
                lost = Counter(t for t in theirs if not t.isdigit())
                lost.subtract(t for t in mine if not t.isdigit())
                extra = {t: -n for t, n in lost.items() if n < 0}
                lost = {t: n for t, n in lost.items() if n > 0}
                if not lost and not extra:
                    reordered += 1
                    continue
                if ''.join(t for t in theirs if not t.isdigit()) == ''.join(t for t in mine if not t.isdigit()):
                    spacing += 1      # every letter the same and in order; only the word breaks differ
                    continue
                mism += 1
                bad.append((act, lang, sorted(lost.items())[:8], sorted(extra.items())[:8], letters[:2]))
    cat.stdin.close()
    cat.wait()
    for b in bad[:a.show]:
        print('MISMATCH', b)
    print(f'{checked} texts checked against the raw source: {mism} with letter differences, '
          f'{reordered} with the same words in another order, {spacing} spacing-only differences, '
          f'{num_only} differing only in numbers ({numbers} number-only differences)')
    summary = {'checked': checked, 'same': checked - mism - reordered - spacing, 'reordered': reordered,
               'spacing': spacing, 'letters': mism, 'number_only_texts': num_only,
               'mismatches': [f'{b[0]} {b[1]}' for b in bad]}
    (HERE / '.cache' / 'check_words.json').write_text(json.dumps(summary, indent=1) + '\n', 'utf-8')
    sys.exit(1 if mism else 0)


if __name__ == '__main__':
    main()

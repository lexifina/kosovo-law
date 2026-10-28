"""Turn a Kosovo act's source text (the site's text layer, or the gazette PDF) into paragraphs, then into files.

Both sources are line-wrapped gazette pages. What is dropped, and nothing else:
- the gazette's running header ("GAZETA ZYRTARE E REPUBLIKËS SË KOSOVËS / Nr. 17 / 30 qershor 2015, PRISHTINË",
  "OFFICIAL GAZETTE OF THE REPUBLIC OF KOSOVO / No. ...", and the older "... INSTITUCIONEVE TË PËRKOHSHME ...");
- the page numbers (a line holding only the next page number in sequence, optionally between dashes, "- 11 -", and
  the Constitution's roman front-matter numbers "- i -");
- in PDFs, the band just under the gazette header (down to 24 pt below it), where the running title is printed, and
  any line of 12 or more characters in the top 90 pt that recurs there on two or more pages (running titles on
  pages without the gazette header).
Lines are joined into paragraphs (blank lines and PDF block gaps separate them; an article heading, a numbered point
after a finished sentence, or a chapter heading starts a new one), and a paragraph cut by a page break is joined again
when it does not end a sentence and the next page starts in lower case.

Files: the preamble (title, enacting formula), one file per article, and the signature block. Article headings
("Neni 12" / "Article 12") are accepted only in sequence 1, 2, 3 ..., so articles quoted inside an amending act, and
a table of contents, stay inside the text where they stand. An act without numbered articles is one file.
"""
import re
from collections import Counter

HEADER = re.compile(r'^\s*(GAZETA\s+ZYRTARE|OFFICIAL\s+GAZETTE|SLU[ŽZ]BENI\s+LIST|Gazeta\s+Zyrtare\s+e\s+Institucioneve|'
                    r'Official\s+Gazette\s+of\s+the\s+Provisional)', re.I)
CITY = re.compile(r'^\s*(PRISHTIN[ËE]|PRISTINA|PRIŠTINA|PRISTINË)\s*$', re.I)
DIGITS = re.compile(r'^\s*(?:[-–]\s*)?(\d{1,4})(?:\s*[-–])?\s*$')
ROMAN_PAGE = re.compile(r'^\s*[-–]\s*[ivxlc]+\s*[-–]\s*$')
HEAD = {'sq': re.compile(r'^\s*NENI[T]?\s*(\d+)\s*(?:[.:\-–]\s*)?(.*)$', re.I),
        'en': re.compile(r'^\s*ARTICLE\s*(\d+)\s*(?:[.:\-–]\s*)?(.*)$', re.I),
        # UNMIK-era English texts number their articles "Section 1" (the Albanian says "Neni 1")
        'en-section': re.compile(r'^\s*SECTION\s*(\d+)\s*(?:[.:\-–]\s*)?(.*)$', re.I)}
CHAPTER = re.compile(r'^\s*(KREU|KAPITULLI|PJESA|NËNKREU|NENKREU|TITULLI|SEKSIONI|CHAPTER|PART|SUB-?CHAPTER|SECTION|'
                     r'TITLE)\s+([IVXLC]+|\d+)\b', re.I)
POINT = re.compile(r'^\s*(\d+(\.\d+)*\.?\s|\d+(\.\d+)*\)\s|[a-zA-Z]\)\s|[-–•]\s)')
SIGN = re.compile(r'^\s*((Ligji|Kodi|Law|Code)\s*(Nr|No)\s*\.?\s*[0-9]{2}\s*/|Shpallur\s+me\s+dekret|Promulgated\s+by|'
                  r'Kryetari\s+i\s+Kuvendit|President\s+of\s+the\s+Assembly)', re.I)
END = re.compile(r'[.;:!?]["”’)]*\s*$')


def squash(s: str) -> str:
    return re.sub(r'\s+', ' ', s).strip()


def heading(line: str, lang: str) -> int | None:
    """The article number of a heading line ("Neni 12", "Neni 12 [Title]", "NENI 12. Title"), else None."""
    m = HEAD[lang].match(line)
    if not m or re.search(r'\.{4,}|…{2,}', line):
        return None
    rest = m.group(2).strip()
    if rest and not (rest[0].isupper() or rest[0] in '[(“"'):
        return None          # "Neni 2 i ligjit bazik, ..." is a sentence, not a heading
    if len(rest) > 160:
        return None
    return int(m.group(1))


# ------------------------------------------------------------------------------------------------ sources

def html_lines(lines: list[str]) -> list:
    """The site's text layer: lines with '' for blank lines. Returns items: str lines, '' breaks, None page breaks."""
    out = []
    first = next((int(m.group(1)) for l in lines[:6] if (m := DIGITS.match(l))), 1)
    expect = first
    prev_header = False
    for l in lines:
        m = DIGITS.match(l)
        if m and int(m.group(1)) == expect:
            expect += 1
            out.append(None)
            prev_header = False
            continue
        if ROMAN_PAGE.match(l):
            out.append(None)
            continue
        if HEADER.match(l) and len(l) < 200:
            out.append(None)
            prev_header = True
            continue
        if prev_header and CITY.match(l):
            prev_header = False
            continue
        prev_header = False
        out.append(l)
    return out


def pdf_lines(doc: dict) -> list:
    """A pdftext.extract() result as the same item stream: lines, '' at block/gap breaks, None at page breaks."""
    pages = doc['pages']
    # Page numbers: a digits-only line in the top or bottom margin whose value is the page index plus a fixed offset.
    cands = []
    for i, p in enumerate(pages):
        for l in p['lines']:
            m = DIGITS.match(l[6])
            if m and (l[1] > p['height'] - 90 or l[3] < 90):
                cands.append((i, int(m.group(1))))
    offsets = Counter(v - i for i, v in cands)
    off = offsets.most_common(1)[0][0] if offsets else None
    # Running titles: a line of 12 or more characters in the top 90 pt that recurs there on two or more pages.
    tops = Counter()
    for p in pages:
        for t in {squash(l[6]) for l in p['lines'] if l[3] < 90 and len(squash(l[6])) >= 12}:
            tops[t] += 1
    running = {t for t, n in tops.items() if n >= 2}
    out = []
    for i, p in enumerate(pages):
        out.append(None)
        prev = None
        # The header band: the gazette header line and the running title printed just under it (one or two lines,
        # 8 to 12 pt), down to 22 pt below the header line.
        heads = [l[3] for l in p['lines'] if HEADER.match(l[6]) and len(l[6]) < 200 and l[1] < 90]
        band = max(heads) + 24 if heads else None
        for l in sorted(p['lines'], key=lambda l: (l[7], l[1], l[0])):
            x0, y0, x1, y1, size, bold, text, block = l
            m = DIGITS.match(text)
            if m and off is not None and int(m.group(1)) - i == off and (y0 > p['height'] - 90 or y1 < 90):
                continue
            if HEADER.match(text) and len(text) < 200:
                continue
            if band is not None and y1 <= band:
                continue
            if y1 < 90 and squash(text) in running:
                continue
            if prev is not None and (block != prev[7] or y0 - prev[3] > 0.45 * max(size, prev[4])):
                out.append('')
            elif prev is not None and abs(y0 - prev[1]) < 0.5 * size and x0 > prev[2]:
                # same baseline, later on the line (a table cell, a tab): keep on the same line
                out[-1] = out[-1] + ' ' + text.strip()
                prev = l
                continue
            out.append(text)
            prev = l
    return out


# ------------------------------------------------------------------------------------------------ paragraphs

def paragraphs(items: list, lang: str) -> list[str]:
    """Join the item stream into paragraphs (one string each)."""
    paras: list[tuple[list[str], bool]] = []   # (lines, starts right after a page break)
    cur: list[str] = []
    cur_after_break = False
    pb = False

    def flush():
        nonlocal cur
        if cur:
            paras.append((cur, cur_after_break))
        cur = []
    for it in items:
        if it is None:
            flush()
            pb = True
            continue
        t = re.sub(r'\s+', ' ', it.replace('­', '').replace(' ', ' ')).strip()
        if not t:
            flush()
            continue
        if cur and (heading(t, lang) is not None or CHAPTER.match(t)
                    or (POINT.match(t) and END.search(cur[-1]))
                    or heading(cur[-1], lang) is not None or CHAPTER.match(cur[-1])):
            flush()
        if not cur:
            cur_after_break, pb = pb, False
        cur.append(t)
    flush()
    out: list[str] = []
    for p, after_break in paras:
        text = ' '.join(p)
        if after_break and out and not END.search(out[-1]) and re.match(r'^[a-zëç]', text) \
                and heading(out[-1], lang) is None and not CHAPTER.match(out[-1]):
            out[-1] = out[-1] + ' ' + text
        else:
            out.append(text)
    return out


# ------------------------------------------------------------------------------------------------ files

# A heading the strict rule does not read, looked for only where the expected article's heading is missing: the other
# language's word ("Neni 9" in an English text), "Articles 22", "Nen 57", "Nenin 52", "Neni i 28", OCR forms ("Neni l2",
# "NENI 1O", "Artiele-6", "Arlicle I5", "eni 7"), and a heading run into the line before it ("... ADMINISTRATION
# Articles 29 Management", "KOSOVO 3Article 10 Location"). Only the file boundary moves: the words stay as printed.
LOOSE = re.compile(r'(?:^|(?<=[\s\d.;:,)\]“”"]))(?P<word>N\s?E\s?N\s?I\s+I|NENIT|NENIN|NENI|NEN|ENI|WENI|ARTICLES|ARTICLE|'
                   r'ARTIELE|ARLICLE|ÄRTICLE|ARTICIE|ARTICIE)[\s.\-‘’\'_]*(?P<num>(?-i:[0-9lIO]{1,4}))(?![^\W_])'
                   r'[°.:]?[ \t]*(?P<rest>.?)', re.I)
CHAPTER_FOR_ARTICLE = re.compile(r'^(?:CHAPTER|KAPITULLI)\s+(\d+)\s*$', re.I)   # "Chapter 24" printed for "Article 24"
NO_NUMBER = re.compile(r'^(NENI|ARTICLE)\s+(?=[A-ZËÇ])', re.I)


def _loose_number(m: re.Match) -> int | None:
    num = m.group('num')
    if not re.search(r'\d', num) and num not in ('l', 'I'):
        return None
    return int(num.replace('l', '1').replace('I', '1').replace('O', '0'))


def loose_heading(p: str, expect: int) -> int | None:
    """Offset in paragraph p where a loose heading of article `expect` starts, or None."""
    for m in LOOSE.finditer(p):
        if _loose_number(m) != expect:
            continue
        rest = m.group('rest')
        if m.start() == 0 and (not rest or rest[0].isupper() or rest[0] in '[(“"' or len(p) < 30
                               or p[m.start('rest'):].startswith(f'{expect}.')):
            return 0
        if m.start() > 0 and rest and (rest[0].isupper() or rest[0] in '[“"'
                                       or (rest[0] == '1' and END.search(p[:m.start()].rstrip('“”" ')))):
            return m.start()
        if m.start() > 0 and not p[m.end():].strip() and END.search(p[:m.start()].rstrip('“”" ')):
            return m.start()          # the heading ends the paragraph before its text
    if NO_NUMBER.match(p) and len(p) < 80:
        return 0
    return None


IN_FORCE_TITLE = re.compile(r'^(HYRJA\s+N[ËE]\s+FUQI|ENTRY\s+INTO\s+FORCE|ENTERING\s+INTO\s+FORCE|COMING\s+INTO\s+FORCE)',
                            re.I)
SIGNED = re.compile(r'Shpallur\s+me\s+dekret|Promulgated\s+by|(?:Ligji|Kodi|Law|Code)\s*(?:Nr|No)\s*\.?\s*[0-9]{2}\s*/'
                    r'\s*L\s*[-–]\s*\d+\s+\d{1,2}[\s.]+[^\W\d_]+\s+\d{4}', re.I)


def _act_ended(paras: list[str], s: int, i: int, lang: str) -> bool:
    """Whether the article starting at paragraph s is the act's entry-into-force article and the heading at i comes
    after the signature, or after a restart at article 1 (so belongs to an annexed text)."""
    m = HEAD[lang].match(paras[s]) or HEAD['en-section'].match(paras[s])
    title = (m.group(2).strip() if m else '') or (paras[s + 1] if s + 1 < len(paras) else '')
    if not IN_FORCE_TITLE.match(title):
        return False
    return any(SIGNED.search(p) or heading(p, lang) == 1 for p in paras[s + 1:i])


def _contents_list(paras: list[str], starts: list, i: int) -> bool:
    """Whether the headings taken so far are a table of contents: three or more, and at least 80% of them with no
    paragraph that ends a sentence before the next heading."""
    if len(starts) < 3:
        return False
    bounds = [s for s, _ in starts] + [i]
    bare = sum(1 for a, b in zip(bounds, bounds[1:]) if not any(END.search(p) for p in paras[a:b]))
    return bare >= 0.8 * len(starts)


def article_starts(paras: list[str], lang: str, amending: bool = False,
                   ratifies: bool = False) -> tuple[list[str], list, list[str]]:
    """The act's own article headings: (paragraphs, [(paragraph index, number)], notes). Headings are taken 1, 2,
    3 ... in order. Where the expected number's heading is missing before the next one:
    1. a loose heading of that number (LOOSE) between the two is taken; one run into a paragraph splits it there;
    2. else, outside amending acts, a lone heading with a wrong number standing between the two (a misprint,
       "Article 30" for 27) is taken as that article, and noted;
    3. else the next heading is taken (a heading missing from the source), only when the expected number does not
       appear later, so a quoted article in an amending act is not mistaken for the act's own.
    The act's own articles end with its entry-into-force article when what follows restarts at article 1 or is
    printed after the signature (a ratified agreement, an annex): those headings stay in the text."""
    paras = list(paras)
    notes: list[str] = []
    starts: list[tuple[int, int]] = []
    expect = 1
    skipped: set[int] = set()
    i = 0
    while i < len(paras):
        n = heading(paras[i], lang)
        if n is None:
            i += 1
            continue
        if n in (expect, expect + 1) and starts and _act_ended(paras, starts[-1][0], i, lang):
            break
        later = [heading(p, lang) for p in paras[i + 1:]]
        nxt = [x for x in later if x is not None][:6]
        if n == 1 and starts and not amending and 2 in nxt[:3]:
            if len(starts) > 1 and (ratifies or not _contents_list(paras, starts, i)):
                break             # a second text numbered from 1 (a ratified agreement, an annex)
            starts, skipped, notes, expect = [], set(), [], 1   # a table of contents, or a false start
            continue
        if n == expect:
            starts.append((i, n))
            expect += 1
            i += 1
            continue
        if n in skipped and not amending and expect - 4 <= n < expect:
            starts.append((i, n))
            skipped.discard(n)
            notes.append(f'{lang[:2]}: the heading of article {n} is printed out of order in the source (in the '
                         f'text of article {max(m for _, m in starts[:-1])}); its file holds the text that follows it')
            i += 1
            continue
        if n == expect + 1 and not amending and expect in nxt and (expect + 2 in nxt or len(nxt) < 3):
            starts.append((i, n))       # the expected heading comes a little later, out of order
            skipped.add(expect)
            expect = n + 1
            i += 1
            continue
        if expect < n <= expect + 2 and not any(m in later for m in range(expect, n)):
            lo = starts[-1][0] + 1 if starts else 0
            hit = None
            for j in range(lo, i):
                off = loose_heading(paras[j], expect)
                if off is not None:
                    hit = (j, off)
                    break
            if hit is None and not amending:
                for j in range(lo, i):
                    m = CHAPTER_FOR_ARTICLE.match(paras[j])
                    if m and int(m.group(1)) == expect:
                        hit = (j, 0)
                        notes.append(f'{lang[:2]}: the heading of article {expect} reads "{paras[j]}" in the source')
                        break
            if hit is None and not amending:
                lone = [(j, m) for j in range(lo, i) if (m := heading(paras[j], lang)) is not None]
                if len(lone) == 1 and len(paras[lone[0][0]]) < 120:
                    hit = (lone[0][0], 0)
                    notes.append(f'{lang[:2]}: the heading of article {expect} reads "{squash(paras[hit[0]])[:60]}" '
                                 f'in the source')
            if hit is not None:
                j, off = hit
                if off:
                    paras[j:j + 1] = [paras[j][:off].rstrip(), paras[j][off:]]
                    j += 1
                    i += 1
                m = LOOSE.match(paras[j])
                if len(paras[j]) > 160 and m:
                    cut = m.start('rest')
                    paras[j:j + 1] = [paras[j][:cut].rstrip(), paras[j][cut:]]
                    i += 1
                starts.append((j, expect))
                expect += 1
                continue          # paragraph i is looked at again, now as the expected number
            if n == expect + 1 and starts and (any(m == n + 1 for m in nxt[:3]) or not nxt):
                starts.append((i, n))
                expect = n + 1
        i += 1
    return paras, starts, notes


def structure(paras: list[str], lang: str, amending: bool = False, whole: bool = False,
              ratifies: bool = False) -> dict:
    """{'preamble': [...], 'articles': [(n, [lines])], 'signature': [...], 'body': [...] (no articles), 'gaps': [...],
    'notes': [...]}. whole=True (a Constitutional Court judgment, whose article headings are those of the law it
    quotes) keeps the text as one file."""
    if whole:
        return {'preamble': [], 'articles': [], 'signature': [], 'body': paras, 'gaps': [], 'notes': []}
    paras0 = paras
    paras, starts, notes = article_starts(paras0, lang, amending, ratifies)
    chapter = CHAPTER
    if not starts and lang == 'en':
        paras, starts, notes = article_starts(paras0, 'en-section', amending, ratifies)
        if starts:
            lang = 'en-section'
            chapter = re.compile(CHAPTER.pattern.replace('|SECTION|', '|'), re.I)
    if not starts:
        return {'preamble': [], 'articles': [], 'signature': [], 'body': paras0, 'gaps': [], 'notes': []}
    have = {n for _, n in starts}
    gaps = [n - 1 for n in range(1, max(have) + 1) if n not in have]
    pre = paras[:starts[0][0]]
    arts = []
    for k, (i, n) in enumerate(starts):
        j = starts[k + 1][0] if k + 1 < len(starts) else len(paras)
        arts.append((n, paras[i:j]))
    # Chapter headings at the end of an article belong to the next one.
    pending: list[str] = []
    fixed = []
    for k, (n, body) in enumerate(arts):
        body = ['## ' + h for h in pending] + body
        pending = []
        if k + 1 < len(arts):
            cut = None
            for t in range(len(body) - 1, max(len(body) - 4, 0), -1):
                if chapter.match(body[t]):
                    cut = t
            if cut is not None:
                pending = body[cut:]
                body = body[:cut]
        fixed.append((n, body))
    # The signature block after the last article.
    n, body = fixed[-1]
    sig: list[str] = []
    for t in range(1, len(body)):
        if SIGN.match(body[t]) and len(body[t]) < 200:
            sig = body[t:]
            body = body[:t]
            break
    fixed[-1] = (n, body)
    # Preamble chapter headings before article 1 belong to it, as above.
    cut = None
    for t in range(len(pre) - 1, max(len(pre) - 4, -1), -1):
        if chapter.match(pre[t]):
            cut = t
    if cut is not None:
        n1, b1 = fixed[0]
        fixed[0] = (n1, ['## ' + h for h in pre[cut:]] + b1)
        pre = pre[:cut]
    out = []
    for n, body in fixed:
        lines = []
        for t, p in enumerate(body):
            if not p.startswith('## ') and not any(l.startswith('# ') for l in lines):
                lines.append('# ' + p)
            else:
                lines.append(p)
        out.append((n, lines))
    return {'preamble': pre, 'articles': out, 'signature': sig, 'body': [], 'gaps': gaps, 'notes': notes}


def language(paras: list[str]) -> str:
    """'sq', 'en', 'sr' or '' by common words, to catch a text served under the wrong language."""
    t = ' ' + ' '.join(paras[:400]).lower() + ' '
    score = {'sq': sum(t.count(w) for w in (' dhe ', ' të ', ' në ', ' për ', ' së ')),
             'en': sum(t.count(w) for w in (' the ', ' and ', ' of ', ' shall ', ' to ')),
             'sr': sum(t.count(w) for w in (' je ', ' za ', ' od ', ' koji ', ' и ', ' је ', ' за '))}
    best = max(score, key=score.get)
    return best if score[best] >= 5 else ''

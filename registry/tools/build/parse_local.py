"""Kosovo, municipal acts (lane L2, 2026-11-11): the acts of the 38 municipalities that the Official Gazette publishes
(regulations, decisions, statutes), each as published, into corpus parts for the local/ layer:
local/<municipality>/<year>/<Gazette ActID>/ (slug local-<municipality>-<year>-<id>), one file per article as for the
national acts.

    python -X utf8 parse_local.py --src C:/Users/alany/Documents/kosovo-law-src --retrieved YYYY-MM-DD \
        --out corpus-local.d --report <src>/local/holds.jsonl [--cache <src>/local/parse-cache.json.gz]

Reads <src>/local/list.jsonl (live/local_xk.py census: every municipal act the Gazette lists) and each act's files
(the national fetch's act/<id//1000>/<id>/, else local/act/...): detail.html.gz, pdf.json.gz (+ ocr.json.gz, read by
parse_acts.read_text exactly as for the national acts). Acts already on main in the national folders
(local/on-main-national.json) are left to the national parse. Deterministic: the same inputs give the same bytes.

In-force day (municipal acts; MAPL Regulation 01/2017 art. 17, then 02/2021: a municipal normative act takes effect 7
days after its publication on the municipality's website unless it says otherwise; the Gazette publishes it after):
- the act's own rule counted from publication in the Official Gazette (on publication, N days after) -> that day;
- a fixed date printed in the rule -> that date;
- "on adoption" / "N days after adoption" where the act prints the adoption day (in the rule, or the only date printed
  with the signature right after it, within a year before the Gazette day) -> that day (+N);
- any other rule (counted from posting on the municipality's website or notice board, from registration at the
  ministry's protocol office, from adoption with no date printed, from "publication" with no place named) and acts
  with no rule: dated by the Gazette publication day (coordinator decision 2026-11-11), labelled in the version note
  and the `In-force-basis` trailer: the real day is not in the record and may be earlier or later.
Labels: an act the Gazette links as amended/supplemented/repealed by a later act (its page, or the municipal list's
"Shfuqizon" / "Ndryshon/Plotëson" rows under the later act) is published as enacted and labelled "amended, not
consolidated" / "repealed, not consolidated" with amended_by.
Held (report): no PDF, scanned pages without OCR, not in Albanian, irregular articles (parse_acts.read_text's holds),
announcements and notices (Shpallje, Njoftime: not legislation).
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ks_inforce as KI  # noqa: E402
import parse_acts as P  # noqa: E402

DETAIL = P.DETAIL
DOC = P.DOC
# Gazette InstID -> (folder slug: the Albanian name, Albanian name, Serbian name)
MUNI = {
    101: ('decan', 'Deçan', 'Dečani'), 102: ('gjakove', 'Gjakovë', 'Đakovica'), 103: ('drenas', 'Drenas', 'Glogovac'),
    104: ('gjilan', 'Gjilan', 'Gnjilane'), 105: ('dragash', 'Dragash', 'Dragaš'), 106: ('istog', 'Istog', 'Istok'),
    107: ('kacanik', 'Kaçanik', 'Kačanik'), 108: ('kline', 'Klinë', 'Klina'), 109: ('fushe-kosove', 'Fushë Kosovë',
    'Kosovo Polje'), 110: ('kamenice', 'Kamenicë', 'Kamenica'), 111: ('leposaviq', 'Leposaviq', 'Leposavić'),
    112: ('lipjan', 'Lipjan', 'Lipljan'), 113: ('obiliq', 'Obiliq', 'Obilić'), 114: ('rahovec', 'Rahovec', 'Orahovac'),
    115: ('peje', 'Pejë', 'Peć'), 116: ('podujeve', 'Podujevë', 'Podujevo'), 117: ('prishtine', 'Prishtinë', 'Priština'),
    118: ('prizren', 'Prizren', 'Prizren'), 119: ('skenderaj', 'Skënderaj', 'Srbica'), 120: ('shtime', 'Shtime',
    'Štimlje'), 121: ('shterpce', 'Shtërpcë', 'Štrpce'), 122: ('suhareke', 'Suharekë', 'Suva Reka'),
    123: ('ferizaj', 'Ferizaj', 'Uroševac'), 124: ('viti', 'Viti', 'Vitina'), 125: ('vushtrri', 'Vushtrri', 'Vučitrn'),
    126: ('zubin-potok', 'Zubin Potok', 'Zubin Potok'), 127: ('zvecan', 'Zveçan', 'Zvečan'),
    128: ('malisheve', 'Malishevë', 'Mališevo'), 129: ('novoberde', 'Novobërdë', 'Novo Brdo'),
    130: ('mitrovice-e-veriut', 'Mitrovicë e Veriut', 'Severna Mitrovica'), 131: ('mitrovice-e-jugut',
    'Mitrovicë e Jugut', 'Južna Mitrovica'), 132: ('junik', 'Junik', 'Junik'), 133: ('hani-i-elezit', 'Hani i Elezit',
    'Elez Han'), 134: ('mamushe', 'Mamushë', 'Mamuša'), 135: ('gracanice', 'Graçanicë', 'Gračanica'),
    136: ('ranillug', 'Ranillug', 'Ranilug'), 137: ('partesh', 'Partesh', 'Parteš'), 138: ('kllokot', 'Kllokot',
    'Klokot')}
KIND = {'Rregullore': 'rregullore', 'Vendime': 'vendim', 'Statuti': 'statut', 'Urdhëresa': 'urdhrese',
        'Pravilnici': 'rregullore', 'Statut': 'statut', 'Odluke': 'vendim'}  # Serbian page names
NOT_LEGISLATION = {'Shpallje', 'Njoftime'}

VERB = P._VERB
GAZETTE = re.compile(r'gazet[eë]n?\s+zyrtare|gazeta\s+zyrtare', re.I)
ELSEWHERE = re.compile(r'\bueb|\bweb|\bveb|faqe|internet|tabel|regjistrim|rexhistrim|protokol|ministri|MAPL|'
                       r'ligjshm|vler[eë]sim|tirazh|gazet[ae]\s+(?:me|ditore)|gazetat', re.I)
ADOPTION = re.compile(r'miratim|aprovim|n[eë]nshkrim', re.I)
ADOPT_DAY = re.compile(VERB + r'(?:(?:n[eë]|nga)\s+)?(?:dit[eë]n|dita|dat[eë]n)\s+(?:e\s+)?(?:miratimit|aprovimit)\b', re.I)
ADOPT_PERIOD = re.compile(VERB + r'(?:pas\s+)?(?:(\d{1,3})\s*(?:\(\s*[a-zë]+\s*\))?|[a-zë]+\s*\(\s*(\d{1,3})\s*\)|'
                          r'([a-zë]+))\s*dit[eë]\w*\s+(?:pas|nga\s+dita\s+e)\s+(?:miratimit|aprovimit)\b', re.I)
DATE = re.compile(r'\b(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})\b')
WEBSITE = re.compile(r'\bueb|\bweb|\bveb|faqe|internet', re.I)
BOARD = re.compile(r'tabel', re.I)
REGISTRY = re.compile(r'regjistrim|rexhistrim|protokol', re.I)


WORDS_FILE = Path('C:/Users/alany/Documents/kosovo-law-src/ocr/sq-words.txt')   # live/ocr_xk.py build_words()
GATE_SQ = 0.80   # live/ocr_xk.py GATE_SQ
NOISY = 0.92     # below this the version note says the text layer has misread letters
LETTERS = re.compile(r'[^\W\d_]+', re.U)
_words: set | None = None


def sq_rate(text: str) -> float:
    """Share of the words of 3+ letters found in the OCR lane's Albanian word list (as ocr_xk.sq_rate)."""
    global _words
    if _words is None:
        _words = set(WORDS_FILE.read_text(encoding='utf-8').split())
    import unicodedata
    ws = [unicodedata.normalize('NFC', w.lower()) for w in LETTERS.findall(text) if len(w) >= 3]
    return sum(1 for w in ws if w in _words) / len(ws) if ws else 0.0


def lost_articles(pdf_json: Path, units: dict) -> str:
    """'' or 'N_vs_M': the PDF has N lines reading 'Neni <number>' alone but the text has M articles, fewer than
    N - 1."""
    doc = json.loads(gzip.decompress(pdf_json.read_bytes()).decode('utf-8'))
    heads = {int(m.group(1)) for p in doc['pages'] for l in p['lines']
             for m in [re.match(r'\s*Neni\s*(\d{1,3})\s*\.?\s*$', l[6])] if m}
    have = sum(1 for k in units if k.startswith('neni-'))
    # a heading misread here and there ('Neni l') is no loss; most of them missing from the text is
    return f'{len(heads)}_vs_{have}' if len(heads) >= 3 and have < len(heads) - 1 else ''


def iso(y: str, m: str, d: str) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def adoption_day(words: str, tail: list, published: str) -> tuple[str, str] | None:
    """The adoption day the act prints: a date in the in-force sentence after miratu/aprovu, else the only date printed
    in the signature block right after the sentence. It must fall within a year before the Gazette day."""
    w = KI.norm(words)
    a = P.ADOPTED_DATE.search(w)
    if a:
        day, how = iso(a.group(3), a.group(2), a.group(1)), 'the adoption date the act gives'
    else:
        block = KI.norm(' '.join(tail))
        end = w[-40:]
        if end not in block:
            return None
        block = block[block.rfind(end) + len(end):]
        if len(block) > 400 or re.search(r'\bneni\b|' + VERB, block + ' ', re.I):
            return None
        days = {iso(m.group(3), m.group(2), m.group(1)) for m in DATE.finditer(block)}
        if len(days) != 1 or None in days:
            return None
        day, how = days.pop(), 'the date printed with the signature'
    pub = date.fromisoformat(published)
    if not day or not (pub - timedelta(days=366) <= date.fromisoformat(day) <= pub):
        return None
    return day, how


def venue_words(words: str) -> str:
    """What the act's rule counts from, in words, for the label."""
    a = P._after_verb(KI.norm(words)) or KI.norm(words)
    if REGISTRY.search(a) and WEBSITE.search(a):
        return "from its registration at the ministry's protocol office and its posting on the municipality's website"
    if REGISTRY.search(a):
        return "from its registration at the ministry's protocol office"
    if WEBSITE.search(a) and BOARD.search(a):
        return "from its posting on the municipality's notice board and website"
    if WEBSITE.search(a):
        return "from its posting on the municipality's website"
    if BOARD.search(a):
        return "from its posting on the municipality's notice board"
    if re.search(r'tirazh|gazet[ae]\s+(?:me|ditore)|gazetat', a, re.I):
        return 'from its publication in the Official Gazette and in a daily newspaper'
    if re.search(r'ligjshm|vler[eë]sim', a, re.I):
        return "from the ministry's review of its legality"
    if ADOPTION.search(a):
        return 'from its adoption by the municipal assembly, whose day the act does not print'
    if re.search(r'publikim|shpallj|botim', a, re.I):
        return 'from its publication, without naming where'
    return 'on a day the act does not make clear'


def in_force(words: str, tail: list, published: str) -> tuple[str, str, str, dict]:
    """(day, basis code, basis text, extra trailers)."""
    w = KI.norm(words)
    if not w:
        return (published, 'gazette-day:no-rule',
                'the Gazette publication day (the act states no entry into force; under MAPL Regulation 01/2017 '
                'art. 17 and 02/2021 a municipal act takes effect 7 days after posting on the municipality\'s website, '
                'a day the Gazette does not give: the real day is not in the record and may be earlier or later)', {})
    after = P._after_verb(w) or w
    single = len(re.findall(VERB, w + ' ', re.I)) == 1 and not re.search(r'p[eë]rjashtim|p[eë]rve[cç]', w, re.I)
    if single and GAZETTE.search(after) and not ELSEWHERE.search(after) and not P.published_twice(words):
        m = P.more_rules(words, published)
        if m:
            return m[0], 'gazette', m[1] + ' in the Official Gazette', {}
        d, basis = KI.when(words, published)
        if d and ('after publication' in basis or basis == 'on publication'):
            return d, 'gazette', basis + ' in the Official Gazette', {}
    if single and not ELSEWHERE.search(after):
        d, basis = KI.when(words, published)
        # a date only when it follows the verb directly ("hyn në fuqi më 01.01.2020", "... në datën 1 janar 2020"),
        # not a later "fillon të zbatohet / do të implementohet nga 01.01.2009" after a rule counted from adoption
        vm = re.search(VERB, w + ' ', re.I)
        head = w[vm.end():vm.end() + 40] if vm else ''
        direct = re.match(r'(?:(?:m[eë]|n[eë]|nga|prej)\s+)?(?:(?:dat[eë]n|dit[eë]n)\s+)?(?:e\s+)?\d{1,2}\s*(?:[./]\s*\d{1,2}\s*[./]\s*\d{4}|\.?\s*[a-zë]+\s+(?:t[eë]\s+vitit\s+)?\d{4})',
                          head, re.I)
        if basis == 'date in the act' and d and direct:
            pub = date.fromisoformat(published)
            if pub - timedelta(days=731) <= date.fromisoformat(d) <= pub + timedelta(days=731):
                return d, 'date', 'the date in the act', ({'In-force-before-publication': 'yes'} if d < published
                                                           else {})
        if ADOPT_DAY.search(w) or ADOPT_PERIOD.search(w):
            ad = adoption_day(words, tail, published)
            if ad:
                m = ADOPT_PERIOD.search(w)
                n = 0
                if m:
                    n = int(m.group(1) or m.group(2) or 0) or KI.WORDS.get((m.group(3) or '').lower(), 0)
                    if not n:
                        ad = None
                if ad:
                    day = (date.fromisoformat(ad[0]) + timedelta(days=n)).isoformat()
                    basis = (f'day {n} after adoption' if n else 'on adoption') + f' ({ad[1]}, {ad[0]})'
                    return day, 'adoption', basis, ({'In-force-before-publication': 'yes'} if day < published else {})
    v = venue_words(words)
    return (published, 'gazette-day:' + v.split(',')[0][:60],
            f'the Gazette publication day (the act takes effect {v}, a day the Gazette does not give (MAPL Regulation '
            f'01/2017 art. 17, then 02/2021: municipal acts are posted on the municipality\'s website, then published '
            f'in the Gazette); the real day is not in the record and may be earlier or later)', {})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--retrieved', required=True)
    ap.add_argument('--out', default=str(HERE / 'corpus-local.d'))
    ap.add_argument('--report')
    ap.add_argument('--cache')
    a = ap.parse_args()
    src = Path(a.src)
    L = src / 'local'
    census = [json.loads(x) for x in (L / 'list.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    on_main = json.loads((L / 'on-main-national.json').read_text(encoding='utf-8'))
    cache = None
    if a.cache:
        try:
            cache = json.loads(gzip.decompress(Path(a.cache).read_bytes()).decode('utf-8'))
        except (OSError, ValueError, EOFError):
            cache = {}
    by_id = {r['id']: r for r in census}
    # 2026-11-11 (L2b): the act's copy on the municipality's website (parse_web.py's match), shown in the act README
    site_of: dict[int, dict] = {}
    sidx = L / 'sites' / 'index.json'
    if sidx.exists():
        for s in sorted(json.loads(sidx.read_text(encoding='utf-8')), key=lambda s: (s['host'], s['item'])):
            if s.get('gazette_id'):
                site_of.setdefault(int(s['gazette_id']), {'date': s['site_date'], 'url': s['url']})

    # Changes the municipal list records under the changing act: "Shfuqizon X" (repeals X), "Ndryshon/Plotëson X"
    changed_by: dict[int, list[dict]] = defaultdict(list)
    for r in census:
        for rel in r.get('related_list', []):
            changed_by[rel['id']].append({'id': r['id'], 'title': r['title'], 'published': r['published'],
                                          'relation': 'Shfuqizuar nga' if rel['relation'].startswith('Shfuqiz')
                                          else 'Ndryshohet/Plotësohet nga'})

    parts: dict[str, dict] = defaultdict(lambda: {'laws': {}, 'acts': []})
    holds, bases, index = [], Counter(), []
    for r in census:
        i = r['id']
        base = src / 'act' / str(i // 1000) / str(i)
        if not (base / 'detail.html.gz').exists():
            base = L / 'act' / str(i // 1000) / str(i)
        muni = MUNI.get(r['inst_id'])
        row = {'id': i, 'municipality': muni[1] if muni else r['municipality'], 'slug': muni[0] if muni else '',
               'year': r['year'], 'category': r['category'], 'number': r['number'], 'title': r['title'],
               'published': r['published'], 'url': DETAIL.format(id=i)}
        try:
            if str(i) in on_main:
                row.update(status='on main (national folder)', folder=on_main[str(i)])
                raise P.Hold('on_main_national')
            if not muni:
                raise P.Hold('municipality_unknown:' + str(r['inst_id']))
            if not (base / 'detail.html.gz').exists():
                raise P.Hold('not_fetched')
            d = P.detail(gzip.decompress((base / 'detail.html.gz').read_bytes()).decode('utf-8', 'replace'))
            if d['category'] in NOT_LEGISLATION:
                raise P.Hold('not_legislation:' + d['category'])
            if d['category'] not in KIND:
                raise P.Hold('kind_not_built:' + d['category'])
            if not d['published']:
                raise P.Hold('no_publication_day')
            # labels: the act's page ("... nga" links) and the municipal list's rows under later acts
            ch = {x['id']: x for x in d['related'] if P.CHANGED_BY.match(x['relation'])}
            for x in changed_by.get(i, []):
                ch.setdefault(x['id'], x)
            changers = sorted(ch.values(), key=lambda x: (x['published'] or '9999', x['id']))
            if d['by_later'] and not changers:
                raise P.Hold('amended_or_repealed_on_gazette_unlinked')
            repealed = ('shfuqiz' in d['status'].lower()
                        or any(P.REPEALED_BY.match(x['relation']) for x in changers))
            marks = {}
            if changers or repealed:
                marks = {'label': 'repealed, not consolidated' if repealed else 'amended, not consolidated',
                         'amended_by': [{'ref': f'gzk:{x["id"]}', 'title': x['title'], 'url': DETAIL.format(id=x['id']),
                                         'date': x['published'] or None, 'relation': x['relation']} for x in changers]}
            if not (base / 'pdf.json.gz').exists():
                err = (base / 'pdf.err').read_text(encoding='utf-8')[:120] if (base / 'pdf.err').exists() else ''
                raise P.Hold(('office_file_unread:' if any(base.glob('doc.*')) else 'no_pdf:') + err)
            amending = bool(P.CHANGE.search(P.fold(d['title'])))
            got = P.read_text(base / 'pdf.json.gz', amending, cache, d['title'])
            units, rule, tail, sha, scanned, cut = got[:6]
            info = got[6] if len(got) > 6 and isinstance(got[6], dict) else {}
            # 2026-11-11: many municipal PDFs are page scans with a text layer the publisher machine-read; the reader
            # takes it as text. Held when it reads badly (the OCR lane's gate: under 80% of the words of 3+ letters
            # in the Albanian word list) or when the PDF heads more articles than the text gives (headings lost).
            rate = sq_rate(' '.join(u['text'] for u in units.values()))
            if rate < GATE_SQ and str(i) not in P.OCR_SOURCE:
                raise P.Hold(f'text_layer_unreadable:{rate:.2f}')
            lost = lost_articles(base / 'pdf.json.gz', units)
            if lost:
                raise P.Hold('article_headings_lost:' + lost)
            day, code, basis, extra = in_force(rule, tail, d['published'])
        except P.Hold as h:
            reason = str(h)
            holds.append({'id': i, 'municipality': row['municipality'], 'title': (r['title'] or '')[:160],
                          'reason': reason})
            row.setdefault('status', 'held: ' + reason.split(':')[0])
            index.append(row)
            continue
        year = d['published'][:4]
        slug = f'local-{muni[0]}-{year}-{i}'
        bases[code.split(':')[0]] += 1
        title = d['title']
        label = f'{title} (Komuna e {muni[1]}' + (f', GZ {d["gazette"]})' if d['gazette'] else ')')
        note = (f'Issued by the Municipality of {muni[1]} ({muni[2]}); published in the Official Gazette on '
                f'{d["published"]}. In force: {basis}' + (f' ("{rule[:300]}")' if rule else '') + '.')
        if cut:
            note += ' ' + cut
        if info.get('letters'):
            note += (" The PDF's text layer prints 'ë' as 'é' or '€'; the in-force sentence was read, and is quoted, "
                     "with 'ë'.")
        if rate < NOISY and str(i) not in P.OCR_SOURCE:
            note += (" The Gazette's PDF is a page scan carrying a machine-read text layer; that layer is the text here, "
                     "with its misread letters (for example '€', '6' or 'd' for 'ë').")
        ocr = P.OCR_SOURCE.get(str(i))
        if ocr and ocr.get('note'):
            note += ' ' + ocr['note']
        office = next((e for e in ('doc', 'docx') if (base / f'doc.{e}').exists()), None)
        if office:
            note += (f' The Gazette serves this act as a Word file (.{office}), not a PDF; its text was read from a PDF '
                     f'that Microsoft Word made of that file.')
        if scanned:
            note += (f' The PDF ends with {scanned} page(s) printed only as images (after the text), not '
                     f'transcribed here.')
        trailers = [f'Issuer: Komuna e {muni[1]}']
        if code.startswith('gazette-day'):
            trailers.append('In-force-basis: Gazette publication day; the act counts its entry into force '
                            + venue_words(rule) if rule else 'In-force-basis: Gazette publication day; the act '
                            'states no entry into force')
        else:
            trailers.append(f'In-force-basis: {basis}')
        if rule:
            trailers.append('In-force-rule: ' + re.sub(r'\s+', ' ', rule)[:300])
        trailers += [f'{k}: {v}' for k, v in extra.items()]
        if ocr and ocr.get('trailer'):
            trailers.append(ocr['trailer'])
        part = f'60-local-{muni[0]}'
        parts[part]['laws'][slug] = {'label': label, 'title': title, 'kind': 'decree', 'enacted': d['published'],
                                     'published': d['published'], 'url': DETAIL.format(id=i),
                                     'temporary_until': None, 'restores': None, 'note': None}
        parts[part]['acts'].append({
            'slug': slug, 'short': d['number'] or title, 'title': title, 'url': DETAIL.format(id=i),
            'first_law': slug, 'earlier_laws': [],
            'versions': [{'from': day, 'source_url': DOC.format(id=i), 'sha256': sha, 'units': units, 'credits': {},
                          'note': note, 'trailers': trailers}], **marks,
            **({'site_copy': site_of[i]} if i in site_of else {})})
        row.update(status=marks.get('label', 'in force'), folder=f'local/{muni[0]}/{year}/{i}', in_force=day,
                   basis=code.split(':')[0])
        index.append(row)
    if cache is not None:
        tmp = Path(a.cache + '.tmp')
        tmp.write_bytes(gzip.compress(json.dumps(cache, ensure_ascii=False, sort_keys=True).encode('utf-8'), 3, mtime=0))
        tmp.replace(a.cache)
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    decisions = [
        'Municipal acts (the 38 municipalities\' regulations, decisions and statutes the Official Gazette publishes) '
        'live in local/<municipality>/<year>/<Gazette act id>/, one version each: the act as published in the Gazette. '
        'The 72 municipal acts published before this layer keep their national folders (data/local.csv lists them).',
        'In force: the act\'s own rule where it counts from publication in the Official Gazette, prints a date, or '
        'counts from its adoption and prints the adoption day. Most municipal acts count from posting on the '
        'municipality\'s website or notice board or from registration at the ministry (MAPL Regulation 01/2017 '
        'art. 17, then 02/2021: 7 days after posting on the website unless the act says otherwise): the Gazette does '
        'not give that day, so such acts are dated by their Gazette publication day and say so in the version note and '
        'the In-force-basis trailer; the real day may be earlier or later.',
        'An act the Gazette links as amended, supplemented or repealed by a later act (on its page or in the list of '
        'municipal acts) is published as enacted and labelled "amended, not consolidated" or "repealed, not '
        'consolidated", with the changing acts named.']
    written = []
    for name in sorted(parts):
        p = parts[name]
        p['acts'].sort(key=lambda x: x['slug'])
        p['decisions'] = decisions
        p['ai_use'] = ['none']
        f = out / f'{name}.json'
        body = json.dumps(p, ensure_ascii=False, indent=1) + '\n'
        if not f.exists() or f.read_text(encoding='utf-8') != body:
            tmp = f.with_suffix('.tmp')
            tmp.write_text(body, encoding='utf-8', newline='\n')
            P.replace(tmp, f)
        line = (f"{len(p['acts'])} municipal acts checked against the Gazette's page and the PDF text: in-force day "
                f"from the act's own rule or, where it counts from a day the Gazette does not give, the Gazette "
                f"publication day (labelled); articles numbered in sequence; text in Albanian.\n")
        pub = out / f'{name}.PUBLISH'
        if not pub.exists() or pub.read_text(encoding='utf-8') != line:
            pub.write_text(line, encoding='utf-8', newline='\n')
        written.append((name, len(p['acts'])))
    for f in out.glob('60-local-*.json'):   # a municipality with no act left publishable this run
        if f.stem not in parts:
            f.unlink()
            (out / f'{f.stem}.PUBLISH').unlink(missing_ok=True)
    (L / 'index.json').write_text(json.dumps(sorted(index, key=lambda x: x['id']), ensure_ascii=False, indent=0) + '\n',
                                  encoding='utf-8', newline='\n')
    if a.report:
        Path(a.report).write_text(''.join(json.dumps(h, ensure_ascii=False) + '\n' for h in holds), encoding='utf-8',
                                  newline='\n')
    # acts L1's OCR (live/ocr_xk.py) could read: page scans, and scans whose own text layer reads badly
    ocr = sorted(h['id'] for h in holds if h['reason'].split(':')[0] in ('scanned_pages', 'text_layer_unreadable',
                                                                          'article_headings_lost'))
    (L / 'ocr-candidates.txt').write_text(''.join(f'{x}' + chr(10) for x in ocr), encoding='utf-8', newline=chr(10))
    reasons = Counter(h['reason'].split(':')[0] for h in holds)
    print(json.dumps({'listed': len(census), 'published': sum(n for _, n in written), 'held': len(holds),
                      'held_by_reason': dict(reasons), 'in_force_basis': dict(bases), 'parts': len(written)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()

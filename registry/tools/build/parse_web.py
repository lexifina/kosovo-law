"""Kosovo, municipal acts from the municipalities' own websites (lane L2b, 2026-11-11): the regulations, statutes and
general decisions a municipality posts on <name>.rks-gov.net that the Official Gazette does not publish, as a second
source, in the local/ layout: local/<municipality>/<year>/web-<site item id>/ (slug local-<m>-<year>-web-<item>).

    python -X utf8 parse_web.py --src C:/Users/alany/Documents/kosovo-law-src --retrieved YYYY-MM-DD \
        --out corpus-web.d --report <src>/local/sites/holds.jsonl [--cache <src>/local/sites/parse-cache.json.gz]

Reads local/sites/<host>.json (live/sites_xk.py listing), local/sites/files/<sha1(url)>/pdf.json.gz (the pinned reader)
and the Gazette census (local/list.jsonl + each Gazette act's pdf.json.gz). Deterministic.

- Kinds: regulations and statutes (sites_xk.normative); decisions only when general (taxes, fees, tariffs, budgets,
  plans, street naming, rules of procedure, symbols, twinning) and nothing in the title or text names or concerns a
  person (classify(); coordinator decision 2026-11-11, Romania's rule: decisions about individual persons are metadata
  only). Everything else is indexed (title, date, URL), not published.
- In the Gazette: an item whose title matches a Gazette act of the same municipality (all its words, numbers agreeing,
  one candidate, year within one) or whose text shares half its 8-word runs with one is the Gazette's act: not
  published again (the Gazette is the official publication); the site date goes to local.csv, and the site copy of a
  Gazette scan to local/site-copies.jsonl (an OCR cross-check, never the published text).
- The date the site shows is WordPress's post date: taken as the posting day only when it falls in the month of the
  file's upload folder (wp-content/uploads/YYYY/MM) and is not a date the site gave 15 or more items (a migration).
- In force: the act's printed day (a date, adoption day + N; parse_local.in_force); else, with a usable posting day,
  N days after posting on the website when the act says so, otherwise the posting day, labelled (the real day may be
  later: MAPL Reg. 01/2017 art. 17 gives 7 days after posting unless the act says otherwise); a rule counted from
  publication in the Official Gazette, which never published the act: held; no usable posting day: held
  (posting_date_unknown).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'live'))
import parse_acts as P  # noqa: E402
import parse_local as PL  # noqa: E402

HOSTS = {'decan': 101, 'gjakova': 102, 'gllogoc': 103, 'gjilan': 104, 'dragash': 105, 'istog': 106, 'kacanik': 107,
         'kline': 108, 'fushekosove': 109, 'kamenice': 110, 'leposaviq': 111, 'lipjan': 112, 'obiliq': 113,
         'rahovec': 114, 'peja': 115, 'prishtina': 117, 'prizren': 118, 'skenderaj': 119, 'shtime': 120,
         'shterpce': 121, 'ferizaj': 123, 'viti': 124, 'vushtrri': 125, 'zubinpotok': 126, 'zvecan': 127,
         'novoberde': 129, 'gracanica': 135, 'ranillug': 136, 'partesh': 137, 'kllokot': 138}   # = sites_xk.HOSTS
NORMATIVE = re.compile(r'^\W*(?:rregull|statut|pravilnik|uredb)', re.I)
PERSON = re.compile(r'\bz\s*\.|\bznj\b|\bzt\b|\bgjj?\b|emerim|emerohet|caktim|caktohet|shkarkim|shkarkohet|lirim|'
                    r'lirohet|largim|pozit|drejtor|\bu\s*\.?\s*d\b|punesim|pension|burs|ndihm|subvenc|kompensim|banes|'
                    r'shfrytezim|qira|shpronesim|shpronesues|komision|anetar|keshill|grup|delegacion|udhetim|'
                    r'mirenjohj|nderi|qytetar|mjeteve|grant|sponsor|donacion|perkrah|mbeshtetje|pages|rrog|shperblim|'
                    r'vleresim|prone|parcel|ngastr|kerkes|ankes|lende|leje|licenc|perfaqesues|kryesues|zevendes|'
                    r'sekretar|zyrtar|nxenes|student|familj|individ|person|imenov|razres|postavlj|komisij|clan|pomoc|'
                    r'stipend|naknad|zakup|komitet|ekip|kujdestari|kksb|organ\w*\s+kolegjial|bord', re.I)
GENERAL = re.compile(r'taks|tarif|gjob|ngarkes|buxhet|plan\w*\s+(?:zhvillimor|rregullues|hapesinor|komunal|veprim|'
                     r'investim|lokal|sektorial)|kornize|emertim\w*\s+(?:e\s+)?(?:rrug|sheshe|lagj|vendbanim)|'
                     r'rregullore\w*\s+e\s+punes|statut|orar|parkim|transport|mbeturin|ujesjell|ndricim|simbol|flamur|'
                     r'dita\s+e\s+komun|binjakezim|partneritet|asociacion|themelim|harte|zonal|porez|budzet|takse|'
                     r'tarifa|naziv|imenovanje\s+ulic', re.I)
# personal data in a decision's text: a courtesy title before a name, a personal number, a birth date
PERSON_TEXT = re.compile(r'\b(?:z|znj|zj|zt|gj|g-?dja|g-?din)\s*\.\s*[A-ZËÇŠŽČĆĐ]|\bnr\.?\s*personal|numr\w*\s+personal|'
                         r'\bi\s+lindur\b|e\s+lindur\b|datëlindj|ID\s*:?\s*\d{6,}|\b\d{10}\b', re.I)
WEB_PERIOD = re.compile(r'(\d{1,3})\s*(?:\(\s*[a-zë]+\s*\))?\s*dit\w*\s+(?:pas|nga\s+dita\s+e)\s+(?:publikimit|shpalljes|'
                        r'vendosjes|botimit)', re.I)


def fold(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', s.lower()) if not unicodedata.combining(c))


def classify(it: dict) -> str:
    """'normative' (regulation / statute), 'general' (a general decision), 'personal' or 'unclassified'."""
    lst = it.get('list', '').split('.rks-gov.net', 1)[-1]
    if (re.search(r'rregull|statut|pravilnik', lst, re.I) and not re.search(r'vendim', lst, re.I)) \
            or NORMATIVE.match(it['title']):
        return 'normative'
    t = fold(it['title'])
    if PERSON.search(t):
        return 'personal'
    return 'general' if GENERAL.search(t) else 'unclassified'


STOPW = set('per dhe ne te e i se nga me mbi rregullore rregullorja rregullores komunale komunes komuna komunen nr ka kk '
            'k vendim vendimi statuti statut'.split())


def toks(s: str) -> set:
    return {w for w in re.findall(r'[a-z]{3,}', fold(s)) if w not in STOPW}


def nkey(s: str) -> set:
    return {re.sub(r'\D', '', m) for m in re.findall(r'\d{1,6}\s*[/.-]\s*\d{1,6}(?:\s*/\s*\d{2,4})?', s)}


def shingles(text: str) -> set:
    w = re.findall(r'[a-z]{2,}', fold(re.sub(r'[€é]', 'e', text)))
    return {hashlib.md5(' '.join(w[k:k + 8]).encode()).hexdigest()[:12] for k in range(0, max(0, len(w) - 7))}


def dmy(s: str) -> str | None:
    m = re.match(r'\s*(\d{1,2})[/.](\d{1,2})[/.](\d{4})', s or '')
    return PL.iso(m.group(3), m.group(2), m.group(1)) if m else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--retrieved', required=True)
    ap.add_argument('--out', default=str(HERE / 'corpus-web.d'))
    ap.add_argument('--report')
    ap.add_argument('--cache')
    ap.add_argument('--repo', default='C:/Users/alany/Documents/kosovo-law-pub')
    a = ap.parse_args()
    # website acts already on main stay in the corpus when the Gazette later prints the same act: both copies are
    # kept and name each other (live/link_web.py), never one withdrawn
    import subprocess
    pj_main = subprocess.run(['git', 'show', 'main:registry/data/paths.json'], cwd=a.repo, capture_output=True,
                             text=True, encoding='utf-8').stdout
    web_on_main = {k for k in (json.loads(pj_main).get('paths', {}) if pj_main else {}) if '-web-' in k}
    src = Path(a.src)
    L = src / 'local'
    S = L / 'sites'
    cache = None
    if a.cache:
        try:
            cache = json.loads(gzip.decompress(Path(a.cache).read_bytes()).decode('utf-8'))
        except (OSError, ValueError, EOFError):
            cache = {}
    census = [json.loads(x) for x in (L / 'list.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    lindex = {r['id']: r for r in json.loads((L / 'index.json').read_text(encoding='utf-8'))}
    gaz = defaultdict(list)   # inst -> Gazette acts with title tokens and text shingles
    for g in census:
        base = src / 'act' / str(g['id'] // 1000) / str(g['id'])
        if not (base / 'pdf.json.gz').exists():
            base = L / 'act' / str(g['id'] // 1000) / str(g['id'])
        sh = set()
        f = base / 'pdf.json.gz'
        if f.exists():
            doc = json.loads(gzip.decompress(f.read_bytes()).decode('utf-8'))
            sh = shingles(' '.join(l[6] for p in doc.get('pages', []) if not p.get('scanned') for l in p['lines']))
        gaz[g['inst_id']].append({**g, '_t': toks(g['title']), '_n': nkey(g['title']), '_sh': sh})

    items = []
    for f in sorted(S.glob('*.json')):
        r = json.loads(f.read_text(encoding='utf-8'))
        if 'items' not in r or r['host'] not in HOSTS:
            continue
        dates = Counter(i['date'] for i in r['items'])
        for i in r['items']:
            items.append({**i, 'host': r['host'], 'inst': HOSTS[r['host']], '_mass': dates[i['date']] >= 15})
    items.sort(key=lambda i: (i['host'], i['item'], i['url']))

    parts: dict[str, dict] = defaultdict(lambda: {'laws': {}, 'acts': []})
    rows, holds, copies, bases = [], [], [], Counter()
    seen_sha: dict[str, str] = {}
    for it in items:
        muni = PL.MUNI[it['inst']]
        kind = classify(it)
        d = S / 'files' / hashlib.sha1(it['url'].encode('utf-8')).hexdigest()
        site_day = dmy(it['date'])
        up = re.search(r'/uploads/(\d{4})/(\d\d)/', (d / 'url.txt').read_text(encoding='utf-8')
                       if (d / 'url.txt').exists() else it['url'])
        posted = site_day if (site_day and up and site_day[:7] == f'{up.group(1)}-{up.group(2)}'
                              and not it['_mass']) else None
        row = {'host': it['host'], 'municipality': muni[1], 'item': it['item'], 'title': it['title'],
               'site_date': it['date'], 'posting_day': posted or '', 'class': kind, 'url': it['url'],
               'list': it['list'], 'gazette_id': '', 'status': '', 'folder': '', 'in_force': ''}
        try:
            if kind in ('personal', 'unclassified'):
                raise P.Hold('metadata_only:' + kind)
            # the Gazette's act? by title
            ti, ni = toks(it['title']), nkey(it['title'])
            yr = int((site_day or '0000')[:4])
            cands = sorted(((len(ti & g['_t']) / max(1, len(ti | g['_t'])), g) for g in gaz[it['inst']] if ti),
                           key=lambda x: (-x[0], x[1]['id']))
            match = None
            if cands and cands[0][0] >= 0.8 and not (len(cands) > 1 and cands[1][0] >= 0.6):
                g = cands[0][1]
                if not (ni and g['_n'] and not (ni & g['_n'])) and (not yr or abs(yr - int(g['year'] or 0)) <= 1):
                    match = g
            pj = d / 'pdf.json.gz'
            text_sh = set()
            if pj.exists():
                doc = json.loads(gzip.decompress(pj.read_bytes()).decode('utf-8'))
                if doc.get('sha256') in seen_sha:
                    raise P.Hold('same_file_as:' + seen_sha[doc['sha256']])
                seen_sha[doc.get('sha256', '')] = it['url']
                text_sh = shingles(' '.join(l[6] for p in doc.get('pages', []) if not p.get('scanned')
                                            for l in p['lines']))
            if not match and len(text_sh) >= 20:   # by text
                best = max(((len(text_sh & g['_sh']) / len(text_sh), g['id'], g) for g in gaz[it['inst']] if g['_sh']),
                           default=(0, 0, None))
                if best[0] >= 0.5:
                    match = best[2]
            on_main = next((k for k in web_on_main if k.startswith(f'local-{muni[0]}-')
                            and k.endswith(f'-web-{it["item"]}')), None)
            if match:
                row['gazette_id'] = match['id']
                gst = lindex.get(match['id'], {}).get('status', '')
                if pj.exists() and (gst.startswith('held: scanned') or gst.startswith('held: text_layer')):
                    copies.append({'id': match['id'], 'site_pdf_json': str(pj).replace('\\', '/'), 'url': it['url'],
                                   'site_date': it['date']})
                if not on_main:
                    raise P.Hold(f'in_gazette:{match["id"]}')
            if not pj.exists():
                raise P.Hold('not_fetched' if not (d / 'skip.txt').exists() else
                             'no_pdf:' + (d / 'skip.txt').read_text(encoding='utf-8')[:80])
            title = it['title']
            units, rule, tail, sha, scanned, cut = P.read_text(pj, bool(P.CHANGE.search(P.fold(title))), cache, title)[:6]
            rate = PL.sq_rate(' '.join(u['text'] for u in units.values()))
            if rate < PL.GATE_SQ:
                raise P.Hold(f'text_layer_unreadable:{rate:.2f}')
            lost = PL.lost_articles(pj, units)
            if lost:
                raise P.Hold('article_headings_lost:' + lost)
            body = '\n'.join(u['text'] for u in units.values())
            if kind == 'general' and PERSON_TEXT.search(body):
                raise P.Hold('personal_data_in_text')
            ref = posted or site_day or '2000-01-01'
            day, code, basis, extra = PL.in_force(rule, tail, ref)
            if code in ('date', 'adoption'):
                pass
            elif code == 'gazette':
                raise P.Hold('rule_counts_from_gazette_publication')
            elif not posted:
                raise P.Hold('posting_date_unknown')
            else:
                w = P._after_verb(rule) if rule else ''
                m = WEB_PERIOD.search(w) if w and PL.WEBSITE.search(w) and not PL.REGISTRY.search(w) else None
                if m:
                    day = (date.fromisoformat(posted) + timedelta(days=int(m.group(1)))).isoformat()
                    code, basis = 'website', (f'day {m.group(1)} after posting on the municipality\'s website on '
                                              f'{posted} ({it["url"]})')
                else:
                    day, code = posted, 'posting-day'
                    basis = ('the day the municipality posted it on its website, ' + posted + ' (the act takes effect '
                             + (PL.venue_words(rule) if rule else 'as MAPL Regulation 01/2017 art. 17 provides, 7 '
                                'days after posting unless it says otherwise') + '; the real day may be later)')
                extra = {}
        except P.Hold as h:
            reason = str(h)
            row['status'] = ('in the Gazette' if reason.startswith('in_gazette') else 'held: ' + reason.split(':')[0])
            if not reason.startswith(('in_gazette', 'metadata_only')):
                holds.append({'host': it['host'], 'item': it['item'], 'title': it['title'][:160], 'reason': reason})
            rows.append(row)
            continue
        year = on_main.split('-')[-3] if on_main else (posted or day)[:4]
        slug = f'local-{muni[0]}-{year}-web-{it["item"]}'
        bases[code] += 1
        label_status = "published on the municipality's website (not in the Official Gazette)"
        law_label = f'{title} (Komuna e {muni[1]}, website)'
        note = (f"Issued by the Municipality of {muni[1]} ({muni[2]}) and posted on its website ({it['list']}); the "
                f"Official Gazette has not published it. The site shows it dated {it['date']}. In force: {basis}"
                + (f' ("{rule[:300]}")' if rule else '') + '.')
        if cut:
            note += ' ' + cut
        if scanned:
            note += f' The PDF ends with {scanned} page(s) printed only as images, not transcribed here.'
        if rate < PL.NOISY:
            note += (" The PDF is a page scan carrying a machine-read text layer; that layer is the text here, with its "
                     "misread letters.")
        trailers = [f'Issuer: Komuna e {muni[1]}', f'Published-by: the municipality\'s website, {it["host"]}.rks-gov.net '
                    '(not the Official Gazette)', f'Site-date: {it["date"]}', f'In-force-basis: {basis}'[:400]]
        if rule:
            trailers.append('In-force-rule: ' + re.sub(r'\s+', ' ', rule)[:300])
        trailers += [f'{k}: {v}' for k, v in extra.items()]
        part = f'61-web-{muni[0]}'
        parts[part]['laws'][slug] = {'label': law_label, 'title': title, 'kind': 'decree', 'enacted': posted or day,
                                     'published': posted or day, 'url': it['list'], 'temporary_until': None,
                                     'restores': None, 'note': None}
        parts[part]['acts'].append({'slug': slug, 'short': title[:80], 'title': title, 'url': it['url'],
                                    'first_law': slug, 'earlier_laws': [], 'label': label_status,
                                    'versions': [{'from': day, 'source_url': it['url'], 'sha256': sha, 'units': units,
                                                  'credits': {}, 'note': note, 'trailers': trailers}]})
        row.update(status='published (website)', folder=f'local/{muni[0]}/{year}/web-{it["item"]}', in_force=day)
        rows.append(row)
    if cache is not None:
        tmp = Path(a.cache + '.tmp')
        tmp.write_bytes(gzip.compress(json.dumps(cache, ensure_ascii=False, sort_keys=True).encode('utf-8'), 3, mtime=0))
        tmp.replace(a.cache)
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    decisions = [
        "Acts a municipality posts on its own website (<name>.rks-gov.net) that the Official Gazette has not "
        "published are a second source: regulations, statutes and general decisions (taxes, fees, budgets, plans, "
        "street names, rules of procedure), each as posted, in local/<municipality>/<year>/web-<site item id>/. "
        "Decisions about individual persons are listed in data/local.csv as metadata only.",
        "An act the Gazette publishes is taken from the Gazette, never from the website.",
        "The date the site shows is used as the posting day only when it falls in the month of the file's upload "
        "folder and is not a date the site gave to 15 or more items (a migration); the act then takes effect on its "
        "own printed day, N days after posting where it says so, or the posting day, labelled; otherwise it is held."]
    written = []
    for name in sorted(parts):
        p = parts[name]
        p['acts'].sort(key=lambda x: x['slug'])
        p['decisions'], p['ai_use'] = decisions, ['none']
        f = out / f'{name}.json'
        body = json.dumps(p, ensure_ascii=False, indent=1) + '\n'
        if not f.exists() or f.read_text(encoding='utf-8') != body:
            tmp = f.with_suffix('.tmp')
            tmp.write_text(body, encoding='utf-8', newline='\n')
            P.replace(tmp, f)
        line = (f"{len(p['acts'])} acts from the municipality's website, not in the Official Gazette: no Gazette act "
                f"matches title or text; in-force day from the act's own rule and a posting day the upload folder "
                f"confirms; articles in sequence; text in Albanian; decisions only when general, with no personal "
                f"data.\n")
        pub = out / f'{name}.PUBLISH'
        if not pub.exists() or pub.read_text(encoding='utf-8') != line:
            pub.write_text(line, encoding='utf-8', newline='\n')
        written.append((name, len(p['acts'])))
    for f in out.glob('61-web-*.json'):
        if f.stem not in parts:
            f.unlink()
            (out / f'{f.stem}.PUBLISH').unlink(missing_ok=True)
    (S / 'index.json').write_text(json.dumps(rows, ensure_ascii=False, indent=0) + '\n', encoding='utf-8',
                                  newline='\n')
    copies.sort(key=lambda c: (c['id'], c['url']))
    (L / 'site-copies.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in copies),
                                         encoding='utf-8', newline='\n')
    if a.report:
        Path(a.report).write_text(''.join(json.dumps(h, ensure_ascii=False) + '\n' for h in holds), encoding='utf-8',
                                  newline='\n')
    print(json.dumps({'items': len(items), 'published': sum(n for _, n in written),
                      'status': dict(Counter(r['status'].split(':')[0] for r in rows)),
                      'held_by_reason': dict(Counter(h['reason'].split(':')[0] for h in holds)),
                      'in_force_basis': dict(bases), 'site_copies': len(copies)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

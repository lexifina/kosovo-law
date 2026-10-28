"""Build the Kosovo law repository (as enacted) from the gzk.rks-gov.net cache.

    python scripts/kosovo-law/build.py C:/Users/alany/Documents/kosovo-law-build --today YYYY-MM-DD [--workers 8]

The Official Gazette of Kosovo publishes each act as enacted (a text layer on the act's page, or the gazette PDF);
it keeps no dated consolidated versions. So this is an AS-ENACTED record (NATIONAL-CURRENT-BRIEF shape 3):
1. One commit per act, adding its Albanian text (one file per article, at `<kind>/<number>/neni-NNN.md`) and its
   English translation (`en/<kind>/<number>/article-NNN.md`), authored by the act itself.
2. Dated the day the act took effect, read from its own in-force article (inforce.py), at noon Europe/Belgrade time
   (CET/CEST; summer time from the last Sunday of March to the last Sunday of October, `start <= day < end`).
   The basis is the `In-force-basis:` trailer; the publication date and gazette number are trailers too.
3. A repealed act's files are deleted in the commit of the act that repealed it (the repealed act's page names it,
   "Shfuqizuar nga"), on that act's in-force day. Amendments are never applied to the amended text: the links
   between acts (amends, amended by, repeals, partly repeals) are listed in data/amendments.csv.
4. Commits dated after --today go to the `future` branch, which is never merged. Written with one streamed
   git fast-import (messages as bytes), so the same cache gives the same hashes.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import inforce  # noqa: E402
import parse  # noqa: E402
import pdftext  # noqa: E402
import text as textmod  # noqa: E402

CACHE = HERE / '.cache'
PARSED = CACHE / 'parsed'
PARSER_VERSION = '8'
COMMITTER = 'Lexifina <kosovo-law@lexifina.com>'
SITE = 'https://gzk.rks-gov.net/'
KIND_DIR = {'Ligje': 'ligje', 'Kode': 'kode', 'Kushtetuta': 'kushtetuta', 'Aktgjykime': 'aktgjykime',
            'Urdhër': 'urdhera', 'Vendime': 'vendime'}
RELATION_EN = {'Ndryshohet/Plotësohet nga': 'amended or supplemented by', 'Ndryshon/Plotëson': 'amends or supplements',
               'Shfuqizuar nga': 'repealed by', 'Shfuqizon': 'repeals',
               'Shfuqizuar pjesërisht nga': 'partly repealed by', 'Shfuqizon pjesërisht': 'partly repeals',
               'Shtuar nga': 'added to by', 'Ndërlidhur me': 'related to', '': '(no relation named)'}
FILES = {'sq': ('hyrje', 'neni', 'nenshkrimi', 'teksti'), 'en': ('preamble', 'article', 'signature', 'text')}
AMENDING = re.compile(r'NDRYSHIM|PLOTËSIM|PLOTESIM', re.I)
ASCII = str.maketrans({'ë': 'e', 'Ë': 'E', 'ç': 'c', 'Ç': 'C'})


# ---------------------------------------------------------------------------------------------------- acts

def act_ids() -> list[int]:
    cat = json.loads((CACHE / 'catalogue.json').read_text('utf-8'))
    extra = json.loads((HERE / 'extra_acts.json').read_text('utf-8'))['ids']
    return sorted({r['id'] for r in cat['rows']} | set(extra))


def source_key(act: int) -> str:
    h = hashlib.sha256()
    for name in ('detail-sq.html.gz', 'doc-sq.html.gz', 'doc-en.html.gz', 'pdf-sq.pdf', 'pdf-en.pdf'):
        p = CACHE / 'act' / str(act) / name
        h.update(name.encode() + b'\0' + (p.read_bytes() if p.exists() else b'-'))
    return h.hexdigest()


def read_text(act: int, lang: str) -> dict:
    """{'source': 'text layer'|'PDF'|'', 'paras': [...], 'scanned': n, 'title': str}"""
    d = parse.document(act, lang)
    title = (d or {}).get('title', '')
    if d and any(d['lines']):
        items = textmod.html_lines(d['lines'])
        return {'source': 'text layer', 'paras': textmod.paragraphs(items, lang), 'scanned': 0, 'title': title}
    doc = pdftext.cached(act, lang)
    if doc:
        items = textmod.pdf_lines(doc)
        return {'source': 'PDF', 'paras': textmod.paragraphs(items, lang),
                'scanned': sum(1 for p in doc['pages'] if p['scanned']), 'pages': len(doc['pages']), 'title': title}
    return {'source': '', 'paras': [], 'scanned': 0, 'title': title}


def parse_act(act: int) -> int:
    out = PARSED / f'{act}.json'
    key = source_key(act)
    if out.exists():
        try:
            d = json.loads(out.read_text('utf-8'))
            if d.get('parser') == PARSER_VERSION and d.get('key') == key:
                return act
        except (OSError, json.JSONDecodeError):
            pass
    det = parse.detail(act)
    res = {'parser': PARSER_VERSION, 'key': key, 'detail': det, 'text': {}, 'issues': []}
    for lang in ('sq', 'en'):
        t = read_text(act, lang)
        if t['paras']:
            got = textmod.language(t['paras'])
            if got and got != lang:
                res['issues'].append(f'{lang} text is in another language ({got}); left out')
                t = {'source': '', 'paras': [], 'scanned': t['scanned'], 'title': t['title'], 'wrong': got}
        t['structure'] = textmod.structure(t['paras'], lang, amending=bool(AMENDING.search(det['title'])),
                                           whole=det['category'] == 'Aktgjykime',
                                           ratifies='RATIFIKIM' in det['title'].upper()) if t['paras'] else None
        res['text'][lang] = t
    sq, en = res['text']['sq']['paras'], res['text']['en']['paras']
    res['inforce'] = inforce.parse(sq, en, det['published'])
    out.write_text(json.dumps(res, ensure_ascii=False), 'utf-8')
    return act


def load(act: int) -> dict:
    a = json.loads((PARSED / f'{act}.json').read_text('utf-8'))
    # read again at every build (cheap), so a change to inforce.py needs no re-parse
    a['inforce'] = inforce.parse(a['text']['sq']['paras'], a['text']['en']['paras'], a['detail']['published'])
    return a


def slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', s.translate(ASCII).lower()).strip('-') or 'x'


def number_slug(det: dict) -> str:
    num = det['number'] or ''
    m = re.fullmatch(r'\s*(?:KUV-)?(\d{2})\s*/\s*L\s*-\s*(\d+)\s*(?:-KOD)?\s*', num, re.I)
    if m:
        return f'{m.group(1)}-l-{m.group(2)}'
    if det['id'] == 3702:
        return '2008'
    return slug(num) or str(det['id'])


def clean_number(num: str) -> str:
    return re.sub(r'\s*([/-])\s*', r'\1', (num or '').strip())


def author_of(det: dict) -> tuple[str, str]:
    title = det['title'].upper()
    num = clean_number(det['number'])
    if det['id'] == 3702:
        return 'Kushtetuta e Republikës së Kosovës (2008)', 'kushtetuta-2008@gzk.invalid'
    if det['category'] == 'Kushtetuta':
        prefix = 'Amendamenti i Kushtetutës'
    elif title.startswith('LIGJ'):
        prefix = 'Ligji'
    elif title.startswith('KOD'):
        prefix = 'Kodi'
    else:
        prefix = {'Aktgjykime': 'Aktgjykimi', 'Urdhër': 'Urdhri', 'Vendime': 'Vendimi'}.get(det['category'],
                                                                                         det['category'])
    name = f'{prefix} Nr. {num}' if num else prefix
    return name, f'{slug(prefix)}-{slug(num) or det["id"]}@gzk.invalid'


def act_files(a: dict) -> dict[str, str]:
    files = {}
    for lang in ('sq', 'en'):
        st = a['text'][lang].get('structure')
        if not st:
            continue
        base = a['dir'] if lang == 'sq' else 'en/' + a['dir']
        pre, art, sig, body = FILES[lang]
        if st['body']:
            files[f'{base}/{body}.md'] = '\n'.join(st['body']) + '\n'
            continue
        if st['preamble']:
            files[f'{base}/{pre}.md'] = '\n'.join(st['preamble']) + '\n'
        for n, lines in st['articles']:
            files[f'{base}/{art}-{n:03d}.md'] = '\n'.join(lines) + '\n'
        if st['signature']:
            files[f'{base}/{sig}.md'] = '\n'.join(st['signature']) + '\n'
    return files


def load_acts(ids: list[int]) -> list[dict]:
    acts = []
    used: dict[str, int] = {}
    for i in ids:
        a = load(i)
        det = a['detail']
        a['id'] = i
        d = f"{KIND_DIR.get(det['category'], slug(det['category']))}/{number_slug(det)}"
        if d in used:
            d = f'{d}-{i}'
        used[d] = i
        a['dir'] = d
        a['files'] = act_files(a)
        acts.append(a)
    return acts


# ---------------------------------------------------------------------------------------------------- dates

def last_sunday(y: int, m: int) -> date:
    d = date(y, m, 31)
    return d - timedelta(days=(d.weekday() + 1) % 7)


def belgrade(day: str, seq: int) -> str:
    """Noon in Kosovo (Europe/Belgrade): +02:00 from the last Sunday of March to the day before the last Sunday of
    October, else +01:00. Days before 1970 are clamped to seconds after the epoch, in order."""
    d = date.fromisoformat(day)
    if d.year < 1970:
        return f'{seq} +0000'
    summer = last_sunday(d.year, 3) <= d < last_sunday(d.year, 10)
    off = 2 if summer else 1
    ts = int((datetime(d.year, d.month, d.day, 12) - timedelta(hours=off)).replace(tzinfo=timezone.utc).timestamp())
    return f'{ts} +0{off}00'


# ---------------------------------------------------------------------------------------------------- plan

def count_reason(s: dict, e: dict) -> str:
    """Why the Albanian and English article counts differ, from what the parser found."""
    top = {k: max((n for n, _ in st['articles']), default=0) for k, st in (('sq', s), ('en', e))}
    if not s['articles'] or not e['articles']:
        lang = 'Albanian' if not s['articles'] else 'English'
        return f'the {lang} text has no article headings the parser can read (an OCR text layer)'
    if not s['gaps'] and not e['gaps']:
        return (f"both are numbered without gaps (1-{top['sq']} and 1-{top['en']}): the publisher's Albanian and "
                f"English texts differ")
    if top['sq'] == top['en']:
        return (f"both are numbered 1-{top['sq']}; headings missing from the source (listed in this file) account "
                f"for the difference")
    return (f"numbered 1-{top['sq']} in Albanian and 1-{top['en']} in English, with headings missing from the "
            f"source (listed in this file): the publisher's texts differ")


def plan(acts: list[dict], issues: list[dict]) -> list[dict]:
    by_id = {a['id']: a for a in acts}
    for a in acts:
        a['date'] = a['inforce']['date'] or a['detail']['published']
        for msg in a['issues']:
            issues.append({'act': a['id'], 'issue': msg})
        for lang in ('sq', 'en'):
            st = a['text'][lang].get('structure') or {}
            for note in st.get('notes', []):
                issues.append({'act': a['id'], 'issue': note})
            for g in st.get('gaps', []):
                issues.append({'act': a['id'], 'issue': f'{lang}: no heading for article {g + 1} in the source; its '
                                                         f'text (if any) is in article {g}'})
        s, e = (a['text'][l].get('structure') for l in ('sq', 'en'))
        if s and e and len(s['articles']) != len(e['articles']):
            issues.append({'act': a['id'], 'issue': f"articles found: {len(s['articles'])} in Albanian, "
                                                    f"{len(e['articles'])} in English; {count_reason(s, e)}"})
        if not a['files']:
            issues.append({'act': a['id'], 'issue': 'no text in either language (scanned or empty); no commit'})
    order = sorted((a for a in acts if a['files']),
                   key=lambda a: (a['date'], a['detail']['published'], a['id']))
    index = {a['id']: k for k, a in enumerate(order)}
    # Repeals: the repealed act's own page names the repealer ("Shfuqizuar nga"), or the repealer names it
    # ("Shfuqizon") and the repealed act is marked "I shfuqizuar".
    repealers: dict[int, set] = {}
    for a in acts:
        for r in a['detail']['related']:
            if r['relation'] == 'Shfuqizuar nga':
                repealers.setdefault(a['id'], set()).add(r['id'])
            elif r['relation'] == 'Shfuqizon' and r['id'] in by_id and \
                    by_id[r['id']]['detail']['status'] == 'I shfuqizuar':
                repealers.setdefault(r['id'], set()).add(a['id'])
    for a in order:
        a['deletes'] = []
    for gone, by in sorted(repealers.items()):
        if gone not in index:
            continue
        cands = sorted((by_id[b] for b in by if b in index), key=lambda b: index[b['id']])
        outside = sorted(b for b in by if b not in index)
        if not cands:
            issues.append({'act': gone, 'issue': f'repealed by act(s) not in this record ({", ".join(map(str, outside))});'
                                                  ' its files are left in place'})
            continue
        b = cands[0]
        if index[b['id']] < index[gone]:
            issues.append({'act': gone, 'issue': f'repealing act {b["id"]} takes effect ({b["date"]}) before this act '
                                                  f'({by_id[gone]["date"]}); its files are left in place'})
            continue
        b['deletes'].append(gone)
    return order


def short(s: str, n: int) -> str:
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def message(a: dict, by_id: dict) -> tuple[str, str]:
    det = a['detail']
    inf = a['inforce']
    name, email = author_of(det)
    sq_n = sum(1 for p in a['files'] if not p.startswith('en/'))
    en_n = len(a['files']) - sq_n
    subject = short(det['title'], 72)
    en_title = a['text']['en'].get('title') or ''
    body = [short(det['title'], 1000)]
    if en_title and en_title.upper() != det['title'].upper():
        body.append(short(en_title, 1000))
    body += ['', f"The act as published in the Official Gazette of the Republic of Kosovo"
             f"{' No. ' + det['gazette'] if det['gazette'] else ''} on {det['published']}: {sq_n} file(s) in Albanian"
             f"{f', {en_n} in English' if en_n else ', no English text'}. Later amendments are not applied to it;"
             f" the acts that amend it are listed in data/amendments.csv."]
    if a['deletes']:
        body += ['', f"Repeals {len(a['deletes'])} act(s) in this record, whose files are deleted:"]
        for g in a['deletes']:
            body.append(f"- {short(by_id[g]['detail']['title'], 200)} ({by_id[g]['dir']}/)")
    trailers = ['Kind: enacted', f"In-force: {a['date']}", f"In-force-basis: {inf['basis']}"]
    if inf.get('words'):
        trailers.append(f"In-force-rule: {short(inf['words'], 300)}")
    if a['date'] < det['published']:
        trailers.append(f"In-force-before-publication: yes")
    trailers.append(f"Published: {det['published']}")
    if det['gazette']:
        trailers.append(f"Gazette: {det['gazette']}")
    if det['number']:
        trailers.append(f"Number: {clean_number(det['number'])}")
    trailers.append(f"Act: {a['id']}")
    trailers.append(f"Source: {SITE}ActDetail.aspx?ActID={a['id']}")
    for lang, key in (('sq', 'Text-sq'), ('en', 'Text-en')):
        t = a['text'][lang]
        trailers.append(f"{key}: {t['source'] or 'none'}" + (f" ({t['scanned']} scanned page(s) not transcribed)"
                                                            if t.get('scanned') else ''))
    for r in det['related']:
        if r['relation'] in ('Ndryshon/Plotëson', 'Shfuqizon pjesërisht'):
            key = 'Amends' if r['relation'] == 'Ndryshon/Plotëson' else 'Partly-repeals'
            where = by_id[r['id']]['dir'] + '/' if r['id'] in by_id else 'not in this record'
            trailers.append(f"{key}: {r['id']} | {where}")
    for g in a['deletes']:
        trailers.append(f"Repeals: {g} | {by_id[g]['dir']}/")
    msg = '\n'.join([subject, '', *body, '', *trailers]) + '\n'
    return f'{name} <{email}>', msg


# ---------------------------------------------------------------------------------------------------- write

def fast_import(repo: Path, order: list[dict], by_id: dict, docs: dict[str, bytes], today: str) -> None:
    proc = subprocess.Popen(['git', '-C', str(repo), 'fast-import', '--quiet', '--force', '--done'],
                            stdin=subprocess.PIPE)
    w = proc.stdin.write
    mark = 0
    seq = 0

    def commit(a: dict, ref: str, parent: int | None) -> int:
        nonlocal mark, seq
        seq += 1
        mark += 1
        author, msg = message(a, by_id)
        when = belgrade(a['date'], seq)
        w(f'commit {ref}\nmark :{mark}\nauthor {author} {when}\ncommitter {COMMITTER} {when}\n'.encode('utf-8'))
        m = msg.encode('utf-8')
        w(f'data {len(m)}\n'.encode() + m + b'\n')
        if parent:
            w(f'from :{parent}\n'.encode())
        for g in a['deletes']:
            for path in sorted(by_id[g]['files']):
                w(f'D {path}\n'.encode('utf-8'))
        for path, text in sorted(a['files'].items()):
            t = text.encode('utf-8')
            w(f'M 100644 inline {path}\ndata {len(t)}\n'.encode('utf-8') + t + b'\n')
        w(b'\n')
        return mark

    head = None
    for a in order:
        if a['date'] <= today:
            head = commit(a, 'refs/heads/main', head)
    seq += 1
    mark += 1
    # The documentation commit: at the start of the retrieval day (00:00 Kosovo time), so it is never in the future
    ts, off = belgrade(today, seq).split()
    when = f'{int(ts) - 12 * 3600} {off}'
    msg = (f'Documentation: README, REPRODUCE, SOURCES, tools and data\n\nBuilt from the gzk.rks-gov.net cache '
           f'retrieved by {today}.\n\nKind: documentation\n').encode()
    w(f'commit refs/heads/main\nmark :{mark}\nauthor {COMMITTER} {when}\ncommitter {COMMITTER} {when}\n'.encode())
    w(f'data {len(msg)}\n'.encode() + msg + b'\n')
    w(f'from :{head}\n'.encode())
    for path, data in sorted(docs.items()):
        w(f'M 100644 inline {path}\ndata {len(data)}\n'.encode('utf-8') + data + b'\n')
    w(b'\n')
    prev = mark
    for a in order:
        if a['date'] > today:
            prev = commit(a, 'refs/heads/future', prev)
    w(b'done\n')
    proc.stdin.close()
    if proc.wait():
        sys.exit('git fast-import failed')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('repo', type=Path)
    ap.add_argument('--today', required=True, help='the build day: later in-force dates go to the future branch')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--parse-only', action='store_true')
    args = ap.parse_args()
    PARSED.mkdir(parents=True, exist_ok=True)
    import docs as docmod  # fail before the long part

    ids = act_ids()
    print(f'{len(ids)} acts; parsing', flush=True)
    try:
        if args.workers <= 1:
            raise RuntimeError('one process')
        with ProcessPoolExecutor(min(args.workers, 8)) as pool:
            for k, _ in enumerate(pool.map(parse_act, ids, chunksize=4), 1):
                if k % 200 == 0:
                    print(f'  parsed {k}/{len(ids)}', flush=True)
    except Exception as e:  # noqa: BLE001 - a broken pool (seen under Git Bash on Windows): parse in this process
        print(f'  parsing in one process ({type(e).__name__}: {e})', flush=True)
        for k, i in enumerate(ids, 1):
            parse_act(i)
            if k % 200 == 0:
                print(f'  parsed {k}/{len(ids)}', flush=True)
    if args.parse_only:
        return
    acts = load_acts(ids)
    by_id = {a['id']: a for a in acts}
    issues: list[dict] = []
    order = plan(acts, issues)
    future = sum(1 for a in order if a['date'] > args.today)
    print(f'{len(order)} commits ({future} future), {sum(len(a["deletes"]) for a in order)} repeals; '
          f'{len(issues)} issues', flush=True)
    docs = docmod.render(acts, order, by_id, issues, args.today)

    repo = args.repo
    repo.mkdir(parents=True, exist_ok=True)
    if (repo / '.git').exists():
        import os
        import shutil
        import stat

        def onerr(func, path, _):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(repo / '.git', onerror=onerr)
        for child in repo.iterdir():
            shutil.rmtree(child, onerror=onerr) if child.is_dir() else child.unlink()
    elif any(repo.iterdir()):
        sys.exit(f'{repo} is not empty and not an earlier build; refusing to write into it')
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], check=True)
    for k, v in (('core.autocrlf', 'false'), ('core.quotepath', 'false'), ('core.longpaths', 'true')):
        subprocess.run(['git', '-C', str(repo), 'config', k, v], check=True)
    fast_import(repo, order, by_id, docs, args.today)
    subprocess.run(['git', '-C', str(repo), 'checkout', '-q', '-f', 'main'], check=True)
    head = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    count = subprocess.run(['git', '-C', str(repo), 'rev-list', '--count', 'HEAD'], capture_output=True,
                           text=True).stdout.strip()
    print(f'built {repo}: {count} commits on main, head {head}', flush=True)


if __name__ == '__main__':
    main()

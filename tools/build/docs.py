"""README, REPRODUCE.md, SOURCES.md, LICENSE, corpus.json, laws.csv, data/ and tools for the Kosovo law repository
(called by build.py)."""
import csv
import gzip
import hashlib
import io
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
REPO_FILES = HERE / 'repo'
CACHE = HERE / '.cache'
SCRIPTS = ('build.py', 'text.py', 'pdftext.py', 'inforce.py', 'parse.py', 'gzk.py', 'fetch.py', 'docs.py',
           'check_words.py', 'extra_acts.json')
KIND_NAMES = {'ligje': 'laws', 'kode': 'codes', 'kushtetuta': 'the 2008 Constitution and its amendments',
              'aktgjykime': 'Constitutional Court judgments', 'urdhera': 'orders', 'vendime': 'decisions'}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def source_sums(ids: list[int]) -> str:
    """sha256 of every cached source page (decompressed) and PDF, one line each."""
    rows = []
    for i in ids:
        d = CACHE / 'act' / str(i)
        for name in ('detail-sq.html.gz', 'doc-sq.html.gz', 'doc-en.html.gz', 'pdf-sq.pdf', 'pdf-en.pdf'):
            p = d / name
            if p.exists():
                b = p.read_bytes()
                if name.endswith('.gz'):
                    b = gzip.decompress(b)
                rows.append(f'{_sha(b)}\t{i}/{name.removesuffix(".gz")}')
    for f in sorted((CACHE / 'consolidated').glob('20*-p*.html')):
        rows.append(f'{_sha(f.read_bytes())}\tconsolidated/{f.name}')
    return '\n'.join(rows) + '\n'


NUMBER_IN_TITLE = re.compile(r'\b(\d{2}\s*/?\s*L\s*[-–]\s*\d+|\d{4}\s*/\s*\d+)\b', re.I)   # "04L-042" too


def number_key(num: str) -> str:
    """'04/L-036', '04/ L – 036', 'KUV-04/L-036' -> '04/L-036'; '2003/22' as is."""
    m = NUMBER_IN_TITLE.search(num or '')
    if not m:
        return ''
    k = re.sub(r'\s+', '', m.group(1)).upper().replace('–', '-')
    k = re.sub(r'^(\d{2})L', r'\1/L', k)
    return re.sub(r'/L-?0*(\d+)', lambda x: f'/L-{int(x.group(1)):03d}', k)


def iso(dmy: str) -> str:
    d, m, y = dmy.split('.')
    return f'{y}-{int(m):02d}-{int(d):02d}'


def csv_text(header: list[str], rows: list[list]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator='\n')
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue()


def git_version() -> str:
    return subprocess.run(['git', '--version'], capture_output=True, text=True).stdout.strip()


def render(acts: list[dict], order: list[dict], by_id: dict, issues: list[dict], today: str) -> dict[str, bytes]:
    main = [a for a in order if a['date'] <= today]
    future = [a for a in order if a['date'] > today]
    repealed_in = {g: a['id'] for a in order for g in a['deletes']}
    basis = Counter()
    for a in order:
        b = a['inforce']['basis']
        basis['publication' if b == 'on publication' else 'day' if b.startswith('day ') else
              'date' if b in ('date in the act', 'first day of the month named in the act') else 'months' if 'month' in b or 'year' in b else
              'promulgation' if 'promulgation' in b else 'fallback'] += 1
    src = Counter((a['text']['sq']['source'] or 'none', a['text']['en']['source'] or 'none') for a in acts)
    sq_files = sum(1 for a in order for p in a['files'] if not p.startswith('en/'))
    en_files = sum(1 for a in order for p in a['files'] if p.startswith('en/'))
    kinds = Counter(a['dir'].split('/')[0] for a in order)
    no_text = [a for a in acts if not a['files']]
    scanned = sum(a['text'][l].get('scanned', 0) for a in acts for l in ('sq', 'en'))
    first = min(a['date'] for a in main)
    last = max(a['date'] for a in main)
    status_repealed = sum(1 for a in acts if a['detail']['status'] == 'I shfuqizuar')

    laws_rows = []
    for a in sorted(acts, key=lambda a: a['id']):
        det = a['detail']
        laws_rows.append([
            a['id'], det['category'], det['number'], det['title'], det['published'], det['gazette'],
            a['inforce']['date'] if a['files'] else '', a['inforce']['basis'] if a['files'] else '',
            det['status'] or 'in force', a['text']['sq']['source'] or 'none', a['text']['en']['source'] or 'none',
            sum(1 for p in a['files'] if not p.startswith('en/')), sum(1 for p in a['files'] if p.startswith('en/')),
            a['text']['sq'].get('scanned', 0) + a['text']['en'].get('scanned', 0),
            (a['dir'] + '/') if a['files'] else '', repealed_in.get(a['id'], ''),
            f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={a['id']}"])
    laws_csv = csv_text(['act', 'category', 'number', 'title', 'published', 'gazette', 'in_force', 'in_force_basis',
                         'status_on_gzk', 'text_sq', 'text_en', 'files_sq', 'files_en', 'scanned_pages', 'path',
                         'files_deleted_by_act', 'source'], laws_rows)

    from build import RELATION_EN
    am_rows = []
    for a in sorted(acts, key=lambda a: a['id']):
        for r in a['detail']['related']:
            o = by_id.get(r['id'])
            am_rows.append([a['id'], a['detail']['number'], (a['dir'] + '/') if a['files'] else '', r['relation'],
                            RELATION_EN.get(r['relation'], r['relation']), r['id'], r['title'], r['published'],
                            'yes' if o else 'no', (o['dir'] + '/') if o and o['files'] else '',
                            o['inforce']['date'] if o and o['files'] else ''])
    amendments_csv = csv_text(['act', 'number', 'path', 'relation', 'relation_en', 'other_act', 'other_title',
                               'other_published', 'other_in_record', 'other_path', 'other_in_force'], am_rows)
    # English documents that hold the Albanian text: left out of en/ (the Albanian text is under its own path)
    wrong_rows = []
    for a in sorted(acts, key=lambda a: a['id']):
        if a['text']['en'].get('wrong'):
            d = CACHE / 'act' / str(a['id'])
            same = (d / 'pdf-sq.pdf').exists() and (d / 'pdf-en.pdf').exists() and                 _sha((d / 'pdf-sq.pdf').read_bytes()) == _sha((d / 'pdf-en.pdf').read_bytes())
            wrong_rows.append([a['id'], a['detail']['number'], a['detail']['title'], a['text']['en'].get('title', ''),
                               {'sq': 'Albanian', 'sr': 'Serbian'}.get(a['text']['en']['wrong'],
                                                                     a['text']['en']['wrong']),
                               'yes' if same else 'no', (a['dir'] + '/') if a['files'] else '',
                               f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={a['id']}"])
    en_left_out_csv = csv_text(['act', 'number', 'title', 'english_page_title', 'language_of_english_document',
                                'same_file_as_albanian_pdf', 'albanian_path', 'source'], wrong_rows)
    # The consolidated texts the Gazette publishes (ConsolidatedActs.aspx, "(KONSOLIDUAR)"): a list, not history
    cons_path = CACHE / 'consolidated.json'
    cons = json.loads(cons_path.read_text('utf-8')) if cons_path.exists() else {'rows': []}
    by_number = {}
    for a in sorted(acts, key=lambda a: a['id']):
        if a['detail']['category'] in ('Ligje', 'Kode') and number_key(a['detail']['number']):
            by_number.setdefault(number_key(a['detail']['number']), a)
    cons_rows = []
    for r in sorted(cons['rows'], key=lambda r: (iso(r['published']), r['id'])):
        key = number_key(r['title'])
        base = by_number.get(key) if key else (by_id.get(3702) if r['title'].upper().startswith('KUSHTETUTA')
                                               else None)   # the Constitution has no number
        cons_rows.append([r['id'], key, r['title'], iso(r['published']), base['id'] if base else '',
                          (base['dir'] + '/') if base and base['files'] else '',
                          f"https://gzk.rks-gov.net/ActDetail.aspx?ActID={r['id']}"])
    consolidated_csv = csv_text(['act', 'number', 'title', 'published', 'base_act_in_record', 'base_path', 'source'],
                                cons_rows)
    issues_csv = csv_text(['act', 'issue'], [[i['act'], i['issue']] for i in sorted(issues, key=lambda i: (i['act'],
                                                                                                          i['issue']))])
    relations = Counter(r['relation'] for a in acts for r in a['detail']['related'])
    outside = len({r['id'] for a in acts for r in a['detail']['related'] if r['id'] not in by_id})

    stats = {
        'today': today, 'acts': len(acts), 'with_text': len(order), 'no_text': len(no_text),
        'commits': len(main) + 1, 'future': len(future), 'first': first, 'last': last,
        'repeals': len(repealed_in), 'status_repealed': status_repealed,
        'sq_files': sq_files, 'en_files': en_files, 'scanned_pages': scanned,
        'basis_publication': basis['publication'], 'basis_day': basis['day'], 'basis_date': basis['date'],
        'basis_months': basis['months'], 'basis_promulgation': basis['promulgation'],
        'basis_fallback': basis['fallback'],
        'src_html': sum(v for (s, _), v in src.items() if s == 'text layer'),
        'src_pdf': sum(v for (s, _), v in src.items() if s == 'PDF'),
        'en_html': sum(v for (_, e), v in src.items() if e == 'text layer'),
        'en_pdf': sum(v for (_, e), v in src.items() if e == 'PDF'),
        'en_none': sum(v for (_, e), v in src.items() if e == 'none'),
        'sq_none': sum(v for (s, _), v in src.items() if s == 'none'),
        'relations': sum(relations.values()), 'outside': outside,
        'amended_by': relations['Ndryshohet/Plotësohet nga'], 'partly_repealed': relations['Shfuqizuar pjesërisht nga'],
        'issues': len(issues),
        'en_left_out': len(wrong_rows),
        'consolidated': len(cons_rows),
        'consolidated_matched': sum(1 for r in cons_rows if r[4] != ''),
        'consolidated_first': cons_rows[0][3] if cons_rows else '',
        'consolidated_last': cons_rows[-1][3] if cons_rows else '',
        'consolidated_retrieved': cons.get('retrieved', ''),
        'kinds_line': '; '.join(f'{v} {KIND_NAMES.get(k, k)}' for k, v in sorted(kinds.items(), key=lambda x: -x[1])),
        'git': git_version(),
    }
    # The independent check's result on the previous build of the same texts (check_words.py writes it).
    cw_path = CACHE / 'check_words.json'
    cw = json.loads(cw_path.read_text('utf-8')) if cw_path.exists() else {}
    stats.update({'cw_checked': cw.get('checked', 'n/a'), 'cw_same': cw.get('same', 'n/a'),
                  'cw_reordered': cw.get('reordered', 'n/a'), 'cw_spacing': cw.get('spacing', 'n/a'),
                  'cw_bad': cw.get('letters', 'n/a'),
                  'cw_list': ', '.join(cw.get('mismatches', [])) or 'none'})
    sums = source_sums(sorted(by_id))
    stats['source_files'] = sums.count('\n')
    stats['sums_sha'] = _sha(sums.encode())

    def fill(t: str) -> str:
        for k, v in stats.items():
            t = t.replace('{{' + k.upper() + '}}', str(v))
        for name in SCRIPTS:
            t = t.replace('{{SHA_' + name.upper().replace('.', '_') + '}}', _sha((HERE / name).read_bytes()))
        return t

    readme = fill((REPO_FILES / 'README.md').read_text('utf-8'))
    reproduce = fill((REPO_FILES / 'REPRODUCE.md').read_text('utf-8'))
    sources = fill((REPO_FILES / 'SOURCES.md').read_text('utf-8'))

    corpus = {
        'corpus': 'xk/national/acts',
        'name': 'Legislation of Kosovo, as enacted (Official Gazette, gzk.rks-gov.net)',
        'label': 'Kosovo: laws as enacted',
        'language': 'sq',
        'languages': ['sq', 'en'],
        'history': 'as-enacted',
        'history_from': first,
        'record_to': last,
        'checked_on': today,
        'built': today,
        'record_note': "every act in the Official Gazette's list of laws (LawInForceList: laws, codes, Constitutional "
                       "Court judgments, in force or repealed) plus the 2008 Constitution and its amendments, each as "
                       "enacted, dated by its own in-force article; amendments are not applied (listed in "
                       "data/amendments.csv); repealed acts' files are deleted on the repealing act's in-force day; "
                       "English translations under en/; acts in force after the build day are on the future branch",
        'in_force_trailer': 'In-force',
        'baseline_trailer': 'In-force',
        'has_future_branch': True,
        'future_branch': 'future',
        'acts': dict(kinds),
        'dates': {'commit': 'in-force (from the act\'s own in-force article)',
                  'other_trailers': ['Published', 'Gazette', 'In-force-basis', 'In-force-rule'],
                  'time': '12:00 Europe/Belgrade (CET +01:00 / CEST +02:00)',
                  'future': 'branch future, never merged'},
        'author': {'enacted': 'the act itself', 'documentation': 'Lexifina'},
        'scope': {
            'trailer': 'Applies',
            'groups': 'any one line',
            'conditions': 'all of a line',
            'when_absent': 'no scope note extracted for Kosovo; transitional provisions are in each act',
            'default_reach': {
                'rule': 'no retroactive criminal liability or heavier penalty',
                'meaning': 'no one may be charged or punished for an act that was not a criminal offence under law '
                           'when committed, and penalties follow the law in force at the time unless a later law is '
                           'more favourable; no general rule for other laws was checked here',
                'authority': 'Constitution of the Republic of Kosovo (2008), art. 33(1) and (4)',
                'decided_here': False,
            },
        },
        'citation': {
            'file': r'^([a-z]+/[0-9a-z-]+)/neni-0*([0-9]+)\.md$',
            'cites': r'[Nn]en(i|it|in|et|eve)[[:space:]]+{n}([^0-9/]|$)',
            'note': 'Albanian forms "neni N", "nenit N", "nenin N"; citations are within the same act; the English '
                    'files (en/.../article-NNN.md) are not matched by the file rule',
        },
        'tool': 'tools/in_force_on.py',
    }
    files = {
        'corpus.json': (json.dumps(corpus, indent=2, ensure_ascii=False) + '\n').encode('utf-8'),
        'README.md': readme.encode('utf-8'),
        'REPRODUCE.md': reproduce.encode('utf-8'),
        'SOURCES.md': sources.encode('utf-8'),
        'LICENSE': (REPO_FILES / 'LICENSE').read_bytes(),
        'laws.csv': laws_csv.encode('utf-8'),
        'data/amendments.csv': amendments_csv.encode('utf-8'),
        'data/issues.csv': issues_csv.encode('utf-8'),
        'data/en-left-out.csv': en_left_out_csv.encode('utf-8'),
        'data/consolidated.csv': consolidated_csv.encode('utf-8'),
        'data/stats.json': (json.dumps(stats, indent=1, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8'),
        'data/source-sha256.tsv': sums.encode('utf-8'),
        'tools/in_force_on.py': (REPO_FILES / 'tools' / 'in_force_on.py').read_bytes(),
    }
    for name in SCRIPTS:
        files[f'tools/build/{name}'] = (HERE / name).read_bytes()
    for name in ('README.md', 'REPRODUCE.md', 'SOURCES.md', 'LICENSE'):
        files[f'tools/build/repo/{name}'] = (REPO_FILES / name).read_bytes()
    return files

"""Parse cached gzk.rks-gov.net pages: ActDetail (metadata and links to related acts) and ActDocumentDetail (text)."""
import gzip
import html
import re
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / '.cache'


def load(act: int, name: str) -> str | None:
    p = CACHE / 'act' / str(act) / f'{name}.html.gz'
    return gzip.decompress(p.read_bytes()).decode('utf-8') if p.exists() else None


def clean(s: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s))).strip()


def span(page: str, ident: str) -> str:
    m = re.search(rf'id="MainContent_{ident}"[^>]*>(.*?)</(?:span|a)>', page, re.S)
    return clean(m.group(1)) if m else ''


def dmy(s: str) -> str:
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', s or '')
    return f'{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}' if m else ''


def detail(act: int) -> dict | None:
    page = load(act, 'detail-sq')
    if page is None:
        return None
    m = re.search(r'id="MainContent_rAktet_lblAn_0"[^>]*>(.*?)</a>', page, re.S)
    status = span(page, 'lblAct_Ne_Fuqi_Txt')
    gz = re.search(r'id="MainContent_lblDGZK" href="OfficialGazetteDetail\.aspx\?GZID=(\d+)">(.*?)</a>', page, re.S)
    out = {
        'id': act,
        'title': clean(m.group(1)) if m else span(page, 'lblActName'),
        'category': span(page, 'lblDActCategoryName_1'),
        'number': span(page, 'lblDActNo'),
        'institution': span(page, 'lblDInstSpons'),
        'status': status,
        'published': dmy(span(page, 'lblDPubDate')),
        'gazette': clean(gz.group(2)) if gz else '',
        'gazette_id': int(gz.group(1)) if gz else 0,
        'related': [],
    }
    i = page.find('id="MainContent_drActRelated"')
    j = page.find('id="MainContent_drSubNormAct"')
    rel_part = page[i:j if j > i else len(page)] if i >= 0 else ''
    for box in re.findall(r'<div class="act_link_box_1">(.*?)<!--fund act_link_box-->', rel_part, re.S):
        rel = re.search(r'<span class="span_margin" style="[^"]*">(.*?)</span>', box, re.S)
        link = re.search(r'href="ActDetail\.aspx\?ActID=(\d+)"[^>]*>(.*?)</a>', box, re.S)
        date = re.search(r'lblRPubDate_\d+">.*?</span>(.*?)</span>', box, re.S)
        if link:
            out['related'].append({'relation': clean(rel.group(1)) if rel else '', 'id': int(link.group(1)),
                                   'title': clean(link.group(2)), 'published': dmy(date.group(1)) if date else ''})
    return out


def document(act: int, lang: str) -> dict | None:
    """The text layer as served: {'title', 'lines'} (one source line per entry, '' for empty lines)."""
    page = load(act, f'doc-{lang}')
    if page is None:
        return None
    want = 'lbEnglish' if lang == 'en' else 'lbAlbanian'
    if f'id="ctlLang1_{want}" class="lang_main_active"' not in page:
        return None
    m = re.search(r'<span id="MainContent_txtDocument">(.*?)</span>\s*</p>', page, re.S)
    if not m:
        return {'title': span(page, 'lblActName'), 'lines': [], 'raw': ''}
    raw = m.group(1)
    lines = []
    for part in re.split(r'<br\s*/?>', raw):
        t = html.unescape(re.sub(r'<[^>]+>', '', part))
        t = t.replace('­', '').replace(' ', ' ').replace('\r', '').replace('\n', ' ')
        lines.append(re.sub(r'[ \t\f\v]+', ' ', t).strip())
    return {'title': span(page, 'lblActName'), 'lines': lines, 'raw': raw}

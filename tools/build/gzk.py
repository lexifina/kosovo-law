"""Minimal client for gzk.rks-gov.net (the Official Gazette of Kosovo), an ASP.NET WebForms site.

Each Session keeps its own cookies, so its language choice (a postback) sticks. Standard library only.
"""
import gzip
import html
import http.cookiejar
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://gzk.rks-gov.net/'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/130.0 Safari/537.36 (Lexifina law-history builder; corpus@lexifina.com)')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Session:
    def __init__(self, lang: str = 'sq'):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect)
        self.requests = 0
        self.lang = 'sq'
        if lang == 'en':
            self.set_english()

    def raw(self, url: str, data: dict | None = None) -> tuple[int, dict, bytes]:
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        for attempt in range(5):
            r = urllib.request.Request(urllib.parse.urljoin(BASE, url), data=body,
                                       headers={'User-Agent': UA, 'Accept-Encoding': 'gzip'})
            try:
                try:
                    resp = self.op.open(r, timeout=120)
                except urllib.error.HTTPError as e:
                    resp = e
                b = resp.read()
                self.requests += 1
                if resp.headers.get('Content-Encoding') == 'gzip':
                    b = gzip.decompress(b)
                code = resp.status if hasattr(resp, 'status') else resp.code
                if code >= 500 and attempt < 4:
                    time.sleep(5 * (attempt + 1))
                    continue
                return code, dict(resp.headers), b
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                if attempt == 4:
                    raise
                time.sleep(5 * (attempt + 1))
        raise RuntimeError('unreachable')

    def get(self, url: str) -> str:
        code, h, b = self.raw(url)
        if code == 302:
            return self.get(h['Location'])
        if code != 200:
            raise RuntimeError(f'{url}: HTTP {code}')
        return b.decode('utf-8')

    def postback(self, url: str, page: str, target: str, image: bool = False, extra: dict | None = None) -> str:
        f = hidden_fields(page)
        if image:
            f[target + '.x'], f[target + '.y'] = '10', '10'
        else:
            f['__EVENTTARGET'], f['__EVENTARGUMENT'] = target, ''
        if extra:
            f.update(extra)
        code, h, b = self.raw(url, f)
        if code == 302:
            return self.get(h['Location'])
        if code != 200:
            raise RuntimeError(f'{url} postback {target}: HTTP {code}')
        return b.decode('utf-8')

    def set_english(self) -> None:
        url = 'ActDetail.aspx?ActID=2700'
        page = self.get(url)
        self.postback(url, page, 'ctl00$ctlLang1$lbEnglish')
        self.lang = 'en'


def hidden_fields(page: str) -> dict:
    out = {}
    for m in re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page):
        out[m.group(1)] = html.unescape(m.group(2))
    return out

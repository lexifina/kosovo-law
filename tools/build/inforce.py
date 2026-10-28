"""When a Kosovo act took effect, read from its own in-force article ("Hyrja në fuqi" / "Entry into force").

Kosovo laws end with an in-force article, nearly always in one of these forms:
    Ky ligj hyn në fuqi pesëmbëdhjetë (15) ditë pas publikimit në Gazetën Zyrtare ...   publication + 15 days
    Ky ligj hyn në fuqi ditën e publikimit në Gazetën Zyrtare ...                       the publication day
    Ky ligj hyn në fuqi më 1 janar 2011 ...                                            a date
    Ky ligj hyn në fuqi gjashtë (6) muaj pas publikimit ...                            publication + 6 months
    Ky Ligj hyn në fuqi pas miratimit nga Kuvendi ... dhe shpalljes nga PSSP-ja         promulgation (UNMIK era)
"N days after publication" is publication + N days (a period in days starts the day after the event). A rule that is
not a date (promulgation by the SRSG or the President, another event) falls back to the publication date in the
Official Gazette, with the rule quoted in the commit (`In-force-basis: published (...)`). The Albanian text is read
first, the English one when the Albanian has no rule. Standard library only.
"""
import calendar
import re
from datetime import date, timedelta

MONTHS = [('janar', 1), ('shkurt', 2), ('mars', 3), ('prill', 4), ('maj', 5), ('qershor', 6), ('korrik', 7),
          ('gusht', 8), ('shtator', 9), ('tetor', 10), ('nëntor', 11), ('nentor', 11), ('dhjetor', 12),
          ('january', 1), ('february', 2), ('march', 3), ('april', 4), ('may', 5), ('june', 6), ('july', 7),
          ('august', 8), ('september', 9), ('october', 10), ('november', 11), ('december', 12)]
WORDS = {'një': 1, 'dy': 2, 'tre': 3, 'tri': 3, 'katër': 4, 'pesë': 5, 'gjashtë': 6, 'shtatë': 7, 'tetë': 8,
         'nëntë': 9, 'dhjetë': 10, 'pesëmbëdhjetë': 15, 'njëzet': 20, 'tridhjetë': 30, 'gjashtëdhjetë': 60,
         'nëntëdhjetë': 90, 'one': 1, 'two': 2, 'three': 3, 'six': 6, 'eight': 8, 'ten': 10, 'fifteen': 15,
         'twenty': 20, 'thirty': 30, 'sixty': 60, 'ninety': 90}
# The verb: "hyn/hynë/hyjë/hyrë në fuqi", "fillon të zbatohet"; English "enter(s) into force", "come(s) into force".
VERB = re.compile(r'\bhy(?:n|në|ne|jë|je|rë|re)\s+n[eë]\s+fuqi|\bfillon\s+të\s+zbatohet|'
                  r'\b(?:enters?|entered|come|comes)\s+in(?:to)?\s+force|\bshall\s+be\s+effective', re.I)
SUBJECT = re.compile(r'\b(?:ky|kjo|this|the\s+present)\s+(?:ligj|kod|kushtetut|amendament|aktgjykim|urdh|vendim|'
                     r'rregullore|law|code|constitution|amendment|judgment|judgement|order|decision|regulation)',
                     re.I)
DATE = re.compile(r'(\d{1,2})\s*\.?\s*([A-Za-zëË]+)\s+(?:t[eë]\s+vitit\s+)?(\d{4})')
MONTH_ONLY = re.compile(r'\bn[eë]\s+([A-Za-zëË]+)\s+(?:t[eë]\s+vitit\s+)?(\d{4})')
ARTICLE = re.compile(r'^(?:#\s*)?(?:Neni|Article|Section)\s*\d+\s*(?:\[\s*)?(?:Hyrja\s+n[eë]\s+fuqi|Entry\s+into\s+force|'
                     r'Effective\s+date)|^(?:Hyrja\s+n[eë]\s+fuqi|Entry\s+into\s+force)\b', re.I)
MDY = re.compile(r'([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(\d{4})')
DMY = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4})')
PERIOD = re.compile(r'(?:\(\s*(\d+)\s*\)|\b(\d+)\b|\b([a-zë]+)\b)\s*(?:\(\s*\d+\s*\)\s*)?'
                    r'(dit|muaj|vit|day|month|year)', re.I)
NOW = re.compile(r'dit[eë]n\s+e\s+(?:publikimit|botimit)|n[eë]\s+dit[eë]n\s+e\s+(?:publikimit|botimit)|'
                 r'menj[eë]her[eë]|me\s+t[eë]\s+publikuar|pas\s+publikimit|on\s+the\s+day\s+of\s+(?:its\s+)?'
                 r'publication|upon\s+(?:its\s+)?publication|immediately|on\s+publication|'
                 r'after\s+(?:its\s+)?publication\s+in', re.I)
PROMULGATION = re.compile(r'shpallj|PSSP|Përfaqësuesi\s+Special|Pёrfaqёsuesi|promulgat|SRSG|Special\s+Representative|'
                          r'dekret', re.I)


def month(word: str) -> int | None:
    w = word.lower().replace('ё', 'ë')
    for stem, n in MONTHS:
        if w.startswith(stem):
            return n
    return None


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def norm(s: str) -> str:
    return re.sub(r'\s+', ' ', s.replace('ё', 'ë').replace('Ё', 'Ë')).strip()


def rule_of(paragraphs: list[str]) -> str:
    """The sentence that states when the act itself takes effect, or ''. The text after the act's last in-force
    heading ("Hyrja në fuqi" / "Entry into force") is read first, then the whole act."""
    heads = [k for k, p in enumerate(paragraphs) if len(p) < 90 and ARTICLE.search(norm(p))]
    for k in reversed(heads):   # an annexed agreement has its own "Hyrja në fuqi": take the act's own ("Ky ligj")
        part = rule_of_text(norm(' '.join(paragraphs[k:k + 4])))
        if part and SUBJECT.search(part[:VERB.search(part).start() + 1]):
            return part
    return rule_of_text(norm(' '.join(paragraphs)))


def rule_of_text(text: str) -> str:
    sentences = re.split(r'(?<=[.;])\s+(?=[A-ZËÇ0-9])', text)
    hits = [s for s in sentences if VERB.search(s)]
    own = [s for s in hits if SUBJECT.search(s[:VERB.search(s).start() + 1])]
    pick = (own or hits)
    return pick[-1][:600] if pick else ''


def when(rule: str, published: str) -> tuple[str | None, str]:
    """(ISO date or None, basis) for an in-force sentence."""
    m = VERB.search(rule)
    after = rule[m.end():] if m else rule
    pub = date.fromisoformat(published) if published else None
    # An explicit date right after the verb ("hyn në fuqi më 1 janar 2011").
    for dm in DATE.finditer(after[:120]):
        mo = month(dm.group(2))
        if mo:
            try:
                return date(int(dm.group(3)), mo, int(dm.group(1))).isoformat(), 'date in the act'
            except ValueError:
                pass
    for dm in MDY.finditer(after[:120]):
        mo = month(dm.group(1))
        if mo:
            try:
                return date(int(dm.group(3)), mo, int(dm.group(2))).isoformat(), 'date in the act'
            except ValueError:
                pass
    mm = MONTH_ONLY.search(after[:60])
    if mm and month(mm.group(1)):
        return date(int(mm.group(2)), month(mm.group(1)), 1).isoformat(), 'first day of the month named in the act'
    dm = DMY.search(after[:120])
    if dm:
        try:
            return date(int(dm.group(3)), int(dm.group(2)), int(dm.group(1))).isoformat(), 'date in the act'
        except ValueError:
            pass
    pm = PERIOD.search(after[:120])
    if pm and pub and re.search(r'pas|nga|after|following|from', after[pm.end():pm.end() + 40], re.I):
        n = int(pm.group(1) or pm.group(2) or 0) or WORDS.get((pm.group(3) or '').lower(), 0)
        unit = pm.group(4).lower()
        if n:
            if unit in ('dit', 'day'):
                return (pub + timedelta(days=n)).isoformat(), f'day {n} after publication'
            if unit in ('muaj', 'month'):
                return add_months(pub, n).isoformat(), f'{n} month(s) after publication'
            if unit in ('vit', 'year'):
                return add_months(pub, 12 * n).isoformat(), f'{n} year(s) after publication'
    if NOW.search(after[:160]) and not PROMULGATION.search(after[:160]):
        return published or None, 'on publication'
    if PROMULGATION.search(after[:200]):
        return published or None, 'published (the act takes effect on promulgation; the Official Gazette date is used)'
    return published or None, 'published (no date read from the in-force rule)'


def parse(sq: list[str], en: list[str], published: str) -> dict:
    """{'date', 'basis', 'words', 'lang'} for an act, from its Albanian paragraphs, else its English ones."""
    for lang, paras in (('sq', sq), ('en', en)):
        rule = rule_of(paras or [])
        if rule:
            d, basis = when(rule, published)
            return {'date': d or published, 'basis': basis, 'words': rule, 'lang': lang}
    return {'date': published, 'basis': 'published (no in-force rule found)', 'words': '', 'lang': ''}

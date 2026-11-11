"""Kosovo: acts of the Official Gazette (gzk.rks-gov.net) not yet in this repository, each as published, when no later
act amends, supplements or repeals them.

Reads only a local copy of the Gazette's pages:
  list/<category>.jsonl            {id, title, cat}: the Gazette's list of acts of each category (SearchIn, by CatID)
  act/<id//1000>/<id>/detail.html.gz   the act's page (ActDetail): category, number, institution, status, publication
                                   day, Gazette issue, related acts ("amended / supplemented / repealed by")
  act/<id//1000>/<id>/pdf.json.gz  the text layer of the act's Albanian PDF (ActDocumentDetail), line by line with its
                                   position: {sha256, pages: [{height, width, scanned, lines: [[x0,y0,x1,y1,size,bold,
                                   text,block]]}]}
and writes corpus.d parts (SCHEMA.md in scripts/gitlaw_common). Deterministic: the same inputs give the same bytes.

    python -X utf8 parse_acts.py --src <folder> --retrieved YYYY-MM-DD [--exclude ids.txt] [--report holds.jsonl]

Text: ks_text.py (the same reader the rest of this repository was built with) turns the PDF lines into paragraphs and
files: the preamble (hyrje), one file per article (neni-NNN), the signature block (nenshkrimi); an act without numbered
articles is one file (teksti). In-force day: ks_inforce.py reads the act's own in-force article (N days after
publication, the publication day, a date); "on the day of signature" takes the date in the act's title.

Added for acts first held back (rules applied only where the rules above hold an act, so acts they publish are
unchanged):
- a PDF printing the act in Albanian beside or after its English and Serbian texts is read from its Albanian column or
  pages alone, when the boundary is clean (albanian_part), the Albanian text ends at the same article number as the
  translations, and no English or Serbian is left in it;
- more in-force wordings (more_rules): on publication in the Official Gazette in its other forms, "N (word) days after
  publication in the Official Gazette", "on the day of adoption" where the act gives the adoption date, and "N days
  after signature" where the act prints its signature day (after_signature);
- such an act is held when its Gazette title is annotated as repealed or amended ("(Shfuqizuar ...)"), or its
  in-force sentence counts from registration, a municipal website or notice board, or approval by an assembly.

An act is held back, not published, when (the reason goes to the report):
- its Gazette page links an act that amends, supplements or repeals it, or marks it repealed, or a later act's title
  names it ("... PËR NDRYSHIMIN DHE PLOTËSIMIN E UDHËZIMIT ADMINISTRATIV NR. 05/2023");
- its PDF is missing, scanned, not in Albanian (and not cleanly cut to its Albanian part), or its articles don't
  number cleanly;
- no in-force day can be read from it.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ks_inforce  # noqa: E402
import ks_text  # noqa: E402

PARTS = HERE / "corpus.d"
DETAIL = "https://gzk.rks-gov.net/ActDetail.aspx?ActID={id}"
DOC = "https://gzk.rks-gov.net/ActDocumentDetail.aspx?ActID={id}"
KINDS = {"Rregullore": ("rregullore", "decree"), "Udhëzime Administrative": ("udhezim", "decree"),
         "Ligje": ("ligj", "law"), "Kode": ("kod", "law"), "Marrëveshje ndërkombetare": ("marreveshje", "treaty"),
         "Dekretet e Presidentit": ("dekret", "decree"), "Vendime": ("vendim", "decree"),
         "Statuti": ("statut", "decree"), "Urdhëresa": ("urdhrese", "decree"), "Urdhër": ("urdher", "decree"),
         "Rregulla": ("rregulla", "decree"), "Deklarata dhe Rezoluta të Kuvendit": ("deklarate", "decree"),
         "Aktgjykime": ("aktgjykim", "court"), "Mendime": ("mendim", "court"), "Aktvendime": ("aktvendim", "decree")}
CHANGE = re.compile(r"NDRYSHIM|PLOTËSIM|PLOTESIM|SHFUQIZIM|AMENDAMENTIM", re.I)
NUM = re.compile(r"\bNR\s*\.?\s*([0-9]{1,4}\s*/\s*[0-9]{2,4}|[0-9]{2}\s*/\s*L\s*-\s*[0-9]+)", re.I)
KIND_WORD = re.compile(r"\b(UDH[ËE]ZIM\w*|RREGULLOR\w*|VENDIM\w*|LIGJ\w*|URDH[ËE]RES\w*|STATUT\w*|AKTVENDIM\w*|"
                       r"DEKRET\w*)\b", re.I)
SIGNED_ON = re.compile(r"n[eë]nshkrim|miratim", re.I)
AFTER_SIGNATURE = re.compile(r"\bpas\s+(?:n[eë]nshkrimit|miratimit)|after\s+(?:its\s+)?(?:signature|signing|adoption)", re.I)
# "hyn në fuqi në datën e publikimit / nga data e publikimit / në ditën e shpalljes në Gazetën Zyrtare"
ON_PUBLICATION = re.compile(r"hy\w*\s+n[eë]\s+fuqi\s+(?:n[eë]\s+|nga\s+)?(?:dat[eë]n?|dit[eë]n)\s+(?:e\s+)?"
                            r"(?:publikimit|shpalljes)\s+(?:s[eë]\s+saj\s+|t[eë]\s+tij\s+)?n[eë]\s+Gazet", re.I)
TITLE_DATE = re.compile(r"\bDAT[AËE]\s*[:.]?\s*(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})", re.I)
# A title the Gazette has annotated after a later act: "... (Shfuqizuar me Vendim të QRK, Nr. 02/50 ...)".
# The Gazette's links from an act to the later acts that change it ("Ndryshohet/Plotësohet nga", "Shfuqizuar nga");
# a whole repeal is "Shfuqizuar/Shfuqizohet nga" without "pjesërisht" (in part).
CHANGED_BY = re.compile(r"^\s*(?:Ndryshohet|Plotësohet|Plotesohet|Shfuqizohet|Shfuqizuar|Shtuar|Pezullohet|Pezulluar)\b"
                        r".*\bnga\b", re.I)
REPEALED_BY = re.compile(r"^\s*Shfuqizu(?:ar|het)\b(?!.*pjes)", re.I)
def PROMULGATED(law_kind: str, basis: str, words: str) -> bool:
    """2026-11-09: a law in force "pas miratimit nga Kuvendi ... dhe shpalljes nga PSSP-ja / Presidenti" (on adoption
    and promulgation, no date or period, no signature day named): dated by the Gazette day, as the first build dates
    its 111 such laws. A rule naming the signature ("në datën e nënshkrimit nga PSSP-ja") keeps the signature rules."""
    return (law_kind == "law" and basis.startswith("published (the act takes effect on promulgation")
            and bool(re.search(r"shpallj", words or "", re.I)) and not re.search(r"n[eë]nshkrim", words or "", re.I))


MARKED = re.compile(r"\(\s*(?:e\s+|i\s+)?(?:shfuqizuar|ndryshuar|plot[eë]suar|pezulluar)\b", re.I)
# Applied to every act: a period run from registration with the ministry or from publication on the municipality's
# website or notice board (days the Gazette doesn't give), or N days after adoption.
OFF_GAZETTE = re.compile(r"regjistrim|rexhistrim|\bueb|\bweb|\bveb|tabel[eë]n\s+e\s+shpalljeve|protokoll|certifik|"
                         r"dit[eë]\s+pas\s+(?:dit[eë]s\s+s[eë]\s+)?(?:miratimit|aprovimit)|fillon\s+t[eë]\s+zbatohet",
                         re.I)


def _after_verb(words: str) -> str:
    """The in-force sentence from its verb on ("hyn në fuqi ..."), or '' when it has none."""
    m = re.search(r"\bhy(?:n|në|ne|jë|je|rë|re)\s+n[eë]\s+fuqi\b", words, re.I)
    return words[m.start():] if m else ""


OTHER_EVENT = re.compile(r"regjistrim|rexhistrim|\bueb|\bweb|\bveb|tabel[eë]n|protokoll|certifik|kuvend|asamble|"
                         r"miratim|aprovim", re.I)

# In-force wordings read by more_rules (added after the first acts were published; applied only to acts the rules
# above leave unread). "Publication in the Official Gazette" in its usual forms ("shpaIljes" is a common misprint).
_IN_GAZETTE = (r"(?:publikimit|shpa[lI][lI]jes|botimit)(?:\s+(?:s[eë]|t[eë])\s+(?:saj|tij))?\s+n[eë]\s+"
               r"[“\"]?Gazet[eë]n[”\"]?\s+Zyrtare")
# Any period in an in-force sentence ("7 (shtatë) ditë", "shtatë (7) ditë", "15 ditë", "gjashtë muaj")
ANY_PERIOD = re.compile(r"(?:\d+|\b[a-zë]+\s*\(\s*\d+\s*\))\s*(?:\(\s*[a-zë]+\s*\)\s*)?(?:dit|muaj|vit)", re.I)
_VERB = r"\bhy(?:n|në|ne|jë|je|rë|re)\s+n[eë]\s+fuqi\s+"   # the verb, not the heading "Hyrja në fuqi"
ON_GAZETTE = re.compile(_VERB + r"(?:(?:n[eë]|nga|me)\s+)?(?:dit[eë]n|dat[eë]n|data|momentin)\s+(?:e\s+)?"
                        + _IN_GAZETTE, re.I)
AFTER_GAZETTE = re.compile(_VERB + r"pas\s+" + _IN_GAZETTE, re.I)
# "7 (shtatë) ditë pas publikimit në Gazetën Zyrtare": ks_inforce reads "shtatë (7) ditë" but not this order
PERIOD_GAZETTE = re.compile(_VERB + r"(\d{1,3})\s*\(\s*[a-zëç]+\s*\)\s*(dit|muaj)[a-zë]*\s+(?:pas|nga\s+dita\s+e)\s+"
                            + _IN_GAZETTE, re.I)
ON_ADOPTION = re.compile(_VERB + r"(?:n[eë]\s+|nga\s+)?(?:dit[eë]n|dita)\s+e\s+(?:aprovimit|miratimit)\b", re.I)
ADOPTED_DATE = re.compile(r"\b(?:miratohet|miratuar|aprovohet|aprovuar)\b[^.]{0,100}?\b(?:me|më|n[eë])\s+"
                          r"(?:dt\.?|dat[eë]n?)\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)


def more_rules(words: str, published: str) -> tuple[str, str] | None:
    """(day, basis) for in-force wordings the rules above don't read, or None (the act stays held):
    on publication in the Official Gazette ("në ditën e shpalljes së tij në Gazetën Zyrtare", "në momentin e
    publikimit në Gazetën Zyrtare", "pas publikimit në Gazetën Zyrtare"); "N (word) days/months after publication in
    the Official Gazette"; "on the day of adoption" when the act itself gives the adoption date. A sentence with an
    exception or a second entry into force is left unread."""
    from datetime import date, timedelta
    w = ks_inforce.norm(words)
    if len(re.findall(_VERB, w + " ", re.I)) != 1 or re.search(r"p[eë]rjashtim|p[eë]rve[cç]", w, re.I):
        return None
    if ON_GAZETTE.search(w) or AFTER_GAZETTE.search(w):
        return published, "on publication"
    m = PERIOD_GAZETTE.search(w)
    if m:
        n, pub = int(m.group(1)), date.fromisoformat(published)
        if m.group(2).lower() == "dit":
            return (pub + timedelta(days=n)).isoformat(), f"day {n} after publication"
        return ks_inforce.add_months(pub, n).isoformat(), f"{n} month(s) after publication"
    if ON_ADOPTION.search(w):
        a = ADOPTED_DATE.search(w)
        if a:
            try:
                day = date(int(a.group(3)), int(a.group(2)), int(a.group(1))).isoformat()
            except ValueError:
                return None
            if str(int(published[:4]) - 1) <= day[:4] and day <= published:
                return day, "on adoption (the adoption date the act gives)"
    return None


SIG_PERIOD = re.compile(_VERB + r"(?:(\d{1,3})\s*\(\s*[a-zë]+\s*\)|[a-zë]+\s*\(\s*(\d{1,3})\s*\)|(\d{1,3})\.?|([a-zë]+))"
                        r"\s*(dit|muaj)[a-zë]*\s+pas\s+n[eë]nshkrimit", re.I)
SIG_DATE = re.compile(r"\b(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})\b|\b(\d{1,2})\s*[./]?\s*([a-zë]{3,})\s*[./]?\s*(\d{4})\b",
                      re.I)


def after_signature(words: str, tail: list, title: str, published: str) -> tuple[str, str] | None:
    """(day, basis) for "N days (months) after signature" when the act prints its signature day: the date in its
    title ("... DATË 12.05.2014"), else the only date printed in the signature block right after the in-force sentence
    (a short block with no other sentence in it). None (held) otherwise."""
    from datetime import date, timedelta
    w = ks_inforce.norm(words)
    if len(re.findall(_VERB, w + " ", re.I)) != 1 or re.search(r"p[eë]rjashtim|p[eë]rve[cç]", w, re.I):
        return None
    m = SIG_PERIOD.search(w)
    if not m or re.search(r"n[eë]nshkrimit[^.]*\b(?:dhe|e|ose)\s+(?:pas\s+)?(?:publikimit|shpalljes|botimit)", w, re.I):
        return None   # "N days after signature and publication": counted from the later of the two, held
    n = int(m.group(1) or m.group(2) or m.group(3) or 0) or ks_inforce.WORDS.get((m.group(4) or "").lower(), 0)
    if not n:
        return None
    t = TITLE_DATE.search(title)
    if t:
        days = {(int(t.group(3)), int(t.group(2)), int(t.group(1)))}
        how = "the date in the act's title"
    else:
        block = ks_inforce.norm(" ".join(tail))
        end = ks_inforce.norm(words)[-40:]
        if end not in block:
            return None
        block = block[block.rfind(end) + len(end):]
        if len(block) > 300 or re.search(r"miratu|vendim|\bneni\b|" + _VERB, block + " ", re.I):
            return None
        days = set()
        for d in SIG_DATE.finditer(block):
            if d.group(1):
                days.add((int(d.group(3)), int(d.group(2)), int(d.group(1))))
            elif ks_inforce.month(d.group(5)):
                days.add((int(d.group(6)), ks_inforce.month(d.group(5)), int(d.group(4))))
            else:
                return None
        how = "the date printed with the signature"
    if len(days) != 1:
        return None
    try:
        sig = date(*days.pop())
    except ValueError:
        return None
    pub = date.fromisoformat(published)
    if not (pub - timedelta(days=366) <= sig <= pub):
        return None
    if m.group(5).lower() == "dit":
        return (sig + timedelta(days=n)).isoformat(), f"day {n} after signature ({how}, {sig.isoformat()})"
    return ks_inforce.add_months(sig, n).isoformat(), f"{n} month(s) after signature ({how}, {sig.isoformat()})"


# ---------------------------------------------------------------- 2026-11-11 rules (each only where the above hold)
# The text layer of some recognised scans prints 'ë' as 'é' or '€' (Albanian writes neither): the in-force sentence is
# read from a copy with those letters taken for 'ë'; the text itself is published as printed.
OCR_E = str.maketrans({"é": "ë", "É": "Ë", "€": "ë"})


def letters_rule(paras: list) -> tuple[str, dict]:
    """(in-force sentence, {"letters": True, "all": every in-force sentence, "fixed": the read copy}) or ('', {})."""
    fixed = [p.translate(OCR_E) for p in paras]
    if fixed == paras:
        return "", {}
    rule = ks_inforce.rule_of(fixed)
    if not rule:
        return "", {}
    text = ks_inforce.norm(" ".join(fixed))
    hits = [x[:600] for x in re.split(r"(?<=[.;])\s+(?=[A-ZËÇ0-9])", text) if ks_inforce.VERB.search(x)]
    return rule, {"letters": True, "all": hits[:40], "fixed": fixed}


def after_rule(paras: list, rule: str) -> list:
    """The paragraphs printed after the in-force sentence (the first one is the rest of its own paragraph)."""
    if not rule:
        return []
    end = ks_inforce.norm(rule)[-40:]
    joined = "\n".join(ks_inforce.norm(p) for p in paras)
    pos = joined.replace("\n", " ").rfind(end)
    if pos < 0:
        return []
    return [x[:300] for x in joined[pos + len(end):].split("\n")[:8]]


SIG_ANY = re.compile(r"\b(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})\b|\b(\d{1,2})\s*\.?\s*([a-zë]{3,})\s*[,.]?\s*(\d{4})\b",
                     re.I)
SIG_STOP = re.compile(r"^\s*(?:Article|Član|Člen|Члан|Neni|Aneks|Annex|Shtojc|Prilog|Tabel|Kopj|Tu?\s+d[eë]rgohet|"
                      r"Ju\s+d[eë]rgohet)", re.I)
SIG_SENTENCE = re.compile(r"shfuqiz|\bnen[ie]t?\b|\bligj|udh[eë]zim|rregullor|vendim|marr[eë]veshj|\bdat[eë]s\b|"
                          r"\bhy\w*\s+n[eë]\s+fuqi", re.I)


def sig_date(after: list, published: str):
    """The signature day printed in the signature block right after the in-force sentence: the one date (12.05.2014,
    12/05/2014, 12 maj 2014) in its short lines (a name, a title, a place), read up to the first line that starts an
    article, annex or distribution list, is in English or Serbian, or is another sentence; within the year before
    publication. None when there is no such date or more than one."""
    from datetime import date, timedelta
    days = set()
    for k, p in enumerate(after):
        if not p.strip():
            continue
        if SIG_STOP.search(p) or (k and lang_of(p, minimum=3) in ("en", "sr")) or foreign_letters(p):
            break
        if len(p) > 150 or SIG_SENTENCE.search(p):
            if k == 0:
                continue   # the rest of the in-force paragraph: another sentence, not the signature
            break
        for m in SIG_ANY.finditer(p):
            if m.group(1):
                days.add((int(m.group(3)), int(m.group(2)), int(m.group(1))))
            elif ks_inforce.month(m.group(5)):
                days.add((int(m.group(6)), ks_inforce.month(m.group(5)), int(m.group(4))))
    if len(days) != 1:
        return None
    try:
        sig = date(*days.pop())
    except ValueError:
        return None
    pub = date.fromisoformat(published)
    return sig if pub - timedelta(days=366) <= sig <= pub else None


# "Datë: 20.05.2016" / "DATA: ..." / "Date: ..." (folded); not "e datës ..." (of the date of another act)
HEAD_DATE = re.compile(r"\bDAT[AE]\b\s*[:.]?\s*(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})\b")


HEAD_KIND = {"rregullore": r"rregullor", "udhezim": r"udh[eë]zim|\bUA\b", "vendim": r"vendim", "dekret": r"dekret",
             "statut": r"statut", "urdher": r"urdh[eë]r", "urdhrese": r"urdh[eë]res", "rregulla": r"rregull"}


def head_date(info: dict, published: str, words: str = "", kind: str = "", title: str = ""):
    """The act's own date at its head ("Nr. 01/88 Datë: 20.05.2016"), for an act in force on signature that prints
    no date with the signature: one distinct "Datë:" date in its first lines, none at all in or after the in-force
    sentence; the sentence names the act's own kind ("Ky udhëzim ...", not an annexed "Kjo Marrëveshje ...") and has
    no list or exception in it; the date is not before the year in the act's number and within the year before
    publication. None otherwise."""
    from datetime import date, timedelta
    w = ks_inforce.norm(words)
    v = re.search(_VERB, w + " ", re.I)
    if (not v or kind not in HEAD_KIND or not re.search(HEAD_KIND[kind], w[:v.start()], re.I)
            or len(re.findall(_VERB, w + " ", re.I)) != 1 or re.search(r"\b[a-e]\)|p[eë]rjashtim|p[eë]rve[cç]", w, re.I)
            or SIG_ANY.search(w) or any(SIG_ANY.search(p) for p in info.get("after", []))):
        return None
    days = {(int(m.group(3)), int(m.group(2)), int(m.group(1))) for m in HEAD_DATE.finditer(fold(info.get("head", "")))}
    if len(days) != 1:
        return None
    try:
        sig = date(*days.pop())
    except ValueError:
        return None
    pub = date.fromisoformat(published)
    n = NUM.search(fold(title))
    year = re.search(r"/\s*((?:19|20)\d\d)$", n.group(1)) if n else None
    if year and sig.year < int(year.group(1)):
        return None
    return sig if pub - timedelta(days=366) <= sig <= pub else None


def after_signature_block(words: str, after: list, published: str) -> tuple[str, str] | None:
    """after_signature for acts it leaves held, with the signature day read by sig_date."""
    from datetime import timedelta
    w = ks_inforce.norm(words)
    if len(re.findall(_VERB, w + " ", re.I)) != 1 or re.search(r"p[eë]rjashtim|p[eë]rve[cç]", w, re.I):
        return None
    m = SIG_PERIOD.search(w)
    if not m or re.search(r"n[eë]nshkrimit[^.]*\b(?:dhe|e|ose)\s+(?:pas\s+)?(?:publikimit|shpalljes|botimit)", w, re.I):
        return None
    n = int(m.group(1) or m.group(2) or m.group(3) or 0) or ks_inforce.WORDS.get((m.group(4) or "").lower(), 0)
    sig = sig_date(after, published) if n else None
    if not sig:
        return None
    how = "the date printed with the signature"
    if m.group(5).lower() == "dit":
        return (sig + timedelta(days=n)).isoformat(), f"day {n} after signature ({how}, {sig.isoformat()})"
    return ks_inforce.add_months(sig, n).isoformat(), f"{n} month(s) after signature ({how}, {sig.isoformat()})"


# The Constitutional Court's decisions take effect on publication in the Official Gazette unless the Court sets another
# day (Law No. 03/L-121 on the Constitutional Court, art. 20(5), in force since 2009-01-15); a judge's separate
# opinion has no entry into force of its own.
COURT = "Gjykata Kushtetuese"
COURT_DECISION = ("on publication (Law No. 03/L-121 on the Constitutional Court, art. 20(5): a decision takes effect on "
                  "the day of its publication in the Official Gazette unless the Court sets another day; no in-force "
                  "sentence is read in this decision)")
COURT_OPINION = ("published (a judge's separate opinion: it has no entry into force of its own; the Official Gazette "
                 "date is used)")
DAILY = re.compile(r"\bditor|informimit|\bmedia|\bueb|\bweb|tabel[eë]n|\bt\w{0,2}azh", re.I)


def published_twice(words: str) -> bool:
    """An in-force sentence counting from publication in the Official Gazette and somewhere else too ("... dhe
    publikimit të tij në njërën nga gazetat me tirazh të madh"): the later day is not in the Gazette."""
    w = _after_verb(words)
    return bool(DAILY.search(w) or len(re.findall(r"ga[zi]et", w, re.I)) >= 2
                or len(re.findall(r"publikim|shpallj|botim", w, re.I)) >= 2)


def foreign_text(path: Path):
    """(units, in-force sentence, last four paragraphs, sha256, trailing image pages, 'en' | 'sr') for an act whose PDF
    is in English or Serbian only (Albanian common words at most 5% of that language's, the other at most 10%, no
    page image inside the text), or None. English files follow the first build's en/ names (preamble, article-NNN,
    signature) when its articles number cleanly; otherwise, and for Serbian, the whole text is one file (text)."""
    doc = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    if doc.get("no_pdf") or not doc.get("pages"):
        return None
    flags = [bool(p.get("scanned")) for p in doc["pages"]]
    n_text = len(flags) - flags[::-1].index(False) if False in flags else 0
    if n_text == 0 or any(flags[:n_text]):
        return None
    s = lang_scores(" ".join(l[6] for p in doc["pages"] for l in _body(p)))
    lang = max(("en", "sr"), key=lambda k: s[k])
    other = "sr" if lang == "en" else "en"
    if s[lang] < 30 or s["sq"] > 0.05 * s[lang] or s[other] > 0.1 * s[lang]:
        return None
    paras = ks_text.paragraphs(ks_text.pdf_lines(doc), "en")
    if not paras:
        return None
    units = {}
    st = ks_text.structure(paras, "en") if lang == "en" else None
    if st and not st["gaps"] and not st["notes"] and st["articles"] and not st["body"]:
        if st["preamble"]:
            units["preamble"] = {"label": "Preamble", "kind": "preamble", "text": "\n".join(st["preamble"]) + "\n"}
        for n, lines in st["articles"]:
            units[f"article-{n:03d}"] = {"label": f"Article {n}", "kind": "art", "text": "\n".join(lines) + "\n"}
        if st["signature"]:
            units["signature"] = {"label": "Signature", "kind": "signature", "text": "\n".join(st["signature"]) + "\n"}
    else:
        units["text"] = {"label": "Text", "kind": "text", "text": "\n".join(paras) + "\n"}
    rule = ks_inforce.rule_of(paras)
    return units, rule, paras[-4:], doc["sha256"], len(flags) - n_text, lang


_ISSUER: dict[int, str] = {}


def issuer(src: Path, i: int) -> str:
    """The issuing institution on act i's Gazette page ('' when the page is not in the local copy)."""
    if i not in _ISSUER:
        f = src / "act" / str(i // 1000) / str(i) / "detail.html.gz"
        _ISSUER[i] = (span(gzip.decompress(f.read_bytes()).decode("utf-8", "replace"), "lblDInstSpons")
                      if f.exists() else "")
    return _ISSUER[i]


class Hold(Exception):
    pass


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).upper()


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def span(page: str, ident: str) -> str:
    m = re.search(rf'id="MainContent_{ident}"[^>]*>(.*?)</(?:span|a)>', page, re.S)
    return clean(m.group(1)) if m else ""


def dmy(s: str) -> str:
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""


def detail(page: str) -> dict:
    m = re.search(r'id="MainContent_rAktet_lblAn_0"[^>]*>(.*?)</a>', page, re.S)
    gz = re.search(r'id="MainContent_lblDGZK" href="OfficialGazetteDetail\.aspx\?GZID=(\d+)">(.*?)</a>', page, re.S)
    out = {"title": clean(m.group(1)) if m else span(page, "lblActName"),
           "category": span(page, "lblDActCategoryName_1"), "number": span(page, "lblDActNo"),
           "institution": span(page, "lblDInstSpons"), "status": span(page, "lblAct_Ne_Fuqi_Txt"),
           "published": dmy(span(page, "lblDPubDate")), "gazette": clean(gz.group(2)) if gz else "", "related": []}
    i = page.find('id="MainContent_drActRelated"')
    j = page.find('id="MainContent_drSubNormAct"')
    part = page[i:j if j > i else len(page)] if i >= 0 else ""
    for box in re.findall(r'<div class="act_link_box_1">(.*?)<!--fund act_link_box-->', part, re.S):
        rel = re.search(r'<span class="span_margin" style="[^"]*">(.*?)</span>', box, re.S)
        link = re.search(r'href="ActDetail\.aspx\?ActID=(\d+)"[^>]*>(.*?)</a>', box, re.S)
        if link:
            pub = re.search(r'lblRPubDate_\d+">[^<]*</span>\s*([0-9.]+)', box)
            out["related"].append({"relation": clean(rel.group(1)) if rel else "", "id": int(link.group(1)),
                                   "title": clean(link.group(2)), "published": dmy(pub.group(1)) if pub else ""})
    out["by_later"] = bool(re.search(r"(?:Ndryshohet|Plotësohet|Shfuqizohet|Shfuqizuar)[^<]{0,40}nga", page, re.I))
    return out


def ref_keys(title: str) -> set[tuple[str, str]]:
    """(kind stem, number) of every act a title names after its own kind word: 'NDRYSHIMIN E UDHËZIMIT ADMINISTRATIV
    (Shëndetësi) NR. 05/2023' -> ('UDHEZIM', '05/2023')."""
    out = set()
    t = fold(title)
    for m in KIND_WORD.finditer(t):
        k = _key(t, m)
        if k:
            out.add(k)
    return out


def _key(t: str, m: re.Match) -> tuple[str, str, str] | None:
    """(kind stem, number, institution acronym or '') for the kind word at m: '... (MF) NR. 01/2026'."""
    n = NUM.search(t, m.end(), m.end() + 80)
    if not n:
        return None
    acr = re.search(r"\(\s*([A-Z]{1,8})\s*\)", t[m.end():n.start()])
    return (m.group(1)[:6], re.sub(r"\s+", "", n.group(1)), acr.group(1) if acr else "")


def own_key(title: str) -> tuple[str, str, str] | None:
    t = fold(title)
    m = KIND_WORD.search(t)
    return _key(t, m) if m else None


def named_by(named: dict, k: tuple[str, str, str]) -> set[int]:
    """Acts whose titles name this one: same kind and number, and the same institution where both give one."""
    out: set[int] = set()
    for (kind, num, acr), ids in named.get((k[0], k[1]), {}).items():
        if not acr or not k[2] or acr == k[2]:
            out |= ids
    return out


SELF = hashlib.sha256(Path(__file__).read_bytes() + (HERE / "ks_text.py").read_bytes()
                      + (HERE / "ks_inforce.py").read_bytes()).hexdigest()[:16]


MULTI = re.compile(r"shall\s+(?:enter|come)\s+into\s+force|stupa\s+na\s+snagu|^(?:Article|Član|Člen)\s+\d+\b", re.M | re.I)
# Holds that a PDF printing the Albanian text beside or after its English and Serbian translations can cause: such a
# file is read again from its Albanian column or pages alone (albanian_part).
CUTTABLE = ("multilingual_pdf", "not_albanian", "article_gaps", "article_headings_irregular", "no_text")


def _read(doc: dict, amending: bool) -> tuple[dict, str, list, dict]:
    paras = ks_text.paragraphs(ks_text.pdf_lines(doc), "sq")
    if ks_text.language(paras) != "sq":
        raise Hold("not_albanian:" + ks_text.language(paras))
    st = ks_text.structure(paras, "sq", amending=amending)
    if st["gaps"]:
        raise Hold("article_gaps:" + ",".join(map(str, st["gaps"][:5])))
    if st["notes"]:
        raise Hold("article_headings_irregular")
    units = units_of(st)
    if not units:
        raise Hold("no_text")
    rule = ks_inforce.rule_of(paras)
    extra = {}
    if not rule:
        rule, extra = letters_rule(paras)   # 2026-11-11: 'ë' printed as 'é' / '€' in the text layer
    if MULTI.search("\n".join(paras)):
        raise Hold("multilingual_pdf")   # Albanian, English and Serbian texts in one file
    extra["after"] = after_rule(extra.pop("fixed", None) or paras, rule)
    extra["head"] = ks_inforce.norm(" ".join(paras[:12]))[:800]
    return units, rule, paras, extra


# 2026-11-11 (OCR lane): acts the Gazette publishes as page scans (held "scanned_pages") are read from
# ocr.json.gz (live/ocr_xk.py: Tesseract over the same PDF, same line schema) where it exists, only for the pages
# pdf.json.gz marks scanned and only for acts that hold would otherwise keep back (acts published from their text
# layer never change). Held instead when the OCR file reads another PDF than pdf.json.gz or fails its gate (mean word
# confidence, Albanian word rate). The version note and a Text-source trailer say the text was read by OCR.
OCR_DIR = __import__("os").environ.get("XK_OCR_DIR", "")   # trial parses only: read OCR results from this folder
OCR_SOURCE: dict[str, dict] = {}   # act id -> {"note", "trailer"} for the acts read_text read through OCR


def with_ocr(doc: dict, f: Path) -> tuple[dict, dict]:
    """(doc with its scanned pages replaced by the OCR lines, {"note", "trailer"}) or Hold. In an act whose other pages
    have a text layer, an image page where OCR found few words (gate "figures": a picture, a stamp page, an annex
    cover) is left out of the OCR gate; its words are given and the note says so."""
    o = json.loads(gzip.decompress(f.read_bytes()).decode("utf-8"))
    if o.get("sha256") != doc.get("sha256") or len(o.get("pages", [])) != len(doc["pages"]):
        raise Hold("ocr_pdf_changed")
    g = o.get("gate") or {}
    if not g.get("ok"):
        raise Hold(g.get("reason") or "ocr_gate_failed")
    figures = set(g.get("figures", []))
    pages, n = [], 0
    for k, (p, q) in enumerate(zip(doc["pages"], o["pages"]), 1):
        if p.get("scanned") and q.get("ocr"):
            turned = {"height": q["height"], "width": q["width"]} if q.get("rotate") else {}   # read turned
            pages.append(dict(p, scanned=False, lines=q["lines"], **turned))
            n += k not in figures
        else:
            pages.append(p)
    m = o["ocr"]
    ver = re.sub(r"^tesseract\s+v?", "", m.get("version", ""), flags=re.I).split(".2")[0]
    notes = []
    if n:
        conf = round(g["conf"])
        src = f"OCR (Tesseract {ver}, tessdata_best Latin; mean word confidence {conf}%)"
        notes.append(f"{n} of the PDF's {len(pages)} page(s) are printed only as images (the Gazette's scan is the "
                     f"official text): their text was read by OCR (Tesseract {ver}, tessdata_best Latin-script "
                     f"model; mean word confidence {conf}%) and may misread single characters; check the Gazette's PDF "
                     f"before relying on a figure.")
    else:
        src = f"text layer; {len(figures)} image page(s) with few words read by OCR (Tesseract {ver}, tessdata_best Latin)"
    if figures:
        notes.append(f"Page(s) {', '.join(map(str, sorted(figures)))} of the PDF are images with few words (a figure, "
                     f"a stamp page, an annex cover): the words OCR read on them are given here, the images are not "
                     f"reproduced.")
    dropped = int(g.get("dropped_lines", 0))
    trailers = [f"Text-source: {src}"]
    if dropped:
        notes.append(f"{dropped} line(s) OCR read on the image pages were left out as stamps, signatures, handwritten "
                     f"marks or other debris (read with low confidence, or a registry stamp): names under a "
                     f"signature may be missing.")
        trailers.append(f"OCR-dropped-lines: {dropped} (stamps, signatures, marks)")
    return dict(doc, pages=pages), {"note": " ".join(notes), "trailer": trailers[0], "trailers": trailers}


def read_text(path: Path, amending: bool, cache: dict | None, title: str = "") -> tuple[dict, str, list, str, int, str,
                                                                                           dict]:
    """(units, in-force sentence, last four paragraphs, sha256 of the PDF, trailing image pages, cut note) for one
    act's PDF text, or Hold. The cut note is '' unless the text is the Albanian part of a PDF that also prints the
    English and Serbian texts. Results are kept in `cache` keyed by the file's size and time and this parser's own
    hash: a cached run gives the same bytes."""
    stt = path.stat()
    tkey = hashlib.sha256(title.encode("utf-8")).hexdigest()[:8]
    key = f"{path.parent.name}|{stt.st_size}|{stt.st_mtime_ns}|{int(amending)}|{tkey}|{SELF}"
    ocr_file = path.parent / "ocr.json.gz"   # 2026-11-11 (OCR lane): page scans read by OCR (live/ocr_xk.py)
    if OCR_DIR:   # trial parses of OCR results not yet released (ocr_xk.py's own out folder)
        ocr_file = Path(OCR_DIR) / str(int(path.parent.name) // 1000) / f"{path.parent.name}.json.gz"
    if ocr_file.exists():
        so = ocr_file.stat()
        key += f"|ocr{so.st_size}-{so.st_mtime_ns}"
    OCR_SOURCE.pop(path.parent.name, None)
    if cache is not None and key in cache:
        r = cache[key]
        if "hold" in r:
            raise Hold(r["hold"])
        if r.get("ocr"):
            OCR_SOURCE[path.parent.name] = r["ocr"]
        return r["units"], r["rule"], r["tail"], r["sha"], r["scanned"], r.get("cut", ""), r.get("extra", {})
    cut, ocr = "", None
    try:
        doc = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        if doc.get("no_pdf") or not doc.get("pages"):
            raise Hold("no_pdf")
        flags = [bool(p.get("scanned")) for p in doc["pages"]]
        n_text = len(flags) - flags[::-1].index(False) if False in flags else 0
        if (n_text == 0 or any(flags[:n_text])) and ocr_file.exists():
            doc, ocr = with_ocr(doc, ocr_file)
            flags = [bool(p.get("scanned")) for p in doc["pages"]]
            n_text = len(flags) - flags[::-1].index(False) if False in flags else 0
        if n_text == 0 or any(flags[:n_text]):
            raise Hold("scanned_pages")   # a page image inside the text: words would be missing
        # page images after the text (an organigram, a scanned annex) are not transcribed; the note counts them
        scanned_tail = len(flags) - n_text
        try:
            units, rule, paras, extra = _read(doc, amending)
        except Hold as h:
            if not str(h).startswith(CUTTABLE):
                raise
            part = albanian_part({"sha256": doc["sha256"], "pages": doc["pages"][:n_text]}, title)
            if isinstance(part, str):
                raise Hold(f"{h}" if part == "single_language" else f"{h}|cut:{part}")
            try:
                units, rule, paras, extra = _read(part[0], amending)
            except Hold as h2:
                raise Hold(f"{h}|cut:{h2}")
            # the translations number their articles too: the Albanian text must end at the same article
            mine = max((int(k[5:]) for k in units if k.startswith("neni-")), default=0)
            if any(n != mine for n in part[2].values()):
                raise Hold(f"{h}|cut:article_count_{mine}_vs_{part[2]}")
            # and no English or Serbian may be left in it
            alltext = "\n".join(u["text"] for u in units.values())
            sc = lang_scores(alltext)
            if foreign_letters(alltext) > 2 or 15 * sc["en"] > sc["sq"] or any(
                    len(re.findall(r"\b(?:the|of|and|shall)\b", line, re.I)) >= 2 for line in alltext.splitlines()):
                raise Hold(f"{h}|cut:other_language_left_in_text")
            cut = part[1]
    except Hold as h:
        if cache is not None:
            cache[key] = {"hold": str(h)}
        raise
    if ocr:
        cut = (cut + " " + ocr["note"]).strip()
        OCR_SOURCE[path.parent.name] = ocr
    r = {"units": units, "rule": rule, "tail": paras[-4:], "sha": doc["sha256"], "scanned": scanned_tail}
    if cut:
        r["cut"] = cut
    if ocr:
        r["ocr"] = ocr
    r["extra"] = extra   # 2026-11-11: the signature block, the head, OCR-letter reading (see _read)
    if cache is not None:
        cache[key] = r
    return units, rule, paras[-4:], doc["sha256"], scanned_tail, cut, extra


# ------------------------------------------------------------------------------------------- the Albanian part
# Official PDFs of many sub-legal acts print the act in Albanian, English and Serbian, either side by side (columns,
# Albanian on the left) or one after another (whole pages). The Albanian part is taken only when its boundary is
# clean:
# - a column page has a gap no line crosses at the left column's edge (within 15 points of where it sits on the
#   other column pages): its left side reads as Albanian, its right side as English/Serbian;
# - any other page is in one language throughout (each text block too), or has too few words to tell and stands
#   between two Albanian pages; the Albanian ones are kept, the English/Serbian ones left out;
# - a first page of 25 lines or fewer not in one language (emblem and the act's title in each language) is the cover
#   page and is left out, only when the Albanian text gives the act's number again near its start.
# Anything else (a line running across the boundary, a page whose language is unclear) keeps the act held.

LANG_WORDS = {"sq": (" dhe ", " të ", " në ", " për ", " së ", " nga ", " ose ", " është "),
              "en": (" the ", " and ", " of ", " shall ", " to ", " or ", " is ", " for "),
              "sr": (" je ", " za ", " od ", " koji ", " ili ", " se ", " na ", " и ", " је ", " за ", " од ",
                     " или ", " се ", " на ")}
LANG_NAME = {"en": "English", "sr": "Serbian"}
OTHER_ARTICLE = re.compile(r"^\s*(Article|ARTICLE|Član|ČLAN|Člen|ČLEN|Члан|ЧЛАН)\s*(\d{1,3})\s*[.:]?\s*$")


def lang_scores(text: str) -> dict:
    t = " " + re.sub(r"\s+", " ", text.lower().replace("ё", "ë")) + " "
    return {k: sum(t.count(w) for w in ws) for k, ws in LANG_WORDS.items()}


def lang_of(text: str, minimum: int = 8, ratio: float = 3.0) -> str:
    """'sq', 'en' or 'sr' when one language clearly leads; '?' when unclear; '' when there are too few words."""
    s = lang_scores(text)
    order = sorted(s.values(), reverse=True)
    if order[0] < minimum:
        return ""
    return max(s, key=s.get) if order[0] >= ratio * max(order[1], 1) else "?"


def not_albanian(text: str, minimum: int = 8) -> str:
    """'' (too few words), 'yes' (English and/or Serbian, Albanian words under a third of theirs) or 'no'."""
    s = lang_scores(text)
    if max(s.values()) < minimum:
        return ""
    return "yes" if 3 * s["sq"] <= max(s["en"], s["sr"]) else "no"


def foreign_letters(text: str) -> int:
    """Letters of Serbian (Latin čćšžđ, Cyrillic) that Albanian doesn't use; 'ё' stands for 'ë' in many PDFs."""
    return len(re.findall(r"[čćšžđČĆŠŽĐ]", text)) + sum(1 for c in text if "Ѐ" <= c <= "ӿ" and c not in "ёЁ")


def _weak_albanian(text: str) -> bool:
    s = lang_scores(text)
    return s["sq"] > 0 and s["en"] == 0 and foreign_letters(text) == 0 and not re.search(
        r"\b(?:je|za|od|koji|ili|the|of|and|shall)\b", text, re.I)


def _header(l: list) -> bool:
    return bool(ks_text.HEADER.match(l[6])) and len(l[6]) < 200


def _body(p: dict) -> list:
    """The page's lines other than the gazette header and bare page numbers in the top or bottom margin."""
    return [l for l in p["lines"] if l[6].strip() and not _header(l)
            and not (ks_text.DIGITS.match(l[6]) and (l[1] > p["height"] - 90 or l[3] < 90))]


def _gaps(lines: list, gap: float = 1.5) -> list[tuple[float, float]]:
    """(start, end) of each horizontal gap that no line crosses, between stretches covered by text."""
    out, right = [], None
    for x0, x1 in sorted((l[0], l[2]) for l in lines):
        if right is not None and x0 > right + gap:
            out.append((right, x0))
        right = x1 if right is None else max(right, x1)
    return out


def _left_edge(pages: list) -> float | None:
    """Where the left column ends: the first gap of pages whose text falls into 2 or 3 stretches of 5+ lines each
    (3 preferred), taken where most of them put it (within 15 points)."""
    import statistics
    firsts: dict[int, list[float]] = {2: [], 3: []}
    for p in pages:
        body = _body(p)
        gaps = _gaps(body)
        if len(gaps) not in (1, 2):
            continue
        edges = [-1e9] + [(a + b) / 2 for a, b in gaps] + [1e9]
        if all(sum(1 for l in body if edges[k] <= l[0] and l[2] <= edges[k + 1]) >= 5 for k in range(len(gaps) + 1)):
            firsts[len(gaps) + 1].append(sum(gaps[0]) / 2)
    found = firsts[3] or firsts[2]
    if not found:
        return None
    clusters: list[list[float]] = []
    for g in sorted(found):
        if clusters and g - clusters[-1][-1] <= 15:
            clusters[-1].append(g)
        else:
            clusters.append([g])
    best = max(clusters, key=len)
    return statistics.median(best) if max(best) - min(best) <= 30 else None


def albanian_part(doc: dict, title: str) -> tuple[dict, str, dict] | str:
    """(a copy of doc holding only the Albanian column / pages, a note saying what was taken, {language: highest
    article number heading a line of the text left out}) or the reason the Albanian part can't be cut cleanly
    ('single_language' when the file is not laid out in several languages)."""
    pages = doc["pages"]
    edge = _left_edge(pages)
    kinds: list[tuple[str, object]] = []   # per page with text: ("col", left lines) / ("sq"|"en"|"sr"|"few"|"cover", None)
    left_text, right_text = [], []
    first_text = next((k for k, p in enumerate(pages) if _body(p)), None)
    for k, p in enumerate(pages):
        body = _body(p)
        if not body:
            kinds.append(("blank", None))
            continue
        cut, gap = None, False
        if edge is not None:
            near = [g for g in _gaps(body) if abs((g[0] + g[1]) / 2 - edge) <= 15]
            if near:
                cut, gap = (near[0][0] + near[0][1]) / 2, True
            elif all(l[2] <= edge + 3 or l[0] >= edge - 3 for l in body):
                cut = edge   # no line reaches across the edge (text on one side only, or a gap there too narrow)
        if cut is not None:
            left = [l for l in body if l[2] <= cut + 3]
            right = [l for l in body if l[2] > cut + 3]
            lt, rt = " ".join(l[6] for l in left), " ".join(l[6] for l in right)
            ll = lang_of(lt)
            if ll not in ("sq", ""):
                return f"page_{k + 1}_left_language_{ll}"
            if not_albanian(rt) == "no":
                return f"page_{k + 1}_right_side_albanian"
            # Too few words on the left to tell its language: taken only beside text on the right, with an Albanian
            # word and no English or Serbian one in it (a full-width table in English or Serbian can fall on one side
            # of the edge); with no gap at the edge, the left side must read as Albanian outright.
            if left and ll == "" and (not gap or not right or not _weak_albanian(lt)):
                cut = None
        if cut is not None:
            left_text.append(lt)
            right_text.append(rt)
            # the gazette header stays (the reader drops it, and the running title printed under it)
            ids = {id(l) for l in left}
            kinds.append(("col", [l for l in p["lines"] if _header(l) or id(l) in ids]))
            continue
        lg = lang_of(" ".join(l[6] for l in body))
        blocks = defaultdict(list)
        for l in body:
            blocks[l[7]].append(l[6])
        blg = {lang_of(" ".join(b)) for b in blocks.values()} - {""}
        clean = lg in ("en", "sr", "sq") and blg <= {lg}
        if k == first_text and len(body) <= 25 and not clean:
            kinds.append(("cover", None))
        elif clean:
            kinds.append((lg, None))
        elif lg == "" and not blg:
            kinds.append(("few", None))
        else:
            return f"page_{k + 1}_language_{lg or 'mixed_blocks'}"
    content = [x for x, _ in kinds if x not in ("blank", "cover")]
    if not any(x == "col" for x in content) and not ({"en", "sr"} & set(content) and "sq" in content):
        return "single_language"
    # a page with too few words to tell is kept only between two Albanian pages
    seq = [(k, x) for k, (x, _) in enumerate(kinds) if x not in ("blank", "cover")]
    for n, (k, x) in enumerate(seq):
        if x == "few" and not (0 < n < len(seq) - 1 and seq[n - 1][1] == "sq" and seq[n + 1][1] == "sq"):
            return f"page_{k + 1}_language_few_words"
    out_pages, others, dropped_lines = [], set(), []
    for (x, left), p in zip(kinds, pages):
        if x == "col":
            out_pages.append(dict(p, lines=left))
            ids = {id(l) for l in left}
            dropped_lines += [l[6] for l in _body(p) if id(l) not in ids]
        elif x in ("sq", "few"):
            out_pages.append(p)
        elif x in ("en", "sr"):
            others.add(x)
            dropped_lines += [l[6] for l in _body(p)]
    # the highest article number heading a line in the left-out English / Serbian text
    numbered: dict[str, int] = {}
    for t in dropped_lines:
        m = OTHER_ARTICLE.match(t)
        if m:
            lg = "en" if m.group(1).lower().startswith("art") else "sr"
            numbered[lg] = max(numbered.get(lg, 0), int(m.group(2)))
    cols = sum(1 for x in content if x == "col")
    if cols:
        lt, rt = " ".join(left_text), " ".join(right_text)
        if lang_of(lt, minimum=20) != "sq":
            return f"left_column_language_{lang_of(lt, minimum=20) or 'few_words'}"
        if not_albanian(rt, minimum=20) != "yes":
            return f"right_columns_albanian_{not_albanian(rt, minimum=20) or 'few_words'}"
        s = lang_scores(rt)
        others |= {x for x in ("en", "sr") if s[x] >= 10 and s[x] >= 0.25 * max(s["en"], s["sr"])}
        if len(re.findall(r"[čćšžđČĆŠŽĐЀ-ӿ]", rt)) >= 20:   # letters of Serbian, not of Albanian or English
            others.add("sr")
    names = " and ".join(LANG_NAME[x] for x in ("en", "sr") if x in others)
    dropped = sum(1 for x in content if x in ("en", "sr"))
    cover = any(x == "cover" for x, _ in kinds)
    if cover:
        # the cover is left out only when the Albanian text gives the act's title (its number) again near its start
        head = fold(" ".join(l[6] for p in out_pages[:2] for l in p["lines"][:80]))
        n = NUM.search(fold(title))
        want = re.sub(r"\s+", "", n.group(1)) if n else ""
        if not want or want not in re.sub(r"\s+", "", head):
            return "cover_title_not_repeated"
    if cols:
        note = (f"The PDF prints the act in Albanian and {names} side by side; this text is its Albanian column"
                + (f", with its {len(content) - cols - dropped} page(s) printed in Albanian only"
                   if len(content) - cols - dropped else "")
                + (f", without its {dropped} page(s) printed in another language only" if dropped else "")
                + (", without the cover page, which gives the act's title in each language" if cover else "") + ".")
    else:
        note = (f"The PDF prints the act in Albanian, then in {names}; this text is its Albanian pages "
                f"({len(out_pages)} of {len(content) + int(cover)})"
                + (", without the cover page, which gives the act's title in each language" if cover else "") + ".")
    return {"sha256": doc["sha256"], "pages": out_pages}, note, numbered


def units_of(st: dict) -> dict:
    u = {}
    if st["body"]:
        u["teksti"] = {"label": "Teksti", "kind": "text", "text": "\n".join(st["body"]) + "\n"}
        return u
    if st["preamble"]:
        u["hyrje"] = {"label": "Hyrje", "kind": "preamble", "text": "\n".join(st["preamble"]) + "\n"}
    for n, lines in st["articles"]:
        key = f"neni-{n:03d}"
        if key in u:
            raise Hold(f"duplicate_article:{n}")
        u[key] = {"label": f"Neni {n}", "kind": "art", "text": "\n".join(lines) + "\n"}
    if st["signature"]:
        u["nenshkrimi"] = {"label": "Nënshkrimi", "kind": "signature", "text": "\n".join(st["signature"]) + "\n"}
    return u


def replace(tmp: Path, f: Path) -> None:
    """Atomic rename; a reader holding the old file open (Windows) gets a few seconds to let go."""
    import time
    for k in range(20):
        try:
            tmp.replace(f)
            return
        except PermissionError:
            if k == 19:
                raise
            time.sleep(0.5)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--retrieved", required=True, help="the day the inputs were retrieved (YYYY-MM-DD)")
    ap.add_argument("--exclude", help="file of Gazette act ids already in the repository (one per line)")
    ap.add_argument("--report")
    ap.add_argument("--rejects", help="JSON {id: reason}: acts held back by hand or by a failed read-back check")
    ap.add_argument("--kept", help="JSON {id: note}: acts published before the in-force checks on periods counted "
                                   "outside the Gazette were added, kept as published by decision")
    ap.add_argument("--out", help="folder for the parts (default: corpus.d next to this file)")
    ap.add_argument("--cache", help="optional .json.gz file keeping each PDF's parsed text between runs")
    a = ap.parse_args()
    src = Path(a.src)
    exclude = set(Path(a.exclude).read_text().split()) if a.exclude and Path(a.exclude).exists() else set()
    rejects = json.loads(Path(a.rejects).read_text(encoding="utf-8")) if a.rejects and Path(a.rejects).exists() else {}
    kept = set(json.loads(Path(a.kept).read_text(encoding="utf-8"))) if a.kept and Path(a.kept).exists() else set()
    cache = None
    if a.cache:
        try:
            cache = json.loads(gzip.decompress(Path(a.cache).read_bytes()).decode("utf-8"))
        except (OSError, ValueError, EOFError):
            cache = {}

    named: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(set))
    listed: dict[int, tuple[str, str]] = {}   # every listed act: (title, publication day)
    for f in sorted((src / "list").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            listed[int(r["id"])] = (r["title"], dmy(r.get("published") or ""))
            if CHANGE.search(fold(r["title"])):
                own = own_key(r["title"])
                for k in ref_keys(r["title"]):
                    if k != own:
                        named[(k[0], k[1])][k].add(int(r["id"]))

    parts: dict[str, dict] = defaultdict(lambda: {"laws": {}, "acts": []})
    holds = []
    ids = sorted(int(p.parent.name) for p in (src / "act").glob("*/*/pdf.json.gz"))
    for i in ids:
        if str(i) in exclude:
            continue
        d = {"title": ""}
        try:
            base = src / "act" / str(i // 1000) / str(i)
            d = detail(gzip.decompress((base / "detail.html.gz").read_bytes()).decode("utf-8", "replace"))
            if str(i) in rejects:
                raise Hold("rejected:" + str(rejects[str(i)])[:200])
            # 2026-11-09 (Romania standard): an act the Gazette links as amended, supplemented or repealed by a later
            # act is published as enacted and labelled (was: held back): "amended, not consolidated" with the
            # changing acts, or "repealed, not consolidated" when one of them repeals it whole or its page marks it
            # repealed. Its text is the act as enacted; the changes are not applied.
            changers = sorted((r for r in d["related"] if CHANGED_BY.match(r["relation"])),
                              key=lambda r: (r["published"] or "9999", r["id"]))
            if d["by_later"] and not changers:
                raise Hold("amended_or_repealed_on_gazette_unlinked")
            # the Gazette also annotates a title: "... (Shfuqizuar me Vendim të QRK, Nr. 02/50 të datës 23.12.2021)"
            noted = re.search(r"\(\s*(?:e\s+|i\s+)?(?:shfuqizuar|ndryshuar|plot[eë]suar|pezulluar)\b[^()]*\)?",
                              d["title"], re.I)
            repealed = ("shfuqiz" in d["status"].lower() or any(REPEALED_BY.match(r["relation"]) for r in changers)
                        or bool(noted and re.search(r"shfuqizuar", noted.group(0), re.I)
                                and not re.search(r"pjes", noted.group(0), re.I)))
            marks = {}
            if changers or repealed or noted:
                marks = {"label": "repealed, not consolidated" if repealed else "amended, not consolidated",
                         "amended_by": [{"ref": f"gzk:{r['id']}", "title": r["title"], "url": DETAIL.format(id=r["id"]),
                                         "date": r["published"] or None, "relation": r["relation"]} for r in changers]
                         + ([{"ref": "gzk-title", "title": f"the Gazette's note in the act's title: {noted.group(0)}",
                              "url": DETAIL.format(id=i), "date": None, "relation": "noted in the title"}]
                            if noted and not changers else [])}
            if d["category"] not in KINDS:
                raise Hold("kind_not_built:" + d["category"])
            kind, law_kind = KINDS[d["category"]]
            k = own_key(d["title"])
            others = (named_by(named, k) - {i}) if k else set()
            # 2026-11-11: numbers repeat across issuers ("NR. 01/2017" of the MAPL, the AAC, the KHAIA): a naming act
            # counts only when its Gazette page names the same issuing institution as this act's page
            others = {o for o in others if d["institution"] and issuer(src, o) == d["institution"]}
            # 2026-11-10: the act's own key must be its own kind and number (the title starts with its kind word);
            # a court decision's title names the act it reviews ("... VLERËSIM I KUSHTETUTSHMËRISË SË LIGJIT NR. ..."),
            # so a later decision naming that act names the reviewed act, not this one
            own_at_start = bool(re.match(r"\s*\W{0,3}" + KIND_WORD.pattern, fold(d["title"]), re.I))
            if others and (kind in ("aktgjykim", "aktvendim", "mendim") or not own_at_start):
                others = set()
            if others:
                # 2026-11-10 (Romania standard): a later act whose title names this one as amended (same kind word,
                # number and, where both give one, institution) labels it "amended, not consolidated" (was: held).
                # Only when every naming act was published on or after this act's own day (a naming act published
                # before it names another act with the same number): otherwise still held.
                pub = d["published"]
                when = {o: listed.get(o, ("", ""))[1] for o in others}
                if not pub or any(not w or w < pub for w in when.values()):
                    raise Hold("named_as_amended_ambiguous:" + ",".join(map(str, sorted(others)[:5])))
                rep = any(re.search(r"SHFUQIZIM", fold(listed[o][0])) and not CHANGE.search(
                    fold(re.sub(r"(?i)shfuqizim", "", listed[o][0]))) for o in others)
                prior = marks.get("amended_by", [])
                seen = {x["ref"] for x in prior}
                extra = [{"ref": f"gzk:{o}", "title": listed[o][0], "url": DETAIL.format(id=o), "date": when[o],
                          "relation": "named as amended in its title"}
                         for o in sorted(others, key=lambda o: (when[o], o)) if f"gzk:{o}" not in seen]
                marks = {"label": "repealed, not consolidated" if (rep or marks.get("label", "").startswith("repealed"))
                         else "amended, not consolidated", "amended_by": prior + extra}
            if not d["published"]:
                raise Hold("no_publication_day")
            amending = bool(CHANGE.search(fold(d["title"])))
            foreign = ""
            try:
                units, rule, tail_paras, sha, scanned, cut, info = read_text(base / "pdf.json.gz", amending, cache,
                                                                             d["title"])
            except Hold as h:
                # 2026-11-11: the Gazette's PDF is in English or Serbian only: published in that language, labelled
                got = foreign_text(base / "pdf.json.gz") if str(h).startswith("not_albanian") else None
                if not got:
                    raise
                units, rule, tail_paras, sha, scanned, foreign = got
                cut, info = "", {}
            released = bool(cut) or bool(foreign)   # read by a rule added after acts were first published
            doc = {"sha256": sha}
            if rule:
                when, how = ks_inforce.when(rule, d["published"])
                inf = {"date": when or d["published"], "basis": how, "words": rule}
            else:
                inf = {"date": d["published"], "basis": "published (no in-force rule found)", "words": ""}
            day, basis = inf["date"], inf["basis"]
            if info.get("letters"):
                # 2026-11-11: read with 'é' / '€' taken for 'ë'. A file holding several decisions is read only when
                # every in-force sentence in it gives the same day; publication elsewhere too holds it.
                released = True
                if len({ks_inforce.when(x, d["published"]) for x in info.get("all", [])} | {(day, basis)}) > 1:
                    raise Hold("in_force_rules_differ:" + inf["words"][:100])
                if published_twice(inf["words"]):
                    raise Hold("in_force_period_from_other_event:" + inf["words"][:100])
            if PROMULGATED(law_kind, basis, inf["words"]):
                # 2026-11-09: "hyn në fuqi pas miratimit nga Kuvendi ... dhe shpalljes nga PSSP-ja" (a UNMIK-era law:
                # in force on promulgation): the Gazette day, as for the 111 such laws of the first build. Not a
                # period counted from adoption (that is AFTER_SIGNATURE's "N days after signature").
                pass
            elif inf["words"] and AFTER_SIGNATURE.search(inf["words"]):
                # "N days after signature": ks_inforce counts from publication, which is wrong here; counted from the
                # signature day when the act prints it (after_signature), else held
                more = after_signature(inf["words"], tail_paras, d["title"], d["published"])
                if not more:   # 2026-11-11: the date printed in the signature block after the sentence (sig_date)
                    more = after_signature_block(inf["words"], info.get("after", []), d["published"])
                if not more:
                    raise Hold("in_force_counted_from_signature:" + inf["words"][:100])
                day, basis = more
                released = True
            if "after publication" in basis and not re.search(r"publikim|botim|shpallj|publication", inf["words"], re.I):
                raise Hold("in_force_period_from_other_event:" + inf["words"][:100])
            if (basis.startswith("published (no") or basis.startswith("published (the act")) and law_kind != "law" \
                    and inf["words"] and ON_PUBLICATION.search(inf["words"]):
                day, basis = d["published"], "on publication"
            elif basis.startswith("published (no") or basis.startswith("published (the act"):
                if PROMULGATED(law_kind, basis, inf["words"]):
                    pass  # 2026-11-09: the Gazette day, as the first build dates such laws (see above)
                elif inf["words"] and SIGNED_ON.search(inf["words"]):
                    m = TITLE_DATE.search(d["title"])
                    basis = "on signature (the date in the act's title)"
                    if not m:
                        # the date printed with the signature, after the in-force sentence ("Prishtinë, 30.12.2025")
                        tail = " ".join(tail_paras)
                        tail = tail[tail.find(inf["words"][-40:]) + 40:] if inf["words"][-40:] in tail else tail
                        dates = re.findall(r"\b(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})\b", tail)
                        if len(set(dates)) != 1:
                            # 2026-11-11: the one date printed in the signature block after the sentence (sig_date)
                            sig = sig_date(info.get("after", []), d["published"])
                            how = "on signature (the date printed with the signature)"
                            if not sig:   # else the act's own date at its head ("Nr. 01/88 Datë: 20.05.2016")
                                sig = head_date(info, d["published"], inf["words"], kind, d["title"])
                                how = "on signature (the act's date, printed at its head; no date with the signature)"
                            if not sig:
                                raise Hold("in_force_on_signature_day_unknown:" + inf["words"][:100])
                            dates = [(str(sig.day), str(sig.month), str(sig.year))]
                            released = True
                        else:
                            how = "on signature (the date printed with the signature)"
                        m = re.match(r"(\d+)\.(\d+)\.(\d+)", ".".join(dates[0]))
                        basis = how
                    day = f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
                    if not (d["published"][:4] >= day[:4] >= str(int(d["published"][:4]) - 1)):
                        raise Hold(f"signature_day_implausible:{day}")
                elif law_kind == "law" and basis.startswith("published (the act"):
                    pass  # takes effect on promulgation: the Gazette day, as in the rest of this repository
                elif inf["words"] and (more := more_rules(inf["words"], d["published"])):
                    day, basis = more
                    released = True
                elif not inf["words"] and d["institution"] == COURT and d["published"] >= "2009-01-15":
                    # 2026-11-11: no in-force sentence read: the statutory default (COURT_DECISION); an opinion: its
                    # category or title, or its reference number ("Nr. ref.: MM386/13", "MK460/13")
                    opinion = (d["category"] == "Mendime" or re.match(r"\s*(?:MENDIM|OPINION)", fold(d["title"]))
                               or re.search(r"\bref\W{0,4}(?:nr\W{0,4})?M[MK]\s*\d|\bmendim\w*\s+(?:mospajtues|konkurrues)",
                                            info.get("head", ""), re.I))
                    day, basis = d["published"], COURT_OPINION if opinion else COURT_DECISION
                    released = True
                else:
                    raise Hold("in_force_rule_unread:" + (inf["words"][:100] or "none"))
            if not re.fullmatch(r"\d{4}-\d\d-\d\d", day or ""):
                raise Hold("in_force_unknown")
            # (2026-11-10: a title the Gazette annotated as repealed or amended is labelled above, no longer held)
            guard = released or str(i) not in kept   # `kept`: published before these checks, kept by decision
            if ((guard and OFF_GAZETTE.search(_after_verb(inf["words"])))
                    or (released and OTHER_EVENT.search(inf["words"]))) and not basis.startswith("on adoption"):
                # counted from registration with the ministry, publication on the municipality's website or notice
                # board, approval by an assembly: days the Gazette doesn't give
                raise Hold("in_force_period_from_other_event:" + inf["words"][:100])
            if guard and basis == "on publication" and ANY_PERIOD.search(_after_verb(inf["words"])):
                # ks_inforce takes "7 (shtatë) ditë pas publikimit" for "pas publikimit" (on publication): read the
                # period, else hold
                more = more_rules(inf["words"], d["published"])
                if not more or more[1] == "on publication":
                    raise Hold("in_force_period_unread:" + inf["words"][:100])
                day, basis = more
        except Hold as h:
            holds.append({"id": i, "title": d.get("title", "")[:160], "reason": str(h)})
            continue
        year = int(d["published"][:4])
        slug = f"{kind}-{year}-{i}"
        title = d["title"]
        label = f"{title} (GZ {d['gazette']})" if d["gazette"] else title
        note = f"In force: {basis}" + (f" (\"{inf['words'][:300]}\")" if inf.get("words") else "") + "."
        if cut:
            note += " " + cut
        if foreign:
            note += (f" The Gazette publishes this act's text in {LANG_NAME[foreign]} only (its PDF has no Albanian text); "
                     f"the text here is that {LANG_NAME[foreign]} text, as published.")
        if info.get("letters"):
            note += (" The PDF's text layer prints 'ë' as 'é' or '€'; the in-force sentence was read, and is quoted, "
                     "with 'ë'.")
        office = next((e for e in ("doc", "docx") if (base / f"doc.{e}").exists()), None)
        if office:   # 2026-11-10: the Gazette serves this act as a Word file, not a PDF (read through Word)
            note += (f" The Gazette serves this act as a Word file (.{office}), not a PDF; its text was read from a PDF "
                     f"that Microsoft Word made of that file.")
        if scanned:
            note += (f" The PDF ends with {scanned} page(s) printed only as images (after the text), not "
                     f"transcribed here.")
        part = f"50-{kind}-{year}"
        parts[part]["laws"][slug] = {"label": label, "title": title, "kind": law_kind, "enacted": d["published"],
                                     "published": d["published"], "url": DETAIL.format(id=i),
                                     "temporary_until": None, "restores": None, "note": None}
        parts[part]["acts"].append({
            "slug": slug, "short": d["number"] or title, "title": title, "url": DETAIL.format(id=i),
            "first_law": slug, "earlier_laws": [],
            "versions": [{"from": day, "source_url": DOC.format(id=i), "sha256": doc["sha256"], "units": units,
                          "credits": {}, "note": note,
                          **({"trailers": OCR_SOURCE[str(i)].get("trailers", [OCR_SOURCE[str(i)]["trailer"]])} if str(i) in OCR_SOURCE else {}),
                          **({"trailers": [f"Language: {foreign} (the Gazette publishes no Albanian text for this act)"]}
                             if foreign else {})}],
            **marks})
    if cache is not None:
        cache = {k: v for k, v in cache.items() if k.endswith("|" + SELF)}
        tmp = Path(a.cache + ".tmp")
        tmp.write_bytes(gzip.compress(json.dumps(cache, ensure_ascii=False).encode("utf-8"), 3))
        tmp.replace(a.cache)
    PARTS = Path(a.out) if a.out else HERE / "corpus.d"
    PARTS.mkdir(exist_ok=True)
    country = {
        "country": {
            "code": "XK", "name": "Kosovo", "slug": "kosovo", "lang": "sq", "tz": "Europe/Belgrade",
            "future_branch": "future",
            "publisher": {"name": "Gazeta Zyrtare e Republikës së Kosovës", "email": "gazeta@gzk.invalid"},
            "default_in_force_rule": {
                "text": "Each act states its own entry into force ('Hyrja në fuqi'), usually a number of days after "
                        "publication in the Official Gazette, the publication day or a date.",
                "source": "https://gzk.rks-gov.net"},
            "licence_note": "Official texts of a legislative, administrative and judicial nature are not protected by "
                            "copyright (Law No. 08/L-205, art. 6(1)). Text from the Official Gazette of the Republic "
                            "of Kosovo (gzk.rks-gov.net)."},
        "acts": [], "laws": {},
        "sources": [{"name": "Gazeta Zyrtare e Republikës së Kosovës: acts by category, as published",
                     "url": "https://gzk.rks-gov.net", "retrieved": a.retrieved,
                     "licence": "Official texts, outside copyright (Law No. 08/L-205, art. 6(1))",
                     "notes": "Each act's Gazette page (category, status, publication day, related acts) and the text "
                              "layer of its Albanian PDF."}],
        "decisions": [], "ai_use": ["none"]}
    written = []
    outputs = {"00-country": country}
    for name in sorted(parts):
        p = parts[name]
        p["acts"].sort(key=lambda x: x["slug"])
        p["decisions"] = [
            "Acts added after the first build (sub-legal acts and laws not yet in the record) are published as "
            "published in the Official Gazette, one version each, only when the Gazette links no act that amends, "
            "supplements or repeals them, does not mark them repealed, and no later act's title names them; the "
            "others are held back.",
            "Each one takes effect on the day its own in-force article gives (days after publication, the "
            "publication day, a date); 'on the day of signature' takes the date in the act's title; an act with no "
            "readable rule is held back. The rule's words are quoted in the version note.",
            "Acts held back for want of a readable in-force rule are also read for these wordings: on publication in "
            "the Official Gazette in its other forms ('në ditën e shpalljes së tij', 'në momentin e publikimit', "
            "'pas publikimit në Gazetën Zyrtare'), 'N (word) days or months after publication in the Official "
            "Gazette', and 'on the day of adoption' where the act itself gives the adoption date. A period counted "
            "from signature, adoption, registration or publication elsewhere still holds the act back.",
            "Where the Gazette's PDF prints the act in Albanian and in English and/or Serbian, side by side in "
            "columns or one after another, the text is its Albanian column or pages alone, taken only when the "
            "boundary is clean: every line stands inside one column, the columns sit at the same place on every "
            "page, and each whole page is in one language. The version note says so.",
            "The enacted date given is the Gazette publication day.",
            "Text: the Albanian PDF's text layer, joined into paragraphs and split into the preamble (hyrje), one "
            "file per article (neni-NNN) and the signature (nenshkrimi), by the same reader as the rest of the "
            "record; tables run on as lines."]
        p["ai_use"] = ["none"]
        outputs[name] = p
    for name, p in outputs.items():
        f = PARTS / f"{name}.json"
        body = json.dumps(p, ensure_ascii=False, indent=1) + "\n"
        if not f.exists() or f.read_text(encoding="utf-8") != body:
            tmp = f.with_suffix(".tmp")
            tmp.write_text(body, encoding="utf-8", newline="\n")
            replace(tmp, f)
        pub = PARTS / f"{name}.PUBLISH"
        line = (f"{len(p['acts'])} acts checked against the Gazette's page and the PDF text layer: no amending or "
                f"repealing act linked or named, in-force day read from the act's own article, articles numbered in "
                f"sequence, text in Albanian.\n")
        if not pub.exists() or pub.read_text(encoding="utf-8") != line:
            pub.write_text(line, encoding="utf-8", newline="\n")
        written.append((name, len(p["acts"])))
    if a.report:
        Path(a.report).write_text("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in holds), encoding="utf-8")
    reasons = defaultdict(int)
    for h in holds:
        reasons[h["reason"].split(":")[0]] += 1
    print(json.dumps({"pdfs": len(ids), "published": sum(n for _, n in written), "held": len(holds),
                      "held_by_reason": dict(reasons), "parts": len(written)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

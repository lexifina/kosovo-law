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
MARKED = re.compile(r"\(\s*(?:e\s+|i\s+)?(?:shfuqizuar|ndryshuar|plot[eë]suar|pezulluar)\b", re.I)
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
            out["related"].append({"relation": clean(rel.group(1)) if rel else "", "id": int(link.group(1))})
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


def _read(doc: dict, amending: bool) -> tuple[dict, str, list]:
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
    if MULTI.search("\n".join(paras)):
        raise Hold("multilingual_pdf")   # Albanian, English and Serbian texts in one file
    return units, rule, paras


def read_text(path: Path, amending: bool, cache: dict | None, title: str = "") -> tuple[dict, str, list, str, int, str]:
    """(units, in-force sentence, last four paragraphs, sha256 of the PDF, trailing image pages, cut note) for one
    act's PDF text, or Hold. The cut note is '' unless the text is the Albanian part of a PDF that also prints the
    English and Serbian texts. Results are kept in `cache` keyed by the file's size and time and this parser's own
    hash: a cached run gives the same bytes."""
    stt = path.stat()
    tkey = hashlib.sha256(title.encode("utf-8")).hexdigest()[:8]
    key = f"{path.parent.name}|{stt.st_size}|{stt.st_mtime_ns}|{int(amending)}|{tkey}|{SELF}"
    if cache is not None and key in cache:
        r = cache[key]
        if "hold" in r:
            raise Hold(r["hold"])
        return r["units"], r["rule"], r["tail"], r["sha"], r["scanned"], r.get("cut", "")
    cut = ""
    try:
        doc = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        if doc.get("no_pdf") or not doc.get("pages"):
            raise Hold("no_pdf")
        flags = [bool(p.get("scanned")) for p in doc["pages"]]
        n_text = len(flags) - flags[::-1].index(False) if False in flags else 0
        if n_text == 0 or any(flags[:n_text]):
            raise Hold("scanned_pages")   # a page image inside the text: words would be missing
        # page images after the text (an organigram, a scanned annex) are not transcribed; the note counts them
        scanned_tail = len(flags) - n_text
        try:
            units, rule, paras = _read(doc, amending)
        except Hold as h:
            if not str(h).startswith(CUTTABLE):
                raise
            part = albanian_part({"sha256": doc["sha256"], "pages": doc["pages"][:n_text]}, title)
            if isinstance(part, str):
                raise Hold(f"{h}" if part == "single_language" else f"{h}|cut:{part}")
            try:
                units, rule, paras = _read(part[0], amending)
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
    r = {"units": units, "rule": rule, "tail": paras[-4:], "sha": doc["sha256"], "scanned": scanned_tail}
    if cut:
        r["cut"] = cut
    if cache is not None:
        cache[key] = r
    return units, rule, paras[-4:], doc["sha256"], scanned_tail, cut


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
    ap.add_argument("--out", help="folder for the parts (default: corpus.d next to this file)")
    ap.add_argument("--cache", help="optional .json.gz file keeping each PDF's parsed text between runs")
    a = ap.parse_args()
    src = Path(a.src)
    exclude = set(Path(a.exclude).read_text().split()) if a.exclude and Path(a.exclude).exists() else set()
    rejects = json.loads(Path(a.rejects).read_text(encoding="utf-8")) if a.rejects and Path(a.rejects).exists() else {}
    cache = None
    if a.cache:
        try:
            cache = json.loads(gzip.decompress(Path(a.cache).read_bytes()).decode("utf-8"))
        except (OSError, ValueError, EOFError):
            cache = {}

    named: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(set))
    for f in sorted((src / "list").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
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
            if d["by_later"]:
                raise Hold("amended_or_repealed_on_gazette")
            if "shfuqiz" in d["status"].lower():
                raise Hold("repealed:" + d["status"])
            if d["category"] not in KINDS:
                raise Hold("kind_not_built:" + d["category"])
            kind, law_kind = KINDS[d["category"]]
            k = own_key(d["title"])
            others = (named_by(named, k) - {i}) if k else set()
            if others:
                raise Hold("named_as_amended:" + ",".join(map(str, sorted(others)[:5])))
            if not d["published"]:
                raise Hold("no_publication_day")
            amending = bool(CHANGE.search(fold(d["title"])))
            units, rule, tail_paras, sha, scanned, cut = read_text(base / "pdf.json.gz", amending, cache, d["title"])
            released = bool(cut)   # read by a rule added after acts were first published (see marked_changed)
            doc = {"sha256": sha}
            if rule:
                when, how = ks_inforce.when(rule, d["published"])
                inf = {"date": when or d["published"], "basis": how, "words": rule}
            else:
                inf = {"date": d["published"], "basis": "published (no in-force rule found)", "words": ""}
            day, basis = inf["date"], inf["basis"]
            if inf["words"] and AFTER_SIGNATURE.search(inf["words"]):
                # "N days after signature": ks_inforce counts from publication, which is wrong here; counted from the
                # signature day when the act prints it (after_signature), else held
                more = after_signature(inf["words"], tail_paras, d["title"], d["published"])
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
                if inf["words"] and SIGNED_ON.search(inf["words"]):
                    m = TITLE_DATE.search(d["title"])
                    basis = "on signature (the date in the act's title)"
                    if not m:
                        # the date printed with the signature, after the in-force sentence ("Prishtinë, 30.12.2025")
                        tail = " ".join(tail_paras)
                        tail = tail[tail.find(inf["words"][-40:]) + 40:] if inf["words"][-40:] in tail else tail
                        dates = re.findall(r"\b(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})\b", tail)
                        if len(set(dates)) != 1:
                            raise Hold("in_force_on_signature_day_unknown:" + inf["words"][:100])
                        m = re.match(r"(\d+)\.(\d+)\.(\d+)", ".".join(dates[0]))
                        basis = "on signature (the date printed with the signature)"
                    day = f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
                    if not (d["published"][:4] >= day[:4] >= str(int(d["published"][:4]) - 1)):
                        raise Hold(f"signature_day_implausible:{day}")
                elif law_kind == "law" and basis.startswith("published (the act"):
                    pass  # takes effect on promulgation: the Gazette day, as in the rest of this repository
                elif inf["words"] and (more := more_rules(inf["words"], d["published"])):
                    day, basis = more
                    released = True
                else:
                    raise Hold("in_force_rule_unread:" + (inf["words"][:100] or "none"))
            if not re.fullmatch(r"\d{4}-\d\d-\d\d", day or ""):
                raise Hold("in_force_unknown")
            if released and MARKED.search(d["title"]):
                raise Hold("title_marks_later_change")
            if released and OTHER_EVENT.search(inf["words"]) and not basis.startswith("on adoption"):
                # counted from registration with the ministry, publication on the municipality's website or notice
                # board, approval by an assembly: days the Gazette doesn't give
                raise Hold("in_force_period_from_other_event:" + inf["words"][:100])
            if released and basis == "on publication" and ANY_PERIOD.search(inf["words"]):
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
                          "credits": {}, "note": note}]})
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

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

An act is held back, not published, when (the reason goes to the report):
- its Gazette page links an act that amends, supplements or repeals it, or marks it repealed, or a later act's title
  names it ("... PËR NDRYSHIMIN DHE PLOTËSIMIN E UDHËZIMIT ADMINISTRATIV NR. 05/2023");
- its PDF is missing, scanned, not in Albanian, or its articles don't number cleanly;
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
TITLE_DATE = re.compile(r"\bDAT[AËE]\s*[:.]?\s*(\d{1,2})\s*[./]\s*(\d{1,2})\s*[./]\s*(\d{4})", re.I)


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


def read_text(path: Path, amending: bool, cache: dict | None) -> tuple[dict, str, list, str]:
    """(units, in-force sentence, last four paragraphs, sha256 of the PDF) for one act's PDF text, or Hold. Results
    are kept in `cache` keyed by the file's size and time and this parser's own hash: a cached run gives the same
    bytes."""
    stt = path.stat()
    key = f"{path.parent.name}|{stt.st_size}|{stt.st_mtime_ns}|{int(amending)}|{SELF}"
    if cache is not None and key in cache:
        r = cache[key]
        if "hold" in r:
            raise Hold(r["hold"])
        return r["units"], r["rule"], r["tail"], r["sha"]
    try:
        doc = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        if doc.get("no_pdf") or not doc.get("pages"):
            raise Hold("no_pdf")
        if any(p.get("scanned") for p in doc["pages"]):
            raise Hold("scanned_pages")
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
    except Hold as h:
        if cache is not None:
            cache[key] = {"hold": str(h)}
        raise
    r = {"units": units, "rule": rule, "tail": paras[-4:], "sha": doc["sha256"]}
    if cache is not None:
        cache[key] = r
    return units, rule, paras[-4:], doc["sha256"]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--retrieved", required=True, help="the day the inputs were retrieved (YYYY-MM-DD)")
    ap.add_argument("--exclude", help="file of Gazette act ids already in the repository (one per line)")
    ap.add_argument("--report")
    ap.add_argument("--rejects", help="JSON {id: reason}: acts held back by hand or by a failed read-back check")
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
            units, rule, tail_paras, sha = read_text(base / "pdf.json.gz", amending, cache)
            doc = {"sha256": sha}
            if rule:
                when, how = ks_inforce.when(rule, d["published"])
                inf = {"date": when or d["published"], "basis": how, "words": rule}
            else:
                inf = {"date": d["published"], "basis": "published (no in-force rule found)", "words": ""}
            day, basis = inf["date"], inf["basis"]
            if basis.startswith("published (no") or basis.startswith("published (the act"):
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
                else:
                    raise Hold("in_force_rule_unread:" + (inf["words"][:100] or "none"))
            if not re.fullmatch(r"\d{4}-\d\d-\d\d", day or ""):
                raise Hold("in_force_unknown")
        except Hold as h:
            holds.append({"id": i, "title": d.get("title", "")[:160], "reason": str(h)})
            continue
        year = int(d["published"][:4])
        slug = f"{kind}-{year}-{i}"
        title = d["title"]
        label = f"{title} (GZ {d['gazette']})" if d["gazette"] else title
        note = f"In force: {basis}" + (f" (\"{inf['words'][:300]}\")" if inf.get("words") else "") + "."
        part = f"50-{kind}-{year}"
        parts[part]["laws"][slug] = {"label": label, "title": title, "kind": law_kind, "enacted": d["published"],
                                     "published": d["published"], "url": DETAIL.format(id=i),
                                     "temporary_until": None, "restores": None, "note": None}
        parts[part]["acts"].append({
            "slug": slug, "short": d["number"] or title, "title": title, "url": DETAIL.format(id=i),
            "first_law": slug, "earlier_laws": [],
            "versions": [{"from": day, "source_url": DOC.format(id=i), "sha256": doc["sha256"], "units": units,
                          "credits": {}, "note": note}]})
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
            tmp.replace(f)
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

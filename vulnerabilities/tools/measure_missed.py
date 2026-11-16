"""Counts the places in law texts where "deri" (until) is followed by a past date, which of them the time-limit search
flagged (same file and date), and the forms of those it missed.   python -X utf8 measure_missed.py"""
import collections, csv, json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
G = os.path.join(HERE, "gl", "vulnerabilities", "scripts", "sources", "corpus", "kosovo-law.git")
PIN = "3750d6a3416e306fb8bfaad86bc80a793e1bf739"
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
NOT_LAW = tuple(CFG["not_law"])
MON = "janar shkurt mars prill maj qershor korrik gusht shtator tetor nëntor dhjetor".split()
MONX = "|".join(MON + ["nentor", "nendor", "nëndor"])
DATE = rf"(\d{{1,2}})\s*[./]\s*(\d{{1,2}})\s*[./]\s*((?:19|20)\d\d)|(\d{{1,2}})\.?\s+({MONX})\w*\.?,?\s+(?:të vitit\s+)?((?:19|20)\d\d)|fund(?:in)? të vitit\s+((?:19|20)\d\d)"
PAT = re.compile(rf"\bderi\b(.{{0,30}}?)(?:{DATE})", re.I)
TODAY = "2026-11-15"

flagged = {(r["path"], r["date"]) for r in csv.DictReader(open(os.path.join(HERE, "out", "data", "flags.csv"), encoding="utf-8"))
           if r["detector"] == "lapsed_limit"}
out = subprocess.run(["git", "-C", G, "grep", "-I", "-n", "-i", "-E", r"\bderi\b", PIN, "--", "*.md"], capture_output=True).stdout.decode("utf-8", "replace")
hit, miss, forms = 0, 0, collections.Counter()
ex = collections.defaultdict(list)
for line in out.splitlines():
    _, path, _, text = line.split(":", 3)
    if path.startswith(NOT_LAW) or path.endswith("/README.md"):
        continue
    for m in PAT.finditer(text):
        g = m.groups()
        if g[3]:
            y, mo, d = int(g[3]), int(g[2]), int(g[1])
        elif g[6]:
            y, mo, d = int(g[6]), (MON.index(g[5].lower()) + 1 if g[5].lower() in MON else 11), int(g[4])
        else:
            y, mo, d = int(g[7]), 12, 31
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        iso = f"{y:04d}-{mo:02d}-{d:02d}"
        if iso >= TODAY:
            continue
        if (path, iso) in flagged:
            hit += 1
        else:
            miss += 1
            lead = re.sub(r"\s+", " ", (m.group(0)[5:5 + len(g[0])] if g[0] else "").strip().lower())
            key = lead.split(" ")[0] if lead else "(none)"
            forms[key] += 1
            if len(ex[key]) < 3:
                ex[key].append((path, m.group(0)[:80]))
print(f"past dates after 'deri' in law texts: {hit + miss}; flagged {hit}; missed {miss}")
for k, n in forms.most_common(15):
    print(n, repr(k), ex[k][:2])

"""Hand-check helper for retroactive-date flags whose act takes effect on (or N days after) signature: is the signature
date the repository read printed near the end of the act's text (the signature block) or at its head?
Prints the acts where it is in neither place, with the lines that hold that date.   python -X utf8 check_signature_dates.py"""
import csv, os, re, subprocess
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
G = os.path.join(HERE, "gl", "vulnerabilities", "scripts", "sources", "corpus", "kosovo-law.git")
PIN = "3750d6a3416e306fb8bfaad86bc80a793e1bf739"
MON = "janar shkurt mars prill maj qershor korrik gusht shtator tetor nëntor dhjetor".split()


def git(*a):
    return subprocess.run(["git", "-C", G, *a], capture_output=True).stdout.decode("utf-8", "replace")


def forms(d):
    y, m, dd = d.year, d.month, d.day
    return [f"{dd:02d}.{m:02d}.{y}", f"{dd}.{m}.{y}", f"{dd:02d}/{m:02d}/{y}", f"{dd}/{m}/{y}", f"{dd} {MON[m-1]} {y}",
            f"{dd:02d} {MON[m-1]} {y}", f"{dd}.{MON[m-1]}", f"{dd}. {MON[m-1]}", f"{dd} {MON[m-1]}", f"{dd:02d}.{m:02d}.{str(y)[2:]}"]


n = bad = 0
for r in csv.DictReader(open(os.path.join(HERE, "out", "data", "flags.csv"), encoding="utf-8")):
    if r["detector"] != "retroactive_date":
        continue
    c = r["url"].rsplit("/", 1)[-1]
    b = git("show", "-s", "--format=%B", c)
    m = re.search(r"In force: (on signature|day (\d+) after signature)", b)
    if not m:
        continue
    n += 1
    sig = date.fromisoformat(r["date"]) - timedelta(days=int(m.group(2) or 0))
    folder = r["path"].rsplit("/", 1)[0]
    files = [f for f in git("ls-tree", "--name-only", PIN, folder + "/").split() if not f.endswith("README.md")]
    text = "\n".join(git("show", f"{PIN}:{f}") for f in files)
    low = text.lower()
    head, tail = low[:1500], low[-1500:]
    fs = [f.lower() for f in forms(sig)]
    if any(f in tail or f in head for f in fs):
        continue
    bad += 1
    hits = [l.strip()[:160] for l in text.splitlines() if any(f in l.lower() for f in fs)][:2]
    print(f"{folder}  in force {r['date']}  signature read as {sig}  {r['reference'][:70]}")
    for h in hits:
        print("     ", h)
print(f"{n} signature-dated flags; {bad} with that date neither at the head nor in the signature block")

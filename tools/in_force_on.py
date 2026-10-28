"""Print a Kosovo act, or one article of it, as this record holds it on a date.

    python tools/in_force_on.py 2015-01-01 ligje/03-l-199            # the Law on Courts (Albanian), every file
    python tools/in_force_on.py 2015-01-01 ligje/03-l-199 neni-043   # article 43
    python tools/in_force_on.py 2015-01-01 en/ligje/03-l-199 article-043
    python tools/in_force_on.py --future 2027-01-01 ligje/10-l-050   # include acts not yet in force

This record is AS ENACTED: an act's text is the text it was enacted with; amendments are not applied (see
data/amendments.csv for the acts that amend it). On a date the tool prints the act if it had taken effect and had not
been repealed (its files are deleted on the day the repealing act took effect). It reads the `In-force:` trailer, so
the answer does not depend on your time zone. The folder of each act is in laws.csv. Standard library only.
"""
import re
import subprocess
import sys


def git(*args: str) -> str:
    return subprocess.run(['git', *args], capture_output=True, text=True, encoding='utf-8', check=True).stdout


def commit_on(day: str, path: str, ref: str) -> str | None:
    """The last commit on or before `day` that touched `path`."""
    fmt = '%H%x1f%(trailers:key=In-force,valueonly,separator=)'
    for line in git('log', '--first-parent', '--no-merges', f'--format={fmt}', ref, '--', path).splitlines():
        h, d = (line.split('\x1f') + [''])[:2]
        d = d.strip()[:10]
        if d and d <= day:
            return h
    return None


def order(name: str) -> tuple:
    stem = name.rsplit('/', 1)[-1][:-3]
    rank = {'hyrje': 0, 'preamble': 0, 'teksti': 1, 'text': 1, 'nenshkrimi': 3, 'signature': 3}.get(stem, 2)
    m = re.search(r'(\d+)$', stem)
    return rank, int(m.group(1)) if m else 0, stem


def main() -> None:
    args = sys.argv[1:]
    ref = 'main'
    if args and args[0] == '--future':
        ref, args = 'future', args[1:]
    if len(args) < 2 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args[0]):
        sys.exit(__doc__)
    day, act = args[0], args[1].strip('/')
    unit = args[2].removesuffix('.md') if len(args) > 2 else None
    path = f'{act}/{unit}.md' if unit else act
    h = commit_on(day, path, ref)
    if not h:
        sys.exit(f'{path}: no text on or before {day} (not yet in force, not in this record, or no such article)')
    names = git('ls-tree', '-r', '--name-only', h, '--', path if unit else f'{act}/').split('\n')
    names = [n for n in names if n.endswith('.md')]
    if not names:
        sys.exit(f'{path}: not in force on {day} (repealed by then)')
    if unit:
        sys.stdout.write(git('show', f'{h}:{path}'))
        return
    cat = subprocess.Popen(['git', 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    out = sys.stdout.buffer
    for n in sorted(names, key=lambda n: (n.rsplit('/', 1)[0], order(n))):
        cat.stdin.write(f'{h}:{n}\n'.encode('utf-8'))
        cat.stdin.flush()
        size = int(cat.stdout.readline().split()[2])
        out.write(cat.stdout.read(size) + b'\n')
        cat.stdout.read(1)
    cat.stdin.close()
    cat.wait()


if __name__ == '__main__':
    main()

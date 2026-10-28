# Kosovo law, act by act, as enacted

The legislation of Kosovo as a git repository: {{WITH_TEXT}} acts from the [Official Gazette of the Republic of Kosovo](https://gzk.rks-gov.net) (Gazeta Zyrtare), the official publisher, each **as it was enacted**: {{KINDS_LINE}}. There is one folder per act and one file per article, in Albanian, with the Gazette's English translation in a parallel tree under `en/`. Each act is one commit, credited to the act itself and dated the day it took effect, at noon Kosovo time.

**What kind of history this is.** The Official Gazette publishes every act as enacted. It keeps no dated series of consolidated versions of the laws it amends: since {{CONSOLIDATED_FIRST}} it has published {{CONSOLIDATED}} single consolidated texts ("(KONSOLIDUAR)", one per law, each as of its publication day), listed with their publication dates in [`data/consolidated.csv`](data/consolidated.csv) but not used as history. So this record is **as enacted** (`"history": "as-enacted"` in [`corpus.json`](corpus.json)): an act's files hold the text it was enacted with, and **later amendments are not applied to them**. An amending law is its own act, in its own folder, saying what it changes ("Neni 6 i ligjit bazik, pas paragrafit 2, shtohet paragrafi i ri 3 ..."). Which act amends, supplements or repeals which is listed in [`data/amendments.csv`](data/amendments.csv) ({{RELATIONS}} links, as the Gazette gives them). There is no line-by-line history of any law's consolidated text, and none before the record starts. Replaying the amendments into the texts was not attempted, because for most laws there is no official consolidation to check a replay against, and for the others only one, recent.

The record runs from {{FIRST}} to {{LAST}} in {{COMMITS}} commits on `main`. {{FUTURE}} further acts, published but taking effect after {{TODAY}}, are on the branch `future`, which is never merged. A repealed act's files are deleted on the day the act that repealed it took effect ({{REPEALS}} acts).

## A lawyer's questions as git commands

Each act's folder is `<kind>/<number>/`, listed with its title, dates and status in [`laws.csv`](laws.csv): `kushtetuta/2008` (the Constitution as adopted in 2008), `ligje/03-l-199` (Law No. 03/L-199 on Courts, 2010, repealed in 2019), `ligje/06-l-054` (Law No. 06/L-054 on Courts, which repealed it), `kode/06-l-074` (the Criminal Code of 2019).

| Question | Command |
| --- | --- |
| What did article 43 of Law No. 03/L-199 say, and was it in force on 1 January 2015? | `python tools/in_force_on.py 2015-01-01 ligje/03-l-199 neni-043` |
| The whole act on a date (Albanian; English under `en/`) | `python tools/in_force_on.py 2015-01-01 en/ligje/03-l-199` |
| Was it still in force on 1 March 2019? | `python tools/in_force_on.py 2019-03-01 ligje/03-l-199` (it says "repealed by then") |
| Counting acts already published but not yet in force | `python tools/in_force_on.py --future 2027-01-01 <folder>` |
| Which acts amend Law No. 03/L-199? | `grep '^2700,' data/amendments.csv`, or search the file for `03/L-199` |
| When did an act take effect, and why that day? | `git log -1 --format='%(trailers)' -- ligje/03-l-199/neni-001.md` (`In-force:`, `In-force-basis:`, `In-force-rule:`) |
| Every act that took effect in 2020 | `git log --format='%(trailers:key=In-force,valueonly,separator=) %s' \| grep '^2020'` |
| Which act repealed this one? | `git log --diff-filter=D --format='%an %(trailers:key=In-force,valueonly)' -- ligje/03-l-199` |
| Who wrote a line? | `git blame kode/06-l-074/neni-001.md` (always the act itself: nothing is amended in place) |
| Commits on or before a day, without time-zone surprises | `git log --before='2019-01-01T23:59:59+01:00' -1` |

In PowerShell, `git show $(...):path` splits into two arguments; use `$r = git rev-list -1 main -- ligje/03-l-199; git show "$($r):ligje/03-l-199/neni-043.md"`.

Files: `hyrje.md` holds the title and enacting formula, `neni-001.md` ... one article each (`# Neni 1` heading, the article title, then one line per paragraph; chapter headings above an article as `##` lines), `nenshkrimi.md` the signature and promulgation block. In `en/` the same files are `preamble.md`, `article-001.md` ... and `signature.md`; UNMIK-era English texts call their articles "Section", and keep that word in the heading. An act without numbered articles (Constitutional Court judgments, the constitutional amendments) is one file, `teksti.md` / `text.md`. Article headings are taken only in sequence (1, 2, 3 ...), so the articles an amending law quotes stay inside the article that quotes them.

## The dates, and which one we use

**Commits are dated by the day the act took effect**, read from the act's own in-force article ("Hyrja në fuqi"):

- "hyn në fuqi pesëmbëdhjetë (15) ditë pas publikimit në Gazetën Zyrtare" (N days after publication): the publication date plus N days. {{BASIS_DAY}} acts.
- "hyn në fuqi ditën e publikimit" (on the day of publication): the publication date. {{BASIS_PUBLICATION}} acts.
- A date in the act ("hyn në fuqi më 1 janar 2011"; a month alone, "në janar të vitit 2017", is read as its first day): that date. {{BASIS_DATE}} acts. Budget laws often take effect on 1 January before they are published, and some 2002–2005 laws were published in the Gazette only later; these commits say `In-force-before-publication: yes`.
- Months or years after publication: the publication date plus that period. {{BASIS_MONTHS}} acts.
- On promulgation by the UNMIK Special Representative or the President (laws of 2001–2008): the Gazette publication date, labelled `In-force-basis: published (the act takes effect on promulgation; ...)`. {{BASIS_PROMULGATION}} acts.
- No rule found or no date in it: the publication date, labelled `In-force-basis: published (...)`. {{BASIS_FALLBACK}} acts.

The Albanian text is read first, the English one where the Albanian has no rule. Every commit carries `In-force:`, `In-force-basis:`, `In-force-rule:` (the act's words), `Published:` and `Gazette:`. Where parts of an act take effect on other dates ("... hyn në fuqi më 1 janar 2011 për nenet 29, 35 ... kurse për nenet e tjera fillon të zbatohet nga 1 janari 2013"), the commit has the first date and the whole rule is quoted in `In-force-rule:`.

## What "author" means

The author of each commit is the act itself, at an address that cannot exist: `Ligji Nr. 03/L-199 <ligji-03-l-199@gzk.invalid>`. Since nothing is amended in place, `git blame` always names the act whose own text it is. The commit of an act that repealed others also deletes their files, and says so in `Repeals:` lines.

## What it does not show

- **Amendments applied to the text.** Read the amending acts (see `data/amendments.csv`) alongside the act. Partial repeals and Constitutional Court judgments that annul provisions are links there too, not deletions. For {{CONSOLIDATED_MATCHED}} acts in this record the Gazette has published one consolidated text ({{CONSOLIDATED_FIRST}} to {{CONSOLIDATED_LAST}}); [`data/consolidated.csv`](data/consolidated.csv) links each to the law's folder here, but its text is not in this record.
- **English documents that are the Albanian text.** For {{EN_LEFT_OUT}} acts the Gazette's "English" document holds the Albanian text (for most, the same PDF file). They are left out of `en/` and listed in [`data/en-left-out.csv`](data/en-left-out.csv); the Albanian text is under the act's own folder.
- **Annexed texts as articles.** A ratified agreement or an annex printed after a law's signature, numbered from article 1 again, stays inside the law's last file; its articles are not split out. A Constitutional Court judgment is one file (`teksti.md`), since its article headings are those of the law it reviews.
- The Serbian texts, which the Gazette also publishes (Albanian and Serbian are the official languages of Kosovo, Constitution art. 5). Only the Albanian text and the Gazette's own English translation are used here.
- Sub-legal acts (regulations, administrative instructions, decisions of the Government) and the UNMIK regulations, except the few in the Gazette's list of laws.
- Annexes that the Gazette publishes only as page scans (agreements annexed to ratification laws, budget tables): {{SCANNED_PAGES}} scanned pages are not transcribed; the commit's `Text-sq:`/`Text-en:` trailer counts them. Acts with no text at all: {{NO_TEXT}}, listed in [`data/issues.csv`](data/issues.csv).
- Formatting, tables as tables (cells run on in one line), footnotes and images.
- Acts repealed by an act outside this record keep their files; `status_on_gzk` in `laws.csv` says which acts the Gazette marks repealed ({{STATUS_REPEALED}}).

This is a research aid. Only the texts published in the Official Gazette of the Republic of Kosovo are official.

## How it is checked

- Every act's letters, in both languages, are compared with the raw source (the Gazette's text layer or PDF, read by a separate minimal extractor), after removing page numbers and the Gazette's running headers (`check_words.py`). Of {{CW_CHECKED}} texts, {{CW_SAME}} have every letter in place; {{CW_REORDERED}} have the same words in another order (table cells and OCR layers, which the two readers take in a different order, and acts with a heading printed out of order, whose article files the check reads by number), {{CW_SPACING}} differ only in where letter-spaced words break, and {{CW_BAD}} differ in letters (listed in REPRODUCE.md). Numbers alone differ more often: page numbers inside tables are kept here.
- Every commit has `In-force:`; `main` has no merges, its dates never go backwards or past the build day, and every commit is at noon Kosovo time.
- The build is deterministic: from the same pages it gives the same commit hashes. The sha256 of every source page and PDF is in [`data/source-sha256.tsv`](data/source-sha256.tsv).

## How it is built

`fetch.py` reads the Gazette's list of laws (LawInForceList.aspx), each act's page (metadata and links to related acts) and its text in Albanian and English, and the gazette PDF where the page has no text layer. `text.py` and `pdftext.py` turn each text into paragraphs and articles; `inforce.py` reads the in-force article; `build.py` writes one commit per act with one streamed `git fast-import`; `docs.py` writes these files. No AI model takes part in building or checking it. See [`REPRODUCE.md`](REPRODUCE.md).

## Licence

Source: the Official Gazette of the Republic of Kosovo (Gazeta Zyrtare e Republikës së Kosovës), https://gzk.rks-gov.net. Under Law No. 08/L-205 on Copyright and Related Rights, article 6(1), "Copyright protection shall not extend to official texts of a legislative, administrative and judicial nature, and the official translations of such texts." The texts were converted to one file per article and arranged as commits; their wording was not changed. Lexifina's own contributions (the tools, the arrangement and the commit messages) are CC0. See [`LICENSE`](LICENSE) and [`SOURCES.md`](SOURCES.md).

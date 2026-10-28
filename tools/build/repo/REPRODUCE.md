# How this repository was made

This repository replaces the placeholder history ("Kosovo: sources, before any law") entirely; it does not append to it.

## Source

- The Official Gazette of the Republic of Kosovo, https://gzk.rks-gov.net (an ASP.NET WebForms site), retrieved 28–29 October 2026:
  - the list of laws, `LawInForceList.aspx`: 63 pages by postback, 1,258 rows, 1,043 distinct acts (laws, codes, Constitutional Court judgments, in force or repealed, and the acts they are linked to);
  - six acts added by hand in `extra_acts.json`: the Constitution as adopted (ActID 3702) and its five amendments (3293, 8650, 10997, 12222, 31730), which are not in that list;
  - for each of the {{ACTS}} acts: `ActDetail.aspx?ActID=N` (Albanian: category, number, publication date, gazette, status, related acts) and `ActDocumentDetail.aspx?ActID=N` in Albanian and in English (the text layer);
  - where a document page has no text layer, the gazette PDF through the page's PDF button (a form postback).
- Fetch rate: one session per thread, at most 4 requests at a time, about 4,600 requests in all ({{SOURCE_FILES}} files kept; the PDF fetch took about 10 minutes for 658 PDFs). robots.txt allows these paths and sets no Crawl-delay; no request was refused or challenged.
- The sha256 of every page (decompressed) and PDF is in `data/source-sha256.tsv` (sha256 of that file: `{{SUMS_SHA}}`).
- Legal basis for reuse: Law No. 08/L-205 on Copyright and Related Rights, article 6(1) (see SOURCES.md).

## Commands, in order

From `scripts/kosovo-law/` in the Lexifina repository (copies of every script are in `tools/build/`):

1. `python fetch.py catalogue`
1a. `python fetch.py consolidated`: the list of consolidated texts (`ConsolidatedActs.aspx`, every year and page; 10 requests, 1 s apart) for `data/consolidated.csv`. Their texts are not fetched.
2. `python fetch.py acts --workers 4`
3. `python fetch.py pdfs --workers 4`
4. `python build.py <empty folder> --today {{TODAY}}`: parses every act (`text.py`, `pdftext.py`, `inforce.py`), plans one commit per act and writes the history with one `git fast-import`; acts in force after `--today` go to the `future` branch. The documentation commit is dated `--today`, the day the retrieval finished.
5. `python check_words.py <repo>`: the independent letters-and-digits check against the raw source. It writes `.cache/check_words.json`, whose counts the next build puts into this file and the README; so the final sequence is build, check, build, build (the last two must give the same head).

## Script blobs (sha256)

| Script | sha256 |
| --- | --- |
| build.py | {{SHA_BUILD_PY}} |
| text.py | {{SHA_TEXT_PY}} |
| pdftext.py | {{SHA_PDFTEXT_PY}} |
| inforce.py | {{SHA_INFORCE_PY}} |
| parse.py | {{SHA_PARSE_PY}} |
| gzk.py | {{SHA_GZK_PY}} |
| fetch.py | {{SHA_FETCH_PY}} |
| docs.py | {{SHA_DOCS_PY}} |
| check_words.py | {{SHA_CHECK_WORDS_PY}} |
| extra_acts.json | {{SHA_EXTRA_ACTS_JSON}} |

Tools: Python 3.12.10, PyMuPDF 1.28.5 (MuPDF), {{GIT}}, on Windows 11.

## Result

- {{COMMITS}} commits on `main` ({{WITH_TEXT}} acts plus this documentation), {{FUTURE}} on `future`; {{REPEALS}} acts' files deleted by the act that repealed them.
- Albanian text: {{SRC_HTML}} acts from the text layer, {{SRC_PDF}} from the PDF, {{SQ_NONE}} none. English: {{EN_HTML}} text layer, {{EN_PDF}} PDF, {{EN_NONE}} none (no translation, or the "English" document is the Albanian text: listed in data/en-left-out.csv and data/issues.csv). {{SQ_FILES}} Albanian and {{EN_FILES}} English files.
- {{ISSUES}} issues in `data/issues.csv` (texts in the wrong language, article headings missing from the source, misprinted or printed out of order, acts with different article counts in the two languages and why, repealing acts outside the record).
- `check_words.py` (independent letters-and-digits check against the raw source): {{CW_CHECKED}} texts; {{CW_SAME}} with every letter in place; {{CW_REORDERED}} with the same words in another order (table cells and OCR text layers, read in a different order by the builder and by the check, and acts with a heading printed out of order, whose article files the check reads by number); {{CW_SPACING}} differing only in where letter-spaced words break; {{CW_BAD}} with letters that differ: {{CW_LIST}} (act, language). The one known case, 13513 sq, is a defect of the PDF's text layer: on page 24 (a fill-in template annexed to the law) one line is printed in a font that maps only some of its glyphs to letters, so the builder's reader (PyMuPDF `dict`, flags whitespace and media-box clip) gives "dhe Bank ë … ë r Rind ë p ë r Projekti" where "dhe Bankës Evropiane për Rindërtim dhe Zhvillim lidhur me Huanë për Projektin" is printed, and the check's reader (`rawdict`, default flags) gives nothing. It is left as extracted; nothing was corrected by hand. Number-only differences (page numbers kept inside tables, table cells in another order) are counted apart.
- Two builds from the same cache give the same `main` hash.

## Decisions made by hand

- As enacted, not replayed: the Gazette keeps no dated series of consolidated versions to check a replay against (NATIONAL-CURRENT-BRIEF shape 3). Since {{CONSOLIDATED_FIRST}} it has published one consolidated text each for {{CONSOLIDATED}} laws ("(KONSOLIDUAR)", retrieved {{CONSOLIDATED_RETRIEVED}}); they are listed in `data/consolidated.csv` with their publication dates and the law in this record they consolidate ({{CONSOLIDATED_MATCHED}} matched by number), and are not commits: a single recent consolidation per law is not a dated history, and would sit on top of an as-enacted record.
- Article files. Headings are taken 1, 2, 3 ... in order. Where the expected heading is missing before the next one, the parser takes, in this order: a heading in another spelling ("Nen 57", "Nenin 52", "Neni i 28", "Articles 22", the other language's word, OCR forms such as "Neni l2" or "NENI 1O", and one run into the line before it, which is split there); "Chapter N" printed for "Article N"; outside amending acts, a lone heading with a wrong number standing between the two (a misprint); a heading printed out of order ("Neni 25, 27, 28, 26, 30": the file of 26 holds the text that follows its heading). Each of these is listed in `data/issues.csv`. A table of contents read as articles is dropped when the real articles start again at 1. The act's own articles end when what follows starts again at article 1 (a ratified agreement or an annex) or comes after the signature, so those texts stay in the last file. Constitutional Court judgments are one file. Words are never changed: only where a file starts.
- English documents that are the Albanian text ({{EN_LEFT_OUT}}; by the common-word test in `text.py`, and for most the same PDF file as the Albanian one) are left out of `en/` and listed in `data/en-left-out.csv`.
- The 2008 Constitution and its amendments were added to the list by ActID; the Constitution is the text as adopted (it still has the transitional chapter), dated 15 June 2008 by its art. 162.
- A repeal is applied only when the repealed act's page says "Shfuqizuar nga" (repealed by) an act in this record, or the repealing act says "Shfuqizon" and the Gazette marks the other act repealed. Partial repeals and Constitutional Court annulments are listed, never applied.
- Page numbers, the gazette's running header (with the running title printed in the band just under it) and, in PDFs, any line of 12 or more characters that recurs in the top 90 pt of two or more pages are dropped; nothing else is. Scanned pages (fewer than 40 letters and an image) are skipped.
- In-force rules that are events (promulgation) are dated by the Gazette's publication date and labelled.

## What the AI did and did not do

The fetcher, parser, builder and checks were written by Claude Code running Claude Opus 5.5 (`claude-opus-5-5`). No AI model runs when the history is built or checked, and no AI wrote, translated or corrected any legal text: every word in the act files is the Gazette's.

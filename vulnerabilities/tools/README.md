# Tools

The scripts behind this Kosovo-only run of global-law's vulnerability detectors. They run inside a copy of
[global-law/vulnerabilities/scripts](https://github.com/lexifina/global-law/tree/main/vulnerabilities/scripts) (Python 3.11+,
`pip install duckdb pyarrow`), with a bare clone of this repository at `sources/corpus/kosovo-law.git`, a blobless bare
clone of global-law at `sources/global-law.git`, and a `pins.json` that names only kosovo-law and its commit (language
`sq`, code `XK`). `build_vulns.py`, `flags_chart.py`, `late_ext_select.py`, `late_ext_rebut.py`, `patch_xk.py`,
`measure_missed.py`, `check_signature_dates.py`, `runlaw_cfg.sh` and `config.json` sit three folders up, next to the copy of global-law
(`gl/vulnerabilities/scripts/`).

| Script | What it does |
| --- | --- |
| `run.sh` | Indexes the history and texts, maps paths to the folders since a move (`map_moved.py`; this repository has none), adds this repository's history rows, and runs the detectors (`bash run.sh <shards>`) |
| `add_root.py` | Builds the history rows from this repository's own commits (global-law replays it only up to an earlier commit), so the history detectors read every change |
| `run_triage.sh` | The model review: the 40 strongest flags per category, the 40 strongest lapsed time limits in law texts, and the empty periods |
| `runlaw_cfg.sh` | The review of the 40 strongest lapsed time limits in law texts again, with law texts read from `config.json` (it sits next to `config.json`; reviews already made are kept) |
| `late_ext_select.py` | Chooses the empty periods for global-law's review of that category (there were none here) |
| `late_ext_rebut.py` | Adds the second, arguing-against pass to the empty-period review, as `triage.py` does for the other categories |
| `build_vulns.py` | Builds `data/flags.csv`, `data/reviewed.csv` and `data/by_category.csv` from the findings and the model review |
| `flags_chart.py` | Draws the chart at the top of the READMEs, in Albanian and English, light and dark |
| `config.json` | The repository, the Albanian category names and chart labels, and what is not law: the top-level folders of court decisions (`aktgjykim/`, `aktgjykime/`, `aktvendim/`, `mendim/`, `urdher/`, `urdhera/`), the English translations (`en/`), `registry/`, `data/`, `tools/`, the root files, each act's `README.md`, and the 325 Constitutional Court decisions this repository files among the acts (324 folders in `vendim/`, one in `rregullore/`) |
| `patch_xk.py` | The Kosovo fix below, in the copy of global-law's scripts (`python -X utf8 patch_xk.py <scripts dir>`; a fix already in place is skipped) |
| `measure_missed.py` | Counts the places in law texts where "deri" is followed by a past date, which of them the time-limit search flagged, and the forms of those it misses (the numbers in the READMEs) |
| `check_signature_dates.py` | Hand-check helper: for each retroactive-date flag on an act that takes effect on or after its signature, whether the signature date the repository read is printed at the head of the act or with its signature |
| `patch_detectors.py` | Fixes blind spots found in runs on several country repositories in the copy of global-law's scripts (`python -X utf8 patch_detectors.py <scripts dir>`; a fix already in place is skipped) |
| `patch_detectors_vi.py`, `patch_es.py`, `patch_ca.py`, `patch_en.py`, `patch_de.py`, `patch_en_et.py`, `patch_co.py`, `patch_sv.py` | The same for the Vietnamese, Spanish, Catalan, English (two rounds), German, Colombian and Salvadoran blind spots found by other runs; they change nothing here, but `redo.py` runs them on every repository |
| `map_moved.py` | Rewrites the paths in the history table to each act's folder after a repository moves its act folders (`data/paths.json`); this repository has no such file, so it changes nothing here |
| `patch_build_r7.py` | Brings a country's `build_vulns.py` up to date: lapsed-limit reviews matched on 400 characters of context, not 80, and a file deleted before a folder move linked under its old folder (already applied to the `build_vulns.py` here) |
| `redo.py` | Runs those patches, then again only the scans and detectors the fixes change, the model review of lapsed time limits, references to deleted provisions and empty periods, and the build (`python -X utf8 redo.py <run folder> [--keep-reviews] [--full]`; `--full` runs every step again through `run.sh`; `EMBED_FONTS` names the script that embeds the chart's fonts). It does not run `patch_xk.py`; run that first |

The model review needs `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` and `LLM_AUTH` set for an OpenAI-compatible Responses API.
It was run as `bash run_triage.sh '^(aktgjykim|aktgjykime|aktvendim|mendim|urdher|urdhera|en|registry|data|tools)/|^(README|REPRODUCE|SOURCES|LICENSE|laws\.csv|corpus\.json)|/README\.md$'`.
That expression does not know the Constitutional Court decisions filed in `vendim/`, and after the fixes below some of
them were among the "law texts" it reviewed, so `runlaw_cfg.sh` drew the 40 strongest lapsed time limits in law texts
again from `config.json`'s list after each run and reviewed those not yet reviewed (one, then two; one survived).

The detectors in this copy already carry every fix of `patch_detectors.py` and the other patches above. Changes made for
this repository:

- `add_root.py` counts the `Kind` value `treaty` (the 179 international agreements in `marreveshje/`) as a change to the
  law, with `enacted`, `decree` and `law`, which it already counted. `court` (the Constitutional Court's judgments and
  judges' opinions) keeps its own kind, so the history detectors leave it out; the court's other decisions are committed as
  `decree` and are set apart by `config.json` instead.
- `patch_xk.py`, Albanian dates: the time-limit search also reads "deri me" (without the diacritic), "deri mé" and
  "deri m€" (the Gazette's text layer often prints "ë" as "é" or "€"), "deri" right before a date ("deri 31 dhjetor
  2014"), and "datë" before the date in those prints and without its diacritic ("deri me daté 10 shtator 2021", "datén",
  "daten") or as "dt.". The two fixes were made one after the other, each followed by `run.sh` from `add_root.py` on and a
  second `run_triage.sh` that kept every review already made. Lapsed time limits went from 1,179 flags to 2,847 and then
  3,009, and in law texts from 242 to 338 and then 370; of the 349 places in law texts where "deri" is followed by a past
  date, the search now reads 338 (225 before). Of the other 11, 5 put "të vitit" before the year ("deri më 30 nëntor të
  vitit 2024"), which the Albania run also left open. 71 lapsed time limits were reviewed in all, two more surviving than
  in the first review; both are spent.
- `build_vulns.py` gives a retroactive-date flag the path of a law file its act's commit wrote: it took the
  alphabetically first path, which for an act of the list of laws was its English translation (`en/ligje/...`, counted as
  not law) and for an act that repealed another was a file of the repealed act. 13 acts of the list of laws moved into the
  law texts (151 of the 153 retroactive dates).

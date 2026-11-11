# How this repository was made (Kosovo)

This file is written by the build on 2026-11-11, the day the source data was retrieved.

## Sources

| Source | Address | Retrieved | Licence |
| --- | --- | --- | --- |
| Gazeta Zyrtare e Republikës së Kosovës: acts by category, as published | <https://gzk.rks-gov.net> | 2026-11-11 | Official texts, outside copyright (Law No. 08/L-205, art. 6(1)) |

Every word of law in this repository comes from these sources. Lexifina reads them and records each act's dated versions, and the laws that made each change, in one corpus file. This repository is built from that file.

## What is in it

| Act | Title | Versions | Span |
| --- | --- | ---: | --- |
| 5061 acts | every act, with its kind, number, status and span, is listed in [ACTS.md](ACTS.md) | 5061 | |

The build made 5126 commits:

| Commits | Kind |
| ---: | --- |
| 5126 | first version of an act |
| 0 | one law on its in-force day |
| 0 | changes no amendment note explains, credited to the publisher |

Other counts:
- 0 commits on the branch `future`: laws not yet in force on 2026-11-11.
- 0 commits dated 1 January 1970: in force before 1970, with the real day in their `In-force` trailer.
- 5064 laws in the record.
- 10158 tags.

## Dates

Each commit is dated at noon (Europe/Belgrade) on the day the change took effect. The other dates, enacted and published, are trailers.

When a law gives no date of its own, the default rule applies: Each act states its own entry into force ('Hyrja në fuqi'), usually a number of days after publication in the Official Gazette, the publication day or a date. https://gzk.rks-gov.net

## How the history is built

`tools/build/build.py` (and, for later publishes, `tools/build/append.py`) turns the corpus into this history in one pass: one commit per law, on the day it took effect. The same corpus always gives the same commit hashes. `tools/build/check_repo.py` reads every version back from git and compares it with the corpus. `tools/on.py` shows the law as it stood on any date. The corpus format is described in `tools/build/SCHEMA.md`.

- Corpus: sha256 `33b4451b6cd899880c6d6a6b689cfca0c7f2f3be6912a3de6a5ada47030ca11a` (169948173 bytes).
- Builder blob hashes (`git hash-object`): `build.py` `facbd764a235a856bc6f90b65043607998c92623`, `check.py` `f7f9c39fff1b1f9a3aded2ad3364a27fb0908033`, `on.py` `0be88de7820b2dafe9f94fa40472a48776aa4cf5`.
- Python 3.12.10; git version 2.46.0.windows.1.

## Checks

Not yet run for this build.

No second build of this corpus has been compared yet.

## Decisions made by hand

- Every act's decisions made by hand (966 in all) are listed in that act's own README.md, under "Decisions made by hand".

## What AI did and did not do

The scripts that read the sources and build this repository were written by Claude Code running Claude Opus 5.5 (`claude-opus-5-5`) under Lexifina's direction.

No model wrote, translated or corrected legal text. No model runs at build time. Every word of law in this repository comes from the official sources above.

The commit messages are written by `build.py` from the source data.

Model use at data-build time:
- none

# Sources for Kosovo

| Source | Kind | Past versions by date | Names the amending act | API or bulk | Format and licence | Used here |
|---|---|---|---|---|---|---|
| [Official Gazette of the Republic of Kosovo](https://gzk.rks-gov.net) (Gazeta Zyrtare) | Official legislation, Albanian, Serbian and English | no (each act as enacted; since {{CONSOLIDATED_FIRST}}, one consolidated text for each of {{CONSOLIDATED}} laws, listed in data/consolidated.csv, not used as history) | yes: each act's page links the acts that amend, supplement or repeal it | no (ASP.NET pages, plain GET and form postbacks) | HTML text layer, or the gazette PDF; official texts excluded from copyright (below) | yes: every act in the list of laws, Albanian and English |

## Legal basis for reuse

The Gazette's site has no terms of use; its footer reads "Copyright ZKM - MAP (c) 2022" (the Office of the Prime Minister and the Ministry of Public Administration, for the site). The texts themselves are outside copyright:

- **Law No. 08/L-205 on Copyright and Related Rights** (Official Gazette, 12 October 2023; in this record at `ligje/08-l-205/neni-006.md`), **article 6(1)**:
  - Albanian: "Mbrojtja e të drejtës së autorit nuk përfshinë tekstet zyrtare të natyrës legjislative, administrative dhe gjyqësore dhe përkthimet zyrtare të teksteve të tilla."
  - English (official translation): "Copyright protection shall not extend to official texts of a legislative, administrative and judicial nature, and the official translations of such texts."

## Access

- robots.txt (checked 2026-10-28 and 2026-10-29): `User-agent: *` disallows only application folders (`/AppCode/`, `/App_Data/`, `/Scripts/` ...) and `/gzk.asmx`; no rule names an AI agent; no Crawl-delay.

Research guides that cover every country: [GlobaLex](https://www.nyulawglobal.org/globalex/) and the [Law Library of Congress Guide to Law Online](https://www.loc.gov/research-centers/law-library-of-congress/researcher-resources/guide-to-law-online/).

# npp-finder

**Filter new Wikipedia pages by whether their references contain URLs — a New Pages Patrol triage utility.**

## Why this exists

New Pages Patrol reviewers face a persistent backlog of thousands of unreviewed
articles. A common red flag during review is references that cite a source
*without providing a clickable link*. These come in several forms:

| Reference type | Wikitext | Verifiable online? |
|---|---|---|
| Citation template with a URL | `<ref>{{cite web \| url=https://... \| title=...}}</ref>` | ✅ Yes |
| Citation template — no URL | `<ref>{{cite book \| title=X \| year=2020}}</ref>` | ❌ Only if you own the book |
| Plain-text citation | `<ref>Smith, J. *The Book*. 2020, p. 42.</ref>` | ❌ No link at all |
| Shortened footnote | `<ref>{{harvsp\|Smith\|2020}}</ref>` (points to bibliography) | ❌ Indirection; bibliography may lack URLs |
| Named ref — no URL in definition | `<ref name="smith">{{cite journal \| title=X}}</ref>` | ❌ No URL parameter |

A page where **every single reference lacks a URL** is difficult to verify
quickly. Reviewers must either own the cited books, chase down print-only
journals, or take the citations on faith. These pages deserve extra scrutiny —
and `npp-finder` surfaces them automatically.

## What it does

1. Pulls all newly created mainspace pages from the last N days via the
   MediaWiki Action API (`list=recentchanges&rctype=new`)
2. Batch-fetches each page's raw wikitext, size, revision ID, and categories
   in one combined query (50 pages per API call via
   `prop=revisions|info|categories`)
3. Parses every `<ref>` tag with `mwparserfromhell` — proper AST parsing,
   not fragile regex
4. Resolves named references (`<ref name="x" />` → finds the original
   definition elsewhere on the page)
5. Checks each reference for:
   - Raw `http://` or `https://` strings in the body text
   - Citation template parameters: `url`, `archive-url`, `chapter-url`,
     `conference-url`, `contribution-url`, `transcript-url` (and their
     camelCase variants)
   - Nested templates inside references (e.g. a `{{cite web}}` inside a
     `<ref>` tag)
6. Enriches each page with:
   - **Page size** (bytes) — from `prop=info`
   - **Infobox presence** — parsed via `mwparserfromhell` for `{{Infobox *}}` templates
   - **Category count** — from `prop=categories`
   - **Previous deletions** — checks the deletion log for same-title matches
   - **Article quality prediction** — Lift Wing ML model (`Stub` / `Start` / `C` / `B` / `GA` / `FA`)
   - **Creator edit count** — from `list=users&usprop=editcount`
7. Outputs the **pages where zero references have a URL** — the strict set,
   with all enrichment fields in the same table

Pages with no references at all are reported separately. Pages with *some*
URLs and *some* URL-free refs are excluded from the main output because at
least one citation is verifiable online.

## Installation

```bash
git clone https://github.com/fuzheado/npp-finder.git
cd npp-finder
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requires Python 3.10+ and an internet connection. No Wikipedia account needed
for read-only queries.

## Usage

### Basic scan — last 7 days, 100 pages

```bash
npp-finder --days 7 --limit 100
```

### JSON output (for piping into other tools)

```bash
npp-finder --days 7 --limit 200 --output json > suspicious.json
```

### CSV for a spreadsheet

```bash
npp-finder --days 7 --limit 200 --output csv > suspicious.csv
```

### Wikitable for posting on-wiki

```bash
npp-finder --days 7 --limit 200 --output wikitable > patrol-log.wiki
```

Paste the contents of the file directly into any wiki page. It renders with:
- **Article titles** wikilinked (`[[Title]]`) — clickable
- **Usernames** linked to their user page (`[[User:Name|Name]]`) — clickable
- `class="wikitable sortable"` for automatic styling and column sorting
- Summary embedded as an HTML comment at the top

Example output:

```wikitext
{| class="wikitable sortable"
! Date
! Title
! Creator
! Edits
! Size
! Infbx
! Cats
! Del?
! Quality
! Refs
! URL
! Sample ref
|-
| 2026-06-09
| [[LOL: Slutty Bass]]
| [[User:Vvenom974|Vvenom974]]
| 148
| 4,364
| Y
| 6
| N
| Start
| 3
| 0
| <code>[cite Instagram]</code>
|-
| 2026-06-09
| [[Betka Ait Mokran]]
| [[User:Naslechat|Naslechat]]
| 402
| 2,175
| Y
| 11
| N
| Stub
| 2
| 0
| <code>[harvsp]</code>
|}
```

### Skip slow ML predictions

The Lift Wing quality model adds ~0.15s per page. Use `--no-quality` to skip it:

```bash
npp-finder --days 7 --limit 100 --no-quality
```

### Example output (terminal table)

```
Pages created in last 1 days: 30
Pages with references: 27
Pages with ONLY non-URL references: 2
Pages with no references at all: 3

+----------+------------------+-----------+--------+--------+------+------+------+--------+------+-----+----------------------------+
|   Date  |      Title      |  Creator | Edits |  Size | Infbx| Cats| Del?| Quality| Refs| URL|         Sample ref         |
+----------+------------------+-----------+--------+--------+------+------+------+--------+------+-----+----------------------------+
| 2026-06-09| LOL: Slutty Bass| Vvenom974|    147|  4,366|  Y  |    6|  N  | Start |    3|   0| [cite Instagram]           |
| 2026-06-09| Betka Ait Mokran| Naslechat|    402|  2,175|  Y  |   11|  N  |  Stub |    2|   0| [harvsp]                   |
+----------+------------------+-----------+--------+--------+------+------+------+--------+------+-----+----------------------------+
```

### Column guide

| Column | What it tells you |
|---|---|
| **Date** | When the page was created |
| **Title** | Page title (linked on Wikipedia) |
| **Creator** | The user who created the page |
| **Edits** | How many total edits that user has made — a rough experience gauge |
| **Size** | Page size in bytes — 400-byte "articles" are almost always stubs or junk |
| **Infbx** | Does the page have an `{{Infobox ...}}` template? Missing on a person/place/film = red flag |
| **Cats** | Number of categories assigned — 0–1 = incomplete, 5+ = well-structured |
| **Del?** | Has a page with this **exact title** been deleted before? If Yes, CSD G4 may apply |
| **Quality** | Lift Wing ML prediction: Stub / Start / C / B / GA / FA (see *What the quality labels mean* below) |
| **Refs** | Total reference count on the page |
| **URL** | How many of those references contain a URL |
| **Sample ref** | A snippet of one URL-free reference so you can see what kind it is |

### What the quality labels mean

| Label | Meaning (approximate) |
|---|---|
| **Stub** | Very short — a sentence or two, almost certainly needs expansion |
| **Start** | Basic coverage — some structure but still incomplete |
| **C** | Decent article — covers the topic reasonably |
| **B** | Good article — nearly complete, well-sourced |
| **GA** / **FA** | Good Article / Featured Article quality — rare on new pages |

### Interpreting the sample column

The rightmost column shows a snippet of one of the URL-free references on the
page, with wikitext formatting simplified:

- `[harvsp]` — a shortened footnote template (`{{harvsp|Author|Year}}`) that
  points to a bibliography section
- `[Cite journal]` — a `{{cite journal}}` template with no `|url=` parameter
- `[cite Instagram]` — an Instagram citation, which is rarely a reliable source
- `Venters, Colin C., et al. "Sof...` — a plain-text reference with no
  template wrapping at all (no title, no publisher, no link)

## Options

| Flag | Default | Description |
|---|---|---|
| `--days` | `7` | Look back this many days from now |
| `--limit` | `100` | Maximum new pages to check |
| `--output` | `table` | Output format: `table`, `json`, `csv`, or `wikitable` |
| `--unreviewed-only` | off | Only show unpatrolled pages (**requires `patrol` user right**) |
| `--no-quality` | off | Skip Lift Wing ML quality predictions (faster, fewer API calls) |
| `--quiet` | off | Suppress progress messages on stderr |

## Limitations

- **Read-only.** This tool does not tag pages, leave talk page messages, or
  nominate for deletion. It's a discovery aid, not an automated reviewer.
- **Inline refs only.** References defined inside `<ref>` tags are fully
  analyzed. List-defined references and bibliography-only citations outside
  `<ref>` tags are checked but some edge cases may be missed.
- **Recent changes window.** The `recentchanges` API has a practical limit of
  ~30 days of history.
- **No authentication needed.** For read-only queries, no Wikipedia login is
  required. `--unreviewed-only` needs the `patrol` user right.
- **Quality predictions are best-effort.** The Lift Wing model may be unavailable
  or return errors for very new pages. Predictions are informational only and
  should not be treated as authoritative.

## File layout

| File | Purpose |
|---|---|
| `src/npp_finder/api.py` | `NPPSession` — API client with retry-on-429, batched page details, edit counts, deletion log, Lift Wing quality |
| `src/npp_finder/refcheck.py` | `has_any_url_refs()` + `has_infobox()` — wikitext parsing with `mwparserfromhell` |
| `src/npp_finder/cli.py` | CLI entry point — argparse, terminal table, JSON, CSV output |

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
2. Batch-fetches each page's raw wikitext (50 pages per API call)
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
6. Outputs the **pages where zero references have a URL** — the strict set

Pages with no references at all are reported separately (they're a different
kind of problem). Pages with *some* URLs and *some* URL-free refs are excluded
from the main output because at least one citation is verifiable online.

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

### Example output (terminal table)

```
Pages created in last 1 days: 200
Pages with references: 179
Pages with ONLY non-URL references: 3
Pages with no references at all: 21

+----------+-------------------------+------------+------+-------+----------------------------------+
|   Date   |          Title          |  Creator   | Refs |  URL  |        Sample non-URL ref        |
+----------+-------------------------+------------+------+-------+----------------------------------+
| 2026-06-09 | Betka Ait Mokran        | Naslechat  |    2 |     0 | [harvsp]                         |
| 2026-06-09 | Shakajlura              | SlvrHwk    |    1 |     0 | [Cite journal]                   |
| 2026-06-09 | Software sustainability | JenniGross |    1 |     0 | Venters, Colin C., et al. "Sof   |
+----------+-------------------------+------------+------+-------+----------------------------------+
```

### Interpreting the sample column

The rightmost column shows a snippet of one of the URL-free references on the
page, with wikitext formatting simplified:

- `[harvsp]` — a shortened footnote template (`{{harvsp|Author|Year}}`) that
  points to a bibliography section. The inline ref has no URL; the
  bibliography entry might or might not.
- `[Cite journal]` — a `{{cite journal}}` template with no `|url=` parameter.
- `Venters, Colin C., et al. "Sof...` — a plain-text reference with no
  template wrapping at all.

## Options

| Flag | Default | Description |
|---|---|---|
| `--days` | `7` | Look back this many days from now |
| `--limit` | `100` | Maximum new pages to check |
| `--output` | `table` | Output format: `table`, `json`, or `csv` |
| `--unreviewed-only` | off | Only show unpatrolled pages (**requires `patrol` user right**) |
| `--quiet` | off | Suppress progress messages on stderr |

## Limitations

- **Read-only.** This tool does not tag pages, leave talk page messages, or
  nominate for deletion. It's a discovery aid, not an automated reviewer.
- **Inline refs only.** References defined inside `<ref>` tags are fully
  analyzed. List-defined references (`<ref name="x">` in a `{{reflist|refs=}}`
  block) are handled via named-ref resolution, but bibliography-only citations
  (e.g. `* {{cite book|...}}` outside `<ref>` tags) are not deeply checked for
  URL presence.
- **Recent changes window.** The `recentchanges` API has a practical limit of
  ~30 days of history. For longer time windows, use the `--days` flag
  cautiously — you may get fewer results than expected if pages age out.
- **No authentication needed.** For read-only queries, no Wikipedia login is
  required. The `--unreviewed-only` flag, however, needs the `patrol` user
  right (New Page Reviewer or admin). Without it, the flag is silently
  skipped.

## Contributing

Bug reports and feature requests are welcome on the
[issue tracker](https://github.com/fuzheado/npp-finder/issues).

The codebase is small and intentionally simple:

| File | Purpose |
|---|---|
| `src/npp_finder/api.py` | `NPPSession` — API client with retry-on-429, batch wikitext fetch, date filtering |
| `src/npp_finder/refcheck.py` | `has_any_url_refs()` — parses wikitext with `mwparserfromhell`, resolves named refs, detects URLs in 18+ template parameter names |
| `src/npp_finder/cli.py` | CLI entry point — argparse, terminal table, JSON, and CSV output formatters |

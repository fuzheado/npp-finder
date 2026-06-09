# npp-finder

Find new English Wikipedia pages whose references contain **no URLs** — a New Pages Patrol utility.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Usage

```bash
# Table output (default) — pages from last 7 days
npp-finder --days 7 --limit 100

# JSON output
npp-finder --days 7 --limit 100 --output json

# CSV output
npp-finder --days 7 --limit 100 --output csv

# Only unpatrolled pages (requires patrol user right)
npp-finder --days 7 --limit 100 --unreviewed-only
```

## How It Works

1. Queries `list=recentchanges&rctype=new` for newly created mainspace pages
2. Batch-fetches raw wikitext (50 pages per API call)
3. Parses each page with `mwparserfromhell` to find all `<ref>` tags
4. Resolves named refs (e.g., `<ref name="smith" />` → finds the definition)
5. Checks each reference body for:
   - Raw `http://` or `https://` URLs
   - Citation templates with `|url=`, `|archive-url=`, etc. parameters
   - Nested templates within refs
6. Outputs pages where **every** reference lacks a URL

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--days` | `7` | Days back to scan |
| `--limit` | `100` | Max pages to check |
| `--output` | `table` | `table`, `json`, or `csv` |
| `--unreviewed-only` | `false` | Filter to unpatrolled pages (needs patrol right) |
| `--quiet` | `false` | Suppress progress output |

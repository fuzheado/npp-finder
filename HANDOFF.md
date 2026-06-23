# npp-finder — Handoff Document

**Generated:** 2026-06-23
**Repository:** https://github.com/fuzheado/npp-finder
**Current commit:** `739af59`

---

## 1. What it does

`npp-finder` scans newly created English Wikipedia pages and finds those
where **every reference lacks a clickable URL** — a red flag for NPP
reviewers because the citations cannot be verified online.

### One-sentence pitch

> *A CLI tool that surfaces unreviewable Wikipedia articles by detecting
> references with no URLs, enriched with author metadata, ML quality
> scores, and deletion history.*

---

## 2. Architecture

### Codebase (1,038 lines of Python)

```
npp-finder/
├── pyproject.toml              # Dependencies: requests, mwparserfromhell
├── README.md                   # User-facing documentation
├── IDEAS.md                    # Tiered list of future features
└── src/npp_finder/
    ├── __init__.py             # Version
    ├── api.py   (308 lines)    # NPPSession — all API interaction
    ├── cli.py  (480 lines)     # Entry point, pipeline orchestration, output
    └── refcheck.py (247 lines) # Reference URL detection logic
```

### The Two-Pass Pipeline (architecture lesson learned)

```
PHASE 1 — light (all pages):
  RecentChanges API → fetch wikitext → refcheck → filter matches

PHASE 2 — heavy (matches only):
  → fetch page metadata (size, categories)
  → fetch creator edit counts
  → check deletion history
  → fetch Lift Wing quality scores
```

**Why:** Phase 1 uses a lightweight `prop=revisions` call only. Phase 2
only enriches the ~2–5% of pages that actually match. A 300-page scan
went from ~50s to ~8s with this change.

### Key design decisions

| Decision | Rationale |
|---|---|
| `mwparserfromhell` for ref parsing | Handles nested templates, named refs, self-closing tags — regex would miss edge cases |
| Named refs resolved in two passes | First pass indexes all definitions; second pass evaluates refs against the index |
| Wikitext-only in phase 1 | `prop=revisions` is the smallest API call that gives us what we need for ref analysis |
| No `rcprop=patrolled` by default | Requires `patrol` user right — `permissiondenied` for unauthenticated users |
| 18+ URL parameter names checked | `url`, `archive-url`, `chapter-url`, `conference-url`, etc. (catches edge cases) |
| Lift Wing called last | Slowest operation (~0.15s/page) — only done for matches, and skippable via `--no-quality` |

---

## 3. Current Output

### Supported formats

| `--output` | Format | Use case |
|---|---|---|
| `table` | Terminal table with 12 columns | Interactive review |
| `json` | Structured JSON with full metadata | Piping into other tools |
| `csv` | Comma-separated values | Spreadsheet import |
| `wikitable` | MediaWiki `{| class="wikitable" |}` markup | Pasting into on-wiki reports |

### Current columns

```
Date | Title | Creator | Edits | Size | Infbx | Cats | Del? | Quality | Refs | URL | Sample ref
```

### Command-line flags

```
--days, --limit, --output, --unreviewed-only, --no-quality, --quiet
```

---

## 4. What's been tested

- **Live Wikipedia API calls** — 300-page scans run reliably
- **Edge cases handled:** bare URLs, template `url=` params, named refs
  (definition-before-reuse and reuse-before-definition), shortened
  footnotes (`harvsp`, `sfn`, `harvnb`), `archive-url`, nested templates,
  inline `||` cells in wikitables, zero-match fast path
- **27 test cases in the wikipedia-reference-verifiability skill** (in
  Wikipedia-AI-Skills repo), all passing

---

## 5. Related work in Wikipedia-AI-Skills

These skills were developed alongside or informed by npp-finder:

| Skill | Description |
|---|---|
| `pagetriage-api` | PageTriage extension — patrol status codes, API endpoints, permission model, patrol simulator |
| `wikipedia-reference-verifiability` | Reference URL detection library (refactored from npp-finder's refcheck.py) |
| `wikipedia-wikitables` | Wikitable creation, parsing, styling — `--output wikitable` uses this |
| `wikimedia-ml-services` | Lift Wing model integration (article quality, revert risk, topics) |

---

## 6. Next steps

### Quick wins (hours, not days)

| Priority | Feature | Effort | Why |
|---|---|---|---|
| 1 | **`pip install npp-finder`** on PyPI | ~30 min | Someone can `pipx install npp-finder` without cloning. Needs `pyproject.toml` tweaks and a PyPI token. |
| 2 | **Autocomplete / `--json` piping to `jq`** examples in README | ~15 min | Show users how to chain: `npp-finder --output json \| jq '.matches[] \| .title'` |
| 3 | **Filter by edit count** (`--min-edits`, `--max-edits`) | ~20 min | Trivial argparse addition, useful for focusing on new-user pages |
| 4 | **Filter by size** (`--min-size`) | ~10 min | Skip sub-stub pages entirely |

### New interfaces (medium effort)

| Interface | Effort | Rationale |
|---|---|---|
| **Web UI (Toolforge)** | 2–3 days | Deploy a lightweight Flask/FastAPI app on Toolforge Kubernetes. Pages loads results, reviewer clicks through. Would reach the most NPP reviewers (they're already on the web). |
| **Wiki bot report** | 1 day | Post a daily report to `Wikipedia:New pages patrol/Reports/No URL references` — a wikitable that updates daily via cron on Toolforge. Zero-install for reviewers; they read it on-wiki. |
| **~/.pi skill integration** | 4 hours | Package the tool as a pi skill so any coding agent can run `npp-finder --days 7` as a subagent task. Makes it available inside agent workflows. |

### The Web UI — rough sketch

```
                  ┌─────────────────────────┐
                  │   npp-finder Dashboard   │
                  │  (Toolforge Kubernetes)  │
                  └─────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
   ┌────────────┐      ┌────────────┐      ┌──────────────┐
   │ Scan form  │      │ Results    │      │ Page detail  │
   │            │      │ table      │      │ panel        │
   │ days: [__] │      │            │      │              │
   │ limit: [__]│      │ sortable   │      │ wikitext     │
   │ [Run]      │      │ clickable  │      │ ref analysis │
   └────────────┘      │ links      │      │ action btns  │
                       └────────────┘      └──────────────┘
```

### The Wiki Bot — workflow

```
Cron job (daily) → npp-finder --days 1 --limit 500 --output wikitable
                   → posts to Wikipedia:New pages patrol/Reports/Daily
                   → reviewers check the report as part of their routine
```

The bot would need:
- A Toolforge tool account with `patrol` right (or just post read-only reports)
- A bot password for the Action API login
- A cron job calling `python3 -m npp_finder.cli`

### Web dashboard — feature ideas

| Feature | Description |
|---|---|
| **One-click review** | Mark a page as "checked" (delegate to action=pagetriageaction) |
| **Session tracking** | Remember which pages you've already seen across visits |
| **Filter by SNG** | Toggle to highlight pages matching specific subject notability guidelines (via keyword detection — see Novem Linguae's DetectSNG script) |
| **Collaborative triage** | Multiple reviewers can claim pages, reducing duplicate work |
| **Bookmarklet** | A browser bookmark that runs npp-finder on the current page and shows results in an overlay |

### See also

- `IDEAS.md` — the full catalog of ~25 feature ideas, from trivial (short description detection) to ambitious (interactive filtering dashboard, review priority score)

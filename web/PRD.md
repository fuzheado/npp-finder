# npp-finder Web Dashboard — Product Requirements

**Version:** 1.0-draft
**Date:** 2026-06-23
**Status:** Prototype

---

## 1. Overview

npp-finder is a New Pages Patrol (NPP) triage tool for English Wikipedia.
It scans newly created articles, applies user-selectable filters, and
displays matching pages in a sortable table with enrichment metadata
(creator experience, page size, categories, deletion history, ML quality
predictions).

The web dashboard makes this functionality available through a browser
interface, with real-time progress tracking during scans.

---

## 2. Goals

1. **Surface problematic new pages** — identify articles that exhibit red
   flags (no URL references, missing infobox, previously deleted title,
   no references at all)
2. **Accelerate NPP triage** — let a reviewer scan 100–500 pages in
   seconds and immediately see which ones need attention
3. **Enrich with context** — show creator experience, ML quality scores,
   and deletion history alongside the raw reference analysis, so reviewers
   can make informed decisions without leaving the dashboard
4. **Read-only** — no Wikipedia login required; no patrol actions taken
   from the dashboard

---

## 3. Target Users

- **New Page Patrol reviewers** on English Wikipedia (primary)
- **Wikipedia editors** curious about article quality on recently created pages
- **Tool researchers** studying new article patterns

---

## 4. Functional Requirements

### 4.1 Scan Configuration

| Requirement | Priority | Notes |
|---|---|---|
| User can set days back (1–30) | P1 | Default 7 |
| User can set max pages (10–500) | P1 | Default 100 |
| User can toggle quality predictions on/off | P1 | Lift Wing model is slow (~0.15s/page); skip for speed |

### 4.2 Filters

| Requirement | Priority | Notes |
|---|---|---|
| **No URL references** — pages with refs but zero clickable URLs | P1 | Default ON. Original npp-finder use case. |
| **No references at all** — pages with zero `<ref>` tags | P2 | |
| **Missing infobox** — pages without an `{{Infobox ...}}` template | P2 | |
| **Previously deleted (G4)** — title appears in deletion log | P2 | |
| Filters are combinable (AND logic) | P1 | |

### 4.3 Scan Execution

| Requirement | Priority | Notes |
|---|---|---|
| Scan runs in background thread | P1 | POST returns immediately |
| Progress bar with message updates | P1 | Polled via `/api/progress` |
| Progress messages detail each pipeline step | P1 | "Fetching wikitext...", "Analyzing references...", etc. |
| Concurrent scans blocked | P1 | In-memory lock, 429 if busy |

### 4.4 Results Display

| Requirement | Priority | Notes |
|---|---|---|
| Table with columns: Date, Title, Creator, Edits, Size, Infobox, Cats, Deleted, Quality, Refs, URL, Sample ref | P1 | |
| Article titles link to Wikipedia | P1 | `https://en.wikipedia.org/wiki/Title` |
| Usernames link to user page | P1 | `https://en.wikipedia.org/wiki/User:Name` |
| Summary bar showing scan stats | P1 | Total pages, matches, duration, timestamp |
| "No URL" column cells highlighted red | P1 | |
| Previously-deleted rows highlighted pink | P2 | |
| Download results as JSON | P2 | `/api/results` endpoint |
| Sortable by column | P3 | Future — uses `<th>` with `sortable` class |

### 4.5 About Panel

| Requirement | Priority | Notes |
|---|---|---|
| About button in header opens modal | P1 | |
| Modal explains what the tool does | P1 | Steps, column meanings, data sources |
| Modal explains Lift Wing / quality column | P1 | |
| Modal closes on × button or click-outside | P1 | |

### 4.6 API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Main page with cached results |
| `/scan` | GET | Scan form |
| `/scan` | POST | Start background scan |
| `/about` | GET | About modal HTML fragment |
| `/api/results` | GET | Cached scan results (JSON) |
| `/api/progress` | GET | Current scan progress (JSON) |
| `/api/scan` | POST | Synchronous scan returning JSON |

---

## 5. Non-Functional Requirements

| Requirement | Target | Notes |
|---|---|---|
| Scan time (100 pages, no quality) | < 10s | API calls are the bottleneck |
| Scan time (100 pages, with quality) | < 30s | Lift Wing adds ~0.15s/page |
| Scan time (500 pages, with quality) | < 120s | Warning in UI for large scans |
| Concurrent users | 1 scan at a time | Single in-memory lock; no queue |
| Browser support | Modern Chrome, Firefox, Safari | |
| Dependencies | Python 3.10+, FastAPI, uvicorn, jinja2 | |
| Deployment | Toolforge Kubernetes or local | |

---

## 6. Architecture

### 6.1 Two-Pass Pipeline

```
PHASE 1 (all pages):
  RecentChanges API → fetch wikitext → refcheck → apply filters

PHASE 2 (matches only):
  → fetch page metadata (size, categories)
  → fetch creator edit counts
  → check deletion history
  → fetch Lift Wing quality scores (if enabled)
```

### 6.2 File Layout

```
web/
├── app.py             # FastAPI application (API + scan logic)
├── requirements.txt   # Python dependencies
├── README.md          # Deploy instructions
├── templates/
│   ├── index.html     # Main page (scan form, results, progress)
│   └── about.html     # About modal content fragment
├── static/
│   └── style.css      # All styles
└── results.json       # Cached scan output (created at runtime)
```

### 6.3 Data Flow

```
Browser → POST /scan → start background thread → return progress page
Browser → GET /api/progress (every 500ms) → progress JSON
Background thread → _do_scan() → _save_results() → progress[status]=done
Browser → GET / → results page with fresh data
```

---

## 7. Future Considerations (post-v1)

| Feature | Notes |
|---|---|
| Persistent result history | Store past scans by date |
| Sortable table columns | Add client-side sorting via JS |
| Page detail view | Click a row to see full wikitext and per-ref breakdown |
| One-click patrol | OAuth login → `action=pagetriageaction` to mark reviewed |
| Collaborative triage | Claim pages, track who reviewed what |
| Schedule recurring scans | Cron-triggered daily report posted to a wiki page |
| More filters | By creator edit count threshold, by category, by topic (Lift Wing topic model) |
| Dark mode | CSS variable swap |

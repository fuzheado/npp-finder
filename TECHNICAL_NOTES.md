# Technical Notes — Lessons Learned

**Project:** npp-finder
**Period:** 2026-06-09 to 2026-06-23

---

## Architecture decisions

### Two-pass pipeline (Phase 1 light → Phase 2 heavy)

**Decision:** Fetch wikitext first (cheap — just `prop=revisions`), run
reference analysis on ALL pages, filter down to matches, THEN enrich
only the matches with expensive metadata.

**Why:** The original single-pass approach fetched size, categories, edit
counts, deletion history, and Lift Wing quality scores for every page
before analysis. For 300 pages, quality scores alone cost ~45 seconds
(~0.15s × 300). Since only 2–5% of pages typically match, ~95% of those
API calls were wasted.

**Result:** 300-page scan went from ~50s to ~8s (with `--no-quality`).

### Background thread + progress polling for web UI

**Decision:** The POST /scan endpoint starts a daemon thread, writes
progress to a shared dict, and returns immediately. The frontend polls
`/api/progress` every 500ms.

**Why:** The synchronous approach blocked the HTTP request for the entire
scan duration (potentially 60+ seconds). The browser would show a
spinner with no feedback. Polling gives granular progress updates.

**Trade-off:** Single in-memory lock (`SCAN_LOCK`) means only one scan
at a time. No queueing. A production version would need a job queue
(Redis + RQ / Celery).

---

## Bugs encountered

### 1. Checkbox hidden inputs accumulated across submissions

**Symptom:** Filters appeared to be ignored after the first scan.
"Only no references" returned all pages on the second use.

**Root cause:** The JS injected hidden `<input type="hidden" value="false">`
elements for unchecked checkboxes, but never removed old ones. On the
second submission, stale hidden `false` inputs sat alongside new
checkbox `true` values. FastAPI received both; the stale `false` won.

**Fix:** Mark injected inputs with `className = 'hf-input'` and remove
`.hf-input` elements at the start of each submit handler.

**Lesson:** Any client-side form manipulation that adds elements must
clean up after itself. Always clear injected elements before re-injecting.

### 2. HTML forms don't send unchecked checkboxes

**Symptom:** Filter checkboxes always defaulted to True regardless of
whether they were checked.

**Root cause:** The Python handler used `bool = Form(True)` as the
default. When a checkbox was unchecked, the browser didn't send the
field at all, so FastAPI used the default. Unchecking "No URL references"
still sent `filter_no_url=True`.

**Fix:** JS injects a hidden `false` input for every unchecked checkbox
before form submission. Python handler changed to `str = Form("false")`
with manual `.lower() == "true"` conversion.

**Lesson:** Forms + checkboxes + FastAPI is a known pitfall. Never rely
on browser sending unchecked checkbox values. Use hidden inputs or
intercept the form submission.

### 3. Jinja2 3.1.6 + Python 3.14 cache incompatibility

**Symptom:** `TypeError: cannot use 'tuple' as a dict key` when rendering
templates via Starlette's `Jinja2Templates`.

**Root cause:** Jinja2's template cache uses a cache key that includes
the `globals` dict. On Python 3.14, dict layout changes made the cache
key tuple unhashable. Starlette's `Jinja2Templates` wrapper triggered
this code path.

**Fix:** Bypassed Starlette's wrapper entirely. Use raw `jinja2.Environment`
+ `FileSystemLoader` directly with a `_render()` helper.

**Lesson:** FastAPI/Starlette's template integration can be fragile with
new Python versions. Use the Jinja2 API directly for more control.

### 4. MediaWiki API: patrol status requires the `patrol` right

**Symptom:** `action=query&list=recentchanges&rcprop=patrolled` returned
`permissiondenied` for unauthenticated users.

**Root cause:** The `patrolled` flag in the `patrolmarks` or `patrolled`
`rcprop` value requires the `patrol` or `patrolmarks` user right. Most
users don't have this.

**Fix:** Omit `patrolled` from `rcprop` by default. The `--unreviewed-only`
flag adds it back with a warning that it requires authentication.

**Lesson:** Wikimedia API permissions are granular. Test without auth
first. Document which features require which rights.

### 5. Lift Wing API uses ORES-compatible response format

**Symptom:** Quality score predictions returned as `None` even though the
API responded with 200.

**Root cause:** The response format is the older ORES-compatible nested
structure (`enwiki.scores.<rev_id>.articlequality.score.prediction`),
not the simpler `result.prediction` format documented in some examples.

**Correct path:**
```python
payload.get("enwiki", {}).get("scores", {}).get(str(rev_id), {}).get("articlequality", {}).get("score", {}).get("prediction")
```

**Lesson:** Always dump and inspect the full API response before writing
the parser. Don't assume the format from documentation.

---

## Performance characteristics

| Operation | Time per unit | Notes |
|---|---|---|
| RecentChanges API (500 pages) | ~1s | Paginated, 500 per call |
| Batch wikitext fetch (50 pages) | ~0.3s + API latency | |
| Reference analysis (per page) | ~5ms | mwparserfromhell is fast |
| Lift Wing quality (per rev_id) | ~0.15s | POST + JSON parse. The bottleneck. |
| User edit counts (50 users) | ~0.1s + API latency | |
| Deletion log check (5000 events) | ~2s | 10 paginated calls |
| Page metadata (50 pages) | ~0.3s + API latency | |

---

## macOS-specific issues

- **PEP 668 (`externally-managed-environment`)** — Homebrew Python 3.14
  blocks `pip install` outside a venv. Always use `python3 -m venv .venv`
  + `source .venv/bin/activate` + `pip install`. Documented in README.
- **Port in use (Errno 48)** — The dev server on port 8080 persists after
  Ctrl+C. Use `lsof -ti :8080 | xargs kill` to free it.
- **Jinja2 3.1.6 cache bug** — See above. Only manifests with Python 3.14 /
  Homebrew Python. Ubuntu/Docker with Python 3.11 likely unaffected.

---

## Testing patterns

- **API-level testing** — Test the `/api/scan` synchronous endpoint with
  `curl` to verify filter logic without the JS/browser layer. This
  isolates backend bugs from frontend bugs.
- **Polling flow testing** — Simulate the full browser flow: POST /scan,
  poll /api/progress until done, GET /api/results. Captures race
  conditions in the background thread + `_save_results` + `_load_results`
  chain.
- **Hidden field accumulation** — Submit the same form twice with
  different filter settings and verify correct results on the second
  run. This catches DOM accumulation bugs that work on the first
  submission and fail on subsequent ones.

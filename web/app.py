"""npp-finder web dashboard — FastAPI application.

Supports background scan with progress polling, multiple filter criteria,
and an info panel explaining the tool.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Ensure the npp-finder package is importable
_repo_root = Path(__file__).resolve().parent.parent
_src = _repo_root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from npp_finder.api import NPPSession
from npp_finder.refcheck import has_any_url_refs, has_infobox, detect_page_type

app = FastAPI(title="npp-finder Dashboard")

_template_dir = str(Path(__file__).parent / "templates")
_env = Environment(
    loader=FileSystemLoader(_template_dir),
    autoescape=select_autoescape(["html", "xml"]),
)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

RESULTS_FILE = Path(__file__).parent / "results.json"
SCAN_LOCK = threading.Lock()

# In-memory scan progress: { "status": str, "message": str, "pct": int, "done": bool }
_scan_progress: dict[str, Any] = {}


def _render(name: str, context: dict[str, Any]) -> str:
    template = _env.get_template(name)
    return template.render(**context)


# ---------------------------------------------------------------------------
# Routes — pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main page — shows last scan results or empty state."""
    results = _load_results()
    return HTMLResponse(
        _render("index.html", {
            "request": request,
            "results": results,
        })
    )


@app.get("/about", response_class=HTMLResponse)
async def about():
    """Return the About modal content as HTML."""
    return HTMLResponse(_render("about.html", {}))


@app.get("/scan", response_class=HTMLResponse)
async def scan_form(request: Request):
    """Show the scan page (also used as the progress/results page)."""
    return HTMLResponse(
        _render("index.html", {
            "request": request,
            "results": _load_results(),
        })
    )


@app.post("/scan", response_class=HTMLResponse)
async def run_scan(
    request: Request,
    days: int = Form(7),
    limit: int = Form(100),
    no_quality: bool = Form(False),
    filter_no_url: str = Form("false"),
    filter_no_refs: str = Form("false"),
    filter_no_infobox: str = Form("false"),
    filter_was_deleted: str = Form("false"),
):
    """Start a scan in a background thread and return the progress page."""
    acquired = SCAN_LOCK.acquire(blocking=False)
    if not acquired:
        return HTMLResponse(
            "<div class='alert alert-warning'>A scan is already running. "
            "Please wait for it to finish.</div>",
            status_code=429,
        )

    def _run():
        global _scan_progress
        try:
            results = _do_scan(
                days=days,
                limit=limit,
                no_quality=no_quality,
                filter_no_url=filter_no_url.lower() == "true",
                filter_no_refs=filter_no_refs.lower() == "true",
                filter_no_infobox=filter_no_infobox.lower() == "true",
                filter_was_deleted=filter_was_deleted.lower() == "true",
            )
            _save_results(results)
            _scan_progress = {
                "status": "done",
                "message": "Complete",
                "pct": 100,
                "done": True,
            }
        except Exception as exc:
            _scan_progress = {
                "status": "error",
                "message": f"Error: {exc}",
                "pct": 0,
                "done": True,
            }
        finally:
            SCAN_LOCK.release()

    # Initialize progress and start background thread
    _scan_progress = {
        "status": "starting",
        "message": "Starting scan...",
        "pct": 0,
        "done": False,
    }
    threading.Thread(target=_run, daemon=True).start()

    return HTMLResponse(
        _render("index.html", {
            "request": request,
            "results": None,
            "scan_started": True,
        })
    )


# ---------------------------------------------------------------------------
# Routes — API
# ---------------------------------------------------------------------------


@app.get("/api/results")
async def api_results():
    return JSONResponse(_load_results())


@app.get("/api/progress")
async def api_progress():
    """Return current scan progress. Frontend polls this every 500ms."""
    global _scan_progress
    return JSONResponse(_scan_progress)


@app.post("/api/scan")
async def api_scan(
    days: int = Form(7),
    limit: int = Form(100),
    no_quality: bool = Form(False),
    filter_no_url: str = Form("false"),
    filter_no_refs: str = Form("false"),
    filter_no_infobox: str = Form("false"),
    filter_was_deleted: str = Form("false"),
):
    """Run a scan synchronously and return JSON results."""
    results = _do_scan(
        days=days, limit=limit, no_quality=no_quality,
        filter_no_url=filter_no_url.lower() == "true",
        filter_no_refs=filter_no_refs.lower() == "true",
        filter_no_infobox=filter_no_infobox.lower() == "true",
        filter_was_deleted=filter_was_deleted.lower() == "true",
    )
    _save_results(results)
    return JSONResponse(results)


# ---------------------------------------------------------------------------
# Scan logic
# ---------------------------------------------------------------------------


def _set_progress(status: str, message: str, pct: int) -> None:
    """Update the shared progress dict."""
    global _scan_progress
    _scan_progress = {
        "status": status,
        "message": message,
        "pct": min(pct, 99),
        "done": False,
    }


def _do_scan(
    *,
    days: int,
    limit: int,
    no_quality: bool,
    filter_no_url: bool,
    filter_no_refs: bool,
    filter_no_infobox: bool,
    filter_was_deleted: bool,
) -> dict[str, Any]:
    """Run the npp-finder pipeline and return structured results."""
    session = NPPSession()
    start = time.time()
    total_steps = 6 if no_quality else 7

    # Step 1: fetch pages
    _set_progress("fetching_pages", "Fetching list of new pages...", 5)
    pages = session.fetch_new_pages(days=days, limit=limit)
    if not pages:
        return {
            "error": None, "total_pages": 0,
            "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": round(time.time() - start, 1),
            "matches": [], "no_refs": [],
            "filter_no_url": filter_no_url,
        }

    # Step 2: fetch wikitext
    page_ids = [p["pageid"] for p in pages]
    _set_progress("fetching_wikitext", f"Fetching wikitext for {len(page_ids)} pages...", 15)
    wikitexts = session.fetch_wikitexts(page_ids)

    # Step 3: analyze references
    _set_progress("analyzing", "Analyzing references...", 30)
    results: list[dict[str, Any]] = []
    for page in pages:
        pid = page["pageid"]
        raw = wikitexts.get(pid, "")
        if not raw:
            continue
        has_url, total_refs, url_refs, bad_samples = has_any_url_refs(raw)
        results.append({
            "pageid": pid,
            "title": page["title"],
            "timestamp": page["timestamp"],
            "user": page["user"],
            "revid": page.get("revid"),
            "editcount": None,
            "size": None,
            "has_infobox": has_infobox(raw),
            "page_type": detect_page_type(raw, page["title"]),
            "categories": [],
            "was_deleted": None,
            "quality": None,
            "has_url": has_url,
            "total_refs": total_refs,
            "url_refs": url_refs,
            "bad_samples": bad_samples,
        })

    # Apply filters
    matches = [r for r in results if _page_matches(
        r, filter_no_url, filter_no_refs, filter_no_infobox, filter_was_deleted
    )]
    no_refs = [r for r in results if r["total_refs"] == 0]

    if not matches:
        return {
            "error": None,
            "total_pages": len(pages),
            "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": round(time.time() - start, 1),
            "matches": [],
            "no_refs": [{"title": r["title"], "timestamp": r["timestamp"]} for r in no_refs],
            "filter_no_url": filter_no_url,
        }

    # Step 4: enrich matches
    step = 4
    _set_progress("enriching", f"Enriching {len(matches)} matching pages...", 45)

    pct_base = 45
    pct_range = 50 if no_quality else 40

    # 4a: metadata
    _set_progress("enriching_metadata", "Fetching page metadata...", pct_base)
    match_ids = [r["pageid"] for r in matches]
    meta = session.fetch_page_metadata(match_ids)
    for r in matches:
        m = meta.get(r["pageid"], {})
        r["size"] = m.get("size")
        r["categories"] = m.get("categories", [])

    # 4b: edit counts
    step_pct = pct_base + int(pct_range * 0.3)
    _set_progress("enriching_edits", "Fetching edit counts...", step_pct)
    match_users = sorted({r["user"] for r in matches})
    edit_counts = session.fetch_user_edit_counts(match_users)
    for r in matches:
        r["editcount"] = edit_counts.get(r["user"])

    # 4c: deletion history
    step_pct = pct_base + int(pct_range * 0.5)
    _set_progress("enriching_deletions", "Checking deletion history...", step_pct)
    match_titles = {r["title"] for r in matches}
    deleted_titles = session.fetch_deleted_titles(match_titles)
    for r in matches:
        r["was_deleted"] = r["title"] in deleted_titles

    # 4d: quality scores
    if not no_quality:
        step_pct = pct_base + int(pct_range * 0.8)
        match_revids = [r["revid"] for r in matches if r.get("revid")]
        if match_revids:
            total_q = len(match_revids)
            _set_progress("enriching_quality", f"Fetching quality scores... 0/{total_q}", step_pct)
            quality = session.fetch_quality_scores(
                match_revids,
                on_progress=lambda done, _tot: _set_progress(
                    "enriching_quality",
                    f"Fetching quality scores... {done}/{total_q}",
                    step_pct + int((pct_range * 0.2) * done / total_q),
                ),
            )
            _set_progress("enriching_quality", f"Fetching quality scores... {total_q}/{total_q}", step_pct + int(pct_range * 0.2))
            for r in matches:
                if r.get("revid") in quality:
                    r["quality"] = quality[r["revid"]]

    return {
        "error": None,
        "total_pages": len(pages),
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(time.time() - start, 1),
        "matches": [dict(r) for r in matches],
        "no_refs": [{"title": r["title"], "timestamp": r["timestamp"]} for r in no_refs],
        "filter_no_url": filter_no_url,
    }


def _page_matches(
    r: dict[str, Any],
    filter_no_url: bool,
    filter_no_refs: bool,
    filter_no_infobox: bool,
    filter_was_deleted: bool,
) -> bool:
    """Check if a page matches all enabled filters."""
    if filter_no_url and not (r["total_refs"] > 0 and not r["has_url"]):
        return False
    if filter_no_refs and not (r["total_refs"] == 0):
        return False
    if filter_no_infobox and r.get("has_infobox") is not False:
        return False
    if filter_was_deleted and r.get("was_deleted") is not True:
        return False
    return True


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _save_results(results: dict[str, Any]) -> None:
    safe = json.loads(json.dumps(results, default=str))
    RESULTS_FILE.write_text(json.dumps(safe, indent=2))


def _load_results() -> dict[str, Any] | None:
    if RESULTS_FILE.exists():
        try:
            return json.loads(RESULTS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

"""npp-finder web dashboard — FastAPI application.

Deploys on Toolforge Kubernetes or runs locally for development.
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
from npp_finder.refcheck import has_any_url_refs, has_infobox

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


def _render(name: str, context: dict[str, Any]) -> str:
    """Render a Jinja2 template with the given context."""
    template = _env.get_template(name)
    return template.render(**context)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, days: int = Query(7), limit: int = Query(100)):
    """Main page — show scan results, optionally re-run with given params."""
    results = _load_results()
    return HTMLResponse(
        _render("index.html", {
            "request": request,
            "results": results,
            "days": days,
            "limit": limit,
            "scanned_at": results.get("scanned_at") if results else None,
        })
    )


@app.get("/scan", response_class=HTMLResponse)
async def scan_form(request: Request):
    """Show the scan form (GET request)."""
    return HTMLResponse(
        _render("index.html", {
            "request": request, "results": None, "days": 7, "limit": 100,
        })
    )


@app.post("/scan", response_class=HTMLResponse)
async def run_scan(
    request: Request,
    days: int = Form(7),
    limit: int = Form(100),
    no_quality: bool = Form(False),
):
    """Run the scan and show results."""
    acquired = SCAN_LOCK.acquire(blocking=False)
    if not acquired:
        return HTMLResponse(
            "<div class='alert alert-warning'>A scan is already running. "
            "Please wait for it to finish.</div>",
            status_code=429,
        )
    try:
        results = _do_scan(days=days, limit=limit, no_quality=no_quality)
        _save_results(results)
    finally:
        SCAN_LOCK.release()

    return HTMLResponse(
        _render("index.html", {
            "request": request,
            "results": results,
            "days": days,
            "limit": limit,
            "scanned_at": results.get("scanned_at"),
        })
    )


@app.get("/api/results")
async def api_results():
    """Return cached scan results as JSON."""
    return JSONResponse(_load_results())


@app.post("/api/scan")
async def api_scan(
    days: int = Form(7),
    limit: int = Form(100),
    no_quality: bool = Form(False),
):
    """Run a scan and return JSON results."""
    results = _do_scan(days=days, limit=limit, no_quality=no_quality)
    _save_results(results)
    return JSONResponse(results)


# ---------------------------------------------------------------------------
# Scan logic
# ---------------------------------------------------------------------------


def _do_scan(*, days: int, limit: int, no_quality: bool) -> dict[str, Any]:
    """Run the npp-finder pipeline and return structured results."""
    session = NPPSession()

    start = time.time()

    pages = session.fetch_new_pages(days=days, limit=limit)
    if not pages:
        return {
            "error": None,
            "total_pages": 0,
            "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": round(time.time() - start, 1),
            "matches": [],
            "no_refs": [],
        }

    page_ids = [p["pageid"] for p in pages]
    wikitexts = session.fetch_wikitexts(page_ids)

    pass_ids: set[int] = set()
    results: list[dict[str, Any]] = []
    for page in pages:
        pid = page["pageid"]
        raw = wikitexts.get(pid, "")
        if not raw:
            continue
        has_url, total_refs, url_refs, bad_samples = has_any_url_refs(raw)
        is_match = total_refs > 0 and not has_url
        if is_match:
            pass_ids.add(pid)
        results.append({
            "pageid": pid,
            "title": page["title"],
            "timestamp": page["timestamp"],
            "user": page["user"],
            "revid": page.get("revid"),
            "editcount": None,
            "size": None,
            "has_infobox": has_infobox(raw),
            "categories": [],
            "was_deleted": None,
            "quality": None,
            "has_url": has_url,
            "total_refs": total_refs,
            "url_refs": url_refs,
            "bad_samples": bad_samples,
        })

    matches = [r for r in results if r["total_refs"] > 0 and not r["has_url"]]
    no_refs = [r for r in results if r["total_refs"] == 0]

    if not matches:
        return {
            "error": None,
            "total_pages": len(pages),
            "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": round(time.time() - start, 1),
            "matches": [],
            "no_refs": [{"title": r["title"], "timestamp": r["timestamp"]} for r in no_refs],
        }

    match_ids = [r["pageid"] for r in matches]
    meta = session.fetch_page_metadata(match_ids)
    for r in matches:
        m = meta.get(r["pageid"], {})
        r["size"] = m.get("size")
        r["categories"] = m.get("categories", [])

    match_users = sorted({r["user"] for r in matches})
    edit_counts = session.fetch_user_edit_counts(match_users)
    for r in matches:
        r["editcount"] = edit_counts.get(r["user"])

    match_titles = {r["title"] for r in matches}
    deleted_titles = session.fetch_deleted_titles(match_titles)
    for r in matches:
        r["was_deleted"] = r["title"] in deleted_titles

    if not no_quality:
        match_revids = [r["revid"] for r in matches if r.get("revid")]
        if match_revids:
            quality = session.fetch_quality_scores(match_revids)
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
    }


def _save_results(results: dict[str, Any]) -> None:
    """Persist scan results to a JSON file."""
    safe = json.loads(json.dumps(results, default=str))
    RESULTS_FILE.write_text(json.dumps(safe, indent=2))


def _load_results() -> dict[str, Any] | None:
    """Load cached scan results, if any."""
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

"""API client for querying English Wikipedia.

Handles User-Agent, rate-limiting, pagination, and batched data fetching.
"""

from __future__ import annotations

import collections.abc
import time
from typing import Any

import requests


USER_AGENT = (
    "NPP-Finder/0.1 (https://github.com/example/npp-finder; npp-finder@example.com) "
    "NPPBacklogFiltering"
)

LIFT_WING_BASE = "https://api.wikimedia.org/service/lw/inference/v1/models"


class NPPSession:
    """A requests.Session configured for the Wikimedia API with proper UA and 429 handling."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers["User-Agent"] = USER_AGENT
        self._base = "https://en.wikipedia.org/w/api.php"

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        """GET the Action API with retry-on-429 logic."""
        backoff = 1.0
        for attempt in range(5):
            resp = self._session.get(
                self._base, params=params, timeout=(10, 60)
            )
            if resp.status_code == 200:
                return resp.json()  # type: ignore[no-any-return]
            if resp.status_code == 429:
                retry = int(resp.headers.get("Retry-After", backoff))
                time.sleep(retry)
                backoff = min(backoff * 2, 60)
                continue
            if resp.status_code == 403:
                raise PermissionError(
                    "403 Forbidden — check User-Agent. "
                    "If you need patrol-level data, authenticate with a "
                    "New Page Reviewer account."
                )
            resp.raise_for_status()
        raise RuntimeError("Too many 429s — aborting")

    # ------------------------------------------------------------------
    # Fetch new pages via recentchanges
    # ------------------------------------------------------------------

    def fetch_new_pages(
        self,
        *,
        days: int = 7,
        limit: int = 500,
        unreviewed_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return list of newly created mainspace pages.

        Each dict has keys: pageid, title, revid, timestamp, user.

        ``unreviewed_only`` requires the ``patrol`` user right
        (New Page Reviewer or admin); without it the filter is silently skipped.
        """
        rcprop = "title|timestamp|ids|user"
        rcshow = "!redirect"

        if unreviewed_only:
            rcprop += "|patrolled"
            rcshow += "|!patrolled"

        params: dict[str, Any] = {
            "action": "query",
            "list": "recentchanges",
            "rctype": "new",
            "rcnamespace": "0",
            "rcshow": rcshow,
            "rclimit": "max",
            "rcprop": rcprop,
            "format": "json",
        }

        pages: list[dict[str, Any]] = []
        cutoff_ts: str | None = None

        while True:
            data = self._get(params)
            rc_list = data.get("query", {}).get("recentchanges", [])

            for rc in rc_list:
                ts = rc["timestamp"]
                if cutoff_ts is None:
                    from datetime import datetime, timedelta, timezone

                    try:
                        page_dt = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")
                        )
                    except ValueError:
                        continue
                    cutoff = page_dt - timedelta(days=days)
                    cutoff_ts = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

                if ts < cutoff_ts:
                    in_window = [p for p in pages if p["timestamp"] >= cutoff_ts]
                    return in_window[:limit]

                pages.append(
                    {
                        "pageid": rc["pageid"],
                        "title": rc["title"],
                        "revid": rc.get("revid"),
                        "timestamp": ts,
                        "user": rc.get("user", "Unknown"),
                    }
                )

            if len(pages) >= limit:
                return pages[:limit]

            if "continue" not in data:
                return pages

            params["rccontinue"] = data["continue"]["rccontinue"]
            params["continue"] = data["continue"]["continue"]

    # ------------------------------------------------------------------
    # Wikitext-only fetch (lightweight — used in first pass before filtering)
    # ------------------------------------------------------------------

    def fetch_wikitexts(self, page_ids: list[int]) -> dict[int, str]:
        """Return {pageid: wikitext}.  Minimal overhead — just revisions."""
        result: dict[int, str] = {}
        for i in range(0, len(page_ids), 50):
            chunk = page_ids[i : i + 50]
            data = self._get(
                {
                    "action": "query",
                    "prop": "revisions",
                    "rvprop": "content",
                    "rvslots": "main",
                    "pageids": "|".join(str(pid) for pid in chunk),
                    "format": "json",
                }
            )
            for page_info in data.get("query", {}).get("pages", {}).values():
                pid = page_info.get("pageid")
                revisions = page_info.get("revisions", [])
                if pid is not None and revisions:
                    result[int(pid)] = revisions[0].get("slots", {}).get(
                        "main", {}
                    ).get("*", "")
            time.sleep(0.3)
        return result

    # ------------------------------------------------------------------
    # Batch page metadata (size + categories — second pass, matches only)
    # ------------------------------------------------------------------

    def fetch_page_metadata(
        self, page_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        """Return {pageid: {size, categories}}.

        Used *after* the ref-filtering pass to enrich only matching pages.
        """
        result: dict[int, dict[str, Any]] = {}
        for i in range(0, len(page_ids), 50):
            chunk = page_ids[i : i + 50]
            data = self._get(
                {
                    "action": "query",
                    "prop": "info|categories",
                    "cllimit": "max",
                    "pageids": "|".join(str(pid) for pid in chunk),
                    "format": "json",
                }
            )
            for page_info in data.get("query", {}).get("pages", {}).values():
                pid = page_info.get("pageid")
                if pid is None:
                    continue
                cats = page_info.get("categories", [])
                result[int(pid)] = {
                    "size": page_info.get("length"),
                    "categories": sorted(
                        c["title"] for c in cats if "title" in c
                    ),
                }
            time.sleep(0.3)
        return result

    # ------------------------------------------------------------------
    # User edit count lookup
    # ------------------------------------------------------------------

    def fetch_user_edit_counts(
        self, usernames: list[str]
    ) -> dict[str, int | None]:
        """Return {username: editcount}. Anonymous users are ``None``."""
        result: dict[str, int | None] = {}
        for i in range(0, len(usernames), 50):
            chunk = usernames[i : i + 50]
            data = self._get(
                {
                    "action": "query",
                    "list": "users",
                    "ususers": "|".join(chunk),
                    "usprop": "editcount",
                    "format": "json",
                }
            )
            for user_info in data.get("query", {}).get("users", []):
                name = user_info.get("name", "")
                if "missing" in user_info or "invalid" in user_info:
                    result[name] = None
                else:
                    ec = user_info.get("editcount")
                    result[name] = int(ec) if ec is not None else None
            time.sleep(0.1)
        return result

    # ------------------------------------------------------------------
    # Previous deletion check
    # ------------------------------------------------------------------

    def fetch_deleted_titles(
        self, page_titles: set[str]
    ) -> set[str]:
        """Return subset of ``page_titles`` that appear in the deletion log.

        Queries the last ~5000 deletion events (paginated) and checks for
        title matches.  Catches G4 candidates.
        """
        titles_norm: set[str] = {t.replace(" ", "_") for t in page_titles}
        deleted: set[str] = set()

        params: dict[str, Any] = {
            "action": "query",
            "list": "logevents",
            "letype": "delete",
            "leaction": "delete/delete",
            "lelimit": "max",
            "leprop": "title",
            "format": "json",
        }

        for _ in range(10):  # up to 10 pages × 500 = 5000 entries
            data = self._get(params)
            events = data.get("query", {}).get("logevents", [])
            if not events:
                break
            for ev in events:
                title = ev.get("title", "").replace(" ", "_")
                if title in titles_norm:
                    deleted.add(title)
            if "continue" not in data:
                break
            params["lecontinue"] = data["continue"]["lecontinue"]
            params["continue"] = data["continue"]["continue"]

        return {d.replace("_", " ") for d in deleted}

    # ------------------------------------------------------------------
    # Lift Wing article quality prediction
    # ------------------------------------------------------------------

    def fetch_quality_scores(
        self,
        rev_ids: list[int],
        on_progress: collections.abc.Callable[[int, int], Any] | None = None,
    ) -> dict[int, str]:
        """Return {rev_id: predicted_quality_class}.

        Classes: Stub, Start, C, B, GA, FA.
        Uses the Lift Wing inference API (ORES-compatible format).

        Args:
            rev_ids: List of revision IDs to score.
            on_progress: Optional callback ``f(done, total)`` invoked after
                each individual API call.
        """
        result: dict[int, str] = {}
        total = len(rev_ids)
        for idx, rid in enumerate(rev_ids):
            try:
                resp = self._session.post(
                    f"{LIFT_WING_BASE}/enwiki-articlequality:predict",
                    json={"rev_id": rid},
                    timeout=(10, 30),
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    # The response is ORES-compatible nested format:
                    # enwiki.scores.<rev_id>.articlequality.score.prediction
                    prediction = (
                        payload.get("enwiki", {})
                        .get("scores", {})
                        .get(str(rid), {})
                        .get("articlequality", {})
                        .get("score", {})
                        .get("prediction")
                    )
                    if prediction:
                        result[rid] = prediction
                # 429/503/504 — skip instead of retry storm
            except (requests.RequestException, ValueError, TypeError):
                pass
            if on_progress:
                on_progress(idx + 1, total)
            time.sleep(0.15)
        return result

"""API client for querying English Wikipedia.

Handles User-Agent, rate-limiting, pagination, and batch wikitext fetching.
"""

from __future__ import annotations

import time
from typing import Any

import requests


USER_AGENT = (
    "NPP-Finder/0.1 (https://github.com/example/npp-finder; npp-finder@example.com) "
    "NPPBacklogFiltering"
)


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

        Each dict has keys: pageid, title, timestamp, user.

        Note: ``unreviewed_only`` requires the ``patrol`` user right
        (New Page Reviewer or admin). Without it the filter is silently skipped.
        """
        # recentchanges `rctype=new` gives page creations.
        # We deliberately omit rcprop=patrolled because it requires the patrol
        # right (permissiondenied for unauthenticated users).  To filter by
        # patrol status you must authenticate with a New Page Reviewer account.
        rcprop = "title|timestamp|ids|user"
        rcshow = "!redirect"  # skip redirects

        if unreviewed_only:
            # These require authentication — if the user isn't a patroller,
            # the API will return a permission error.  We warn on stderr.
            rcprop += "|patrolled"
            rcshow += "|!patrolled"

        params: dict[str, Any] = {
            "action": "query",
            "list": "recentchanges",
            "rctype": "new",
            "rcnamespace": "0",
            "rcshow": rcshow,
            "rclimit": "max",              # 500
            "rcprop": rcprop,
            "format": "json",
        }

        pages: list[dict[str, Any]] = []
        cutoff_ts: str | None = None  # computed from first batch

        while True:
            data = self._get(params)
            rc_list = data.get("query", {}).get("recentchanges", [])

            for rc in rc_list:
                ts = rc["timestamp"]
                if cutoff_ts is None:
                    # Timestamps from recentchanges are ISO 8601: "YYYY-MM-DDTHH:MM:SSZ"
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
                    # We've gone past our date window — stop paginating
                    in_window = [p for p in pages if p["timestamp"] >= cutoff_ts]
                    return in_window[:limit]

                pages.append(
                    {
                        "pageid": rc["pageid"],
                        "title": rc["title"],
                        "timestamp": ts,
                        "user": rc.get("user", "Unknown"),
                    }
                )

            # Stop if we have enough or no more pages
            if len(pages) >= limit:
                return pages[:limit]

            if "continue" not in data:
                return pages

            params["rccontinue"] = data["continue"]["rccontinue"]
            params["continue"] = data["continue"]["continue"]

    # ------------------------------------------------------------------
    # Batch wikitext fetching
    # ------------------------------------------------------------------

    def fetch_wikitexts(
        self, page_ids: list[int]
    ) -> dict[int, str]:
        """Return {pageid: wikitext} for a batch of page IDs (max 50 per call)."""
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
            time.sleep(0.3)  # gentle rate-limiting between batches
        return result

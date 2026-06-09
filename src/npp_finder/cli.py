"""CLI entry point for npp-finder."""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from typing import Any

from .api import NPPSession
from .refcheck import has_any_url_refs


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    session = NPPSession()

    # ------------------------------------------------------------------
    # 1. Fetch new pages
    # ------------------------------------------------------------------
    print(f"Fetching new pages (last {args.days} days, limit {args.limit})...",
          file=sys.stderr)
    pages = session.fetch_new_pages(
        days=args.days,
        limit=args.limit,
        unreviewed_only=args.unreviewed_only,
    )
    if not pages:
        print("No new pages found in the date window.", file=sys.stderr)
        return

    print(f"  → {len(pages)} pages retrieved", file=sys.stderr)

    # ------------------------------------------------------------------
    # 2. Batch-fetch wikitext
    # ------------------------------------------------------------------
    page_ids = [p["pageid"] for p in pages]
    print(f"Fetching wikitext for {len(page_ids)} pages...", file=sys.stderr)
    wikitexts = session.fetch_wikitexts(page_ids)

    # ------------------------------------------------------------------
    # 3. Analyze references
    # ------------------------------------------------------------------
    print("Analyzing references...", file=sys.stderr)
    results: list[dict[str, Any]] = []
    for page in pages:
        pid = page["pageid"]
        raw = wikitexts.get(pid, "")
        if not raw:
            continue
        has_url, total_refs, url_refs, bad_samples = has_any_url_refs(raw)
        results.append(
            {
                "title": page["title"],
                "timestamp": page["timestamp"],
                "user": page["user"],
                "has_url": has_url,
                "total_refs": total_refs,
                "url_refs": url_refs,
                "bad_samples": bad_samples,
            }
        )

    # ------------------------------------------------------------------
    # 4. Filter to no-URL pages
    # ------------------------------------------------------------------
    matches = [r for r in results if r["total_refs"] > 0 and not r["has_url"]]
    no_refs = [r for r in results if r["total_refs"] == 0]

    # ------------------------------------------------------------------
    # 5. Output
    # ------------------------------------------------------------------
    if args.output == "json":
        _output_json(matches, no_refs, args)
    elif args.output == "csv":
        _output_csv(matches, args)
    else:
        _output_table(matches, no_refs, results, args)


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _output_table(
    matches: list[dict[str, Any]],
    no_refs: list[dict[str, Any]],
    all_results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    """Print a terminal table of pages with no URL references."""
    total_checked = len(all_results)
    pages_with_refs = total_checked - len(no_refs)

    # Header
    print()
    print(f"Pages created in last {args.days} days: {total_checked}")
    print(f"Pages with references: {pages_with_refs}")
    print(f"Pages with ONLY non-URL references: {len(matches)}")
    print(f"Pages with no references at all: {len(no_refs)}")
    print()

    if not matches:
        print("No pages found where every reference lacks a URL.")
        if no_refs and not args.quiet:
            print()
            print("Pages with zero references (not counted as matches):")
            for r in sorted(no_refs, key=lambda x: x["timestamp"], reverse=True):
                print(f"  • {r['title']}")
        return

    # Table
    date_width = 10
    title_width = min(60, max(len(r["title"]) for r in matches) + 2)
    user_width = min(25, max(len(r["user"]) for r in matches) + 2)

    sep = (
        f"+{'-' * date_width}+{'-' * title_width}+{'-' * user_width}"
        f"+------+-------+----------------------------------+"
    )
    header = (
        f"| {'Date':^{date_width - 2}}"
        f" | {'Title':^{title_width - 2}}"
        f" | {'Creator':^{user_width - 2}}"
        f" | {'Refs':^4}"
        f" | {'URL':^5}"
        f" | {'Sample non-URL ref':^32} |"
    )

    print(sep)
    print(header)
    print(sep)

    for r in sorted(matches, key=lambda x: x["timestamp"], reverse=True):
        ts = r["timestamp"]
        # ts is ISO 8601: "YYYY-MM-DDTHH:MM:SSZ"
        date_str = ts[:10]
        title = r["title"][:title_width - 2]
        user = r["user"][:user_width - 2]
        refs = str(r["total_refs"])
        urls = str(r["url_refs"])
        sample = (r["bad_samples"][0] if r["bad_samples"] else "(none)")[:30]

        print(
            f"| {date_str:<{date_width - 2}}"
            f" | {title:<{title_width - 2}}"
            f" | {user:<{user_width - 2}}"
            f" | {refs:>4}"
            f" | {urls:>5}"
            f" | {sample:<32} |"
        )

    print(sep)


def _output_json(
    matches: list[dict[str, Any]],
    no_refs: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    """JSON output with metadata."""
    output = {
        "query": {
            "days": args.days,
            "unreviewed_only": args.unreviewed_only,
            "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
        "matches": [
            {
                "title": r["title"],
                "timestamp": _format_iso(r["timestamp"]),
                "user": r["user"],
                "total_refs": r["total_refs"],
                "url_refs": r["url_refs"],
                "sample_bad_refs": r["bad_samples"],
            }
            for r in matches
        ],
        "no_references": [r["title"] for r in no_refs],
    }
    json.dump(output, sys.stdout, indent=2)
    print()


def _output_csv(matches: list[dict[str, Any]], args: argparse.Namespace) -> None:
    """CSV output."""
    import csv

    writer = csv.writer(sys.stdout)
    writer.writerow(["Title", "Created", "Creator", "TotalRefs", "URLRefs", "SampleBadRef"])
    for r in sorted(matches, key=lambda x: x["timestamp"], reverse=True):
        writer.writerow(
            [
                r["title"],
                _format_iso(r["timestamp"]),
                r["user"],
                r["total_refs"],
                r["url_refs"],
                (r["bad_samples"][0] if r["bad_samples"] else ""),
            ]
        )


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="npp-finder",
        description="Find new Wikipedia pages whose references contain no URLs.",
    )
    p.add_argument(
        "--days",
        type=int,
        default=7,
        help="Days back to scan (default: 7)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max pages to check (default: 100)",
    )
    p.add_argument(
        "--unreviewed-only",
        action="store_true",
        default=False,
        help="Only show unpatrolled pages (requires patrol user right)",
    )
    p.add_argument(
        "--output",
        choices=["table", "json", "csv"],
        default="table",
        help="Output format (default: table)",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress summary stats on stderr",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_iso(ts: str) -> str:
    """Normalize timestamp to ISO 8601 (handles both ISO and MW formats)."""
    if "T" in ts:
        return ts  # already ISO
    # MediaWiki compact format: YYYYMMDDHHMMSS
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"

"""CLI entry point for npp-finder."""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from typing import Any

from .api import NPPSession
from .refcheck import has_any_url_refs, has_infobox


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
    # 2. Batch-fetch page details (wikitext, size, categories)
    # ------------------------------------------------------------------
    page_ids = [p["pageid"] for p in pages]
    print(f"Fetching page details for {len(page_ids)} pages...",
          file=sys.stderr)
    details = session.fetch_page_details(page_ids)

    # ------------------------------------------------------------------
    # 3. Fetch user edit counts
    # ------------------------------------------------------------------
    unique_users = sorted({p["user"] for p in pages})
    print(f"Fetching edit counts for {len(unique_users)} creators...",
          file=sys.stderr)
    edit_counts = session.fetch_user_edit_counts(unique_users)

    # ------------------------------------------------------------------
    # 4. Fetch deletion history
    # ------------------------------------------------------------------
    all_titles = {p["title"] for p in pages}
    print(f"Checking deletion history for {len(all_titles)} titles...",
          file=sys.stderr)
    deleted_titles = session.fetch_deleted_titles(all_titles)

    # ------------------------------------------------------------------
    # 5. Fetch article quality predictions (Lift Wing)
    # ------------------------------------------------------------------
    rev_ids: list[int] = []
    revid_to_pageid: dict[int, int] = {}
    for p in pages:
        rid = p.get("revid") or details.get(p["pageid"], {}).get("revid")
        if rid:
            rev_ids.append(int(rid))
            revid_to_pageid[int(rid)] = p["pageid"]

    quality_scores: dict[int, str] = {}
    if not args.no_quality and rev_ids:
        print(f"Fetching article quality scores for {len(rev_ids)} pages...",
              file=sys.stderr)
        quality_scores = session.fetch_quality_scores(rev_ids)
    elif args.no_quality:
        print("Skipping quality predictions (--no-quality).", file=sys.stderr)

    # ------------------------------------------------------------------
    # 6. Analyze references
    # ------------------------------------------------------------------
    print("Analyzing references...", file=sys.stderr)
    results: list[dict[str, Any]] = []
    for page in pages:
        pid = page["pageid"]
        d = details.get(pid, {})
        raw = d.get("wikitext", "")
        if not raw:
            continue

        has_url, total_refs, url_refs, bad_samples = has_any_url_refs(raw)

        # Resolve quality score
        rid = page.get("revid") or d.get("revid")
        quality = quality_scores.get(int(rid)) if rid else None

        results.append(
            {
                "title": page["title"],
                "timestamp": page["timestamp"],
                "user": page["user"],
                "editcount": edit_counts.get(page["user"]),
                "size": d.get("size"),
                "revid": rid,
                "has_infobox": has_infobox(raw),
                "categories": d.get("categories", []),
                "was_deleted": page["title"] in deleted_titles,
                "quality": quality,
                "has_url": has_url,
                "total_refs": total_refs,
                "url_refs": url_refs,
                "bad_samples": bad_samples,
            }
        )

    # ------------------------------------------------------------------
    # 7. Filter to no-URL pages
    # ------------------------------------------------------------------
    matches = [r for r in results if r["total_refs"] > 0 and not r["has_url"]]
    no_refs = [r for r in results if r["total_refs"] == 0]

    # ------------------------------------------------------------------
    # 8. Output
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

    # Dynamic column widths
    date_w = 10
    title_w = min(55, max(len(r["title"]) for r in matches) + 2)
    user_w = min(22, max(len(r["user"]) for r in matches) + 2)
    ec_w = 8
    size_w = 8
    infobox_w = 6
    cats_w = 6
    del_w = 6
    qual_w = 8
    refs_w = 6
    url_w = 5
    sample_w = 28

    sep_parts = [
        f"+{'-' * date_w}",
        f"+{'-' * title_w}",
        f"+{'-' * user_w}",
        f"+{'-' * ec_w}",
        f"+{'-' * size_w}",
        f"+{'-' * infobox_w}",
        f"+{'-' * cats_w}",
        f"+{'-' * del_w}",
        f"+{'-' * qual_w}",
        f"+{'-' * refs_w}",
        f"+{'-' * url_w}",
        f"+{'-' * sample_w}+",
    ]
    sep = "".join(sep_parts)

    header_parts = [
        f"| {'Date':^{date_w - 2}}",
        f"| {'Title':^{title_w - 2}}",
        f"| {'Creator':^{user_w - 2}}",
        f"| {'Edits':^{ec_w - 2}}",
        f"| {'Size':^{size_w - 2}}",
        f"| {'Infbx':^{infobox_w - 2}}",
        f"| {'Cats':^{cats_w - 2}}",
        f"| {'Del?':^{del_w - 2}}",
        f"| {'Quality':^{qual_w - 2}}",
        f"| {'Refs':^{refs_w - 2}}",
        f"| {'URL':^{url_w - 2}}",
        f"| {'Sample ref':^{sample_w - 2}} |",
    ]
    header = "".join(header_parts)

    print(sep)
    print(header)
    print(sep)

    for r in sorted(matches, key=lambda x: x["timestamp"], reverse=True):
        date_str = r["timestamp"][:10]
        title = r["title"][:title_w - 2]
        user = r["user"][:user_w - 2]

        ec = r.get("editcount")
        ec_str = f"{ec:,d}" if ec is not None else "—"

        sz = r.get("size")
        sz_str = f"{sz:,d}" if sz is not None else "—"

        ib = "Y" if r.get("has_infobox") else "N"
        nc = len(r.get("categories", []))
        nc_str = str(nc) if nc else "—"

        dl = "Y" if r.get("was_deleted") else "N"

        ql = r.get("quality", "") or "—"
        ql = ql[:qual_w - 2]

        refs = r["total_refs"]
        urls = r["url_refs"]
        sample = (r["bad_samples"][0] if r["bad_samples"] else "(none)")[:sample_w - 2]

        row_parts = [
            f"| {date_str:<{date_w - 2}}",
            f"| {title:<{title_w - 2}}",
            f"| {user:<{user_w - 2}}",
            f"| {ec_str:>{ec_w - 2}}",
            f"| {sz_str:>{size_w - 2}}",
            f"| {ib:^{infobox_w - 2}}",
            f"| {nc_str:>{cats_w - 2}}",
            f"| {dl:^{del_w - 2}}",
            f"| {ql:^{qual_w - 2}}",
            f"| {refs:>{refs_w - 2}}",
            f"| {urls:>{url_w - 2}}",
            f"| {sample:<{sample_w - 2}} |",
        ]
        print("".join(row_parts))

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
                "editcount": r.get("editcount"),
                "size_bytes": r.get("size"),
                "has_infobox": r.get("has_infobox"),
                "category_count": len(r.get("categories", [])),
                "categories": r.get("categories", []),
                "was_previously_deleted": r.get("was_deleted"),
                "quality_prediction": r.get("quality"),
                "total_refs": r["total_refs"],
                "url_refs": r["url_refs"],
                "sample_bad_refs": r["bad_samples"],
            }
            for r in matches
        ],
        "no_references": [
            {"title": r["title"], "timestamp": r["timestamp"]} for r in no_refs
        ],
    }
    json.dump(output, sys.stdout, indent=2)
    print()


def _output_csv(matches: list[dict[str, Any]], args: argparse.Namespace) -> None:
    """CSV output."""
    import csv

    writer = csv.writer(sys.stdout)
    writer.writerow(
        [
            "Title",
            "Created",
            "Creator",
            "EditCount",
            "SizeBytes",
            "HasInfobox",
            "CategoryCount",
            "WasDeleted",
            "Quality",
            "TotalRefs",
            "URLRefs",
            "SampleBadRef",
        ]
    )
    for r in sorted(matches, key=lambda x: x["timestamp"], reverse=True):
        ec = r.get("editcount")
        writer.writerow(
            [
                r["title"],
                _format_iso(r["timestamp"]),
                r["user"],
                ec,
                r.get("size"),
                "Y" if r.get("has_infobox") else "N",
                len(r.get("categories", [])),
                "Y" if r.get("was_deleted") else "N",
                r.get("quality"),
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
        "--no-quality",
        action="store_true",
        default=False,
        help="Skip Lift Wing ML quality predictions (faster)",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress stats on stderr",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_iso(ts: str) -> str:
    """Normalize timestamp to ISO 8601 (handles both ISO and MW formats)."""
    if "T" in ts:
        return ts
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"

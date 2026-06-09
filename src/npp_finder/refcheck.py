"""Reference URL analysis for Wikipedia pages.

Detects whether a page's references contain any HTTP/HTTPS URLs.
Handles ref tags, citation templates, named ref resolution, and
shortened-footnote patterns.
"""

from __future__ import annotations

import re
import mwparserfromhell


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ref_has_url(ref_text: str, named_defs: dict[str, str]) -> bool:
    """Return True if a single <ref> body contains a URL.

    ``ref_text`` is the *inner* content of the ref tag (after resolving
    named refs).  ``named_defs`` is not used here but kept for symmetry.
    """
    # Case 1: Raw URL anywhere in the text
    if _contains_raw_url(ref_text):
        return True

    # Case 2: URL inside a citation template parameter
    try:
        parsed = mwparserfromhell.parse(ref_text)
    except Exception:
        return _contains_raw_url(ref_text)

    for template in parsed.filter_templates():
        if _template_has_url_param(template):
            return True

        # Recurse into nested templates inside this template
        for nested in template.params:
            try:
                inner = mwparserfromhell.parse(str(nested.value))
                for nt in inner.filter_templates():
                    if _template_has_url_param(nt):
                        return True
            except Exception:
                # If nested parsing fails, check raw string
                if _contains_raw_url(str(nested.value)):
                    return True

    return False


def has_any_url_refs(
    wikitext: str,
) -> tuple[bool, int, int, list[str]]:
    """Analyze a page's wikitext for URL presence in references.

    Returns:
        (has_any_url, total_refs, url_refs, sample_bad_refs)
    """
    parsed = mwparserfromhell.parse(wikitext)

    # ---- Step 1: Collect all ref tags ----
    ref_tags = parsed.filter_tags(matches=lambda t: str(t.tag).strip().lower() == "ref")

    # ---- Step 2: Index named ref definitions ----
    named_defs: dict[str, str] = {}
    for tag in ref_tags:
        name = _named_ref_name(tag)
        content = _tag_content(tag)
        if name and content and name not in named_defs:
            named_defs[name] = content

    # ---- Step 3: Evaluate each ref ----
    total = 0
    url_count = 0
    bad_samples: list[str] = []

    seen_named: set[str] = set()

    for tag in ref_tags:
        name = _named_ref_name(tag)
        content = _tag_content(tag)

        if not content and name:
            # Named ref reuse — resolve from definition
            content = named_defs.get(name, "")
        elif not content:
            # Self-closing with no name — skip (shouldn't happen in practice)
            continue

        if name:
            if name in seen_named:
                # Already counted this named-group
                continue
            seen_named.add(name)

        total += 1
        if ref_has_url(content, named_defs):
            url_count += 1
        else:
            if len(bad_samples) < 5:
                bad_samples.append(_summarize_ref(content))

    # ---- Step 4: Also check inline citation templates outside <ref> ----
    # (Rare but possible on very old-style pages)
    for template in parsed.filter_templates():
        name = str(template.name).strip().lower()
        if _is_citation_template(name):
            # Check if this template is already inside a <ref> we counted
            if _is_inside_ref(template, ref_tags):
                continue
            total += 1
            if _template_has_url_param(template):
                url_count += 1
            # else: couldn't find URL in inline template either

    return (url_count > 0, total, url_count, bad_samples)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

URL_RE = re.compile(r"https?://", re.IGNORECASE)

CITATION_TEMPLATES = frozenset(
    {
        "cite web",
        "cite news",
        "cite book",
        "cite journal",
        "cite magazine",
        "cite encyclopedia",
        "cite thesis",
        "cite report",
        "cite conference",
        "cite interview",
        "cite podcast",
        "cite episode",
        "cite serial",
        "cite sign",
        "cite speech",
        "cite map",
        "cite video",
        "cite av media",
        "citation",
        "web citation",
    }
)

URL_PARAM_NAMES = frozenset({"url", "chapter-url", "conference-url", "contribution-url",
                              "transcript-url", "archive-url", "chapterurl", "conferenceurl",
                              "contributionurl", "transcripturl", "archiveurl"})


def _contains_raw_url(text: str) -> bool:
    return bool(URL_RE.search(text))


def _template_has_url_param(template: mwparserfromhell.nodes.Template) -> bool:
    """Check if a citation template has any URL-bearing parameter."""
    for param in template.params:
        name = str(param.name).strip().lower()
        if name in URL_PARAM_NAMES:
            value = str(param.value).strip()
            if value:
                return True
        # Check for unnamed params containing URLs (e.g., {{cite|https://...}})
        if not name and _contains_raw_url(str(param.value)):
            return True
    return False


def _is_citation_template(name: str) -> bool:
    return name in CITATION_TEMPLATES or name.startswith("cite ")


def _named_ref_name(tag: mwparserfromhell.nodes.Tag) -> str | None:
    """Return the 'name' attribute of a <ref> tag, if any."""
    if not tag.has("name"):
        return None
    name_val = str(tag.get("name").value).strip()
    # Strip quotes
    if name_val and name_val[0] in ('"', "'"):
        name_val = name_val[1:]
    if name_val and name_val[-1] in ('"', "'"):
        name_val = name_val[:-1]
    return name_val.strip() or None


def _tag_content(tag: mwparserfromhell.nodes.Tag) -> str:
    """Return inner content of a tag, or '' for self-closing."""
    try:
        content = tag.contents
        return str(content).strip()
    except Exception:
        return ""


def _is_inside_ref(
    template: mwparserfromhell.nodes.Template,
    ref_tags: list[mwparserfromhell.nodes.Tag],
) -> bool:
    """True if template is nested inside any of the given ref tags."""
    for tag in ref_tags:
        try:
            tag_str = str(tag)
        except Exception:
            continue
        if str(template) in tag_str:
            return True
    return False


def _summarize_ref(content: str) -> str:
    """Produce a short, readable snippet of a reference body."""
    # Extract template names instead of just "[template]"
    cleaned = re.sub(
        r"\{\{(\s*[Cc]ite\s+\w+|\s*[Hh]arv[np]?\w*|\s*[Ss]fn)\b[^}]*\}\}",
        lambda m: "[" + m.group(1).strip() + "]",
        content,
    )
    # Generic fallback for unrecognized templates
    cleaned = re.sub(r"\{\{[^}]+\}\}", "[template]", cleaned)
    # Simplify wikilinks: [[Target|Label]] → Label, [[Target]] → Target
    cleaned = re.sub(r"\[\[([^\]|\]]+)\|([^\]]+)\]\]", r"\2", cleaned)
    cleaned = re.sub(r"\[\[([^\]|]+)\]\]", r"\1", cleaned)
    cleaned = re.sub(r"'''''|'''|''", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 80:
        cleaned = cleaned[:77] + "..."
    return cleaned or "(empty ref)"

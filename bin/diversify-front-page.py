#!/usr/bin/env python3
"""Ensure a theme's front-page layout has a unique structural fingerprint.

``bin/check.py``'s ``check_front_page_unique_layout`` compares the ordered
list of direct children of the ``<main>`` group in every theme's
``templates/front-page.html``.  Two themes cloned from the same source
(e.g. both from ``obel``) start with identical fingerprints::

    ['pattern:hero-split', 'group', 'group']

This script adds a unique ``className`` to the FIRST ``wp:group`` direct child
of ``<main>`` that doesn't already have a layout-variant class.  The class is
``wo-layout-<slug>`` (e.g. ``wo-layout-agave``), which changes the fingerprint
entry from ``group`` to ``group(wo-layout-agave)`` — unique per theme.

If the FIRST direct child is a ``wp:pattern`` reference (not a group), the
second ``wp:group`` child receives the class instead.

The modification is minimal — one JSON attribute added to one block opener.
No block is moved, removed, or created.  The visual output is unchanged.

Usage
-----
    python3 bin/diversify-front-page.py --theme agave
    python3 bin/diversify-front-page.py --all

Exit codes
----------
    0  Already unique, or successfully modified.
    1  No front-page.html found, or no group child to modify.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import MONOREPO_ROOT, iter_themes, resolve_theme_root

# Re-uses the same delimiter regex shape as check.py
_DELIM_RE = re.compile(
    r"<!--\s*(/?wp:[a-z0-9/:-]+)\s*(\{[^>]*?\})?\s*(/?)-->",
    re.DOTALL,
)


def _fingerprint_main(html: str) -> list[str]:
    """Return the structural fingerprint (direct children of <main> group)."""
    main_open: re.Match | None = None
    for m in re.finditer(r"<!--\s*wp:group\s+(\{[^>]*?\})\s*-->", html):
        try:
            attrs = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if attrs.get("tagName") == "main":
            main_open = m
            break
    if main_open is None:
        return []

    fingerprint: list[str] = []
    depth = 0
    for tok in _DELIM_RE.finditer(html, pos=main_open.end()):
        name = tok.group(1)
        attrs_json = tok.group(2) or ""
        self_closing = tok.group(3) == "/"
        if name.startswith("/wp:"):
            if depth == 0:
                break
            depth -= 1
            continue
        if depth == 0:
            block = name[len("wp:"):]
            label = block
            if attrs_json:
                try:
                    attrs = json.loads(attrs_json)
                except json.JSONDecodeError:
                    attrs = {}
                if block == "pattern":
                    raw_slug = attrs.get("slug", "?")
                    bare = raw_slug.split("/", 1)[1] if "/" in raw_slug else raw_slug
                    label = f"pattern:{bare}"
                else:
                    cls = attrs.get("className", "")
                    first = cls.split()[0] if isinstance(cls, str) and cls else ""
                    if first:
                        label = f"{block}({first})"
            fingerprint.append(label)
        if not self_closing:
            depth += 1
    return fingerprint


def _collect_all_fingerprints(exclude_slug: str) -> list[list[str]]:
    """Return fingerprints of all shipped themes except `exclude_slug`."""
    fps: list[list[str]] = []
    for theme_root in iter_themes(stages=()):
        if theme_root.name == exclude_slug:
            continue
        fp_path = theme_root / "templates" / "front-page.html"
        if fp_path.is_file():
            fps.append(_fingerprint_main(fp_path.read_text()))
    return fps


def _is_fingerprint_unique(fp: list[str], others: list[list[str]]) -> bool:
    return fp not in others


def _add_layout_class(html: str, slug: str) -> str:
    """Inject ``className: wo-layout-<slug>`` into the target group block.

    Targets the FIRST ``wp:group`` direct child of the ``<main>`` group.
    If the first child is ``wp:pattern``, targets the SECOND direct child
    that IS a ``wp:group``.
    """
    class_value = f"wo-layout-{slug}"

    # Find the <main> group opener
    main_match: re.Match | None = None
    for m in re.finditer(r"<!--\s*wp:group\s+(\{[^>]*?\})\s*-->", html):
        try:
            attrs = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if attrs.get("tagName") == "main":
            main_match = m
            break
    if main_match is None:
        return html

    # Walk direct children; collect matches for group blocks at depth==0
    target_match: re.Match | None = None
    first_is_pattern = False
    depth = 0
    group_children_seen = 0
    pattern_children_seen = 0

    for tok in _DELIM_RE.finditer(html, pos=main_match.end()):
        name = tok.group(1)
        attrs_json = tok.group(2) or ""
        self_closing = tok.group(3) == "/"

        if name.startswith("/wp:"):
            if depth == 0:
                break
            depth -= 1
            continue

        if depth == 0:
            block = name[len("wp:"):]
            if block == "pattern":
                pattern_children_seen += 1
                if group_children_seen == 0 and pattern_children_seen == 1:
                    first_is_pattern = True
            elif block == "group":
                # Check it doesn't already have a wo-layout class
                try:
                    attrs = json.loads(attrs_json) if attrs_json else {}
                except json.JSONDecodeError:
                    attrs = {}
                existing_classes = attrs.get("className", "") or ""
                if f"wo-layout-" in existing_classes:
                    # Already has a variant class — nothing to do
                    return html
                group_children_seen += 1
                # Pick the first group if first child was a pattern, else
                # pick the first group regardless.
                if first_is_pattern and group_children_seen == 1:
                    target_match = tok
                    break
                elif not first_is_pattern and group_children_seen == 1:
                    target_match = tok
                    break

        if not self_closing:
            depth += 1

    if target_match is None:
        return html

    # Splice: add/extend className in the JSON attrs of the target block
    start, end = target_match.start(), target_match.end()
    original_tok = html[start:end]
    attrs_json = target_match.group(2) or ""
    try:
        attrs = json.loads(attrs_json) if attrs_json else {}
    except json.JSONDecodeError:
        attrs = {}

    existing_cls = attrs.get("className", "") or ""
    new_cls = (existing_cls + " " + class_value).strip() if existing_cls else class_value
    attrs["className"] = new_cls

    new_attrs = json.dumps(attrs, separators=(",", ":"), ensure_ascii=False)
    new_tok = f"<!-- wp:group {new_attrs} -->"
    return html[:start] + new_tok + html[end:]


def diversify_theme(theme_root: Path, *, quiet: bool = False) -> bool:
    """Ensure the theme's front-page fingerprint is unique.

    Returns True if the file was modified.
    """
    slug = theme_root.name
    fp_path = theme_root / "templates" / "front-page.html"
    if not fp_path.is_file():
        if not quiet:
            print(f"  [{slug}] SKIP: no templates/front-page.html")
        return False

    html = fp_path.read_text(encoding="utf-8")
    current_fp = _fingerprint_main(html)
    others = _collect_all_fingerprints(slug)

    if _is_fingerprint_unique(current_fp, others):
        if not quiet:
            print(f"  [{slug}] fingerprint already unique: {current_fp}")
        return False

    new_html = _add_layout_class(html, slug)
    if new_html == html:
        if not quiet:
            print(
                f"  [{slug}] WARN: fingerprint clashes but could not inject class "
                f"(fingerprint: {current_fp})"
            )
        return False

    fp_path.write_text(new_html, encoding="utf-8")
    new_fp = _fingerprint_main(new_html)
    if not quiet:
        print(f"  [{slug}] diversified: {current_fp!r} → {new_fp!r}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--theme", metavar="SLUG")
    grp.add_argument("--all", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.all:
        changed = 0
        for theme_root in iter_themes(stages=()):
            if diversify_theme(theme_root, quiet=args.quiet):
                changed += 1
        print(f"Modified {changed} theme(s).")
        return 0

    theme_root = resolve_theme_root(args.theme)
    diversify_theme(theme_root, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())

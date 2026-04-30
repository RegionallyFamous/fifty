#!/usr/bin/env python3
"""Render `<slug>/design-target.json` into the live theme files.

This is the deterministic compiler that turns the structured target into:

* A complete palette in `<slug>/theme.json` (every entry in
  `_design_lib.KNOWN_COLOR_SLUGS` gets a value derived from the brand
  hexes, not Obel's leftovers).
* A per-theme `<slug>/design-intent.md` rubric that the vision reviewer
  reads (replaces the previous "clone Obel's intent verbatim" step).
* A best-effort font-family update for any slot named in
  `target.type` — the actual `.woff2` files still need to be on disk
  for the font to load, but at least theme.json points at the right
  family + fallback now.

The renderer never invents a hex that wasn't in the target or derivable
from one. The only LLM in the picture is the (optional) extractor that
wrote `design-target.json`; this script is pure Python.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import _design_target_lib as dt
from _design_lib import (
    KNOWN_COLOR_SLUGS,
    apply_fonts,
    apply_palette,
    serialize_theme_json,
)
from _lib import MONOREPO_ROOT, iter_themes


def _theme_dir(slug: str) -> Path:
    return MONOREPO_ROOT / slug


def _target_path(slug: str) -> Path:
    return _theme_dir(slug) / "design-target.json"


def _intent_path(slug: str) -> Path:
    return _theme_dir(slug) / "design-intent.md"


def _theme_json_path(slug: str) -> Path:
    return _theme_dir(slug) / "theme.json"


def _apply_target_to_theme_json(target: dt.DesignTarget) -> bool:
    """Write the expanded palette + fonts back into the theme's theme.json.

    Returns True if the file was modified.
    """
    path = _theme_json_path(target.slug)
    if not path.is_file():
        return False

    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    expanded = dt.expand_palette(target)
    # Only the canonical 16 slugs go in. Any extra hexes the source theme
    # ships are left untouched (e.g. brand-specific palette extensions a
    # theme adds in addition to the standard set).
    palette_to_apply = {slug: expanded[slug] for slug in expanded if slug in KNOWN_COLOR_SLUGS}
    apply_palette(data, palette_to_apply)

    # Fonts: only apply slots that are real font defs, skip None/null
    # entries (which mean "this slot is unused for this theme").
    fonts_to_apply: dict[str, Any] = {}
    for slot in ("display", "sans", "serif", "mono"):
        value = target.type.get(slot)
        if not isinstance(value, dict):
            continue
        # Normalise: weights must be a list of ints
        weights = value.get("weights") or [400]
        fonts_to_apply[slot] = {
            "family": value["family"],
            "fallback": value.get("fallback", ""),
            "google_font": bool(value.get("google_font", True)),
            "weights": [int(w) for w in weights],
        }
    if fonts_to_apply:
        apply_fonts(data, fonts_to_apply)

    new_text = serialize_theme_json(data)
    if path.read_text(encoding="utf-8") == new_text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def _render_one(slug: str, *, write_intent: bool, write_theme_json: bool) -> int:
    target_path = _target_path(slug)
    if not target_path.is_file():
        print(
            f"!! {slug}: missing design-target.json at "
            f"{target_path.relative_to(MONOREPO_ROOT)} — "
            f"run `python3 bin/extract-design-target.py {slug}` first.",
            file=sys.stderr,
        )
        return 1

    try:
        target = dt.read_target(target_path)
    except Exception as exc:
        print(f"!! {slug}: invalid design-target.json: {exc}", file=sys.stderr)
        return 1

    if write_intent:
        live_palette: dict[str, str] | None = None
        if not write_theme_json:
            # Caller said "don't touch theme.json" — that means the live
            # palette is whatever is shipped, not whatever the target
            # would project. Read the live values so the rubric reflects
            # what the vision reviewer will actually see on screen.
            tj = _theme_json_path(slug)
            if tj.is_file():
                try:
                    raw = json.loads(tj.read_text(encoding="utf-8"))
                    palette = (
                        raw.get("settings", {}).get("color", {}).get("palette") or []
                    )
                    live_palette = {
                        str(entry.get("slug")): str(entry.get("color")).lower()
                        for entry in palette
                        if isinstance(entry, dict) and entry.get("slug") and entry.get("color")
                    }
                except Exception:
                    live_palette = None
        intent_md = dt.render_design_intent_md(target, live_palette=live_palette)
        intent_path = _intent_path(slug)
        intent_path.write_text(intent_md, encoding="utf-8")
        print(f"ok {slug}: wrote {intent_path.relative_to(MONOREPO_ROOT)}")

    if write_theme_json:
        if _apply_target_to_theme_json(target):
            print(
                f"ok {slug}: updated {_theme_json_path(slug).relative_to(MONOREPO_ROOT)}"
            )
        else:
            print(
                f"   {slug}: {_theme_json_path(slug).relative_to(MONOREPO_ROOT)} unchanged"
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", nargs="?", help="theme slug")
    parser.add_argument(
        "--all",
        action="store_true",
        help="render every theme that has a design-target.json on disk",
    )
    parser.add_argument(
        "--no-theme-json",
        action="store_true",
        help="skip the theme.json palette/fonts rewrite (only write design-intent.md)",
    )
    parser.add_argument(
        "--no-intent",
        action="store_true",
        help="skip the design-intent.md regeneration",
    )
    args = parser.parse_args(argv)

    if args.all and args.slug:
        parser.error("pass either a slug or --all, not both")

    slugs: list[str] = []
    if args.all:
        for theme_dir in iter_themes():
            if _target_path(theme_dir.name).is_file():
                slugs.append(theme_dir.name)
    elif args.slug:
        slugs.append(args.slug)
    else:
        parser.error("provide a theme slug or --all")

    rc = 0
    for slug in slugs:
        rc = max(
            rc,
            _render_one(
                slug,
                write_intent=not args.no_intent,
                write_theme_json=not args.no_theme_json,
            ),
        )
    return rc


if __name__ == "__main__":
    sys.exit(main())

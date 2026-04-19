#!/usr/bin/env python3
"""Print every design token defined in theme.json.

Saves agents the cost of reading and parsing theme.json just to discover
what colors/sizes/spacings exist. Output is short and grep-friendly.

Usage:
    python3 bin/list-tokens.py                 # human-readable text
    python3 bin/list-tokens.py --format json   # JSON for machine consumption
    python3 bin/list-tokens.py colors          # only show colors
    python3 bin/list-tokens.py spacing         # only show spacing scale
    python3 bin/list-tokens.py --css-vars      # show with CSS variable names

Categories: colors, fonts, font-sizes, spacing, shadows, layout, custom

Requires Python 3.8+ (standard library only).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import resolve_theme_root  # noqa: E402

ROOT: Path = Path.cwd()
THEME: Path = ROOT / "theme.json"


def load_theme() -> dict:
    return json.loads(THEME.read_text(encoding="utf-8"))


def collect(data: dict) -> dict:
    settings = data.get("settings", {})
    color = settings.get("color", {})
    typography = settings.get("typography", {})
    spacing = settings.get("spacing", {})
    shadow = settings.get("shadow", {})
    layout = settings.get("layout", {})
    custom = settings.get("custom", {})

    return {
        "colors": [(p["slug"], p.get("color", "")) for p in color.get("palette", [])],
        "fonts": [
            (f["slug"], (f.get("fontFamily", "") or "").split(",")[0].strip("'\""))
            for f in typography.get("fontFamilies", [])
        ],
        "font-sizes": [
            (s["slug"], _fluid(s)) for s in typography.get("fontSizes", [])
        ],
        "spacing": [(s["slug"], s.get("size", "")) for s in spacing.get("spacingSizes", [])],
        "shadows": [(s["slug"], s.get("shadow", "")) for s in shadow.get("presets", [])],
        "layout": [(k, v) for k, v in layout.items()],
        "custom": _flatten_custom(custom),
    }


def _fluid(entry: dict) -> str:
    size = entry.get("size", "")
    fluid = entry.get("fluid")
    if isinstance(fluid, dict):
        return f"{size}  (fluid: {fluid.get('min','?')} -> {fluid.get('max','?')})"
    return str(size)


def _flatten_custom(node: dict, prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for k, v in node.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.extend(_flatten_custom(v, key))
        else:
            out.append((key, str(v)))
    return out


def render_text(tokens: dict, only: str | None, css_vars: bool) -> str:
    lines: list[str] = []
    sections = list(tokens.keys()) if not only else [only]
    for section in sections:
        items = tokens.get(section)
        if not items:
            continue
        lines.append(f"\n{section}")
        lines.append("-" * len(section))
        width = max((len(str(s)) for s, _ in items), default=4) + 2
        for slug, value in items:
            if css_vars:
                var = _css_var(section, slug)
                lines.append(f"  {str(slug).ljust(width)}{value}    {var}")
            else:
                lines.append(f"  {str(slug).ljust(width)}{value}")
    return "\n".join(lines).lstrip()


def _css_var(section: str, slug: str) -> str:
    map_ = {
        "colors": f"var(--wp--preset--color--{slug})",
        "fonts": f"var(--wp--preset--font-family--{slug})",
        "font-sizes": f"var(--wp--preset--font-size--{slug})",
        "spacing": f"var(--wp--preset--spacing--{slug})",
        "shadows": f"var(--wp--preset--shadow--{slug})",
        "custom": f"var(--wp--custom--{slug.replace('.', '--')})",
    }
    return map_.get(section, "")


def main() -> int:
    global ROOT, THEME
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--theme", default=None, help="Theme directory name (defaults to cwd if it has theme.json).")
    parser.add_argument("category", nargs="?", choices=["colors", "fonts", "font-sizes", "spacing", "shadows", "layout", "custom"])
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--css-vars", action="store_true", help="Show the CSS variable name next to each token.")
    args = parser.parse_args()

    ROOT = resolve_theme_root(args.theme)
    THEME = ROOT / "theme.json"

    if not THEME.exists():
        print(f"error: {THEME} not found", file=sys.stderr)
        return 2

    tokens = collect(load_theme())

    if args.format == "json":
        if args.category:
            print(json.dumps(dict(tokens.get(args.category, [])), indent=2))
        else:
            print(json.dumps({k: dict(v) for k, v in tokens.items()}, indent=2))
        return 0

    print(render_text(tokens, args.category, args.css_vars))
    return 0


if __name__ == "__main__":
    sys.exit(main())

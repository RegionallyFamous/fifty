#!/usr/bin/env python3
"""Generate INDEX.md, a single-file project index for LLMs and humans.

INDEX.md saves an assistant from spending tokens reading files just to discover:
  - what templates and parts exist and what each covers
  - what patterns are registered (slug, title, description, categories)
  - what style variations are available
  - every design token defined in theme.json
  - every block already styled in theme.json

Run this script after any structural change to the codebase. `bin/check.py`
verifies INDEX.md is in sync and fails if it is stale.

Usage:
    python3 bin/build-index.py            # write INDEX.md
    python3 bin/build-index.py --check    # exit 1 if INDEX.md is out of date

Requires Python 3.8+ (standard library only).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import iter_themes, resolve_theme_root  # noqa: E402

ROOT: Path = Path.cwd()
INDEX: Path = ROOT / "INDEX.md"

# One-line description for every well-known WP / WC template slug. When a
# template ships in this theme, the matching description is shown.
TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "index.html": "Default fallback for any unspecified template",
    "front-page.html": "Site front page (when set to a static page)",
    "home.html": "Blog index (when front page is a static page)",
    "page.html": "Default static page",
    "page-cart.html": "WooCommerce cart page",
    "page-checkout.html": "WooCommerce checkout page",
    "page-coming-soon.html": "WooCommerce coming-soon / launch placeholder",
    "single.html": "Default single post",
    "single-product.html": "WooCommerce single product",
    "singular.html": "Fallback for posts and pages",
    "archive.html": "Default post archive",
    "archive-product.html": "WooCommerce shop archive",
    "category.html": "Category archive",
    "tag.html": "Tag archive",
    "author.html": "Author archive",
    "date.html": "Date archive",
    "taxonomy.html": "Default custom taxonomy archive",
    "search.html": "Search results",
    "product-search-results.html": "WooCommerce product search results",
    "order-confirmation.html": "WooCommerce order received page",
    "404.html": "404 not-found",
    "page-no-title.html": "Custom template: page without printed title",
    "page-full-width.html": "Custom template: full-bleed page (no constrained content width)",
    "page-landing.html": "Custom template: landing page (no header/footer, full-bleed)",
}

PART_DESCRIPTIONS: dict[str, str] = {
    "header.html": "Site header (logo, nav, mini-cart, search)",
    "footer.html": "Site footer (columns, copyright)",
    "checkout-header.html": "Stripped header used during checkout",
    "comments.html": "Post comments region",
    "no-results.html": "Empty-state message for queries with no results",
    "post-meta.html": "Post metadata strip (date, author, terms)",
    "product-meta.html": "Product metadata strip (SKU, categories, tags)",
    "sidebar-product-filters.html": "Sidebar with product filter blocks",
}


def run_for(theme_root: Path, check_only: bool) -> int:
    global ROOT, INDEX
    ROOT = theme_root
    INDEX = ROOT / "INDEX.md"

    new_text = build_index()

    if check_only:
        if not INDEX.exists():
            print(f"{theme_root.name}: INDEX.md is missing. Run: python3 bin/build-index.py {theme_root.name}", file=sys.stderr)
            return 1
        if INDEX.read_text(encoding="utf-8") != new_text:
            print(
                f"{theme_root.name}: INDEX.md is out of date. Run: python3 bin/build-index.py {theme_root.name}",
                file=sys.stderr,
            )
            return 1
        return 0

    INDEX.write_text(new_text, encoding="utf-8")
    print(f"{theme_root.name}: wrote INDEX.md ({len(new_text.splitlines())} lines)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme", nargs="?", default=None, help="Theme directory name (defaults to cwd).")
    parser.add_argument("--all", action="store_true", help="Run against every theme in the monorepo.")
    parser.add_argument("--check", action="store_true", help="Exit 1 if INDEX.md is stale.")
    args = parser.parse_args()

    if args.all:
        codes = [run_for(t, args.check) for t in iter_themes()]
        return 1 if any(codes) else 0

    return run_for(resolve_theme_root(args.theme), args.check)


def build_index() -> str:
    parts: list[str] = []
    parts.append(header_section())
    parts.append(stats_section())
    parts.append(tree_section())
    parts.append(templates_section())
    parts.append(parts_section())
    parts.append(patterns_section())
    parts.append(style_variations_section())
    parts.append(tokens_section())
    parts.append(block_styles_section())
    parts.append(scripts_section())
    parts.append(docs_section())
    return "\n".join(parts).rstrip() + "\n"


def header_section() -> str:
    return (
        "# Project Index\n"
        "\n"
        "Auto-generated by `python3 bin/build-index.py`. **Do not edit by hand.**\n"
        "\n"
        "If this file is out of date, `python3 bin/check.py` will fail. Regenerate it with `python3 bin/build-index.py`.\n"
        "\n"
        "Read this file at the start of any LLM session to discover the project's structure without reading every file individually.\n"
    )


def stats_section() -> str:
    theme = load_theme()
    blocks = theme.get("styles", {}).get("blocks", {}) or {}
    n_templates = len(list((ROOT / "templates").glob("*.html"))) if (ROOT / "templates").exists() else 0
    n_parts = len(list((ROOT / "parts").glob("*.html"))) if (ROOT / "parts").exists() else 0
    n_patterns = len(list((ROOT / "patterns").glob("*.php"))) if (ROOT / "patterns").exists() else 0
    n_styles = len(list((ROOT / "styles").glob("*.json"))) if (ROOT / "styles").exists() else 0
    n_block_styles = len(blocks)
    n_core = sum(1 for k in blocks if k.startswith("core/"))
    n_wc = sum(1 for k in blocks if k.startswith("woocommerce/"))

    return (
        "## At a glance\n"
        "\n"
        f"- {n_templates} templates, {n_parts} parts\n"
        f"- {n_patterns} starter patterns\n"
        f"- {n_styles} style variations\n"
        f"- {n_block_styles} block style entries in `theme.json` ({n_core} core, {n_wc} woocommerce)\n"
    )


def tree_section() -> str:
    skip = {".git", "node_modules", "vendor", "__pycache__", "languages"}
    lines: list[str] = ["## File tree", "", "```"]
    lines.extend(_tree(ROOT, prefix="", skip=skip))
    lines.append("```")
    return "\n".join(lines) + "\n"


def _tree(path: Path, prefix: str, skip: set[str]) -> list[str]:
    entries = sorted(
        [p for p in path.iterdir() if p.name not in skip and not p.name.startswith(".") or p.name in {".editorconfig"}],
        key=lambda p: (not p.is_dir(), p.name.lower()),
    )
    lines: list[str] = []
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "`-- " if is_last else "|-- "
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{prefix}{connector}{entry.name}{suffix}")
        if entry.is_dir():
            extension = "    " if is_last else "|   "
            lines.extend(_tree(entry, prefix + extension, skip))
    return lines


def templates_section() -> str:
    folder = ROOT / "templates"
    if not folder.exists():
        return ""
    rows = []
    for path in sorted(folder.glob("*.html")):
        desc = TEMPLATE_DESCRIPTIONS.get(path.name, "(no description registered)")
        rows.append(f"| `templates/{path.name}` | {desc} |")
    return (
        "## Templates\n"
        "\n"
        "| File | Covers |\n"
        "|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


def parts_section() -> str:
    folder = ROOT / "parts"
    if not folder.exists():
        return ""
    rows = []
    for path in sorted(folder.glob("*.html")):
        desc = PART_DESCRIPTIONS.get(path.name, "(no description registered)")
        rows.append(f"| `parts/{path.name}` | {desc} |")
    return (
        "## Parts\n"
        "\n"
        "| File | Notes |\n"
        "|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


PATTERN_HEADER_RE = re.compile(r"^\s*\*\s*([A-Za-z][A-Za-z ]*?):\s*(.*?)\s*$", re.MULTILINE)


def patterns_section() -> str:
    folder = ROOT / "patterns"
    if not folder.exists():
        return ""
    blocks: list[str] = []
    for path in sorted(folder.glob("*.php")):
        text = path.read_text(encoding="utf-8")
        # Header lives between /** and */ near the top
        header = text.split("*/", 1)[0]
        fields: dict[str, str] = {}
        for m in PATTERN_HEADER_RE.finditer(header):
            fields[m.group(1).strip().lower()] = m.group(2).strip()
        title = fields.get("title", path.stem)
        slug = fields.get("slug", "")
        cats = fields.get("categories", "")
        desc = fields.get("description", "")
        keywords = fields.get("keywords", "")
        blocks.append(
            f"### `patterns/{path.name}`\n"
            f"\n"
            f"- **Slug:** `{slug}`\n"
            f"- **Title:** {title}\n"
            f"- **Categories:** {cats}\n"
            f"- **Keywords:** {keywords}\n"
            f"- **Description:** {desc}\n"
        )
    return "## Patterns\n\n" + "\n".join(blocks)


def style_variations_section() -> str:
    folder = ROOT / "styles"
    if not folder.exists():
        return ""
    rows = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            title = data.get("title", "(no title)")
        except Exception:
            title = "(could not parse)"
        rows.append(f"| `styles/{path.name}` | {title} |")
    return (
        "## Style variations\n"
        "\n"
        "| File | Title shown in Site Editor > Styles |\n"
        "|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


def tokens_section() -> str:
    theme = load_theme()
    settings = theme.get("settings", {})
    color = settings.get("color", {}) or {}
    typography = settings.get("typography", {}) or {}
    spacing = settings.get("spacing", {}) or {}
    shadow = settings.get("shadow", {}) or {}
    layout = settings.get("layout", {}) or {}
    custom = settings.get("custom", {}) or {}

    out: list[str] = ["## Design tokens (from `theme.json`)", ""]

    out.append("### Colors")
    out.append("")
    for p in color.get("palette", []):
        out.append(f"- `{p['slug']}` = {p.get('color','')} ({p.get('name','')})")
    out.append("")

    out.append("### Font sizes")
    out.append("")
    for s in typography.get("fontSizes", []):
        out.append(f"- `{s['slug']}` = {s.get('size','')}")
    out.append("")

    out.append("### Font families")
    out.append("")
    for f in typography.get("fontFamilies", []):
        primary = (f.get("fontFamily", "") or "").split(",")[0].strip("'\"")
        out.append(f"- `{f['slug']}` = {primary}")
    out.append("")

    out.append("### Spacing scale")
    out.append("")
    for s in spacing.get("spacingSizes", []):
        out.append(f"- `{s['slug']}` = {s.get('size','')}")
    out.append("")

    if shadow.get("presets"):
        out.append("### Shadows")
        out.append("")
        for s in shadow["presets"]:
            out.append(f"- `{s['slug']}` = {s.get('shadow','')}")
        out.append("")

    if layout:
        out.append("### Layout")
        out.append("")
        for k, v in layout.items():
            out.append(f"- `{k}` = {v}")
        out.append("")

    if custom:
        out.append("### Custom (settings.custom)")
        out.append("")
        for slug, value in _flatten(custom):
            out.append(f"- `{slug}` = {value}")
        out.append("")

    return "\n".join(out)


def _flatten(node: dict, prefix: str = "") -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for k, v in node.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.extend(_flatten(v, key))
        else:
            items.append((key, str(v)))
    return items


def block_styles_section() -> str:
    blocks = load_theme().get("styles", {}).get("blocks", {}) or {}
    core = sorted(k for k in blocks if k.startswith("core/"))
    wc = sorted(k for k in blocks if k.startswith("woocommerce/"))
    other = sorted(k for k in blocks if not k.startswith(("core/", "woocommerce/")))

    out: list[str] = [
        "## Block styles defined in `theme.json`",
        "",
        "If you want to add styling to one of these blocks, an entry already exists. Edit it.",
        "If you want to style a block not listed here, add a new entry under `styles.blocks.<name>` (verify the name first via `bin/validate-theme-json.py`).",
        "",
        f"### `core/*` ({len(core)})",
        "",
        ", ".join(f"`{b}`" for b in core) if core else "(none)",
        "",
        f"### `woocommerce/*` ({len(wc)})",
        "",
        ", ".join(f"`{b}`" for b in wc) if wc else "(none)",
        "",
    ]
    if other:
        out.extend([f"### Other ({len(other)})", "", ", ".join(f"`{b}`" for b in other), ""])
    return "\n".join(out)


def scripts_section() -> str:
    folder = ROOT / "bin"
    if not folder.exists():
        return ""
    rows: list[str] = []
    for path in sorted(folder.glob("*.py")):
        first_doc = _module_docstring(path)
        rows.append(f"| `bin/{path.name}` | {first_doc} |")
    return (
        "## Tooling (`bin/`)\n"
        "\n"
        "| Script | Purpose |\n"
        "|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


def _module_docstring(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r'"""(.+?)"""', text, re.DOTALL)
    if not m:
        return ""
    first = m.group(1).strip().splitlines()[0]
    return first


def docs_section() -> str:
    folder = ROOT / "docs"
    if not folder.exists():
        return ""
    rows: list[str] = []
    for path in sorted(folder.glob("*.md")):
        first_h1 = _first_heading(path)
        rows.append(f"| `docs/{path.name}` | {first_h1} |")
    return (
        "## Documentation (`docs/`)\n"
        "\n"
        "| File | Topic |\n"
        "|---|---|\n"
        + "\n".join(rows)
        + "\n"
    )


def _first_heading(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def load_theme() -> dict:
    return json.loads((ROOT / "theme.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(main())

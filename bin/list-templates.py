#!/usr/bin/env python3
"""List every template and the WordPress URL pattern it handles.

Output is plain text designed to be pasted into LLM context so the model
knows which file to edit for a given URL without reading the directory.

Usage:
    python3 bin/list-templates.py

WordPress template hierarchy reference:
  https://developer.wordpress.org/themes/basics/template-hierarchy/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import resolve_theme_root  # noqa: E402

ROOT: Path = Path.cwd()

# Map template slug -> human URL description.
# WP picks the most-specific matching template from top to bottom.
TEMPLATE_MAP: list[tuple[str, str]] = [
    # WooCommerce
    ("single-product",              "/product/<slug>  (single product page)"),
    ("archive-product",             "/shop  and  /product-category/*  (product archive + fallback for all product taxonomies)"),
    ("product-search-results",      "/  ?s=<term>&post_type=product  (product search)"),
    ("page-cart",                   "/cart  (WooCommerce cart page)"),
    ("page-checkout",               "/checkout  (WooCommerce checkout page)"),
    ("order-confirmation",          "/checkout/order-received/*  (order confirmation)"),
    # WordPress page/post
    ("front-page",                  "/  (static front page when set in Settings > Reading)"),
    ("home",                        "/  (blog posts index when front page is static)"),
    ("single",                      "/yyyy/mm/dd/<slug>  (single blog post)"),
    ("page",                        "/<slug>  (standard page with title + featured image)"),
    ("singular",                    "/<slug>  (fallback for any singular: page without featured image)"),
    # Archives
    ("archive",                     "/category/*  /tag/*  /author/*  /date/*  (generic archive fallback)"),
    ("category",                    "/category/<slug>  (post category archive)"),
    ("tag",                         "/tag/<slug>  (post tag archive)"),
    ("author",                      "/author/<name>  (author archive)"),
    ("date",                        "/yyyy/  /yyyy/mm/  /yyyy/mm/dd/  (date archives)"),
    ("taxonomy",                    "/custom-taxonomy/<term>  (custom taxonomy fallback)"),
    # Utility
    ("search",                      "/?s=<term>  (site-wide search results)"),
    ("404",                         "/*  (404 not found)"),
    ("index",                       "*  (catch-all fallback; loaded when no other template matches)"),
    # Custom page templates (applied via Page Attributes in the editor)
    ("page-coming-soon",            "any page  (assign via Page Attributes > Template)"),
    ("page-no-title",               "any page  (assign via Page Attributes > Template — no printed title)"),
    ("page-full-width",             "any page  (assign via Page Attributes > Template — no max-width)"),
    ("page-landing",                "any page  (assign via Page Attributes > Template — no header/footer)"),
]


def main() -> None:
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme", nargs="?", default=None, help="Theme directory name (defaults to cwd).")
    args = parser.parse_args()
    ROOT = resolve_theme_root(args.theme)

    templates_dir = ROOT / "templates"
    existing = {p.stem for p in templates_dir.glob("*.html")}

    col_w = max(len(slug) for slug, _ in TEMPLATE_MAP) + 2
    print("Template                          ->  URL / context")
    print("-" * 78)
    for slug, url in TEMPLATE_MAP:
        file = f"templates/{slug}.html"
        exists = slug in existing
        marker = "   " if exists else " * "  # * = registered but file missing
        print(f"{marker}{file:<{col_w + 12}}  {url}")

    missing = existing - {slug for slug, _ in TEMPLATE_MAP}
    if missing:
        print()
        print("Files in templates/ not in this map:")
        for s in sorted(missing):
            print(f"    templates/{s}.html")

    print()
    print("* = entry in theme.json customTemplates but .html file not found")


if __name__ == "__main__":
    main()

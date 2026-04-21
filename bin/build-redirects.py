#!/usr/bin/env python3
"""Generate the docs/ folder that GitHub Pages serves to give every theme a
short, memorable URL that redirects to the canonical (long) WordPress
Playground deeplink for that theme.

Why this exists:
    A canonical Playground deeplink looks like

        https://playground.wordpress.net/?blueprint-url=
            https://raw.githubusercontent.com/<org>/<repo>/<branch>/<theme>/playground/blueprint.json
            &url=/shop/

    That is ~200 characters before any extra parameters. Hard to share, hard
    to type, hard to remember, ugly in tweets and slide decks. wp.me URLs
    are issued only for posts on real wordpress.com / wordpress.org-hosted
    sites and cannot be minted for arbitrary URLs, so we self-host the
    short links via GitHub Pages.

What this script does:
    For every theme in the monorepo it generates a static HTML redirector
    under docs/<theme>/<page-slug>/index.html. Each page_slug corresponds
    to a meaningful entry point of the demo storefront (home, shop, single
    product, cart, checkout, my-account, journal, 404). The HTML uses both
    a `<meta http-equiv="refresh">` (works without JS / on link previews)
    and a `<script>location.replace(...)</script>` (faster, no flash) to
    bounce the browser to the right Playground deeplink.

    It also writes:
      * docs/index.html        — landing page listing every theme + its
                                 short links, suitable as the public face
                                 of the repo.
      * docs/.nojekyll         — tells GH Pages not to run Jekyll, which
                                 would otherwise drop files / folders
                                 starting with `_` and slow builds for no
                                 reason on a static site like this one.

    The script is fully idempotent: every file under docs/ is regenerated
    from scratch on each run, so removing a PAGES entry deletes the
    corresponding folder, and renaming a theme cleans up the old slug.

GitHub Pages setup (one-time, manual):
    Repo settings → Pages → Source: "Deploy from a branch" → Branch: main,
    Folder: /docs → Save. Repo settings → Pages → Custom domain →
    `demo.regionallyfamous.com` (the same value lives in docs/CNAME, which
    this script preserves across rebuilds). Visit
    https://demo.regionallyfamous.com/ once Pages reports a successful
    build (the github.io URL still resolves as a fallback).

Usage:
    python3 bin/build-redirects.py        # rebuild docs/ for every theme
    python3 bin/build-redirects.py --dry-run

Run this whenever you add/remove a theme or change a blueprint URL. It is
safe (and cheap) to re-run on every change; bin/clone.py reminds new-theme
authors to run it as part of the standard add-a-theme workflow.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import (
    GH_PAGES_BASE_URL,
    GITHUB_BRANCH,
    GITHUB_ORG,
    GITHUB_REPO,
    MONOREPO_ROOT,
    gh_pages_short_url,
    iter_themes,
    playground_deeplink,
    theme_blueprint_raw_url,
)

DOCS_DIR = MONOREPO_ROOT / "docs"

# Each entry becomes one redirector under docs/<theme>/<slug>/index.html.
# The blank-slug entry produces the theme root: docs/<theme>/index.html.
#
# Keep `url` aligned with what the demo content actually exposes — every
# entry below is a known-good route in the seeded WordPress install. If you
# add a route here, also add a row to the per-theme README "Deeplinks"
# table so the long URL is discoverable via search too.
PAGES: list[dict[str, str]] = [
    {"slug": "",                          "url": "/",                           "label": "Home"},
    {"slug": "shop",                      "url": "/shop/",                      "label": "Shop"},
    {"slug": "product/bottled-morning",   "url": "/product/bottled-morning/",   "label": "Single product"},
    {"slug": "cart",                      "url": "/cart/?demo=cart",            "label": "Cart (pre-filled)"},
    {"slug": "checkout",                  "url": "/checkout/?demo=cart",        "label": "Checkout"},
    {"slug": "my-account",                "url": "/my-account/",                "label": "My Account"},
    {"slug": "journal",                   "url": "/journal/",                   "label": "Journal"},
    {"slug": "404",                       "url": "/this-route-does-not-exist/", "label": "404"},
]


def html_escape(value: str) -> str:
    """Minimal escaping for HTML attributes / text. Keeps the output free
    of any third-party dependency."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def theme_display_name(theme_dir: Path) -> str:
    """Read the human-readable theme name from theme.json, falling back to
    the title-cased slug. Mirrors the helper in bin/sync-playground.py — I
    intentionally keep these two definitions side-by-side rather than
    sharing through _lib because they encode the same convention twice and
    drifting them is a useful smoke test."""
    theme_json = theme_dir / "theme.json"
    try:
        data = json.loads(theme_json.read_text())
        title = data.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    except (OSError, json.JSONDecodeError):
        pass
    slug = theme_dir.name
    return slug[:1].upper() + slug[1:].lower()


REDIRECT_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
\t<meta charset="utf-8">
\t<title>{title} — WordPress Playground</title>
\t<meta name="viewport" content="width=device-width,initial-scale=1">
\t<meta name="robots" content="noindex,follow">
\t<meta name="description" content="{description}">
\t<meta http-equiv="refresh" content="0; url={deeplink_html}">
\t<link rel="canonical" href="{deeplink_html}">
\t<meta property="og:type" content="website">
\t<meta property="og:title" content="{title}">
\t<meta property="og:description" content="{description}">
\t<meta property="og:url" content="{short_url_html}">
\t<style>
\t\thtml,body{{height:100%;margin:0;background:#0f0f10;color:#f5f5f4;font:16px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
\t\tmain{{min-height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:2rem;gap:1rem}}
\t\th1{{font-size:1.25rem;font-weight:600;letter-spacing:.01em;margin:0}}
\t\tp{{margin:0;color:#a8a29e;max-width:34rem}}
\t\ta{{color:#fafaf9}}
\t\t.spinner{{width:32px;height:32px;border-radius:50%;border:2px solid #44403c;border-top-color:#fafaf9;animation:spin .8s linear infinite}}
\t\t@keyframes spin{{to{{transform:rotate(360deg)}}}}
\t\t@media (prefers-reduced-motion:reduce){{.spinner{{animation:none}}}}
\t</style>
</head>
<body>
\t<main>
\t\t<div class="spinner" aria-hidden="true"></div>
\t\t<h1>Loading {title}…</h1>
\t\t<p>Booting <strong>{theme_name_html}</strong> ({label_html}) in WordPress Playground. The first boot fetches WordPress, WooCommerce, and the demo content, so it can take 20–60 seconds.</p>
\t\t<p><a href="{deeplink_html}">Click here if you are not redirected.</a></p>
\t</main>
\t<script>location.replace({deeplink_json});</script>
</body>
</html>
"""


def render_redirector(
    theme_name: str,
    page_label: str,
    short_url: str,
    deeplink: str,
) -> str:
    title = f"{theme_name} — {page_label}"
    description = (
        f"Boot the {theme_name} demo storefront in WordPress Playground "
        f"({page_label}). No install, runs entirely in your browser."
    )
    return REDIRECT_TEMPLATE.format(
        title=html_escape(title),
        description=html_escape(description),
        theme_name_html=html_escape(theme_name),
        label_html=html_escape(page_label),
        short_url_html=html_escape(short_url),
        deeplink_html=html_escape(deeplink),
        deeplink_json=json.dumps(deeplink),
    )


INDEX_HEAD = """<!doctype html>
<html lang="en">
<head>
\t<meta charset="utf-8">
\t<title>Fifty — WordPress Block Theme Variants</title>
\t<meta name="viewport" content="width=device-width,initial-scale=1">
\t<meta name="description" content="Open one of the Fifty WordPress block theme variants live in WordPress Playground. No install, runs entirely in your browser.">
\t<meta property="og:type" content="website">
\t<meta property="og:title" content="Fifty — WordPress Block Theme Variants">
\t<meta property="og:description" content="Open one of the Fifty WordPress block theme variants live in WordPress Playground. No install, runs entirely in your browser.">
\t<meta property="og:url" content="{base_url}">
\t<style>
\t\t:root{{color-scheme:dark light}}
\t\thtml,body{{margin:0;background:#0f0f10;color:#f5f5f4;font:16px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
\t\tmain{{max-width:64rem;margin:0 auto;padding:clamp(2rem,5vw,4rem) clamp(1.25rem,4vw,2rem)}}
\t\theader{{margin-bottom:3rem}}
\t\theader h1{{font-size:clamp(1.75rem,3.5vw,2.5rem);margin:0 0 .5rem;font-weight:700;letter-spacing:-.01em}}
\t\theader p{{margin:0;color:#a8a29e;max-width:42rem}}
\t\theader p a{{color:#fafaf9}}
\t\t.themes{{display:grid;gap:1.25rem;grid-template-columns:repeat(auto-fit,minmax(18rem,1fr))}}
\t\t.theme{{border:1px solid #2c2a27;border-radius:14px;padding:1.5rem;background:#1a1917;display:flex;flex-direction:column;gap:1rem;transition:border-color 160ms ease,transform 160ms ease}}
\t\t.theme:hover{{border-color:#57534e;transform:translateY(-1px)}}
\t\t.theme h2{{margin:0;font-size:1.25rem;font-weight:600}}
\t\t.theme p{{margin:0;color:#a8a29e;font-size:.95rem}}
\t\t.cta{{display:inline-flex;align-items:center;gap:.5rem;background:#fafaf9;color:#0f0f10;padding:.55rem .95rem;border-radius:9999px;text-decoration:none;font-weight:600;font-size:.9rem;align-self:flex-start;transition:background 160ms ease}}
\t\t.cta:hover{{background:#fff}}
\t\tfooter{{margin-top:3rem;padding-top:2rem;border-top:1px solid #2c2a27;color:#78716c;font-size:.85rem}}
\t\tfooter a{{color:#d6d3d1}}
\t\t@media (prefers-color-scheme:light){{
\t\t\thtml,body{{background:#fafaf9;color:#1c1917}}
\t\t\theader p,.theme p{{color:#57534e}}
\t\t\t.theme{{background:#fff;border-color:#e7e5e4}}
\t\t\t.theme:hover{{border-color:#a8a29e}}
\t\t\t.cta{{background:#1c1917;color:#fafaf9}}
\t\t\t.cta:hover{{background:#0c0a09}}
\t\t\tfooter{{border-color:#e7e5e4;color:#78716c}}
\t\t\tfooter a{{color:#44403c}}
\t\t}}
\t</style>
</head>
<body>
\t<main>
\t\t<header>
\t\t\t<h1>Fifty</h1>
\t\t\t<p>A monorepo of WordPress block themes built around a shared <a href="https://github.com/{org}/{repo}/blob/{branch}/obel/">Obel</a> base. Click any theme below to boot a live demo storefront in WordPress Playground — no install, runs entirely in your browser.</p>
\t\t</header>
\t\t<section class="themes">
"""

INDEX_FOOT = """\t\t</section>
\t\t<footer>
\t\t\t<p>Source: <a href="https://github.com/{org}/{repo}">github.com/{org}/{repo}</a> · The first boot of any theme takes 20–60 seconds while it downloads WordPress, WooCommerce, and the demo content.</p>
\t\t</footer>
\t</main>
</body>
</html>
"""


def render_index(themes_html: list[str]) -> str:
    head = INDEX_HEAD.format(
        base_url=html_escape(GH_PAGES_BASE_URL),
        org=html_escape(GITHUB_ORG),
        repo=html_escape(GITHUB_REPO),
        branch=html_escape(GITHUB_BRANCH),
    )
    foot = INDEX_FOOT.format(
        org=html_escape(GITHUB_ORG),
        repo=html_escape(GITHUB_REPO),
    )
    return head + "".join(themes_html) + foot


_STYLE_CSS_DESCRIPTION_RE = re.compile(
    r"^\s*Description:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def theme_description(theme_dir: Path, theme_name: str) -> str:
    """Read the one-sentence theme tagline from style.css's `Description:`
    header (the standard WP source of truth — it's what the Site Editor's
    theme browser shows too). Falls back to the old generic template if
    the header is missing OR if it's the historical clone-script
    boilerplate ("A block-only WooCommerce starter theme. All styling
    is defined in theme.json…"), which is generic across themes and
    actively misleading on the landing page."""
    style_css = theme_dir / "style.css"
    BOILERPLATE_PREFIX = "A block-only WooCommerce starter theme."
    try:
        text = style_css.read_text(encoding="utf-8")
        # style.css starts with `/* … */`, so confine the search to the
        # first comment block so we don't pick up `Description:` inside
        # CSS rules below the header.
        header_end = text.find("*/")
        header = text[:header_end] if header_end != -1 else text[:2000]
        match = _STYLE_CSS_DESCRIPTION_RE.search(header)
        if match:
            description = match.group(1).strip()
            if description and not description.startswith(BOILERPLATE_PREFIX):
                return description
    except OSError:
        pass
    return (
        f"A {theme_name} demo storefront with WooCommerce and sample "
        f"content, ready to click through."
    )


def render_theme_card(theme_dir: Path, theme_name: str, theme_slug: str) -> str:
    # Per-page chips were intentionally removed from the homepage: they
    # used theme-relative paths (`shop/`, `product/…/`) that resolve
    # against the *site root* on demo.regionallyfamous.com (not against
    # the theme card's URL), so they 404'd. The per-page redirectors
    # under docs/<theme>/<slug>/ are still generated and remain useful
    # for sharing a deep link to a specific entry point — they're just
    # not surfaced on the landing page anymore.
    description = theme_description(theme_dir, theme_name)
    return (
        f'\t\t\t<article class="theme">\n'
        f'\t\t\t\t<h2>{html_escape(theme_name)}</h2>\n'
        f'\t\t\t\t<p>{html_escape(description)}</p>\n'
        f'\t\t\t\t<a class="cta" href="{html_escape(theme_slug + "/")}">Open in Playground →</a>\n'
        f'\t\t\t</article>\n'
    )


def write_file(path: Path, contents: str, *, dry_run: bool, written: list[Path]) -> None:
    """Write `contents` to `path` (mkdir -p the parent). Track every file
    we touch so the caller can print a summary."""
    if dry_run:
        written.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    written.append(path)


def build(*, dry_run: bool = False) -> int:
    themes = list(iter_themes())
    if not themes:
        print("error: no themes found in monorepo", file=sys.stderr)
        return 1

    # Wipe and recreate docs/ so deleting a theme actually removes its short
    # URL on the next deploy. The CNAME file (if any) is preserved across
    # rebuilds so a custom domain doesn't drop on every regeneration.
    cname = DOCS_DIR / "CNAME"
    cname_contents: str | None = None
    if cname.exists():
        cname_contents = cname.read_text()

    if not dry_run and DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)

    written: list[Path] = []
    write_file(DOCS_DIR / ".nojekyll", "", dry_run=dry_run, written=written)
    if cname_contents is not None:
        write_file(DOCS_DIR / "CNAME", cname_contents, dry_run=dry_run, written=written)

    cards: list[str] = []
    for theme_dir in themes:
        theme_slug = theme_dir.name
        theme_name = theme_display_name(theme_dir)
        # Surface a clear error if a theme somehow shipped without a
        # blueprint, but keep going so the rest of docs/ still builds.
        if not (theme_dir / "playground" / "blueprint.json").is_file():
            print(
                f"warn: {theme_slug} has no playground/blueprint.json — "
                "skipping (run bin/sync-playground.py first).",
                file=sys.stderr,
            )
            continue

        for page in PAGES:
            page_slug = page["slug"]
            short_url = gh_pages_short_url(theme_slug, page_slug)
            deeplink = playground_deeplink(theme_slug, page["url"])
            html = render_redirector(
                theme_name=theme_name,
                page_label=page["label"],
                short_url=short_url,
                deeplink=deeplink,
            )
            sub = (DOCS_DIR / theme_slug / page_slug) if page_slug else (DOCS_DIR / theme_slug)
            write_file(sub / "index.html", html, dry_run=dry_run, written=written)

        cards.append(render_theme_card(theme_dir, theme_name, theme_slug))
        # Sanity check: confirm the blueprint URL we're encoding actually
        # matches what bin/sync-playground.py points at. Mismatches mean
        # the docs/ links would 404 in Playground.
        _ = theme_blueprint_raw_url(theme_slug)

    write_file(DOCS_DIR / "index.html", render_index(cards), dry_run=dry_run, written=written)

    verb = "would write" if dry_run else "wrote"
    print(f"{verb} {len(written)} files under {DOCS_DIR.relative_to(MONOREPO_ROOT)}/")
    print(f"  themes: {', '.join(t.name for t in themes)}")
    print(f"  pages per theme: {len(PAGES)}")
    print()
    print(f"Public URL once GH Pages is enabled: {GH_PAGES_BASE_URL}")
    print(f"Per-theme root example: {gh_pages_short_url(themes[0].name)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching the filesystem.",
    )
    args = parser.parse_args()
    return build(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

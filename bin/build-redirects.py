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
      * docs/index.html             — landing page listing every theme + its
                                      short links, suitable as the public
                                      face of the repo.
      * docs/concepts/index.html    — "queue" page listing every concept in
                                      mockups/ that hasn't shipped yet, with
                                      a "Pick this one" CTA that opens a
                                      prefilled GitHub issue. Lets the
                                      Proprietor see at a glance which
                                      concepts are still on the bench and
                                      claim the next one to build.
      * docs/mockups/<slug>.png     — copies of the relevant mockup PNGs so
                                      the concepts page can render them
                                      without leaning on raw.githubusercontent
                                      (cheaper, and survives the repo going
                                      private later).
      * docs/.nojekyll              — tells GH Pages not to run Jekyll, which
                                      would otherwise drop files / folders
                                      starting with `_` and slow builds for
                                      no reason on a static site like this
                                      one.

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
from urllib.parse import quote as url_quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import (
    GH_PAGES_BASE_URL,
    GITHUB_BRANCH,
    GITHUB_ORG,
    GITHUB_REPO,
    MONOREPO_ROOT,
    cache_bust_docs_html,
    gh_pages_short_url,
    iter_themes,
    playground_deeplink,
    theme_blueprint_raw_url,
)
from _readiness import STAGE_SHIPPING, load_readiness

DOCS_DIR = MONOREPO_ROOT / "docs"
MOCKUPS_DIR = MONOREPO_ROOT / "mockups"

# Each entry becomes one redirector under docs/<theme>/<slug>/index.html.
# The blank-slug entry produces the theme root: docs/<theme>/index.html.
#
# Keep `url` aligned with what the demo content actually exposes — every
# entry below is a known-good route in the seeded WordPress install. If you
# add a route here, also add a row to the per-theme README "Deeplinks"
# table so the long URL is discoverable via search too.
PAGES: list[dict[str, str]] = [
    {"slug": "", "url": "/", "label": "Home"},
    {"slug": "shop", "url": "/shop/", "label": "Shop"},
    {
        "slug": "product/bottled-morning",
        "url": "/product/bottled-morning/",
        "label": "Single product",
    },
    {"slug": "cart", "url": "/cart/?demo=cart", "label": "Cart (pre-filled)"},
    {"slug": "checkout", "url": "/checkout/?demo=cart", "label": "Checkout"},
    {"slug": "my-account", "url": "/my-account/", "label": "My Account"},
    {"slug": "journal", "url": "/journal/", "label": "Journal"},
    {"slug": "404", "url": "/this-route-does-not-exist/", "label": "404"},
]


def html_escape(value: str) -> str:
    """Minimal escaping for HTML attributes / text. Keeps the output free
    of any third-party dependency."""
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
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


# Brand-asset link tags injected verbatim into every <head> on the site.
# Each derivative is regenerated from docs/favicon.svg + the OG template
# in bin/build-brand-assets.py — never hand-edit the .png/.ico files.
#
# Why so many <link rel="icon"> entries: every browser-era picks a
# different one to honor.
#   - Modern (Chrome, Firefox, Safari, Edge): pick the SVG (vector, themed
#     light/dark in the future if we add @media (prefers-color-scheme)).
#   - Old IE / Outlook web previews: only ever look at /favicon.ico, which
#     is bundled at the root for them and contains a 16+32 multi-frame.
#   - Legacy non-SVG-aware Chrome (<80) / FF (<41): fall through to the
#     PNG variants by sized hint.
#   - iOS / iPadOS home-screen install: read apple-touch-icon (180x180).
# The OG meta tags use absolute https://demo.regionallyfamous.com/ URLs
# (not paths) because Facebook + LinkedIn require absolute URLs in
# og:image — relative URLs are silently rewritten or dropped.
BRAND_HEAD_TAGS = """\t<link rel="icon" href="/favicon.svg" type="image/svg+xml">
\t<link rel="alternate icon" href="/favicon.ico" sizes="16x16 32x32" type="image/x-icon">
\t<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
\t<link rel="icon" href="/favicon-16.png" sizes="16x16" type="image/png">
\t<link rel="apple-touch-icon" href="/apple-touch-icon.png" sizes="180x180">
\t<meta property="og:image" content="https://demo.regionallyfamous.com/assets/og-default.png">
\t<meta property="og:image:width" content="1200">
\t<meta property="og:image:height" content="630">
\t<meta property="og:image:alt" content="fifty. \u2014 AI-built WooCommerce themes on strict rails, set in heavy industrial sans with a cobalt period and a lime brush-script tag.">
\t<meta name="twitter:card" content="summary_large_image">
\t<meta name="twitter:image" content="https://demo.regionallyfamous.com/assets/og-default.png">"""


# Magazine-cover styled redirector. Inline `<style>` is gone — every page
# loads /assets/style.css (served from the GH Pages root), so the visual
# system is shared with the landing page, the concept queue, and the snap
# gallery. The cobalt pulsing dot replaces the wheel spinner.
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
{brand_head_tags}
\t<link rel="preconnect" href="https://fonts.googleapis.com">
\t<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
\t<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Caveat+Brush&family=Inter:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
\t<link rel="stylesheet" href="/assets/style.css">
</head>
<body class="redirector">
\t<header class="masthead">
\t\t<span class="left"><a href="/">Fifty</a></span>
\t\t<span class="center">{label_html} · {theme_name_html}</span>
\t\t<span class="right">WordPress Playground</span>
\t</header>
\t<main>
\t\t<section class="boot">
\t\t\t<p class="eyebrow"><span class="spinner" aria-hidden="true"></span>Booting WordPress Playground</p>
\t\t\t<h1>{theme_name_lower_html}<span style="color:var(--accent)">.</span></h1>
\t\t\t<p class="lede">Loading the {label_html} entry of the <em>{theme_name_html}</em> demo storefront. First boot takes 20&ndash;60 seconds while WordPress, WooCommerce, and the demo content download.</p>
\t\t\t<hr>
\t\t\t<p class="fallback"><a href="{deeplink_html}">Continue manually if you are not redirected →</a></p>
\t\t</section>
\t</main>
\t<footer class="colophon">
\t\t<span class="left">github.com/RegionallyFamous/fifty</span>
\t\t<span class="center">GPL-2.0+ · Built in public</span>
\t\t<span class="right"><a href="/">← All themes</a></span>
\t</footer>
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
        theme_name_lower_html=html_escape(theme_name.lower()),
        label_html=html_escape(page_label),
        short_url_html=html_escape(short_url),
        deeplink_html=html_escape(deeplink),
        deeplink_json=json.dumps(deeplink),
        brand_head_tags=BRAND_HEAD_TAGS,
    )


# Manifesto-voice landing page. The shape (masthead → cover → theme-rows →
# colophon) is the same; only the visual system has changed. We swapped
# the magazine-cover register (DM Serif Display + DM Serif Text italic +
# IBM Plex Mono caps) for a punk-zine register (Archivo Black industrial
# grotesk + Inter body + Caveat Brush brush-script accents + a cream/
# black/cobalt/lime/hot-pink palette). The copy is unchanged — only the
# wrapper markup grew a `.brand` column for the brush-script signature
# and a couple of `<span class="hi">…</span>` highlighter wraps on the
# key phrases.
#
# Cover shape: the wordmark and deck still sit side-by-side as a single
# lockup (`.lockup` 2-column grid with shared baseline). The wordmark is
# now wrapped in a `.brand` flex column with a brush-script signature
# (`p.signature`) tucked beneath it — the signature is `aria-hidden="true"`
# so screen readers don't read the decoration as part of the heading.
# The deck stays a single sentence with no hardcoded <br> tags —
# `text-wrap: balance` in the stylesheet handles wrap at every viewport.
# Below 880px the lockup collapses to single-column with a smaller
# wordmark and signature.
#
# Highlighter (`<span class="hi">…</span>`): a thin reusable wrapper
# defined in style.css that paints a lime stripe behind whatever text
# it wraps. Used twice in the cover: once on the brush-script "rails"
# tag in the signature, and once on "closing that gap" in the deck.
# The second is the punk-zine equivalent of italicising for emphasis;
# we no longer have italic in the type system, so the highlighter is
# the way you call out a phrase.
#
# Hard rules baked into the copy below:
#   * No theme / concept counts. The repo grows constantly and any number
#     in this template would be stale within days; the deck makes a
#     standing claim instead of a leaderboard report.
#   * "Rich and I", never "Regionally Famous" — see the README opening
#     for the canonical voice.
#   * Acknowledge that WooCommerce knows we're doing this; never claim
#     it was solicited.
INDEX_HEAD = """<!doctype html>
<html lang="en">
<head>
\t<meta charset="utf-8">
\t<title>Fifty — AI-built WooCommerce themes, on strict rails</title>
\t<meta name="viewport" content="width=device-width,initial-scale=1">
\t<meta name="description" content="WooCommerce powers more stores than Shopify and ships nothing like Shopify's themes. Rich and I are closing that gap with AI agents on very strict rails — every storefront below boots in your browser, every rail is in the repo.">
\t<meta property="og:type" content="website">
\t<meta property="og:title" content="Fifty — AI-built WooCommerce themes, on strict rails">
\t<meta property="og:description" content="WooCommerce powers more stores than Shopify and ships nothing like Shopify's themes. Rich and I are closing that gap with AI agents on very strict rails — every storefront below boots in your browser, every rail is in the repo.">
\t<meta property="og:url" content="{base_url}">
{brand_head_tags}
\t<link rel="preconnect" href="https://fonts.googleapis.com">
\t<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
\t<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Caveat+Brush&family=Inter:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
\t<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
\t<header class="masthead">
\t\t<span class="left">An experiment for WooCommerce</span>
\t\t<span class="center">AI agents, on strict rails</span>
\t\t<span class="right"><a href="https://github.com/{org}/{repo}">{repo_short}</a></span>
\t</header>
\t<main>
\t\t<section class="cover">
\t\t\t<div class="lockup">
\t\t\t\t<div class="brand">
\t\t\t\t\t<h1 class="wordmark">fifty<span style="color:var(--accent)">.</span></h1>
\t\t\t\t\t<p class="signature" aria-hidden="true">on&nbsp;<span class="hi">rails</span>.</p>
\t\t\t\t</div>
\t\t\t\t<p class="deck">WooCommerce powers more stores than Shopify and ships nothing like Shopify&rsquo;s themes. Rich&nbsp;and&nbsp;I are <span class="hi">closing that gap</span>, in public.</p>
\t\t\t</div>
\t\t\t<div class="lede">
\t\t\t\t<p>Every storefront below boots a real WordPress + WooCommerce site in your browser &mdash; no install, no signup, no card. Click anything: shop, single product, the pre-filled cart, checkout, the customer dashboard. Break it, refresh.</p>
\t\t\t\t<p>The themes are the demo. The repo is the point. Every rule that keeps the agent honest, every check that catches WordPress&rsquo;s footguns, every visual test that pins the pixels &mdash; it&rsquo;s all in <a href="https://github.com/{org}/{repo}">github.com/{org}/{repo}</a>. Fork any theme, restyle it in an evening, ship to a real store on Monday.</p>
\t\t\t</div>
\t\t\t<div class="cta-row">
\t\t\t\t<a class="cta" href="concepts/">See the concepts on the bench <span class="arrow">→</span></a>
\t\t\t\t<a class="cta" href="https://github.com/{org}/{repo}/blob/{branch}/AGENTS.md">Read the rails <span class="arrow">→</span></a>
\t\t\t\t<a class="cta" href="snaps/">Open the snap gallery <span class="arrow">→</span></a>
\t\t\t</div>
\t\t</section>
\t\t<section class="theme-rows" aria-label="Live themes">
"""

INDEX_FOOT = """\t\t</section>
\t</main>
\t<footer class="colophon">
\t\t<span class="left"><a href="https://github.com/{org}/{repo}">github.com/{org}/{repo}</a></span>
\t\t<span class="center">GPL-2.0+ · Forks welcome · WooCommerce knows</span>
\t\t<span class="right">Built in public by Rich &amp; Nick</span>
\t</footer>
</body>
</html>
"""


def render_index(themes_html: list[str]) -> str:
    """Render the manifesto-voice landing page.

    No more `unbuilt_count` / `shipped_count` parameters: the deck makes a
    standing claim ("Rich and I are closing that gap") instead of reporting
    inventory, so the count plumbing is gone. Theme rows still come from
    the caller — those are the only per-build variant content."""
    head = INDEX_HEAD.format(
        base_url=html_escape(GH_PAGES_BASE_URL),
        org=html_escape(GITHUB_ORG),
        repo=html_escape(GITHUB_REPO),
        repo_short=html_escape(f"github.com/{GITHUB_ORG}/{GITHUB_REPO}"),
        branch=html_escape(GITHUB_BRANCH),
        brand_head_tags=BRAND_HEAD_TAGS,
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


def render_theme_card(
    theme_dir: Path, theme_name: str, theme_slug: str, *, index: int, total: int
) -> str:
    """Render one full-width "magazine row" for the landing page.

    Each row is a single anchor that surfaces:
      - its position in the masthead (THEME 0X / 0Y) in mono caps,
      - the theme name set giant in DM Serif Display lowercase,
      - a one-sentence italic blurb (pulled from style.css's Description),
      - a lone cobalt arrow + "Open Playground" mono caps label on the right.

    Per-page chips were intentionally removed from the homepage: they used
    theme-relative paths (`shop/`, `product/…/`) that resolve against the
    *site root* on demo.regionallyfamous.com (not against the row's URL),
    so they 404'd. The per-page redirectors under docs/<theme>/<slug>/ are
    still generated and remain useful for sharing a deep link to a specific
    entry point — they're just not surfaced on the landing page anymore.
    """
    description = theme_description(theme_dir, theme_name)
    index_label = f"Theme {index:02d} / {total:02d}"
    name_lower = theme_name.lower()
    return (
        f'\t\t\t<a class="theme-row" href="{html_escape(theme_slug + "/")}">\n'
        f'\t\t\t\t<span class="index">{html_escape(index_label)}</span>\n'
        f'\t\t\t\t<h2 class="name">{html_escape(name_lower)}</h2>\n'
        f'\t\t\t\t<p class="blurb">{html_escape(description)}</p>\n'
        f'\t\t\t\t<span class="open"><span class="arrow" aria-hidden="true">→</span><span class="label">Open Playground</span></span>\n'
        f"\t\t\t</a>\n"
    )


# --- Concepts queue page --------------------------------------------------
#
# `mockups/mockup-<slug>.png` is the canonical place we drop a hand-drawn
# (or AI-rendered) mock for a candidate theme before deciding whether to
# build it. A concept is "shipped" once a sibling theme directory with the
# same slug exists at the monorepo root (e.g. mockup-aero.png + aero/).
# The concepts page surfaces every mockup that *doesn't* yet have a paired
# theme directory, so the Proprietor can browse the queue and pick the
# next one to build.
#
# We deliberately re-host the mockup PNGs under docs/mockups/<slug>.png
# rather than hot-linking raw.githubusercontent. This keeps the page
# rendering even if (a) the repo goes private, (b) raw.* gets rate-limited
# by an over-eager crawler, or (c) we add a CDN later. The Pages site
# owns its own assets.

# Both concept layouts are accepted (see mockups/README.md):
#
#   * Single-image:    mockups/mockup-<slug>.png
#   * Multi-image:     mockups/<slug>/home.png  (+ optional pdp / cart / mobile)
#
# Slug grammar matches the controlled vocabulary in concept_seed.py — lower
# kebab, ASCII alnum, no leading dash. The two layouts are mutually
# exclusive per slug; if both exist, the multi-image form wins (and a
# warning is emitted) so a half-finished migration doesn't silently fall
# back to the old PNG.
CONCEPT_MOCKUP_RE = re.compile(r"^mockup-([a-z0-9][a-z0-9-]*)\.png$")
CONCEPT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Recognised additional images inside a multi-image concept directory.
# Order matters: it's the order the carousel walks them. ``home`` is
# required (it's the hero / thumbnail / OG image); the rest are optional
# and silently dropped if missing. Adding a new view here is safe — the
# detail-page renderer only emits a slide when the file exists on disk.
CONCEPT_VIEW_ORDER: list[str] = ["home", "pdp", "cart", "mobile"]


def _load_meta(slug: str) -> dict:
    """Read ``mockups/<slug>.meta.json`` if present.

    Missing files are tolerated (the concept still renders, just with
    minimum metadata derived from the slug) so a contributor adding a
    new mockup PNG can preview the queue page before committing to a
    full ``concept_seed.py`` entry. The build-concept-meta.py script
    is the right place to make this airtight when needed.
    """
    meta_path = MOCKUPS_DIR / f"{slug}.meta.json"
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"warn: ignoring malformed {meta_path.name}: {e}", file=sys.stderr)
        return {}


def _resolve_concept_views(slug: str) -> list[tuple[str, Path]]:
    """Return the list of (view_name, src_path) pairs for a concept.

    For single-image concepts that's exactly one ``("home", …)`` entry.
    For multi-image concepts every PNG in ``CONCEPT_VIEW_ORDER`` that
    actually exists in ``mockups/<slug>/`` is included, in order. Any
    PNG in the directory not in the order list is appended at the end
    (sorted alphabetically) so a contributor experimenting with a new
    view name (e.g. ``account.png``) sees it appear immediately
    without having to teach the script about it.
    """
    multi_dir = MOCKUPS_DIR / slug
    if multi_dir.is_dir():
        all_pngs = {p.stem: p for p in multi_dir.glob("*.png")}
        ordered: list[tuple[str, Path]] = []
        for view in CONCEPT_VIEW_ORDER:
            if view in all_pngs:
                ordered.append((view, all_pngs[view]))
        for stem in sorted(set(all_pngs) - set(CONCEPT_VIEW_ORDER)):
            ordered.append((stem, all_pngs[stem]))
        return ordered
    single = MOCKUPS_DIR / f"mockup-{slug}.png"
    if single.is_file():
        return [("home", single)]
    return []


def discover_concepts(built_theme_slugs: set[str]) -> tuple[list[dict], list[dict]]:
    """Return (unbuilt, built) concept lists, each sorted by slug.

    Each concept is a dict::

        {
            "slug": str,
            "name": str,
            "blurb": str,
            "tags": dict | None,           # full tags object from meta.json
            "palette_hex": list[str],      # auto-extracted hex strings
            "type_specimen": str | None,
            "views": list[(str, Path)],    # (view_name, source_png) pairs
            "hero": Path,                  # convenience: views[0][1]
        }

    Concepts with no source image (no ``mockup-<slug>.png`` and no
    ``<slug>/home.png``) are silently skipped — they'd render as a
    broken thumbnail.
    """
    if not MOCKUPS_DIR.is_dir():
        return [], []
    seen: set[str] = set()
    candidates: list[str] = []

    # Single-image form.
    for path in sorted(MOCKUPS_DIR.glob("mockup-*.png")):
        m = CONCEPT_MOCKUP_RE.match(path.name)
        if not m:
            continue
        slug = m.group(1)
        if slug not in seen:
            candidates.append(slug)
            seen.add(slug)

    # Multi-image form. We accept any subdirectory whose name matches
    # CONCEPT_SLUG_RE and contains at least a `home.png`. This implicitly
    # ignores ad-hoc helper folders (e.g. mockups/_inbox/, mockups/.git/)
    # without an allowlist.
    for sub in sorted(p for p in MOCKUPS_DIR.iterdir() if p.is_dir()):
        slug = sub.name
        if not CONCEPT_SLUG_RE.match(slug):
            continue
        if not (sub / "home.png").is_file():
            continue
        if slug in seen and (MOCKUPS_DIR / f"mockup-{slug}.png").is_file():
            print(
                f"warn: {slug} has both mockup-{slug}.png AND {slug}/home.png — "
                f"using the directory form. Delete the single PNG to silence.",
                file=sys.stderr,
            )
        if slug not in seen:
            candidates.append(slug)
            seen.add(slug)

    unbuilt: list[dict] = []
    built: list[dict] = []
    for slug in sorted(candidates):
        views = _resolve_concept_views(slug)
        if not views:
            continue
        meta = _load_meta(slug)
        record = {
            "slug": slug,
            "name": meta.get("name") or (slug[:1].upper() + slug[1:]),
            "blurb": meta.get("blurb", ""),
            "tags": meta.get("tags") or None,
            "palette_hex": list(meta.get("palette_hex") or []),
            "type_specimen": meta.get("type_specimen"),
            "views": views,
            "hero": views[0][1],
        }
        (built if slug in built_theme_slugs else unbuilt).append(record)
    return unbuilt, built


def _docs_image_path(slug: str, view: str) -> str:
    """URL path (relative to /concepts/) for a copied mockup image.

    Single-image concepts keep the legacy ``../mockups/<slug>.png`` path
    so any deep links / external references that still point there
    continue to resolve. Multi-image concepts publish under
    ``../mockups/<slug>/<view>.png``.
    """
    if view == "home" and not (MOCKUPS_DIR / slug).is_dir():
        return f"../mockups/{slug}.png"
    return f"../mockups/{slug}/{view}.png"


def _docs_image_dest(slug: str, view: str) -> Path:
    """Where to copy the mockup PNG into ``docs/`` so it ships with Pages."""
    if view == "home" and not (MOCKUPS_DIR / slug).is_dir():
        return DOCS_DIR / "mockups" / f"{slug}.png"
    return DOCS_DIR / "mockups" / slug / f"{view}.png"


CONCEPTS_HEAD = """<!doctype html>
<html lang="en">
<head>
\t<meta charset="utf-8">
\t<title>Concept queue — Fifty</title>
\t<meta name="viewport" content="width=device-width,initial-scale=1">
\t<meta name="description" content="WordPress block-theme concepts on the bench, waiting to be built. Click any to claim it.">
\t<meta property="og:type" content="website">
\t<meta property="og:title" content="Concept queue — Fifty">
\t<meta property="og:description" content="WordPress block-theme concepts on the bench, waiting to be built. Click any to claim it.">
\t<meta property="og:url" content="{base_url}concepts/">
{brand_head_tags}
\t<link rel="preconnect" href="https://fonts.googleapis.com">
\t<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
\t<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Caveat+Brush&family=Inter:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
\t<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
\t<header class="masthead">
\t\t<span class="left"><a href="/">← Fifty</a></span>
\t\t<span class="center">AI agents, on strict rails</span>
\t\t<span class="right">On the bench</span>
\t</header>
\t<main>
\t\t<section class="subhero">
\t\t\t<p class="eyebrow">On the bench</p>
\t\t\t<h1>concept queue<span style="color:var(--accent)">.</span></h1>
\t\t\t<p class="deck">Mockups waiting for the agent to pick them up. Each becomes a fully-built WooCommerce storefront &mdash; same template chassis as the live themes, completely different visual language. Click the one you want shipped next; an issue opens for the build agent.</p>
\t\t</section>
"""

# Footer is split into a `.format(org=…, repo=…)`-able prefix (HTML
# only, no curly braces other than the substitutions) and a literal
# script suffix appended verbatim. Python's `str.format` would otherwise
# choke on every `{` in the JS body — the `function () {` and
# `if (…) { … }` blocks each look like an unfinished format spec to
# Python and raise `ValueError: expected ':' after conversion specifier`.
# Splitting keeps the script readable (no `{{`/`}}` doubling) and keeps
# the formatting locus tight (only the org/repo strings need it).
CONCEPTS_FOOT = """\t\t<dialog class="lightbox" aria-label="Concept mockup preview">
\t\t\t<button class="close" type="button" aria-label="Close preview">&times;</button>
\t\t\t<img alt="">
\t\t</dialog>
\t</main>
\t<footer class="colophon">
\t\t<span class="left"><a href="https://github.com/{org}/{repo}">github.com/{org}/{repo}</a></span>
\t\t<span class="center">Drop a new mockup at <code>mockups/mockup-&lt;slug&gt;.png</code> &amp; re-run <code>bin/build-redirects.py</code></span>
\t\t<span class="right"><a href="/">← All themes</a></span>
\t</footer>
"""

CONCEPTS_FILTER_SCRIPT = """\t<script>
\t/* Concept-queue filter strip.
\t *
\t * Each .concept card carries data-{axis} attributes (sector, era,
\t * type, palette). Filter buttons toggle a per-axis selection set;
\t * a card is shown when, for every axis with at least one button
\t * pressed, the card's value (or one of its space-separated palette
\t * tokens) is in that axis's selection set. No deps, no framework.
\t */
\t(function () {
\t\tvar buttons = document.querySelectorAll('.filter-btn[data-filter-axis]');
\t\tif (buttons.length === 0) return;
\t\tvar clearBtn = document.querySelector('[data-filter-clear]');
\t\tvar countNode = document.querySelector('.concept-filters__count');
\t\tvar cards = document.querySelectorAll('.concept');
\t\tvar selection = {};
\t\tfunction matches(card) {
\t\t\tfor (var axis in selection) {
\t\t\t\tvar set = selection[axis];
\t\t\t\tif (!set || set.size === 0) continue;
\t\t\t\tvar val = card.getAttribute('data-' + axis) || '';
\t\t\t\tvar tokens = val.split(/\\s+/);
\t\t\t\tvar hit = false;
\t\t\t\tfor (var i = 0; i < tokens.length; i++) {
\t\t\t\t\tif (set.has(tokens[i])) { hit = true; break; }
\t\t\t\t}
\t\t\t\tif (!hit) return false;
\t\t\t}
\t\t\treturn true;
\t\t}
\t\tfunction apply() {
\t\t\tvar shown = 0;
\t\t\tcards.forEach(function (card) {
\t\t\t\tif (matches(card)) { card.removeAttribute('hidden'); shown++; }
\t\t\t\telse { card.setAttribute('hidden', 'hidden'); }
\t\t\t});
\t\t\tif (countNode) {
\t\t\t\tif (shown === cards.length) {
\t\t\t\t\tcountNode.textContent = 'Showing all ' + cards.length + ' concepts';
\t\t\t\t} else {
\t\t\t\t\tcountNode.textContent = 'Showing ' + shown + ' of ' + cards.length + ' concepts';
\t\t\t\t}
\t\t\t}
\t\t}
\t\tbuttons.forEach(function (btn) {
\t\t\tbtn.addEventListener('click', function () {
\t\t\t\tvar axis = btn.getAttribute('data-filter-axis');
\t\t\t\tvar value = btn.getAttribute('data-filter-value');
\t\t\t\tvar pressed = btn.getAttribute('aria-pressed') === 'true';
\t\t\t\tif (!selection[axis]) selection[axis] = new Set();
\t\t\t\tif (pressed) { selection[axis].delete(value); btn.setAttribute('aria-pressed', 'false'); }
\t\t\t\telse { selection[axis].add(value); btn.setAttribute('aria-pressed', 'true'); }
\t\t\t\tapply();
\t\t\t});
\t\t});
\t\tif (clearBtn) {
\t\t\tclearBtn.addEventListener('click', function () {
\t\t\t\tselection = {};
\t\t\t\tbuttons.forEach(function (b) { b.setAttribute('aria-pressed', 'false'); });
\t\t\t\tapply();
\t\t\t});
\t\t}
\t})();
\t</script>
"""

CONCEPTS_LIGHTBOX_SCRIPT = """\t<script>
\t/* Concept-thumbnail lightbox.
\t *
\t * Each .concept .thumb is rendered as `<a href="…/mockup.png">` so it
\t * works without JS — clicking simply navigates to the raw mockup
\t * PNG. With JS, we hijack the click and present the same image in a
\t * native <dialog> instead, which gives focus trap, Esc-to-close, and
\t * a backdrop dim for free. If the browser doesn't support
\t * `dialog.showModal` (very old) we leave the link alone and the
\t * user gets the navigation fallback.
\t */
\t(function () {
\t\tvar dialog = document.querySelector('.lightbox');
\t\tif (!dialog || typeof dialog.showModal !== 'function') return;
\t\tvar img = dialog.querySelector('img');
\t\tvar closeBtn = dialog.querySelector('.close');
\t\tvar opener = null;
\t\tdocument.querySelectorAll('.concept .thumb').forEach(function (link) {
\t\t\tlink.addEventListener('click', function (e) {
\t\t\t\te.preventDefault();
\t\t\t\timg.src = link.getAttribute('href');
\t\t\t\timg.alt = link.getAttribute('aria-label') || 'Concept mockup preview';
\t\t\t\topener = link;
\t\t\t\tdialog.showModal();
\t\t\t});
\t\t});
\t\tcloseBtn.addEventListener('click', function () { dialog.close(); });
\t\t/* Backdrop click → close. <dialog> receives the click on its own
\t\t * box (since the ::backdrop pseudo isn't a separate event target),
\t\t * so we check whether the click landed inside the <img> rect; if
\t\t * not, the user clicked the dimmed area around it. */
\t\tdialog.addEventListener('click', function (e) {
\t\t\tif (e.target === closeBtn || e.target === img) return;
\t\t\tvar r = img.getBoundingClientRect();
\t\t\tif (
\t\t\t\te.clientX < r.left || e.clientX > r.right ||
\t\t\t\te.clientY < r.top  || e.clientY > r.bottom
\t\t\t) {
\t\t\t\tdialog.close();
\t\t\t}
\t\t});
\t\t/* Restore focus to the thumbnail that opened the lightbox. <dialog>
\t\t * already moves focus into the modal on open, but doesn't restore
\t\t * it on close — that's our job for keyboard users. */
\t\tdialog.addEventListener('close', function () {
\t\t\tif (opener && typeof opener.focus === 'function') opener.focus();
\t\t\timg.removeAttribute('src');
\t\t\topener = null;
\t\t});
\t})();
\t</script>
</body>
</html>
"""


def _new_issue_url(slug: str, name: str) -> str:
    """Prefilled GitHub `new issue` URL for "build this concept" requests."""
    title = f"Build the {name} theme"
    body = (
        f"Build the **{name}** theme from `mockups/mockup-{slug}.png`.\n\n"
        f"- Mockup: "
        f"https://github.com/{GITHUB_ORG}/{GITHUB_REPO}/blob/{GITHUB_BRANCH}"
        f"/mockups/mockup-{slug}.png\n"
        f"- Suggested slug: `{slug}`\n"
        f"- Use `bin/clone.py {slug}` to scaffold from the Obel base, then "
        f"hand the mockup + new theme dir to the agent."
    )
    return (
        f"https://github.com/{GITHUB_ORG}/{GITHUB_REPO}/issues/new"
        f"?title={url_quote(title)}&body={url_quote(body)}&labels=concept"
    )


def _palette_dots_html(palette_hex: list[str], max_dots: int = 5) -> str:
    """Render up to ``max_dots`` color circles for a queue card / detail page.

    Each dot inlines its background color so the static page works
    without runtime CSS variables. The container is rendered even
    when ``palette_hex`` is empty (yields an empty span) so the queue-
    card markup stays grid-aligned regardless of metadata coverage.
    """
    if not palette_hex:
        return '<span class="palette-dots" aria-hidden="true"></span>'
    dots = "".join(
        f'<span class="dot" style="background:{html_escape(c)}" '
        f'aria-label="palette {i + 1} of {len(palette_hex)}"></span>'
        for i, c in enumerate(palette_hex[:max_dots])
    )
    return f'<span class="palette-dots" aria-hidden="false">{dots}</span>'


def _tag_chips_html(tags: dict | None, fields: tuple[str, ...] = ("sector", "era", "type")) -> str:
    """Render scalar tag fields (sector, era, type, hero) as small caps chips.

    ``tags.palette`` is intentionally NOT rendered here — palette is
    visualised by ``_palette_dots_html`` so a chip would be redundant.
    ``hero`` is left out of the queue card too (saves horizontal space
    on the dense grid); the detail page passes a wider ``fields``
    tuple to surface it.
    """
    if not tags:
        return ""
    chips: list[str] = []
    for field in fields:
        value = tags.get(field)
        if not value:
            continue
        chips.append(
            f'<span class="chip chip-{html_escape(field)}" '
            f'data-{html_escape(field)}="{html_escape(str(value))}">'
            f"{html_escape(str(value))}</span>"
        )
    return "".join(chips)


def _filter_data_attrs(concept: dict) -> str:
    """data-* attributes the client-side filter strip reads.

    Output looks like ``data-palette="cream oxblood brown brass"
    data-sector="footwear" data-era="pre-1950" data-type="oldstyle-serif"``.
    Spaces separate multi-value tokens because CSS `[attr~="value"]`
    selectors split on whitespace, which the JS filter falls back to
    when the browser lacks `:has()`.
    """
    tags = concept.get("tags") or {}
    palette = " ".join(tags.get("palette") or [])
    parts = [f'data-slug="{html_escape(concept["slug"])}"']
    for field in ("sector", "era", "type", "hero"):
        v = tags.get(field)
        if v:
            parts.append(f'data-{field}="{html_escape(str(v))}"')
    if palette:
        parts.append(f'data-palette="{html_escape(palette)}"')
    return " ".join(parts)


def render_concept_card(concept: dict, *, shipped: bool) -> str:
    """Concept-queue cell. The body link now goes to the per-concept
    detail page (``concepts/<slug>/``) rather than directly to the
    "pick this one" GitHub issue — the issue CTA + the live-demo CTA
    move down to the detail page where there's room for the carousel
    + palette strip + type spec that justify the click.

    Card layout in render order:

      1. ``.thumb``   — lightbox-trigger link wrapping the hero image.
      2. ``.body``    — link to ``../<slug>/`` (detail page) with:
         - ``<h3>`` lower-cased name
         - ``.palette-dots`` (auto-extracted hex circles)
         - ``.meta``    sector / era / type tag chips + the queue/shipped badge
         - ``.pick``    "Open concept →" CTA arrow

    Two independent click targets per card so the image can be previewed
    without committing to the click-through. Splitting the wrapper means
    the two siblings can carry distinct actions without nesting links
    (which the HTML spec forbids and which screen readers handle
    inconsistently). The lime hover highlight that used to fire on the
    whole `<a class="concept">` is re-applied via
    `.concept:has(.body:hover)` in style.css so the unit still feels
    cohesive when you mouse over the body — the thumb gets its own
    zoom-in cursor + accent outline to telegraph the "preview-only"
    action.
    """
    slug = concept["slug"]
    name = concept["name"]
    mockup_src = _docs_image_path(slug, "home")
    detail_href = f"./{slug}/"
    if shipped:
        badge = '<span class="badge shipped">Shipped</span>'
        cls = "concept shipped"
        cta = 'Open concept <span class="arrow">→</span>'
    else:
        badge = '<span class="badge">In queue</span>'
        cls = "concept"
        cta = 'Open concept <span class="arrow">→</span>'
    thumb_label = f"Preview {name} mockup at full size"
    palette_hex = concept.get("palette_hex") or []
    chips = _tag_chips_html(concept.get("tags"))
    return (
        f'\t\t\t<div class="{cls}" {_filter_data_attrs(concept)}>\n'
        f'\t\t\t\t<a class="thumb" href="{html_escape(mockup_src)}" '
        f'aria-label="{html_escape(thumb_label)}" '
        f'style="background-image:url({html_escape(mockup_src)})"></a>\n'
        f'\t\t\t\t<a class="body" href="{html_escape(detail_href)}">\n'
        f"\t\t\t\t\t<h3>{html_escape(name.lower())}</h3>\n"
        f"\t\t\t\t\t{_palette_dots_html(palette_hex)}\n"
        f'\t\t\t\t\t<p class="meta">{badge}{chips}</p>\n'
        f'\t\t\t\t\t<p class="pick">{cta}</p>\n'
        f"\t\t\t\t</a>\n"
        f"\t\t\t</div>\n"
    )


CONCEPT_DETAIL_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
\t<meta charset="utf-8">
\t<title>{name} — Concept queue — Fifty</title>
\t<meta name="viewport" content="width=device-width,initial-scale=1">
\t<meta name="description" content="{description}">
\t<meta property="og:type" content="article">
\t<meta property="og:title" content="{name} — Concept queue">
\t<meta property="og:description" content="{description}">
\t<meta property="og:url" content="{base_url}concepts/{slug}/">
{brand_head_tags}
\t<link rel="preconnect" href="https://fonts.googleapis.com">
\t<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
\t<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Caveat+Brush&family=Inter:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
\t<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
\t<header class="masthead">
\t\t<span class="left"><a href="../">← Concept queue</a></span>
\t\t<span class="center">Concept on the bench</span>
\t\t<span class="right">{badge_text}</span>
\t</header>
\t<main>
\t\t<article class="concept-detail">
\t\t\t<header class="concept-detail__header">
\t\t\t\t<p class="eyebrow">{eyebrow}</p>
\t\t\t\t<h1>{name_lower}<span style="color:var(--accent)">.</span></h1>
\t\t\t\t<p class="deck">{blurb}</p>
\t\t\t\t<dl class="concept-detail__tags">
{tag_dl}
\t\t\t\t</dl>
\t\t\t</header>
\t\t\t<section class="concept-detail__gallery" aria-label="Mockup gallery">
{gallery}
\t\t\t</section>
{palette_block}
{type_block}
\t\t\t<aside class="concept-detail__cta">
{cta_block}
\t\t\t</aside>
\t\t</article>
\t</main>
\t<footer class="colophon">
\t\t<span class="left"><a href="https://github.com/{org}/{repo}">github.com/{org}/{repo}</a></span>
\t\t<span class="center">Concept &mdash; <code>mockups/{mockup_path}</code></span>
\t\t<span class="right"><a href="../">← Concept queue</a></span>
\t</footer>
</body>
</html>
"""


def _render_palette_block(palette_hex: list[str], tag_palette: list[str]) -> str:
    """Detail-page palette strip: large swatches with hex labels.

    Two layers of truth, intentionally:

      * ``palette_hex``  — auto-extracted from the mockup, true to what's
                           on the canvas right now.
      * ``tag_palette``  — the curated color-family tags from
                           concept_seed.py, the language we use for the
                           audit.

    Showing both lets the build agent (and a human reviewer) see when
    the extracted palette has drifted from the curated one — usually
    a sign that the mockup needs a refresh.
    """
    if not palette_hex and not tag_palette:
        return ""
    hex_swatches = "".join(
        f'\t\t\t\t\t<li class="swatch">'
        f'<span class="swatch__chip" style="background:{html_escape(c)}"></span>'
        f"<code>{html_escape(c)}</code>"
        f"</li>\n"
        for c in palette_hex
    )
    tag_chips = "".join(
        f'<span class="chip chip-palette">{html_escape(t)}</span>' for t in tag_palette
    )
    return (
        '\t\t\t<section class="concept-detail__palette" aria-label="Color palette">\n'
        "\t\t\t\t<h2>Palette</h2>\n"
        + (f'\t\t\t\t<ul class="swatch-row">\n{hex_swatches}\t\t\t\t</ul>\n' if palette_hex else "")
        + (f'\t\t\t\t<p class="palette-tags">{tag_chips}</p>\n' if tag_chips else "")
        + "\t\t\t</section>\n"
    )


def _render_type_block(type_specimen: str | None, tag_type: str | None) -> str:
    if not type_specimen and not tag_type:
        return ""
    parts = [
        '\t\t\t<section class="concept-detail__type" aria-label="Typography">\n',
        "\t\t\t\t<h2>Typography</h2>\n",
    ]
    if tag_type:
        parts.append(
            f'\t\t\t\t<p class="type-genre"><span class="chip chip-type">'
            f"{html_escape(tag_type)}</span></p>\n"
        )
    if type_specimen:
        parts.append(f'\t\t\t\t<p class="type-specimen">{html_escape(type_specimen)}</p>\n')
    parts.append("\t\t\t</section>\n")
    return "".join(parts)


def _render_gallery(slug: str, views: list[tuple[str, Path]]) -> str:
    """Render the carousel of every available view (home, pdp, cart, …).

    Single-image concepts collapse to a single full-width figure with
    no view label so the page doesn't shout "home" at you. Multi-image
    concepts get a labelled <figcaption> per slide and the figures
    flow as a horizontally-scrollable strip on narrow viewports
    (style.css does the rest).
    """
    if len(views) == 1:
        view, _ = views[0]
        src = _docs_image_path(slug, view)
        return (
            f'\t\t\t\t<figure class="gallery-slide gallery-slide--solo">\n'
            f'\t\t\t\t\t<a href="{html_escape(src)}" class="gallery-slide__zoom" '
            f'aria-label="Open the full-size mockup in a new tab" target="_blank" rel="noopener">\n'
            f'\t\t\t\t\t\t<img src="{html_escape(src)}" alt="{html_escape(slug)} mockup" loading="eager">\n'
            f"\t\t\t\t\t</a>\n"
            f"\t\t\t\t</figure>\n"
        )
    parts: list[str] = []
    for view, _ in views:
        src = _docs_image_path(slug, view)
        parts.append(
            f'\t\t\t\t<figure class="gallery-slide">\n'
            f'\t\t\t\t\t<a href="{html_escape(src)}" class="gallery-slide__zoom" '
            f'aria-label="Open the {html_escape(view)} mockup in a new tab" target="_blank" rel="noopener">\n'
            f'\t\t\t\t\t\t<img src="{html_escape(src)}" alt="{html_escape(slug)} {html_escape(view)} view" loading="lazy">\n'
            f"\t\t\t\t\t</a>\n"
            f"\t\t\t\t\t<figcaption>{html_escape(view)}</figcaption>\n"
            f"\t\t\t\t</figure>\n"
        )
    return "".join(parts)


def render_concept_detail_page(concept: dict, *, shipped: bool) -> str:
    """Per-concept detail page. Linked from the queue card body.

    Layout mirrors the queue's design system (eyebrow + lowercase
    display heading + deck), then surfaces every artefact the build
    agent might want before claiming the concept: the full mockup
    gallery, the auto-extracted palette next to the curated palette
    tags, the type specimen, and the actionable CTAs (open issue, or
    visit live demo for shipped themes).
    """
    slug = concept["slug"]
    name = concept["name"]
    blurb = concept.get("blurb") or ""
    tags = concept.get("tags") or {}
    palette_hex = concept.get("palette_hex") or []
    type_specimen = concept.get("type_specimen")
    views = concept.get("views") or []

    # Tag definition list. Empty cells are skipped so the dl never has
    # an "—" placeholder cluttering the layout.
    tag_dl_parts: list[str] = []
    for label, key in (("sector", "sector"), ("era", "era"), ("type", "type"), ("hero", "hero")):
        v = tags.get(key)
        if not v:
            continue
        tag_dl_parts.append(
            f"\t\t\t\t\t<div><dt>{html_escape(label)}</dt>"
            f'<dd><span class="chip chip-{html_escape(key)}">{html_escape(str(v))}</span></dd></div>\n'
        )
    tag_dl = "".join(tag_dl_parts) or "\t\t\t\t\t<div><dt>—</dt><dd>no tags yet</dd></div>\n"

    if shipped:
        eyebrow = "Shipped — live demo"
        badge_text = "Shipped"
        cta_block = (
            f'\t\t\t\t<a class="cta cta-primary" href="../../{html_escape(slug)}/">'
            f'See it live <span class="arrow">→</span></a>\n'
            f'\t\t\t\t<a class="cta cta-secondary" '
            f'href="https://github.com/{html_escape(GITHUB_ORG)}/{html_escape(GITHUB_REPO)}'
            f'/tree/{html_escape(GITHUB_BRANCH)}/{html_escape(slug)}/">'
            f"Source on GitHub →</a>\n"
        )
    else:
        eyebrow = "On the bench — claim it"
        badge_text = "In queue"
        issue_url = _new_issue_url(slug, name)
        cta_block = (
            f'\t\t\t\t<a class="cta cta-primary" href="{html_escape(issue_url)}" '
            f'target="_blank" rel="noopener">Pick this one <span class="arrow">→</span></a>\n'
            f'\t\t\t\t<p class="cta-note">Opens a prefilled GitHub issue tagged '
            f"<code>concept</code>. The build agent picks it up from there.</p>\n"
        )

    multi_dir = MOCKUPS_DIR / slug
    mockup_path = f"{slug}/home.png" if multi_dir.is_dir() else f"mockup-{slug}.png"

    description = (blurb or f"Concept queue entry for {name}.").replace('"', "&quot;")

    return CONCEPT_DETAIL_TEMPLATE.format(
        name=html_escape(name),
        name_lower=html_escape(name.lower()),
        slug=html_escape(slug),
        description=html_escape(description),
        blurb=html_escape(blurb) if blurb else "",
        eyebrow=html_escape(eyebrow),
        badge_text=html_escape(badge_text),
        tag_dl=tag_dl,
        gallery=_render_gallery(slug, views),
        palette_block=_render_palette_block(palette_hex, list(tags.get("palette") or [])),
        type_block=_render_type_block(type_specimen, tags.get("type")),
        cta_block=cta_block,
        mockup_path=html_escape(mockup_path),
        base_url=html_escape(GH_PAGES_BASE_URL),
        brand_head_tags=BRAND_HEAD_TAGS,
        org=html_escape(GITHUB_ORG),
        repo=html_escape(GITHUB_REPO),
    )


def _render_filter_strip(concepts: list[dict]) -> str:
    """Build the client-side filter UI strip.

    Each filter group is a labelled `<details>` so the strip collapses
    on narrow viewports without JS. The `<button>` elements inside carry
    `data-filter-axis` + `data-filter-value`; the inline script at the
    bottom of the page reads them, toggles `aria-pressed`, and shows /
    hides cards by matching against the card's `data-{axis}` attribute.

    The set of available filter values is derived from whatever's
    actually present in the queue, so a freshly-added sector / era
    automatically gets a button without having to teach the script
    about it.
    """
    if not concepts:
        return ""
    axes: dict[str, set[str]] = {"sector": set(), "era": set(), "type": set(), "palette": set()}
    for c in concepts:
        tags = c.get("tags") or {}
        for axis in ("sector", "era", "type"):
            v = tags.get(axis)
            if v:
                axes[axis].add(v)
        for tok in tags.get("palette") or []:
            axes["palette"].add(tok)
    if not any(axes.values()):
        return ""
    parts = ['\t\t<aside class="concept-filters" aria-label="Filter the concept queue">\n']
    for axis_label, axis in (
        ("Sector", "sector"),
        ("Era", "era"),
        ("Type genre", "type"),
        ("Palette", "palette"),
    ):
        values = sorted(axes[axis])
        if not values:
            continue
        parts.append(f'\t\t\t<details class="concept-filters__group" data-axis="{axis}">\n')
        parts.append(f"\t\t\t\t<summary>{html_escape(axis_label)}</summary>\n")
        parts.append('\t\t\t\t<div class="concept-filters__buttons">\n')
        for v in values:
            parts.append(
                f'\t\t\t\t\t<button type="button" class="filter-btn" '
                f'data-filter-axis="{axis}" data-filter-value="{html_escape(v)}" '
                f'aria-pressed="false">{html_escape(v)}</button>\n'
            )
        parts.append("\t\t\t\t</div>\n")
        parts.append("\t\t\t</details>\n")
    parts.append(
        '\t\t\t<button type="button" class="filter-btn filter-clear" '
        'data-filter-clear aria-label="Clear all filters">Clear all</button>\n'
    )
    parts.append(
        '\t\t\t<p class="concept-filters__count" aria-live="polite">'
        f"Showing all {len(concepts)} concepts</p>\n"
    )
    parts.append("\t\t</aside>\n")
    return "".join(parts)


def render_concepts_page(unbuilt: list[dict], built: list[dict]) -> str:
    head = CONCEPTS_HEAD.format(
        base_url=html_escape(GH_PAGES_BASE_URL),
        brand_head_tags=BRAND_HEAD_TAGS,
    )
    foot = CONCEPTS_FOOT.format(
        org=html_escape(GITHUB_ORG),
        repo=html_escape(GITHUB_REPO),
    )
    parts: list[str] = [head, _render_filter_strip(unbuilt + built)]
    if unbuilt:
        parts.append(
            '\t\t<header class="section-head">\n'
            "\t\t\t<h2>On the bench</h2>\n"
            f'\t\t\t<span class="count"><strong>{len(unbuilt):02d}</strong> waiting</span>\n'
            "\t\t</header>\n"
            '\t\t<section class="concept-grid" aria-label="Unbuilt concepts">\n'
        )
        for c in unbuilt:
            parts.append(render_concept_card(c, shipped=False))
        parts.append("\t\t</section>\n")
    else:
        parts.append(
            '\t\t<header class="section-head"><h2>On the bench</h2></header>\n'
            '\t\t<p class="empty-note">No unbuilt mockups &mdash; every concept in '
            "<code>mockups/</code> has a sibling theme directory. Drop a new "
            "<code>mockup-&lt;slug&gt;.png</code> into <code>mockups/</code> and "
            "re-run <code>bin/build-redirects.py</code>.</p>\n"
        )
    if built:
        parts.append(
            '\t\t<header class="section-head">\n'
            "\t\t\t<h2>Already shipped</h2>\n"
            f'\t\t\t<span class="count"><strong>{len(built):02d}</strong> live</span>\n'
            "\t\t</header>\n"
            '\t\t<section class="concept-grid" aria-label="Shipped concepts">\n'
        )
        for c in built:
            parts.append(render_concept_card(c, shipped=True))
        parts.append("\t\t</section>\n")
    parts.append(foot)
    parts.append(CONCEPTS_FILTER_SCRIPT)
    parts.append(CONCEPTS_LIGHTBOX_SCRIPT)
    return "".join(parts)


def write_file(path: Path, contents: str, *, dry_run: bool, written: list[Path]) -> None:
    """Write `contents` to `path` (mkdir -p the parent). Track every file
    we touch so the caller can print a summary.

    HTML output gets the docs/assets/style.css cache-bust query appended
    so deploys never serve stale CSS — see _lib.cache_bust_docs_html for
    the full reasoning. Non-HTML files (we currently emit `.nojekyll`
    via this helper) pass through untouched.
    """
    if dry_run:
        written.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".html":
        contents = cache_bust_docs_html(contents)
    path.write_text(contents)
    written.append(path)


def copy_binary(src: Path, dst: Path, *, dry_run: bool, written: list[Path]) -> None:
    """Copy a binary file (mockup PNG) into the docs/ tree. Logged the same
    way `write_file` is so the build summary stays accurate."""
    if dry_run:
        written.append(dst)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    written.append(dst)


def build(*, dry_run: bool = False) -> int:
    # Include every stage (not just `shipping`) so freshly-cloned
    # themes still at `stage: incubating` get short-URL redirectors
    # written on the first design pass. Without this, a new theme
    # would have no `docs/<slug>/index.html` until promotion —
    # breaking the `_phase_redirects` step `bin/design.py` runs for
    # every freshly-cloned theme. The shipping dashboard and gallery
    # remain stage-filtered because those have their own readiness
    # criteria (`bin/build-theme-status.py`, `bin/build-snap-gallery.py`).
    themes = list(iter_themes(stages=()))
    if not themes:
        print("error: no themes found in monorepo", file=sys.stderr)
        return 1

    # Wipe and recreate docs/ so deleting a theme actually removes its
    # short URL on the next deploy. A small allowlist of human-owned or
    # separately-built artifacts is preserved across rebuilds:
    #
    #   CNAME                         GitHub Pages custom domain mapping
    #                                 — would cost a DNS propagation cycle
    #                                 to recover if dropped, so never wipe.
    #   assets/style.css              Magazine-cover design system —
    #                                 hand-edited, the source of truth for
    #                                 every visual rule on the site.
    #   favicon.svg                   Hand-authored vector mark.
    #   favicon-16/32.png             Generated by bin/build-brand-assets.py.
    #   favicon.ico                   Same — multi-size legacy bundle.
    #   apple-touch-icon.png          Same — iOS home-screen icon.
    #   assets/og-default.png         Same — Open Graph share card.
    #
    # Each generated brand asset is treated as a checked-in binary: this
    # script never *creates* them, but it never *destroys* them either,
    # so a contributor running `bin/build-redirects.py` without first
    # running `bin/build-brand-assets.py` still ships a site with a
    # working favicon.
    #
    # Snap gallery (`docs/snaps/`) is preserved as a directory tree, since
    # it's emitted by an independent script (`bin/build-snap-gallery.py`)
    # and shouldn't vanish whenever this script runs.
    PRESERVED_FILES = [
        Path("CNAME"),
        Path("assets/style.css"),
        Path("favicon.svg"),
        Path("favicon-16.png"),
        Path("favicon-32.png"),
        Path("favicon.ico"),
        Path("apple-touch-icon.png"),
        Path("assets/og-default.png"),
        # AUDIT.md is the rendered output of `bin/audit-concepts.py`,
        # which is run independently. Preserve it here so a contributor
        # can run `bin/build-redirects.py` without first re-running the
        # audit (the queue card markup is rebuilt; the audit summary
        # stays whatever the audit script last wrote).
        Path("concepts/AUDIT.md"),
        # Tier-infrastructure prose — these are human-authored markdown
        # files committed under docs/ and linked from AGENTS.md. They
        # are NOT generated by this script; preserving them here means
        # a naive `bin/build-redirects.py` run can never silently wipe
        # the tier docs (which bit us during the Agave self-heal
        # rehearsal: the LLM loop's docs rebuild deleted six .md files
        # + the themes dashboard before the guard was added).
        Path("batch-playbook.md"),
        Path("blindspot-decisions.md"),
        Path("ci-pat-setup.md"),
        Path("day-0-smoke.md"),
        Path("shipping-a-theme.md"),
        Path("tier-3-deferrals.md"),
        # docs/themes/index.html is rebuilt by `bin/build-theme-status.py`
        # on every merge. Preserve it here so a docs rebuild between
        # theme-status refreshes doesn't leave a stale 404.
        Path("themes/index.html"),
    ]
    preserved: dict[Path, bytes] = {}
    for rel in PRESERVED_FILES:
        src = DOCS_DIR / rel
        if src.is_file():
            preserved[rel] = src.read_bytes()

    snaps_dir = DOCS_DIR / "snaps"
    preserved_snaps_tmp: Path | None = None
    if not dry_run and snaps_dir.is_dir():
        preserved_snaps_tmp = MONOREPO_ROOT / ".tmp-snaps-preserve"
        if preserved_snaps_tmp.exists():
            shutil.rmtree(preserved_snaps_tmp)
        shutil.move(str(snaps_dir), str(preserved_snaps_tmp))

    if not dry_run and DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)

    written: list[Path] = []
    write_file(DOCS_DIR / ".nojekyll", "", dry_run=dry_run, written=written)
    for rel, payload in preserved.items():
        dst = DOCS_DIR / rel
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(payload)
        written.append(dst)
    # Surface any still-missing brand assets so a contributor knows to run
    # the brand-assets builder. The site degrades gracefully (just no
    # favicon / OG card) but the warning is loud enough to be actioned.
    expected_brand = {
        Path("assets/style.css"): "landing page + concepts + redirectors will be unstyled",
        Path("favicon.svg"): "modern browsers will fall back to no favicon",
        Path("favicon.ico"): "legacy IE / Outlook previews will fall back to no favicon",
        Path("apple-touch-icon.png"): "iOS home-screen install will use a generic icon",
        Path("assets/og-default.png"): "social shares will not get a preview card",
    }
    for rel, consequence in expected_brand.items():
        if rel not in preserved:
            print(
                f"warn: docs/{rel} missing \u2014 {consequence}. Run "
                f"`python3 bin/build-brand-assets.py` to generate.",
                file=sys.stderr,
            )
    if preserved_snaps_tmp is not None and not dry_run:
        shutil.move(str(preserved_snaps_tmp), str(snaps_dir))

    # Two-pass over themes: count blueprints first so render_theme_card
    # can stamp the correct "Theme 0X / 0Y" index without having to know
    # the total ahead of time. Skips the same way the original loop did
    # if a theme is missing its blueprint.
    valid_themes = [t for t in themes if (t / "playground" / "blueprint.json").is_file()]
    for missing in [t for t in themes if not (t / "playground" / "blueprint.json").is_file()]:
        print(
            f"warn: {missing.name} has no playground/blueprint.json — "
            "skipping (run bin/sync-playground.py first).",
            file=sys.stderr,
        )

    # Split `valid_themes` into "show on landing page" (stage: shipping)
    # and "write redirectors but keep private" (stage: incubating or
    # retired). Both groups get `docs/<slug>/*/index.html` so private
    # share-links still resolve, but only `shipping` themes appear on
    # `demo.regionallyfamous.com/` and count toward the "Theme 0X / 0Y"
    # index. Without this split, a freshly-cloned chandler at
    # stage=incubating would surface as a live card on the public
    # landing page before the design pass is complete. The bin/promote-theme.py
    # gate flips a theme to stage=shipping once it has passed
    # static + visual verification, and only then does it appear here.
    shipping_themes = [
        t for t in valid_themes if load_readiness(t).stage == STAGE_SHIPPING
    ]
    total_shipped = len(shipping_themes)
    shipping_slug_index: dict[str, int] = {
        t.name: i for i, t in enumerate(shipping_themes, start=1)
    }

    cards: list[str] = []
    for theme_dir in valid_themes:
        theme_slug = theme_dir.name
        theme_name = theme_display_name(theme_dir)
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

        if theme_slug in shipping_slug_index:
            cards.append(
                render_theme_card(
                    theme_dir,
                    theme_name,
                    theme_slug,
                    index=shipping_slug_index[theme_slug],
                    total=total_shipped,
                )
            )
        # Sanity check: confirm the blueprint URL we're encoding actually
        # matches what bin/sync-playground.py points at. Mismatches mean
        # the docs/ links would 404 in Playground.
        _ = theme_blueprint_raw_url(theme_slug)

    # Concept queue page. Built theme slugs are derived from the live
    # `themes` list above (via `iter_themes()`, which is the canonical
    # "what shipped" source) so a concept flips from queue -> shipped
    # automatically when its theme directory lands.
    built_slugs = {t.name for t in themes}
    unbuilt, built_concepts = discover_concepts(built_slugs)
    for concept in unbuilt + built_concepts:
        # Copy every view (single-image concepts have just `home`,
        # multi-image concepts add pdp/cart/mobile/etc.) preserving
        # the view name in the destination filename so the gallery's
        # <img src="…"> URLs resolve.
        for view, src in concept["views"]:
            copy_binary(
                src,
                _docs_image_dest(concept["slug"], view),
                dry_run=dry_run,
                written=written,
            )
        # Per-concept detail page. Lives at concepts/<slug>/index.html so
        # the queue card body link's href="./<slug>/" resolves cleanly.
        is_shipped = concept["slug"] in built_slugs
        write_file(
            DOCS_DIR / "concepts" / concept["slug"] / "index.html",
            render_concept_detail_page(concept, shipped=is_shipped),
            dry_run=dry_run,
            written=written,
        )
    write_file(
        DOCS_DIR / "concepts" / "index.html",
        render_concepts_page(unbuilt, built_concepts),
        dry_run=dry_run,
        written=written,
    )

    write_file(
        DOCS_DIR / "index.html",
        render_index(cards),
        dry_run=dry_run,
        written=written,
    )

    verb = "would write" if dry_run else "wrote"
    print(f"{verb} {len(written)} files under {DOCS_DIR.relative_to(MONOREPO_ROOT)}/")
    print(f"  themes: {', '.join(t.name for t in themes)}")
    print(f"  pages per theme: {len(PAGES)}")
    print(f"  concepts: {len(unbuilt)} in queue, {len(built_concepts)} shipped (with mockup)")
    print()
    print(f"Public URL once GH Pages is enabled: {GH_PAGES_BASE_URL}")
    print(f"Per-theme root example: {gh_pages_short_url(themes[0].name)}")
    print(f"Concepts queue: {GH_PAGES_BASE_URL}concepts/")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching the filesystem.",
    )
    args = parser.parse_args()
    return build(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())

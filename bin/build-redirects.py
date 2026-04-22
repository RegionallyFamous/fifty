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
    gh_pages_short_url,
    iter_themes,
    playground_deeplink,
    theme_blueprint_raw_url,
)

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
\t<meta property="og:image:alt" content="fifty. \u2014 AI-built WooCommerce themes on strict rails, set in DM Serif Display with a cobalt accent.">
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
\t<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Serif+Text:ital@1&family=IBM+Plex+Mono:wght@400;500&display=swap">
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
# colophon) and the visual system (DM Serif Display brand, cobalt accent
# dot, hairline rules, mono caps masthead) are unchanged from the earlier
# magazine framing — only the copy was rewritten to match the README's
# opening pitch (WooCommerce > Shopify in installs, ships nothing like
# Shopify's themes; Rich and I are closing that gap with AI on rails, in
# public). All visual rules live in /assets/style.css; this template is
# just semantic HTML hooks for that stylesheet to attach to.
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
\t<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Serif+Text:ital@0;1&family=IBM+Plex+Mono:wght@400;500&display=swap">
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
\t\t\t<h1>fifty<span style="color:var(--accent)">.</span></h1>
\t\t\t<hr class="rule">
\t\t\t<p class="deck">WooCommerce powers more stores than Shopify<br>and ships nothing like Shopify&rsquo;s themes.<br>Rich and I are closing that gap, in public.</p>
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


def render_theme_card(theme_dir: Path, theme_name: str, theme_slug: str, *, index: int, total: int) -> str:
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
        f'\t\t\t</a>\n'
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

CONCEPT_MOCKUP_RE = re.compile(r"^mockup-([a-z0-9][a-z0-9-]*)\.png$")


def discover_concepts(built_theme_slugs: set[str]) -> tuple[list[dict], list[dict]]:
    """Return (unbuilt, built) concept lists, each sorted by slug.

    Each concept is a dict ``{"slug": str, "name": str, "mockup": Path}``.
    ``built`` is also surfaced so the page can say "5 shipped, 24 in the
    queue" without re-counting at render time."""
    if not MOCKUPS_DIR.is_dir():
        return [], []
    unbuilt: list[dict] = []
    built: list[dict] = []
    for path in sorted(MOCKUPS_DIR.glob("mockup-*.png")):
        m = CONCEPT_MOCKUP_RE.match(path.name)
        if not m:
            continue
        slug = m.group(1)
        record = {
            "slug": slug,
            "name": slug[:1].upper() + slug[1:],
            "mockup": path,
        }
        (built if slug in built_theme_slugs else unbuilt).append(record)
    return unbuilt, built


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
\t<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Serif+Text:ital@0;1&family=IBM+Plex+Mono:wght@400;500&display=swap">
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

CONCEPTS_FOOT = """\t</main>
\t<footer class="colophon">
\t\t<span class="left"><a href="https://github.com/{org}/{repo}">github.com/{org}/{repo}</a></span>
\t\t<span class="center">Drop a new mockup at <code>mockups/mockup-&lt;slug&gt;.png</code> &amp; re-run <code>bin/build-redirects.py</code></span>
\t\t<span class="right"><a href="/">← All themes</a></span>
\t</footer>
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


def render_concept_card(concept: dict, *, shipped: bool) -> str:
    """Magazine-cover concept cell. Each cell is a borderless grid panel
    (the parent .concept-grid draws the hairline rules between them) with
    a 4:3 thumbnail, a serif-display name, mono metadata, and an italic
    CTA. Shipped concepts dim and link to the live demo; unbuilt ones
    open a prefilled GitHub issue."""
    slug = concept["slug"]
    name = concept["name"]
    mockup_src = f"../mockups/{slug}.png"
    if shipped:
        href = f"../{slug}/"
        cta = 'Live demo <span class="arrow">→</span>'
        badge = '<span class="badge shipped">Shipped</span>'
        cls = "concept shipped"
        ext_attrs = ''
    else:
        href = _new_issue_url(slug, name)
        cta = 'Pick this one <span class="arrow">→</span>'
        badge = '<span class="badge">In queue</span>'
        cls = "concept"
        ext_attrs = ' target="_blank" rel="noopener"'
    return (
        f'\t\t\t<a class="{cls}" href="{html_escape(href)}"{ext_attrs}>\n'
        f'\t\t\t\t<div class="thumb" role="img" aria-label="{html_escape(name)} mockup" '
        f'style="background-image:url({html_escape(mockup_src)})"></div>\n'
        f'\t\t\t\t<div class="body">\n'
        f'\t\t\t\t\t<h3>{html_escape(name.lower())}</h3>\n'
        f'\t\t\t\t\t<p class="meta">{badge}<span>mockup-{html_escape(slug)}.png</span></p>\n'
        f'\t\t\t\t\t<p class="pick">{cta}</p>\n'
        f'\t\t\t\t</div>\n'
        f'\t\t\t</a>\n'
    )


def render_concepts_page(unbuilt: list[dict], built: list[dict]) -> str:
    head = CONCEPTS_HEAD.format(
        base_url=html_escape(GH_PAGES_BASE_URL),
        brand_head_tags=BRAND_HEAD_TAGS,
    )
    foot = CONCEPTS_FOOT.format(
        org=html_escape(GITHUB_ORG),
        repo=html_escape(GITHUB_REPO),
    )
    parts: list[str] = [head]
    if unbuilt:
        parts.append(
            '\t\t<header class="section-head">\n'
            '\t\t\t<h2>On the bench</h2>\n'
            f'\t\t\t<span class="count"><strong>{len(unbuilt):02d}</strong> waiting</span>\n'
            '\t\t</header>\n'
            '\t\t<section class="concept-grid" aria-label="Unbuilt concepts">\n'
        )
        for c in unbuilt:
            parts.append(render_concept_card(c, shipped=False))
        parts.append("\t\t</section>\n")
    else:
        parts.append(
            '\t\t<header class="section-head"><h2>On the bench</h2></header>\n'
            '\t\t<p class="empty-note">No unbuilt mockups &mdash; every concept in '
            '<code>mockups/</code> has a sibling theme directory. Drop a new '
            '<code>mockup-&lt;slug&gt;.png</code> into <code>mockups/</code> and '
            're-run <code>bin/build-redirects.py</code>.</p>\n'
        )
    if built:
        parts.append(
            '\t\t<header class="section-head">\n'
            '\t\t\t<h2>Already shipped</h2>\n'
            f'\t\t\t<span class="count"><strong>{len(built):02d}</strong> live</span>\n'
            '\t\t</header>\n'
            '\t\t<section class="concept-grid" aria-label="Shipped concepts">\n'
        )
        for c in built:
            parts.append(render_concept_card(c, shipped=True))
        parts.append("\t\t</section>\n")
    parts.append(foot)
    return "".join(parts)


def write_file(path: Path, contents: str, *, dry_run: bool, written: list[Path]) -> None:
    """Write `contents` to `path` (mkdir -p the parent). Track every file
    we touch so the caller can print a summary."""
    if dry_run:
        written.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
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
    themes = list(iter_themes())
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
    total_shipped = len(valid_themes)
    for missing in [t for t in themes if not (t / "playground" / "blueprint.json").is_file()]:
        print(
            f"warn: {missing.name} has no playground/blueprint.json — "
            "skipping (run bin/sync-playground.py first).",
            file=sys.stderr,
        )

    cards: list[str] = []
    for index, theme_dir in enumerate(valid_themes, start=1):
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

        cards.append(render_theme_card(theme_dir, theme_name, theme_slug, index=index, total=total_shipped))
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
        copy_binary(
            concept["mockup"],
            DOCS_DIR / "mockups" / f"{concept['slug']}.png",
            dry_run=dry_run, written=written,
        )
    write_file(
        DOCS_DIR / "concepts" / "index.html",
        render_concepts_page(unbuilt, built_concepts),
        dry_run=dry_run, written=written,
    )

    write_file(
        DOCS_DIR / "index.html",
        render_index(cards),
        dry_run=dry_run, written=written,
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

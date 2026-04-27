"""Shared helpers for the Fifty monorepo bin/ scripts.

The bin/ scripts live at the monorepo root and operate on a single theme at a
time. Each script resolves its target theme via :func:`resolve_theme_root`:

* If the user passes a positional theme name (e.g. ``python3 bin/check.py obel``),
  resolve it as a sibling directory of bin/.
* Otherwise, if the current working directory contains a ``theme.json``, treat
  cwd as the target theme.
* Otherwise, error out.

Scripts should also expose ``--all`` where it makes sense (check, build-index,
list-tokens) to iterate every theme in the monorepo.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

MONOREPO_ROOT = Path(__file__).resolve().parent.parent

# GitHub identity for this monorepo. Used by bin/sync-playground.py to derive
# per-theme `WO_CONTENT_BASE_URL` constants and the `importWxr` URL inside
# every blueprint, and by bin/build-redirects.py to derive both the raw
# blueprint URL (for the Playground deeplink) and the GH Pages short URL.
# Change here in one place if the org / repo / default branch ever moves.
GITHUB_ORG = "RegionallyFamous"
GITHUB_REPO = "fifty"
GITHUB_BRANCH = "main"

# Public host for the redirector site. The CNAME in docs/CNAME points GitHub
# Pages at this hostname; the underlying fallback (which still works if the
# DNS / CNAME ever breaks) is https://<org-lowercased>.github.io/<repo>/.
# Trailing slash is significant — callers concatenate `<theme>/<page>/`.
GH_PAGES_BASE_URL = "https://demo.regionallyfamous.com/"

# raw.githubusercontent.com base for any file in this repo on the default
# branch. Trailing slash is significant — callers concatenate a sub-path.
RAW_GITHUB_BASE_URL = (
    f"https://raw.githubusercontent.com/"
    f"{GITHUB_ORG}/{GITHUB_REPO}/{GITHUB_BRANCH}/"
)


def theme_content_base_url(theme_slug: str) -> str:
    """Per-theme `playground/` base URL on raw.githubusercontent.com.

    This is what gets baked into each blueprint as `WO_CONTENT_BASE_URL`
    so the inlined PHP can reach `<theme>/playground/content/products.csv`,
    `<theme>/playground/content/category-images.json`, and the per-theme
    images folder."""
    return f"{RAW_GITHUB_BASE_URL}{theme_slug}/playground/"


def theme_blueprint_raw_url(theme_slug: str) -> str:
    """Public raw URL of `<theme>/playground/blueprint.json`. This is what
    Playground fetches when a user clicks a `?blueprint-url=…` link."""
    return f"{RAW_GITHUB_BASE_URL}{theme_slug}/playground/blueprint.json"


def playground_deeplink(theme_slug: str, url_path: str = "/") -> str:
    """Full https://playground.wordpress.net/?blueprint-url=…&url=… deeplink
    for a theme + an in-site path (e.g. "/", "/shop/", "/cart/?demo=cart").

    These URLs are long and ugly on purpose: every byte after `?blueprint-url=`
    is a fully-qualified raw GitHub URL. Use bin/build-redirects.py to expose
    short `demo.regionallyfamous.com/<theme>/<page>/` aliases."""
    bp = theme_blueprint_raw_url(theme_slug)
    return f"https://playground.wordpress.net/?blueprint-url={bp}&url={url_path}"


def gh_pages_short_url(theme_slug: str, page_slug: str = "") -> str:
    """Short URL served by GH Pages from the docs/ folder, fronted by the
    `demo.regionallyfamous.com` custom domain (see docs/CNAME). `page_slug`
    is a path component without leading/trailing slash ("" = theme root,
    "shop", "product/bottled-morning", etc.)."""
    suffix = f"{page_slug}/" if page_slug else ""
    return f"{GH_PAGES_BASE_URL}{theme_slug}/{suffix}"


def resolve_theme_root(name: str | None = None) -> Path:
    """Return the absolute path of the target theme directory.

    Raises :class:`SystemExit` with a helpful message if no theme can be
    determined.
    """
    if name:
        candidate = (MONOREPO_ROOT / name).resolve()
        if candidate.is_dir() and (candidate / "theme.json").is_file():
            return candidate
        # Allow passing an absolute or cwd-relative path too
        candidate = Path(name).resolve()
        if candidate.is_dir() and (candidate / "theme.json").is_file():
            return candidate
        raise SystemExit(
            f"Theme '{name}' not found. Looked in {MONOREPO_ROOT}/{name} and {Path(name).resolve()}."
        )

    cwd = Path.cwd()
    if (cwd / "theme.json").is_file():
        return cwd

    available = ", ".join(sorted(t.name for t in iter_themes())) or "(none found)"
    raise SystemExit(
        "No theme target. Either run from inside a theme directory (one with theme.json), "
        f"or pass a theme name. Available themes: {available}"
    )


def iter_themes(
    monorepo_root: Path = MONOREPO_ROOT,
    stages: Iterable[str] | None = None,
) -> Iterable[Path]:
    """Yield every theme directory in the monorepo (any sibling of bin/ that
    contains theme.json).

    If ``stages`` is None (default), apply the readiness filter's
    ``DEFAULT_VISIBLE_STAGES`` (shipping only) so incubating/retired
    themes drop out of sweeps, gallery, and check.py runs without the
    caller having to know the manifest exists. Pass an explicit tuple
    like ``stages=("shipping", "incubating")`` to opt WIP themes back
    in (what a design/clone script wants while iterating on a new
    concept). Pass ``stages=()`` to yield EVERY theme regardless of
    stage (used by the theme-status dashboard generator).

    A theme with no readiness.json on disk is treated as
    ``stage="shipping"`` (see ``_readiness.load_readiness``), which
    keeps the existing six themes visible until their manifests land.
    """
    from _readiness import DEFAULT_VISIBLE_STAGES, load_readiness

    if stages is None:
        wanted: frozenset[str] | None = DEFAULT_VISIBLE_STAGES
    else:
        s = frozenset(stages)
        wanted = s if s else None

    for entry in sorted(monorepo_root.iterdir()):
        if not (
            entry.is_dir()
            and not entry.name.startswith(".")
            and (entry / "theme.json").is_file()
        ):
            continue
        if wanted is None:
            yield entry
            continue
        if load_readiness(entry).stage in wanted:
            yield entry


def docs_assets_cache_stamp() -> str:
    """Return a short, content-addressed cache-busting stamp for the
    site-wide `docs/assets/style.css`.

    Why this exists:
        GitHub Pages serves assets with a long Cache-Control TTL we can't
        override (Pages doesn't expose response headers). When we change
        `docs/assets/style.css` without changing its URL, every visitor
        whose browser cached the old bytes keeps seeing the old design
        for hours/days — they end up opening incognito windows or
        toggling DevTools "Disable cache" just to see fresh CSS after a
        deploy. This is a real foot-gun for a site whose whole point is
        to showcase visual work.

        The fix is to append a query string (`?v=<stamp>`) to the link
        href in the generated HTML. Browsers treat the URL with a
        different query as a brand-new resource and refetch it, even if
        a prior version is still in cache. As long as the stamp changes
        whenever the stylesheet bytes change, deploys naturally
        invalidate the CSS without manual cache-clearing.

        The HTML pages that reference the stylesheet are themselves
        served with a ~10-min TTL on Pages (Fastly), so they refresh
        quickly and pick up the new query value within minutes of a
        deploy.

    Why content-hash and not git SHA:
        We could stamp with the current commit SHA, but that
        over-invalidates: a routine deploy that doesn't touch
        `style.css` (e.g. fixing a typo in a redirector or a blueprint)
        would still force every visitor to refetch the (unchanged)
        stylesheet. Hashing the file contents means the stamp only
        rolls over when the CSS actually moved, so the cache stays warm
        across commits that don't affect visual output.

    Returns:
        A lowercase hex prefix of the SHA-1 of the stylesheet bytes
        (10 chars — wide enough to be collision-free for any plausible
        history of edits, short enough to keep generated HTML readable).
        Returns "0" if the stylesheet doesn't exist on disk yet — in
        that case we'd have nothing to bust anyway, and the caller's
        warning path (`build-redirects.py` already prints "docs/
        assets/style.css missing — landing page will be unstyled") will
        surface the real problem.
    """
    css = MONOREPO_ROOT / "docs" / "assets" / "style.css"
    try:
        return hashlib.sha1(css.read_bytes()).hexdigest()[:10]
    except OSError:
        return "0"


def cache_bust_docs_html(html: str, stamp: str | None = None) -> str:
    """Append `?v=<stamp>` to every `assets/style.css` href in `html`.

    Hits all three URL forms we use across the docs/ pages:
        * `/assets/style.css`     — absolute, used by every page when
                                    served from demo.regionallyfamous.com
        * `../assets/style.css`   — used by per-theme snap pages so they
                                    work when opened from the local
                                    filesystem (snap PNG QA loop)
        * `assets/style.css`      — used by `docs/snaps/index.html` for
                                    the same local-filesystem reason

    Only the site stylesheet is busted — fonts.googleapis.com is a
    separate origin with its own caching that we don't (and shouldn't)
    try to manage from here.

    The replace is anchored on the trailing `"` so we don't double-bust
    a URL that already has a query, and so we don't accidentally rewrite
    occurrences of `assets/style.css` that appear in (e.g.) docstring
    text inside the HTML — there are none today, but the trailing-quote
    anchor is the cheapest insurance.
    """
    if stamp is None:
        stamp = docs_assets_cache_stamp()
    return html.replace(
        'assets/style.css"',
        f'assets/style.css?v={stamp}"',
    )


def add_theme_arg(parser) -> None:
    """Add the standard ``theme`` positional argument and ``--all`` flag.

    Most scripts accept either:
        python3 bin/<script>.py [theme_name]
        python3 bin/<script>.py --all
    """
    parser.add_argument(
        "theme",
        nargs="?",
        default=None,
        help="Theme directory name (e.g. 'obel'). Defaults to cwd if it contains theme.json.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run against every theme in the monorepo.",
    )

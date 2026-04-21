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


def iter_themes(monorepo_root: Path = MONOREPO_ROOT) -> Iterable[Path]:
    """Yield every theme directory in the monorepo (any sibling of bin/ that
    contains theme.json)."""
    for entry in sorted(monorepo_root.iterdir()):
        if entry.is_dir() and not entry.name.startswith(".") and (entry / "theme.json").is_file():
            yield entry


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

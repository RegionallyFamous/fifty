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
import json
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

MONOREPO_ROOT = Path(__file__).resolve().parent.parent

# Files that can change rendered output for every theme. Keep this narrow:
# unrelated tooling under bin/ must not turn a one-theme PR into a fleet gate.
RENDER_AFFECTING_FRAMEWORK_FILES: frozenset[str] = frozenset(
    {
        "bin/snap.py",
        "bin/snap_config.py",
        "bin/append-wc-overrides.py",
        "bin/sync-playground.py",
        "bin/_lib.py",
        "package.json",
        "package-lock.json",
    }
)

RENDER_AFFECTING_FRAMEWORK_PREFIXES: tuple[str, ...] = (
    "playground/",
)

REPO_INFRA_PREFIXES: tuple[str, ...] = (
    ".github/",
    ".githooks/",
    ".cursor/",
    ".claude/",
    "bin/",
    "tests/",
)

DOCS_ONLY_PREFIXES: tuple[str, ...] = (
    "docs/",
    "mockups/",
)


@dataclass(frozen=True)
class ChangedScope:
    """Classified git-diff scope shared by hooks, CI and snap/check tooling."""

    paths: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    all_themes_required: bool = False
    has_theme_changes: bool = False
    has_repo_infra_changes: bool = False
    docs_only: bool = False
    reason: str = "no relevant changes"
    framework_paths: tuple[str, ...] = ()
    repo_infra_paths: tuple[str, ...] = ()
    docs_paths: tuple[str, ...] = ()
    other_paths: tuple[str, ...] = ()
    theme_paths: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "paths": list(self.paths),
            "themes": list(self.themes),
            "all_themes_required": self.all_themes_required,
            "has_theme_changes": self.has_theme_changes,
            "has_repo_infra_changes": self.has_repo_infra_changes,
            "docs_only": self.docs_only,
            "reason": self.reason,
            "framework_paths": list(self.framework_paths),
            "repo_infra_paths": list(self.repo_infra_paths),
            "docs_paths": list(self.docs_paths),
            "other_paths": list(self.other_paths),
            "theme_paths": {k: list(v) for k, v in self.theme_paths.items()},
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True)

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


def is_render_affecting_framework_path(path: str) -> bool:
    """Return whether a path should force a full visual/theme fleet run."""
    norm = path.strip().replace("\\", "/")
    if norm in RENDER_AFFECTING_FRAMEWORK_FILES:
        return True
    return any(norm.startswith(prefix) for prefix in RENDER_AFFECTING_FRAMEWORK_PREFIXES)


def is_docs_only_path(path: str) -> bool:
    norm = path.strip().replace("\\", "/")
    return any(norm.startswith(prefix) for prefix in DOCS_ONLY_PREFIXES)


def is_repo_infra_path(path: str) -> bool:
    norm = path.strip().replace("\\", "/")
    return any(norm.startswith(prefix) for prefix in REPO_INFRA_PREFIXES)


def git_changed_paths(
    *,
    base: str | None = None,
    staged: bool = False,
    include_untracked: bool = True,
    monorepo_root: Path = MONOREPO_ROOT,
) -> tuple[str, ...] | None:
    """Return changed paths as POSIX strings, or None when git is unavailable.

    `base` uses three-dot diff (`base...HEAD`) so PR/worktree checks compare
    against the merge base. Without a base we inspect the local worktree; with
    `staged=True` we inspect only the index for pre-commit.
    """
    paths: set[str] = set()

    def _run(args: list[str]) -> subprocess.CompletedProcess[str] | None:
        try:
            proc = subprocess.run(
                args,
                cwd=monorepo_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, FileNotFoundError):
            return None
        return proc

    commands: list[list[str]] = []
    if staged:
        commands.append(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    else:
        commands.append(["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"])
        if include_untracked:
            commands.append(["git", "ls-files", "--others", "--exclude-standard"])
    if base:
        commands.append(["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"])

    for cmd in commands:
        proc = _run(cmd)
        if proc is None:
            return None
        if proc.returncode != 0:
            continue
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line:
                paths.add(line.replace("\\", "/"))

    return tuple(sorted(paths))


def classify_changed_paths(
    paths: Iterable[str],
    *,
    monorepo_root: Path = MONOREPO_ROOT,
    theme_stages: Iterable[str] | None = ("shipping", "incubating"),
    known_themes: Iterable[str] | None = None,
) -> ChangedScope:
    """Classify changed paths into theme work, repo infra, docs, or fleet-wide.

    Theme changes stay scoped to the touched slugs. Only the narrow rendering
    framework allowlist widens to all themes.
    """
    cleaned = tuple(sorted({p.strip().replace("\\", "/") for p in paths if p.strip()}))
    if not cleaned:
        return ChangedScope()

    if known_themes is None:
        known = {theme.name for theme in iter_themes(monorepo_root, stages=theme_stages)}
    else:
        known = set(known_themes)
    affected: set[str] = set()
    theme_paths: dict[str, list[str]] = {}
    framework_paths: list[str] = []
    repo_infra_paths: list[str] = []
    docs_paths: list[str] = []
    other_paths: list[str] = []

    for path in cleaned:
        parts = path.split("/")
        head = parts[0]
        if head in known:
            affected.add(head)
            theme_paths.setdefault(head, []).append(path)
            continue
        if (
            head == "tests"
            and len(parts) >= 3
            and parts[1] == "visual-baseline"
            and parts[2] in known
        ):
            affected.add(parts[2])
            theme_paths.setdefault(parts[2], []).append(path)
            continue
        if is_render_affecting_framework_path(path):
            framework_paths.append(path)
            continue
        if is_docs_only_path(path):
            docs_paths.append(path)
            continue
        if is_repo_infra_path(path):
            repo_infra_paths.append(path)
            continue
        other_paths.append(path)

    if framework_paths:
        return ChangedScope(
            paths=cleaned,
            themes=tuple(sorted(known)),
            all_themes_required=True,
            has_theme_changes=bool(affected),
            has_repo_infra_changes=True,
            docs_only=False,
            reason="render-affecting framework changed",
            framework_paths=tuple(sorted(framework_paths)),
            repo_infra_paths=tuple(sorted(repo_infra_paths)),
            docs_paths=tuple(sorted(docs_paths)),
            other_paths=tuple(sorted(other_paths)),
            theme_paths={k: tuple(sorted(v)) for k, v in sorted(theme_paths.items())},
        )

    docs_only = bool(docs_paths) and not affected and not repo_infra_paths and not other_paths
    if affected:
        reason = "theme changes"
    elif repo_infra_paths:
        reason = "repo infrastructure changes"
    elif docs_only:
        reason = "docs/mockups only"
    else:
        reason = "no theme changes"

    return ChangedScope(
        paths=cleaned,
        themes=tuple(sorted(affected)),
        all_themes_required=False,
        has_theme_changes=bool(affected),
        has_repo_infra_changes=bool(repo_infra_paths),
        docs_only=docs_only,
        reason=reason,
        framework_paths=(),
        repo_infra_paths=tuple(sorted(repo_infra_paths)),
        docs_paths=tuple(sorted(docs_paths)),
        other_paths=tuple(sorted(other_paths)),
        theme_paths={k: tuple(sorted(v)) for k, v in sorted(theme_paths.items())},
    )


def resolve_changed_scope(
    *,
    base: str | None = None,
    staged: bool = False,
    include_untracked: bool = True,
    monorepo_root: Path = MONOREPO_ROOT,
    theme_stages: Iterable[str] | None = ("shipping", "incubating"),
) -> ChangedScope:
    paths = git_changed_paths(
        base=base,
        staged=staged,
        include_untracked=include_untracked,
        monorepo_root=monorepo_root,
    )
    if paths is None:
        themes = tuple(sorted(theme.name for theme in iter_themes(monorepo_root, stages=theme_stages)))
        return ChangedScope(
            themes=themes,
            all_themes_required=True,
            reason="git unavailable; falling back to all themes",
        )
    return classify_changed_paths(paths, monorepo_root=monorepo_root, theme_stages=theme_stages)


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

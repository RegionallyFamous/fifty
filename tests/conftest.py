"""Shared pytest fixtures for the Fifty tooling test suite.

The repo's "code" lives in two places:

* `bin/*.py` — standalone scripts that operate on a single theme tree
  (resolved via `bin/_lib.py:resolve_theme_root`). They use a module-level
  `ROOT` global that points at the theme they're operating on, and they
  use `_lib.MONOREPO_ROOT` for cross-theme operations.

* The theme directories themselves (`obel/`, `chonk/`, …) — each is a
  small WordPress block theme with a `theme.json`, `templates/`, `parts/`,
  `patterns/`, and a `playground/` directory.

Tests work by:

1. Putting `bin/` on `sys.path` so `import check`, `import build_index`
   etc. work as top-level modules (no `bin/__init__.py` required).
2. Building a minimal-but-valid theme tree on disk inside `tmp_path`
   (`minimal_theme` fixture), then either calling a single `check_*`
   function against it (after monkeypatching `check.ROOT`) or shelling
   out to a script.
3. For cross-theme checks (`check_distinctive_chrome`,
   `check_pattern_microcopy_distinct`,
   `check_all_rendered_text_distinct_across_themes`), the `monorepo`
   fixture builds a synthetic two-theme monorepo and monkeypatches
   `_lib.MONOREPO_ROOT` so `iter_themes()` yields the fakes.

The fixtures intentionally write the smallest theme that passes
`bin/check.py` so each test starts from a known-passing baseline and
modifies one file to flip a single check from pass → fail.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Make `bin/` importable as top-level modules.
#
# bin/check.py does `from _lib import …` after a sys.path tweak, so as long
# as `bin/` is on sys.path we can `import check` and the `_lib` import
# inside it resolves too. We do this once at conftest import time so every
# test module benefits.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))


# ---------------------------------------------------------------------------
# Minimal theme.json — palette + spacing + typography stubs that are the
# bare minimum every check_* expects to find. Real themes are 2k+ lines;
# this is the floor.
# ---------------------------------------------------------------------------
def _minimal_theme_json() -> dict[str, Any]:
    return {
        "$schema": "https://schemas.wp.org/trunk/theme.json",
        "version": 3,
        "settings": {
            "appearanceTools": True,
            "useRootPaddingAwareAlignments": True,
            "layout": {
                "contentSize": "720px",
                "wideSize": "1280px",
            },
            "color": {
                "defaultPalette": False,
                "palette": [
                    {"slug": "base", "name": "Base", "color": "#FAFAF7"},
                    {"slug": "contrast", "name": "Contrast", "color": "#1A1916"},
                    {"slug": "primary", "name": "Primary", "color": "#3A352B"},
                    {"slug": "border", "name": "Border", "color": "#D9D6CC"},
                ],
            },
            "typography": {
                "fontFamilies": [
                    {
                        "slug": "body",
                        "name": "Body",
                        "fontFamily": "Georgia, serif",
                    },
                    {
                        "slug": "display",
                        "name": "Display",
                        "fontFamily": "Georgia, serif",
                    },
                ],
                "fontSizes": [
                    {"slug": "small", "size": "0.875rem"},
                    {"slug": "medium", "size": "1rem"},
                    {"slug": "large", "size": "1.5rem"},
                ],
            },
            "spacing": {
                "spacingSizes": [
                    {"slug": "30", "size": "clamp(1rem, 2vw, 1.5rem)"},
                    {"slug": "40", "size": "clamp(1.5rem, 3vw, 2rem)"},
                    {"slug": "50", "size": "clamp(2rem, 4vw, 3rem)"},
                ],
            },
        },
        "styles": {
            "css": "",
        },
        "templateParts": [
            {"name": "header", "title": "Header", "area": "header"},
            {"name": "footer", "title": "Footer", "area": "footer"},
        ],
    }


# ---------------------------------------------------------------------------
# Minimal block markup snippets — these are valid (round-trip-clean)
# WordPress block save() output. Tests can use them as-is or splice in
# the specific bug they want a check_* to catch.
# ---------------------------------------------------------------------------
MINIMAL_INDEX_HTML = textwrap.dedent(
    """\
    <!-- wp:template-part {"slug":"header","tagName":"header"} /-->
    <!-- wp:group {"tagName":"main","layout":{"type":"constrained"}} -->
    <main class="wp-block-group">
        <!-- wp:post-title /-->
        <!-- wp:post-content /-->
    </main>
    <!-- /wp:group -->
    <!-- wp:template-part {"slug":"footer","tagName":"footer"} /-->
    """
)

MINIMAL_HEADER_HTML = textwrap.dedent(
    """\
    <!-- wp:group {"tagName":"div","layout":{"type":"constrained"}} -->
    <div class="wp-block-group">
        <!-- wp:site-title /-->
    </div>
    <!-- /wp:group -->
    """
)

MINIMAL_FOOTER_HTML = textwrap.dedent(
    """\
    <!-- wp:group {"tagName":"div","layout":{"type":"constrained"}} -->
    <div class="wp-block-group">
        <!-- wp:paragraph -->
        <p>&copy; Site</p>
        <!-- /wp:paragraph -->
    </div>
    <!-- /wp:group -->
    """
)

MINIMAL_FUNCTIONS_PHP = textwrap.dedent(
    """\
    <?php
    /**
     * Minimal functions.php for the test theme.
     */
    add_action( 'after_setup_theme', static function () {
        add_theme_support( 'wp-block-styles' );
        add_theme_support( 'editor-styles' );
    } );
    """
)

MINIMAL_STYLE_CSS = textwrap.dedent(
    """\
    /*
    Theme Name: {title}
    Theme URI: https://example.test/{slug}
    Author: Tests
    Description: Synthetic test theme.
    Version: 0.0.0
    Requires at least: 6.5
    Tested up to: 6.6
    Requires PHP: 8.1
    License: GPLv2 or later
    Text Domain: {slug}
    */
    """
)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
def _build_minimal_theme(
    root: Path,
    *,
    slug: str = "scratch",
    title: str = "Scratch",
    extra_theme_json: dict[str, Any] | None = None,
) -> Path:
    """Write the smallest valid theme tree at ``root`` and return ``root``.

    The theme has:
      - theme.json   (valid JSON, palette + typography + spacing presets)
      - style.css    (with the WP theme header WP requires)
      - functions.php
      - templates/index.html
      - parts/header.html
      - parts/footer.html
      - patterns/    (empty dir; tests add files here as needed)
      - styles/      (empty dir)
      - playground/  (empty dir; some checks expect it to exist)
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "templates").mkdir(exist_ok=True)
    (root / "parts").mkdir(exist_ok=True)
    (root / "patterns").mkdir(exist_ok=True)
    (root / "styles").mkdir(exist_ok=True)
    (root / "playground").mkdir(exist_ok=True)
    (root / "playground" / "content").mkdir(exist_ok=True)
    (root / "playground" / "images").mkdir(exist_ok=True)

    theme = _minimal_theme_json()
    if extra_theme_json:
        _deep_merge(theme, extra_theme_json)
    (root / "theme.json").write_text(json.dumps(theme, indent="\t") + "\n", encoding="utf-8")

    (root / "style.css").write_text(
        MINIMAL_STYLE_CSS.format(slug=slug, title=title),
        encoding="utf-8",
    )
    (root / "functions.php").write_text(MINIMAL_FUNCTIONS_PHP, encoding="utf-8")
    (root / "templates" / "index.html").write_text(MINIMAL_INDEX_HTML, encoding="utf-8")
    (root / "parts" / "header.html").write_text(MINIMAL_HEADER_HTML, encoding="utf-8")
    (root / "parts" / "footer.html").write_text(MINIMAL_FOOTER_HTML, encoding="utf-8")
    return root


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> None:
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def minimal_theme(tmp_path: Path) -> Path:
    """Return a path to a freshly-built minimal theme.

    The theme is the smallest tree that *should* satisfy every static
    `check_*` in `bin/check.py` once the fixture is paired with the
    `bind_check_root` fixture (which points `check.ROOT` at it).
    Tests add specific files (`patterns/foo.php`, `templates/single.html`)
    to exercise the check they care about.
    """
    return _build_minimal_theme(tmp_path / "scratch")


@pytest.fixture
def make_theme(tmp_path: Path) -> Callable[..., Path]:
    """Factory variant for tests that need >1 theme in the same tmp dir.

    Usage::

        def test_thing(make_theme):
            obel = make_theme(slug="obel", title="Obel")
            chonk = make_theme(slug="chonk", title="Chonk")
            ...
    """

    def _factory(
        slug: str = "scratch",
        title: str | None = None,
        extra_theme_json: dict[str, Any] | None = None,
    ) -> Path:
        return _build_minimal_theme(
            tmp_path / slug,
            slug=slug,
            title=title or slug.capitalize(),
            extra_theme_json=extra_theme_json,
        )

    return _factory


@pytest.fixture
def monorepo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Build a synthetic two-theme monorepo and patch `_lib.MONOREPO_ROOT`.

    Returns a dict ``{"root": <repo-root>, "obel": <theme>, "chonk": <theme>,
    "bin": <bin-dir>}``. The ``bin`` directory is symlinked from the real
    repo's `bin/` so scripts that shell out to e.g. `python3 bin/check.py`
    still find their siblings. The real `_lib.MONOREPO_ROOT` is also
    patched so `iter_themes()` yields just the two synthetic themes.
    """
    repo_root = tmp_path / "fake-monorepo"
    repo_root.mkdir()
    obel = _build_minimal_theme(repo_root / "obel", slug="obel", title="Obel")
    chonk = _build_minimal_theme(repo_root / "chonk", slug="chonk", title="Chonk")

    # Symlink bin/ so subprocess invocations of bin/check.py still work
    # if the test wants to exec the script. Pure-import tests don't need
    # this but it's cheap to wire.
    (repo_root / "bin").symlink_to(BIN_DIR)

    # Patch _lib.MONOREPO_ROOT (the source of truth) so iter_themes()
    # yields the two fakes. bin/check.py also imports the constant by
    # name (`from _lib import MONOREPO_ROOT`) so we patch BOTH names.
    import _lib  # noqa: WPS433  (local import: bin/ on sys.path)

    monkeypatch.setattr(_lib, "MONOREPO_ROOT", repo_root)

    # `iter_themes(monorepo_root: Path = MONOREPO_ROOT)` captures the
    # constant as its default *at function definition time*, so the
    # MONOREPO_ROOT patch above does not change the no-arg call site
    # used by `bin/check.py main()`. Wrap the function so a no-arg
    # call falls through to the patched root.
    real_iter_themes = _lib.iter_themes

    def _patched_iter_themes(monorepo_root: Path = repo_root):
        yield from real_iter_themes(monorepo_root)

    monkeypatch.setattr(_lib, "iter_themes", _patched_iter_themes)
    try:
        import check  # noqa: WPS433
    except Exception:  # pragma: no cover — check.py import failure is its own bug
        pass
    else:
        if hasattr(check, "MONOREPO_ROOT"):
            monkeypatch.setattr(check, "MONOREPO_ROOT", repo_root)
        if hasattr(check, "iter_themes"):
            monkeypatch.setattr(check, "iter_themes", _patched_iter_themes)

    return {"root": repo_root, "obel": obel, "chonk": chonk, "bin": repo_root / "bin"}


@pytest.fixture
def bind_check_root(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], Any]:
    """Bind `bin/check.py`'s module-level `ROOT` global to a path.

    ``check_*`` functions read from `check.ROOT`. Returns the freshly
    imported `check` module so the test can call any function on it::

        def test_foo(minimal_theme, bind_check_root):
            check = bind_check_root(minimal_theme)
            assert check.check_json_validity().passed
    """

    def _bind(theme_root: Path):
        import check  # noqa: WPS433

        monkeypatch.setattr(check, "ROOT", theme_root)
        return check

    return _bind


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def run_bin_script() -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run any script under bin/ as a subprocess.

    Used by tests/tools/ for round-trip tests. Stdin is closed, stdout
    + stderr are captured, env vars are inherited but `PYTHONPATH` is
    pre-pended with `bin/` so the script's `from _lib import …` works
    when launched from an arbitrary cwd.
    """

    def _run(
        script_name: str,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 60,
    ) -> subprocess.CompletedProcess[str]:
        script = BIN_DIR / script_name
        assert script.is_file(), f"missing bin/{script_name}"
        full_env = os.environ.copy()
        full_env["PYTHONPATH"] = f"{BIN_DIR}{os.pathsep}{full_env.get('PYTHONPATH', '')}"
        if env:
            full_env.update(env)
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=str(cwd) if cwd else None,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return _run

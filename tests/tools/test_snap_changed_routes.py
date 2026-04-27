"""Tests for `bin/snap.py`'s per-theme route narrowing.

Phase 1 of the smart-snaps work adds `_changed_routes(theme, base)`,
which refines `_changed_themes` from "reshoot every route whenever
this theme has any diff" to "reshoot only the routes whose dependency
manifest in snap_config.ROUTE_DEPENDENCIES maps to a changed file."

Key contract:
  * Path under a ROUTE_GLOBAL_GLOBS entry  -> None (all routes)
  * Path under a specific route's deps      -> {route_slug, ...}
  * Path inside the theme but unmapped      -> None (degrade safe)
  * Path outside the theme (other theme,
    tests/visual-baseline, etc.)            -> set() (no routes)
  * Framework file                          -> None (all routes)
  * Empty diff                              -> set()

The tests also exercise `_match_glob`, the glob helper that powers the
matcher (pathlib.PurePath.match can't cross segment boundaries on `**`,
fnmatch collapses `**` into `*`; we need both).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = REPO_ROOT / "bin"


@pytest.fixture
def snap_mod():
    """Import bin/snap.py with Playwright stubbed. Same recipe as
    test_snap_content_ref.py / test_snap_changed_scope.py."""
    fake_playwright = type(sys)("playwright")
    fake_playwright.sync_api = type(sys)("playwright.sync_api")
    fake_playwright.sync_api.sync_playwright = lambda: None
    fake_playwright.sync_api.Error = Exception
    fake_playwright.sync_api.TimeoutError = Exception
    sys.modules.setdefault("playwright", fake_playwright)
    sys.modules.setdefault("playwright.sync_api", fake_playwright.sync_api)
    sys.path.insert(0, str(BIN_DIR))
    spec = importlib.util.spec_from_file_location("_snap_for_route_test", BIN_DIR / "snap.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_snap_for_route_test"] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pytest.skip("snap.py exited at import (missing system dep)")
    return module


# ---------------------------------------------------------------------------
# _match_glob: the glob helper
# ---------------------------------------------------------------------------


class TestMatchGlob:
    """These cases enumerate the `**` / `*` / literal semantics the
    dependency manifest relies on. If this regresses every downstream
    match is suspect.
    """

    def test_literal_match(self, snap_mod):
        assert snap_mod._match_glob(
            "templates/single-product.html",
            "templates/single-product.html",
        )

    def test_star_within_segment(self, snap_mod):
        assert snap_mod._match_glob(
            "patterns/product-gallery.html",
            "patterns/product-*.html",
        )

    def test_star_does_not_cross_segment(self, snap_mod):
        # `*` on its own cannot eat a `/`; `patterns/foo/bar.html` should
        # NOT match `patterns/*.html`. Violating this would make the
        # manifest match every sub-pattern-directory edit under the
        # wrong route.
        assert not snap_mod._match_glob(
            "patterns/foo/bar.html",
            "patterns/*.html",
        )

    def test_doublestar_crosses_segments(self, snap_mod):
        assert snap_mod._match_glob(
            "styles/winter.json",
            "styles/**",
        )
        assert snap_mod._match_glob(
            "styles/variations/mono.json",
            "styles/**",
        )

    def test_doublestar_matches_zero_segments(self, snap_mod):
        # `playground/**` should match `playground/blueprint.json`
        # (one segment after) AND anything deeper.
        assert snap_mod._match_glob(
            "playground/blueprint.json",
            "playground/**",
        )
        assert snap_mod._match_glob(
            "playground/content/products.csv",
            "playground/**",
        )

    def test_no_false_match_on_prefix_of_segment(self, snap_mod):
        # `patterns/product-*.html` must not match
        # `patterns/productother.html` -- the `-` is literal.
        assert not snap_mod._match_glob(
            "patterns/productother.html",
            "patterns/product-*.html",
        )


# ---------------------------------------------------------------------------
# _changed_routes: the narrower
# ---------------------------------------------------------------------------


class _FakeRun:
    def __init__(self, lines: list[str]):
        self.lines = lines

    def __call__(self, *args, **kwargs):
        class _R:
            returncode = 0
            stdout = "\n".join(self.lines)

        return _R()


def _install_fake_diff(snap_mod, monkeypatch, lines: list[str]) -> None:
    monkeypatch.setattr(snap_mod.subprocess, "run", _FakeRun(lines))


class TestChangedRoutes:
    def test_single_template_narrows(self, snap_mod, monkeypatch):
        # A one-line edit to single-product.html must narrow to exactly
        # the two product routes. This is the poster-child case for
        # Phase 1: 44 PNGs would drop to 8 in the default matrix.
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["aero/templates/single-product.html"],
        )
        got = snap_mod._changed_routes("aero", "origin/main")
        assert got == {"product-simple", "product-variable"}

    def test_cart_template_narrows(self, snap_mod, monkeypatch):
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["obel/templates/page-cart.html"],
        )
        assert snap_mod._changed_routes("obel", "origin/main") == {
            "cart-filled",
            "cart-empty",
        }

    def test_theme_json_invalidates_all(self, snap_mod, monkeypatch):
        # theme.json is in ROUTE_GLOBAL_GLOBS -> every route stale.
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["aero/theme.json"],
        )
        assert snap_mod._changed_routes("aero", "origin/main") is None

    def test_header_invalidates_all(self, snap_mod, monkeypatch):
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["aero/parts/header.html"],
        )
        assert snap_mod._changed_routes("aero", "origin/main") is None

    def test_styles_subdir_invalidates_all(self, snap_mod, monkeypatch):
        # styles/**: variation files, global css, should invalidate all.
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["aero/styles/variations/mono.json"],
        )
        assert snap_mod._changed_routes("aero", "origin/main") is None

    def test_playground_fixture_invalidates_all(self, snap_mod, monkeypatch):
        # A change to playground/content/products.csv changes what the
        # shop archive + product detail pages paint. Treat as global.
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["aero/playground/content/products.csv"],
        )
        assert snap_mod._changed_routes("aero", "origin/main") is None

    def test_framework_edit_invalidates_all(self, snap_mod, monkeypatch):
        # Framework file -> None for every theme, not just the one being
        # asked about. (The per-theme query doesn't even see the file
        # since it's not under `<theme>/`, but _is_framework_file()
        # catches it before the prefix check.)
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["bin/snap.py"],
        )
        assert snap_mod._changed_routes("aero", "origin/main") is None

    def test_other_theme_is_noop(self, snap_mod, monkeypatch):
        # The query is scoped per-theme; an obel edit doesn't affect
        # aero's route set.
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["obel/templates/home.html"],
        )
        assert snap_mod._changed_routes("aero", "origin/main") == set()

    def test_baseline_edit_is_noop(self, snap_mod, monkeypatch):
        # tests/visual-baseline/<theme>/** is the expected-output tree;
        # it has no route-dep semantics.
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["tests/visual-baseline/aero/desktop/home.png"],
        )
        assert snap_mod._changed_routes("aero", "origin/main") == set()

    def test_empty_diff_is_empty_set(self, snap_mod, monkeypatch):
        _install_fake_diff(snap_mod, monkeypatch, [])
        assert snap_mod._changed_routes("aero", "origin/main") == set()

    def test_unmapped_theme_file_degrades_safe(self, snap_mod, monkeypatch):
        # A theme-scoped path that doesn't match any manifest entry or
        # global glob means we can't prove narrowing is safe -- fall
        # back to None ("shoot every route"). This is what prevents a
        # brand-new template name that hasn't been added to the manifest
        # from silently skipping its own route.
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["aero/some-new-template.html"],
        )
        assert snap_mod._changed_routes("aero", "origin/main") is None

    def test_multi_route_edit_unions(self, snap_mod, monkeypatch):
        # Edit two routes at once -> both slugs come back.
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            [
                "aero/templates/archive-product.html",
                "aero/templates/page-checkout.html",
            ],
        )
        got = snap_mod._changed_routes("aero", "origin/main")
        assert got == {"shop", "category", "checkout-filled"}

    def test_pattern_match_narrows(self, snap_mod, monkeypatch):
        # A new product-* pattern should map to both product routes
        # via the `patterns/product-*.html` glob.
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["aero/patterns/product-gallery.html"],
        )
        got = snap_mod._changed_routes("aero", "origin/main")
        assert got == {"product-simple", "product-variable"}

    def test_post_part_narrows_to_journal_post(self, snap_mod, monkeypatch):
        _install_fake_diff(
            snap_mod,
            monkeypatch,
            ["aero/parts/comments.html"],
        )
        assert snap_mod._changed_routes("aero", "origin/main") == {"journal-post"}

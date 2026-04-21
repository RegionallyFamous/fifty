"""Tests for `check_distinctive_chrome`.

Cross-theme check: scans `theme.json` for every `_KNOWN_THEME_SLUGS`
theme in the monorepo and fails when >=2 themes ship byte-identical
base CSS for any selector in `DISTINCT_CHROME_SELECTORS`, UNLESS each
theme in the cluster also ships a `body.theme-<slug> <selector>`
override.

The monorepo fixture only ships `obel` + `chonk`; the other slugs
(`selvedge`, `lysholm`, `aero`) are silently absent, which is fine —
the check keys off whichever themes are present.
"""

from __future__ import annotations

import json


def _set_theme_css(theme_root, css: str) -> None:
    data = json.loads((theme_root / "theme.json").read_text(encoding="utf-8"))
    data["styles"]["css"] = css
    (theme_root / "theme.json").write_text(json.dumps(data), encoding="utf-8")


SURFACE = ".wc-block-cart__sidebar"


def test_skips_when_no_theme_ships_the_surface(monorepo, bind_check_root):
    """Zero themes paint the selector — nothing to compare."""
    check = bind_check_root(monorepo["obel"])
    result = check.check_distinctive_chrome()
    assert result.passed or result.skipped


def test_passes_when_both_themes_ship_different_base_rules(monorepo, bind_check_root):
    _set_theme_css(
        monorepo["obel"],
        SURFACE + " { padding: 2rem; border: 1px solid red; }",
    )
    _set_theme_css(
        monorepo["chonk"],
        SURFACE + " { padding: 3rem; background: yellow; }",
    )
    check = bind_check_root(monorepo["obel"])
    assert check.check_distinctive_chrome().passed


def test_fails_when_both_themes_ship_identical_base_with_no_override(monorepo, bind_check_root):
    shared = SURFACE + " { padding: 2rem; border: 1px solid red; }"
    _set_theme_css(monorepo["obel"], shared)
    _set_theme_css(monorepo["chonk"], shared)
    check = bind_check_root(monorepo["obel"])
    result = check.check_distinctive_chrome()
    assert not result.passed
    assert any(SURFACE in d for d in result.details)


def test_passes_when_shared_base_but_both_have_per_theme_override(monorepo, bind_check_root):
    shared = SURFACE + " { padding: 2rem; border: 1px solid red; }"
    _set_theme_css(
        monorepo["obel"],
        shared + f" body.theme-obel {SURFACE} {{ border-color: blue; }}",
    )
    _set_theme_css(
        monorepo["chonk"],
        shared + f" body.theme-chonk {SURFACE} {{ background: yellow; }}",
    )
    check = bind_check_root(monorepo["obel"])
    assert check.check_distinctive_chrome().passed

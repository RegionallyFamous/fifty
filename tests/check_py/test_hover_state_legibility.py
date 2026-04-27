"""Tests for `check_hover_state_legibility`.

Walks the CSS string inside `theme.json`, resolves each `:hover` /
`:focus` / `:active` rule's text + background to palette hex values, and
computes WCAG contrast. Anything below 3:1 fails.

Chose real-world values so the ratios we assert match what the
production rule catches on Chonk / Lysholm cart pages.
"""

from __future__ import annotations

import json


def _set_css(theme_root, css: str) -> None:
    data = json.loads((theme_root / "theme.json").read_text(encoding="utf-8"))
    data["styles"]["css"] = css
    (theme_root / "theme.json").write_text(json.dumps(data), encoding="utf-8")


def test_minimal_theme_has_no_hover_rules(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    result = check.check_hover_state_legibility()
    # Minimal theme has no inlined styles.css, so the check skips.
    assert result.passed or result.skipped


def test_legible_hover_passes(minimal_theme, bind_check_root):
    """contrast (dark text) on base (cream) is >= 3:1."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover { color: var(--wp--preset--color--contrast); "
        "background: var(--wp--preset--color--base); }",
    )
    assert check.check_hover_state_legibility().passed


def test_illegible_hover_fails(minimal_theme, bind_check_root):
    """base (cream) text on base (cream) background is ~1:1."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover { color: var(--wp--preset--color--base); "
        "background: var(--wp--preset--color--base); }",
    )
    result = check.check_hover_state_legibility()
    assert not result.passed


def test_hover_with_non_palette_bg_is_skipped(minimal_theme, bind_check_root):
    """Rule sets a gradient background the check can't reason about — skipped."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover { color: var(--wp--preset--color--base); "
        "background: linear-gradient(0deg, red, blue); }",
    )
    # Passing is fine: the rule sets a non-palette background, so the
    # check bails out rather than fail on an unreasonable-to-compute
    # contrast ratio.
    assert check.check_hover_state_legibility().passed


def test_hover_parses_var_fallback_chain(minimal_theme, bind_check_root):
    """The WC override boilerplate uses a `var(--X, var(--Y))` fallback
    chain; the old regex couldn't parse it and the check silently
    passed unpalatable hover colours. The new regex treats `)` AND `,`
    as the slug terminator so the primary slug is captured correctly.

    This fixture declares a hover rule where the primary slug is
    `primary` (#3A352B, dark warm) and the fallback is `contrast`.
    primary-on-base is ~7.8:1 so this passes — the test is confirming
    we don't CRASH / misparse (the old behavior was to never match the
    rule at all, letting bad combos through). A separate fixture
    below asserts that a bad primary slug is caught."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover{"
        "color:var(--wp--preset--color--primary,var(--wp--preset--color--contrast));"
        "background:var(--wp--preset--color--base);}",
    )
    assert check.check_hover_state_legibility().passed


def test_hover_catches_bad_primary_slug_in_fallback_chain(minimal_theme, bind_check_root):
    """Same fallback-chain shape, but this time the primary slug is
    `base` — cream on cream = ~1:1. The check must flag the primary
    (what the browser actually paints), not the fallback."""
    check = bind_check_root(minimal_theme)
    _set_css(
        minimal_theme,
        ".btn:hover{"
        "color:var(--wp--preset--color--base,var(--wp--preset--color--contrast));"
        "background:var(--wp--preset--color--base);}",
    )
    assert not check.check_hover_state_legibility().passed

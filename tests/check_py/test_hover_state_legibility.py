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

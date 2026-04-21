"""Tests for `check_no_hardcoded_colors`.

Scans templates/parts/patterns for `#RRGGBB` literals; everything MUST
route through the palette. `rgba(...)` is allowed.
"""

from __future__ import annotations


def test_no_hardcoded_colors_passes_on_minimal(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_no_hardcoded_colors().passed


def test_hex_in_template_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        '<!-- wp:paragraph --><p style="color:#ff0000">x</p><!-- /wp:paragraph -->\n',
        encoding="utf-8",
    )
    result = check.check_no_hardcoded_colors()
    assert not result.passed
    assert any("#ff0000" in d for d in result.details)


def test_rgba_is_allowed(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        '<!-- wp:paragraph --><p style="color:rgba(0,0,0,0.5)">x</p><!-- /wp:paragraph -->\n',
        encoding="utf-8",
    )
    assert check.check_no_hardcoded_colors().passed


def test_hex_in_pattern_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "patterns" / "x.php").write_text(
        '<?php /** Title: X */ ?>\n<!-- wp:group {"style":{"color":{"background":"#abcdef"}}} /-->',
        encoding="utf-8",
    )
    assert not check.check_no_hardcoded_colors().passed

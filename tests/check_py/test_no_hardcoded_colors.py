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


def test_html_numeric_entity_is_not_a_hex_color(minimal_theme, bind_check_root):
    """Decorative HTML numeric entities (`&#10086;` for fleuron, `&#8212;`
    for em-dash, `&#x2766;` for floral heart) must not trip the hex-color
    check — they're glyph escapes, not color literals. Regression test
    for a foundry-build false positive that blocked a legitimate ornate
    template until the entity was rewritten to Unicode.
    """
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        "<!-- wp:paragraph -->\n<p>&#10086; decorative flourish &#x2766;</p>\n"
        "<!-- /wp:paragraph -->\n",
        encoding="utf-8",
    )
    result = check.check_no_hardcoded_colors()
    assert result.passed, result.details


def test_hex_next_to_entity_still_fails(minimal_theme, bind_check_root):
    """The entity carve-out must not swallow a genuine hex color that
    happens to share a line with an entity — check should still catch
    the `#ff0000` here."""
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        '<!-- wp:paragraph -->\n<p>&#10086; <span style="color:#ff0000">x</span></p>\n'
        "<!-- /wp:paragraph -->\n",
        encoding="utf-8",
    )
    assert not check.check_no_hardcoded_colors().passed

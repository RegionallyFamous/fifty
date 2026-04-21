"""Tests for `check_no_stray_css`.

Only `style.css` at the theme root is allowed. Everything else should
live inside `theme.json`'s `styles.css` field.
"""

from __future__ import annotations


def test_only_root_style_css_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_no_stray_css().passed


def test_stray_css_in_subdir_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "assets").mkdir()
    (minimal_theme / "assets" / "extra.css").write_text("/* stray */", encoding="utf-8")
    result = check.check_no_stray_css()
    assert not result.passed
    assert any("extra.css" in d for d in result.details)

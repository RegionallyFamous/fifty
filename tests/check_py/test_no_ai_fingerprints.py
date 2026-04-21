"""Tests for `check_no_ai_fingerprints`.

Scans `README.md`, `readme.txt`, `style.css` for AI-tell vocabulary:
em-dash (—), leverage, comprehensive, seamless, delve, tapestry, robust.
"""

from __future__ import annotations


def test_minimal_style_css_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_no_ai_fingerprints().passed


def test_em_dash_in_style_css_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "style.css").write_text(
        "/*\nTheme Name: Scratch\nDescription: A theme — with em dash.\n*/\n",
        encoding="utf-8",
    )
    assert not check.check_no_ai_fingerprints().passed


def test_ai_word_in_readme_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "README.md").write_text(
        "# Scratch\n\nA comprehensive theme for the modern web.\n",
        encoding="utf-8",
    )
    assert not check.check_no_ai_fingerprints().passed


def test_clean_readme_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "README.md").write_text(
        "# Scratch\n\nA theme. Plain voice, no flourish.\n",
        encoding="utf-8",
    )
    assert check.check_no_ai_fingerprints().passed

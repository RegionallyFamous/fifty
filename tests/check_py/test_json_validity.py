"""Tests for `check_json_validity`."""

from __future__ import annotations


def test_passes_on_valid_theme_json(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_json_validity().passed


def test_fails_on_missing_theme_json(minimal_theme, bind_check_root):
    (minimal_theme / "theme.json").unlink()
    check = bind_check_root(minimal_theme)
    assert not check.check_json_validity().passed


def test_fails_on_malformed_theme_json(minimal_theme, bind_check_root):
    (minimal_theme / "theme.json").write_text('{"not":"closed"', encoding="utf-8")
    check = bind_check_root(minimal_theme)
    result = check.check_json_validity()
    assert not result.passed


def test_fails_on_malformed_styles_variation(minimal_theme, bind_check_root):
    (minimal_theme / "styles" / "bad.json").write_text("{oops", encoding="utf-8")
    check = bind_check_root(minimal_theme)
    assert not check.check_json_validity().passed

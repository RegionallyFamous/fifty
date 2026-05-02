"""Tests for `check_no_placeholder_microcopy`."""

from __future__ import annotations


def test_minimal_theme_passes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_no_placeholder_microcopy().passed


def test_register_sum_hex_in_template_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "patterns" / "leak.php").write_text(
        "<?php\n// phpcs:ignoreFile\n"
        "<!-- wp:paragraph -->\n<p>Register sum d075</p>\n<!-- /wp:paragraph -->\n",
        encoding="utf-8",
    )
    assert not check.check_no_placeholder_microcopy().passed


def test_fleet_slug_register_hex_in_functions_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "functions.php").write_text(
        "<?php\n"
        "// === BEGIN wc microcopy ===\n"
        "add_filter('gettext', static function ( $t ) {\n"
        "    return 'obel register ab12cd';\n"
        "} );\n"
        "// === END wc microcopy ===\n",
        encoding="utf-8",
    )
    assert not check.check_no_placeholder_microcopy().passed


def test_shop_floor_find_hex_in_overrides_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "microcopy-overrides.json").write_text(
        '{"x": "shop-floor find d5eb"}',
        encoding="utf-8",
    )
    assert not check.check_no_placeholder_microcopy().passed

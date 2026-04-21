"""Tests for `check_no_default_wc_strings`.

Scans `playground/blueprint.json` for the inlined mu-plugin and verifies
every default-WC microcopy override is present in its body.
"""

from __future__ import annotations

import json

REQUIRED_FRAGMENTS = [
    "woocommerce_blocks_cart_totals_label",
    "woocommerce_order_button_text",
    "woocommerce_default_catalog_orderby_options",
    "Lost your password?",
    "render_block_woocommerce/product-results-count",
]


def _write_blueprint(theme_root, mu_php: str) -> None:
    (theme_root / "playground").mkdir(exist_ok=True)
    blueprint = {
        "steps": [
            {
                "step": "writeFile",
                "path": "/wordpress/wp-content/mu-plugins/wo-microcopy-mu.php",
                "data": mu_php,
            }
        ]
    }
    (theme_root / "playground" / "blueprint.json").write_text(
        json.dumps(blueprint), encoding="utf-8"
    )


def test_passes_when_all_overrides_present(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    body = "\n".join(f"// {needle}" for needle in REQUIRED_FRAGMENTS)
    _write_blueprint(minimal_theme, f"<?php\n{body}\n")
    assert check.check_no_default_wc_strings().passed


def test_skips_when_no_blueprint_in_theme(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    result = check.check_no_default_wc_strings()
    assert result.skipped


def test_fails_when_mu_plugin_writefile_missing(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "playground").mkdir(exist_ok=True)
    (minimal_theme / "playground" / "blueprint.json").write_text(
        json.dumps({"steps": []}), encoding="utf-8"
    )
    assert not check.check_no_default_wc_strings().passed


def test_fails_when_any_override_dropped(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    # Drop the Lost-your-password override
    body = "\n".join(
        f"// {needle}" for needle in REQUIRED_FRAGMENTS if needle != "Lost your password?"
    )
    _write_blueprint(minimal_theme, f"<?php\n{body}\n")
    result = check.check_no_default_wc_strings()
    assert not result.passed
    assert any("Lost your password" in d for d in result.details)


def test_fails_on_invalid_blueprint_json(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "playground").mkdir(exist_ok=True)
    (minimal_theme / "playground" / "blueprint.json").write_text("{oops", encoding="utf-8")
    assert not check.check_no_default_wc_strings().passed

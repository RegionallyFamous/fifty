"""Tests for `check_no_wc_tabs_block`.

`woocommerce/product-details` is the umbrella tabs block. Replaced
entirely in this project with `core/details` + individual WC blocks.
Also checks that `theme.json` no longer styles it.
"""

from __future__ import annotations

import json


def test_passes_when_tabs_block_absent(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_no_wc_tabs_block().passed


def test_fails_when_tabs_block_in_template(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "single-product.html").write_text(
        "<!-- wp:woocommerce/product-details /-->\n",
        encoding="utf-8",
    )
    result = check.check_no_wc_tabs_block()
    assert not result.passed
    assert any("product-details" in d for d in result.details)


def test_fails_when_theme_json_styles_tabs_block(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    data = json.loads((minimal_theme / "theme.json").read_text(encoding="utf-8"))
    data["styles"]["blocks"] = {"woocommerce/product-details": {"color": {}}}
    (minimal_theme / "theme.json").write_text(json.dumps(data), encoding="utf-8")
    assert not check.check_no_wc_tabs_block().passed


def test_related_wc_blocks_do_not_trip(minimal_theme, bind_check_root):
    """product-description, product-reviews, product-price — none of these
    should be caught by the tabs regex."""
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "single-product.html").write_text(
        "<!-- wp:woocommerce/product-description /-->\n"
        "<!-- wp:woocommerce/product-price /-->\n"
        "<!-- wp:woocommerce/product-reviews /-->\n",
        encoding="utf-8",
    )
    assert check.check_no_wc_tabs_block().passed

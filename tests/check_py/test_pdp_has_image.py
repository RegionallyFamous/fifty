"""Tests for `check_pdp_has_image`."""

from __future__ import annotations


def test_skips_when_no_single_product_template(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_pdp_has_image().skipped


def test_passes_when_post_featured_image_present(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "single-product.html").write_text(
        "<!-- wp:post-featured-image /-->\n",
        encoding="utf-8",
    )
    assert check.check_pdp_has_image().passed


def test_passes_with_wc_product_image(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "single-product.html").write_text(
        "<!-- wp:woocommerce/product-image /-->\n",
        encoding="utf-8",
    )
    assert check.check_pdp_has_image().passed


def test_fails_when_no_image_block(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "single-product.html").write_text(
        "<!-- wp:post-title /-->\n<!-- wp:post-content /-->\n",
        encoding="utf-8",
    )
    assert not check.check_pdp_has_image().passed

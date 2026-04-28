"""Tests for `bin/check.py:check_modern_blocks_only`.

The check folds three historical `grep -rE` rules from the
`build-block-theme-variant` skill into a single static gate:

1. `<!-- wp:html -->`, `<!-- wp:shortcode -->`, `<!-- wp:freeform -->`
   in `templates/`, `parts/`, `patterns/` is a hard fail. `core/html`
   is narrowly allowed when the body is pure decorative SVG.
2. Legacy WooCommerce page shortcodes (`[woocommerce_cart]`,
   `[woocommerce_checkout]`, `[woocommerce_my_account]`,
   `[woocommerce_order_tracking]`) are a hard fail.
3. Legacy WooCommerce catalogue shortcodes (`[products]`,
   `[product_category]`, `[recent_products]`, `[featured_products]`,
   `[sale_products]`, `[product_page]`, `[add_to_cart]`,
   `[shop_messages]`) are a hard fail.

Each scenario flips a clean fixture into a failing state to verify the
gate fires on exactly the class of regression the skill's manual
greps were supposed to catch.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_passes_with_no_legacy_blocks_anywhere(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "index.html",
        """\
        <!-- wp:paragraph -->
        <p>Hello</p>
        <!-- /wp:paragraph -->
        """,
    )
    assert check.check_modern_blocks_only().passed


def test_fails_on_core_shortcode_block(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "page-cart.html",
        """\
        <!-- wp:shortcode -->[woocommerce_cart]<!-- /wp:shortcode -->
        """,
    )
    result = check.check_modern_blocks_only()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "wp:shortcode" in joined


def test_fails_on_core_freeform_block(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "parts" / "footer.html",
        """\
        <!-- wp:freeform -->
        Free-form classic-editor HTML.
        <!-- /wp:freeform -->
        """,
    )
    result = check.check_modern_blocks_only()
    assert not result.passed


def test_fails_on_core_html_with_form(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "patterns" / "subscribe.php",
        """\
        <?php
        /**
         * Title: Subscribe
         * Slug: demo/subscribe
         */
        ?>
        <!-- wp:html -->
        <form action="/fake"><input type="email" name="email"/></form>
        <!-- /wp:html -->
        """,
    )
    result = check.check_modern_blocks_only()
    assert not result.passed


def test_allows_core_html_with_decorative_svg(minimal_theme, bind_check_root):
    """core/html with a pure decorative SVG body is the documented
    carve-out: it's the only way to ship a token-aware inline SVG
    without a media-library round trip.
    """
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "404.html",
        """\
        <!-- wp:html -->
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
          <circle cx="12" cy="12" r="10"/>
        </svg>
        <!-- /wp:html -->
        """,
    )
    result = check.check_modern_blocks_only()
    assert result.passed, result.details


def test_fails_on_wc_cart_shortcode(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "page-cart.html",
        """\
        <!-- wp:paragraph -->
        <p>[woocommerce_cart]</p>
        <!-- /wp:paragraph -->
        """,
    )
    result = check.check_modern_blocks_only()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "woocommerce_cart" in joined


def test_fails_on_wc_my_account_shortcode(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "parts" / "account-widget.html",
        """\
        <!-- wp:paragraph -->
        <p>[woocommerce_my_account]</p>
        <!-- /wp:paragraph -->
        """,
    )
    result = check.check_modern_blocks_only()
    assert not result.passed


def test_fails_on_wc_catalogue_shortcodes(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:paragraph -->
        <p>[products limit="4"]</p>
        <!-- /wp:paragraph -->

        <!-- wp:paragraph -->
        <p>[product_category category="bags"]</p>
        <!-- /wp:paragraph -->
        """,
    )
    result = check.check_modern_blocks_only()
    assert not result.passed
    joined = "\n".join(result.details)
    assert "[products]" in joined or "`[products]`" in joined

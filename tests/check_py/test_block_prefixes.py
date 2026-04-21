"""Tests for `check_block_prefixes` — only core/* and woocommerce/* blocks."""

from __future__ import annotations


def test_core_only_blocks_pass(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        "<!-- wp:core/paragraph --><p>ok</p><!-- /wp:core/paragraph -->\n"
        "<!-- wp:paragraph --><p>ok</p><!-- /wp:paragraph -->\n"
        "<!-- wp:woocommerce/product-price /-->\n",
        encoding="utf-8",
    )
    assert check.check_block_prefixes().passed


def test_third_party_block_namespace_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "templates" / "page.html").write_text(
        "<!-- wp:jetpack/tiled-gallery /-->\n",
        encoding="utf-8",
    )
    result = check.check_block_prefixes()
    assert not result.passed
    assert any("jetpack" in d for d in result.details)


def test_third_party_block_in_pattern_fails(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "patterns" / "broken.php").write_text(
        "<?php /** Title: Broken */ ?>\n<!-- wp:acf/hero /-->\n",
        encoding="utf-8",
    )
    assert not check.check_block_prefixes().passed

"""Tests for `bin/check.py:check_product_terms_query_show_nested`.

Guards against the Selvedge front-page failure mode: a `core/terms-query`
block walking `product_cat` with `showNested:false` (and no curated
`include` filter) renders one top-level `Shop` tile instead of the
intended sub-category grid because the demo product categories live
under a single parent.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_passes_when_no_terms_query(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    assert check.check_product_terms_query_show_nested().passed


def test_passes_with_show_nested_true(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:terms-query {"termQuery":{"taxonomy":"product_cat","perPage":5,"showNested":true,"hideEmpty":true}} -->
        <div class="wp-block-terms-query"></div>
        <!-- /wp:terms-query -->
        """,
    )
    assert check.check_product_terms_query_show_nested().passed


def test_passes_with_explicit_include(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:terms-query {"termQuery":{"taxonomy":"product_cat","perPage":3,"showNested":false,"include":[12,18,24]}} -->
        <div class="wp-block-terms-query"></div>
        <!-- /wp:terms-query -->
        """,
    )
    assert check.check_product_terms_query_show_nested().passed


def test_passes_for_non_product_taxonomy(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:terms-query {"termQuery":{"taxonomy":"category","perPage":5,"showNested":false}} -->
        <div class="wp-block-terms-query"></div>
        <!-- /wp:terms-query -->
        """,
    )
    assert check.check_product_terms_query_show_nested().passed


def test_fails_on_product_cat_with_show_nested_false(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    _write(
        minimal_theme / "templates" / "front-page.html",
        """\
        <!-- wp:terms-query {"termQuery":{"taxonomy":"product_cat","perPage":5,"showNested":false,"hideEmpty":true,"include":[]}} -->
        <div class="wp-block-terms-query"></div>
        <!-- /wp:terms-query -->
        """,
    )
    result = check.check_product_terms_query_show_nested()
    assert not result.passed
    rendered = " ".join(result.details)
    assert "front-page.html" in rendered
    assert "product_cat" in rendered

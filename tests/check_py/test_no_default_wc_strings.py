"""Tests for `check_no_default_wc_strings`.

After the theme-shipped microcopy refactor, the check scans
`<theme>/functions.php` for the sentinel-bracketed
`// === BEGIN wc microcopy === ... // === END wc microcopy ===`
block and verifies every canonical default-WC override fragment is
present inside it.
"""

from __future__ import annotations

REQUIRED_FRAGMENTS = [
    "woocommerce_blocks_cart_totals_label",
    "woocommerce_order_button_text",
    "woocommerce_default_catalog_orderby_options",
    "Lost your password?",
    "render_block_woocommerce/product-results-count",
]


def _write_functions(theme_root, body: str) -> None:
    """Write a `functions.php` whose body contains the supplied snippet
    bracketed by the canonical BEGIN/END microcopy sentinels.
    """
    (theme_root / "functions.php").write_text(
        f"<?php\n// === BEGIN wc microcopy ===\n{body}\n// === END wc microcopy ===\n",
        encoding="utf-8",
    )


def test_passes_when_all_overrides_present(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    body = "\n".join(f"// {needle}" for needle in REQUIRED_FRAGMENTS)
    _write_functions(minimal_theme, body)
    assert check.check_no_default_wc_strings().passed


def test_skips_when_no_functions_php(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    fn = minimal_theme / "functions.php"
    if fn.exists():
        fn.unlink()
    result = check.check_no_default_wc_strings()
    assert result.skipped


def test_fails_when_microcopy_block_missing(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    (minimal_theme / "functions.php").write_text(
        "<?php\n// no microcopy block here\n", encoding="utf-8"
    )
    assert not check.check_no_default_wc_strings().passed


def test_fails_when_any_override_dropped(minimal_theme, bind_check_root):
    check = bind_check_root(minimal_theme)
    body = "\n".join(
        f"// {needle}" for needle in REQUIRED_FRAGMENTS if needle != "Lost your password?"
    )
    _write_functions(minimal_theme, body)
    result = check.check_no_default_wc_strings()
    assert not result.passed
    assert any("Lost your password" in d for d in result.details)

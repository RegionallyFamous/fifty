"""Tests for `check_mu_plugin_no_legacy_loop_echoes`.

Scans `<monorepo>/playground/wo-microcopy-mu.php` (shared source) for
`add_action( 'woocommerce_before_shop_loop', ... )` callbacks that emit
HTML via echo / print / printf / heredoc.
"""

from __future__ import annotations

import textwrap


def _write_mu(monorepo, body: str) -> None:
    (monorepo["root"] / "playground").mkdir(exist_ok=True)
    (monorepo["root"] / "playground" / "wo-microcopy-mu.php").write_text(
        textwrap.dedent(body),
        encoding="utf-8",
    )


def test_skips_when_no_mu_plugin(monorepo, bind_check_root):
    check = bind_check_root(monorepo["obel"])
    assert check.check_mu_plugin_no_legacy_loop_echoes().skipped


def test_passes_with_no_add_action_on_loop_hooks(monorepo, bind_check_root):
    _write_mu(
        monorepo,
        """\
        <?php
        // Uses render_block_<name> filters, not legacy hooks. Canonical.
        add_filter( 'render_block_woocommerce/product-results-count',
            static function ( $html ) { return $html; }, 10, 1 );
        """,
    )
    check = bind_check_root(monorepo["obel"])
    assert check.check_mu_plugin_no_legacy_loop_echoes().passed


def test_passes_when_hook_callback_only_does_remove_action(monorepo, bind_check_root):
    _write_mu(
        monorepo,
        """\
        <?php
        add_action( 'woocommerce_before_shop_loop', function () {
            remove_action( 'woocommerce_before_shop_loop', 'wc_print_notices', 10 );
        }, 5 );
        """,
    )
    check = bind_check_root(monorepo["obel"])
    assert check.check_mu_plugin_no_legacy_loop_echoes().passed


def test_fails_on_echo_in_before_shop_loop(monorepo, bind_check_root):
    _write_mu(
        monorepo,
        """\
        <?php
        add_action( 'woocommerce_before_shop_loop', function () {
            echo '<p class="wo-result-count">N items</p>';
        }, 20 );
        """,
    )
    check = bind_check_root(monorepo["obel"])
    result = check.check_mu_plugin_no_legacy_loop_echoes()
    assert not result.passed


def test_fails_on_printf_with_markup(monorepo, bind_check_root):
    _write_mu(
        monorepo,
        """\
        <?php
        add_action( 'woocommerce_after_shop_loop', function () {
            printf( '<div>%s</div>', 'x' );
        }, 20 );
        """,
    )
    check = bind_check_root(monorepo["obel"])
    assert not check.check_mu_plugin_no_legacy_loop_echoes().passed


def test_fails_on_heredoc_with_markup(monorepo, bind_check_root):
    _write_mu(
        monorepo,
        """\
        <?php
        add_action( 'woocommerce_no_products_found', function () {
            echo <<<EOT
        <p>No products</p>
        EOT;
        }, 20 );
        """,
    )
    check = bind_check_root(monorepo["obel"])
    assert not check.check_mu_plugin_no_legacy_loop_echoes().passed


def test_comments_mentioning_echo_are_ignored(monorepo, bind_check_root):
    """Docstrings referencing `echo '<p ...>'` must not trip the gate."""
    _write_mu(
        monorepo,
        """\
        <?php
        add_action( 'woocommerce_before_shop_loop', function () {
            // The old code used to do echo '<p class="wo-result-count">...';
            /* Another block comment: echo '<div>x</div>'; */
            remove_action( 'woocommerce_before_shop_loop', 'wc_print_notices', 10 );
        }, 20 );
        """,
    )
    check = bind_check_root(monorepo["obel"])
    assert check.check_mu_plugin_no_legacy_loop_echoes().passed

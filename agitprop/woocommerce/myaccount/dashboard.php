<?php
/**
 * My Account dashboard — Chonk override.
 *
 * Replaces WooCommerce's default `myaccount/dashboard.php` (which
 * hard-codes a "Hello %s (not %s? Log out)" + "From your account
 * dashboard you can…" paragraph pair) with a single hook call. All
 * dashboard markup is rendered by the
 * `chonk_render_account_dashboard` callback registered in
 * `functions.php` (see the `// === BEGIN my-account ===` block) so
 * the greeting + 3-card quick-link grid is the only thing that
 * paints inside the dashboard tab.
 *
 * WC discovers this override via `wc_locate_template()` because the
 * relative path matches: `chonk/woocommerce/myaccount/dashboard.php`.
 *
 * @package chonk
 */

defined( 'ABSPATH' ) || exit;

do_action( 'woocommerce_account_dashboard' );

do_action( 'woocommerce_before_my_account_orders' );

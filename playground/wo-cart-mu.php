<?php
/**
 * Wonders & Oddities demo cart pre-filler (mu-plugin).
 *
 * Installed by the Playground blueprint as a must-use plugin so it is
 * always active without requiring WP-CLI or database activation.
 *
 * When a request includes ?demo=cart the cart is emptied and three
 * known W&O products are added. This makes the Cart and Checkout
 * deeplinks (&url=/cart/?demo=cart, &url=/checkout/?demo=cart)
 * arrive with items already present so reviewers can evaluate the
 * full purchase flow without clicking through the shop manually.
 *
 * Behaviour:
 *  - Only fires on frontend requests.
 *  - Resolves products by SKU so it still works if post IDs change.
 *  - Silently skips any SKU that does not exist (e.g. import not yet run).
 *  - Has no effect on admin pages or when WooCommerce is not active.
 */

add_action(
	'wp_loaded',
	function () {
		if ( empty( $_GET['demo'] ) || 'cart' !== $_GET['demo'] ) {
			return;
		}
		if ( is_admin() ) {
			return;
		}
		if ( ! function_exists( 'WC' ) || ! WC()->cart ) {
			return;
		}

		WC()->cart->empty_cart();

		// Pre-fill the demo cart with three known in-stock products.
		// Defensive: re-prime each product's stock_status BEFORE adding,
		// because on a fresh Playground boot WC's stock cache may not yet
		// reflect the imported `_stock` meta. Without this, the "demo cart"
		// page sometimes renders a persistent pink "out of stock" notice
		// even though the CSV says Stock=8. We force-recalculate via
		// wc_update_product_stock_status() so the cart sees the imported
		// stock truth, then skip any product that is genuinely OOS so the
		// cart never has a phantom "removed" notice either.
		$skus = array( 'WO-BOTTLED-MORNING', 'WO-POCKET-THUNDER', 'WO-CHAOS-SEASONING' );
		foreach ( $skus as $sku ) {
			$pid = wc_get_product_id_by_sku( $sku );
			if ( ! $pid ) {
				continue;
			}
			if ( function_exists( 'wc_update_product_stock_status' ) ) {
				wc_update_product_stock_status( $pid, 'instock' );
			}
			$product = wc_get_product( $pid );
			if ( ! $product || ! $product->is_purchasable() ) {
				continue;
			}
			WC()->cart->add_to_cart( $pid );
		}
	},
	20
);

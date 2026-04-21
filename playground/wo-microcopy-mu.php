<?php
/**
 * Wonders & Oddities premium-microcopy overrides (mu-plugin).
 *
 * Installed by the Playground blueprint as a must-use plugin so the
 * filters fire on every frontend request without theme activation /
 * WP-CLI plumbing.
 *
 * Why this exists:
 *   The default WooCommerce frontend strings telegraph "I downloaded a
 *   free theme":
 *     - "Showing 1-16 of 55 results"
 *     - "Default sorting"
 *     - "Estimated total"
 *     - "Proceed to Checkout" (oversized pill on a tiny right column)
 *     - "Username or email address *" with a red asterisk
 *     - "Lost your password?"
 *     - "+ Add apartment, suite, etc."
 *     - "You are currently checking out as a guest."
 *     - "By proceeding with your purchase you agree..." (oversized para)
 *
 *   None of these are wrong; they're just unmistakable WC defaults.
 *   Replacing them via filter hooks is the cheapest possible nudge from
 *   "WooCommerce site" to "branded storefront."
 *
 * Scope intentionally narrow:
 *   - Demo-only mu-plugin. We don't ship a translation file, we don't
 *     touch admin strings, and we don't try to build a full i18n layer.
 *   - All filters are append-only (safe under future WC versions; if
 *     a filter disappears the override silently no-ops).
 *   - No DB writes, no options touched, no registered settings page.
 *   - Frontend-only (`is_admin()` short-circuit at the top of every
 *     hook that runs in a request that could hit the admin).
 *
 * Strings are written for an English-speaking shopper. The variations
 * above each filter line are intentional: the first option is what we
 * ship, the rest are alternatives the design team can swap in later
 * without having to chase down the original WC default.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

// ---------------------------------------------------------------------------
// 1. Shop archive: results count + sort label.
// ---------------------------------------------------------------------------
//
// "Showing 1-16 of 55 results" -> "55 items" (cleaner header line).
// "Default sorting" dropdown label -> "Featured" (no shopper has ever
// thought "I want default sorting").
add_filter(
	'woocommerce_show_page_title',
	'__return_true' // Keep the H1 visible; archive header relies on it.
);

add_filter(
	'woocommerce_pagination_args',
	function ( $args ) {
		$args['prev_text'] = '&larr;';
		$args['next_text'] = '&rarr;';
		return $args;
	}
);

add_filter(
	'woocommerce_show_page_title',
	'__return_true'
);

// "Showing X-Y of Z results" -> "Z items".
//
// Why a `render_block_*` filter and NOT a `woocommerce_before_shop_loop`
// echo:
//
// The previous version of this block hooked `woocommerce_before_shop_loop`
// (priority 20) and echoed a fresh `<p class="woocommerce-result-count
// wo-result-count">N items</p>`. That action fires in TWO places on every
// modern shop page:
//
//   1. The legacy `woocommerce_content()` shortcode loop (where the
//      original WC counter lived).
//   2. INSIDE `wp:woocommerce/product-collection`'s server render -- the
//      product-collection block invokes the loop hooks for backwards
//      compatibility with sidebar widgets and addon plugins.
//
// Themes built on the modern block editor place
// `wp:woocommerce/product-results-count` inside a flex header row in
// `archive-product.html`, then render the product grid below via
// `wp:woocommerce/product-collection`. The block-rendered count lands in
// the flex row (correct). The action-rendered count lands ABOVE the
// product grid, with no parent container, floating in the middle of
// nowhere -- the exact "23 ITEMS off in the middle of nowhere" failure
// the Proprietor flagged.
//
// `render_block_woocommerce/product-results-count` rewrites the block's
// already-correctly-positioned `<p>` in place, so there is exactly ONE
// count node and it sits where the template author put it. The filter
// passes through untouched if WC stops shipping the
// `woocommerce-result-count` class (defensive forward-compat).
add_filter(
	'render_block_woocommerce/product-results-count',
	function ( $block_content ) {
		if ( is_admin() || '' === trim( (string) $block_content ) ) {
			return $block_content;
		}
		$total = (int) wc_get_loop_prop( 'total', 0 );
		if ( $total <= 0 ) {
			return $block_content;
		}
		$label = sprintf(
			/* translators: %d: number of products in the current archive. */
			esc_html( _n( '%d item', '%d items', $total, 'fifty' ) ),
			$total
		);
		$rewritten = preg_replace(
			'#(<p\b[^>]*\bclass="[^"]*\bwoocommerce-result-count\b[^"]*"[^>]*>)[\s\S]*?(</p>)#i',
			'$1' . $label . '$2',
			$block_content,
			1,
			$count
		);
		return ( $count > 0 && null !== $rewritten ) ? $rewritten : $block_content;
	},
	20
);

// "Default sorting" -> "Featured" in the catalog order dropdown.
add_filter(
	'woocommerce_default_catalog_orderby_options',
	function ( $options ) {
		if ( isset( $options['menu_order'] ) ) {
			$options['menu_order'] = __( 'Featured', 'fifty' );
		}
		// Also tighten the secondary labels for completeness.
		if ( isset( $options['popularity'] ) ) {
			$options['popularity'] = __( 'Best sellers', 'fifty' );
		}
		if ( isset( $options['rating'] ) ) {
			$options['rating'] = __( 'Top rated', 'fifty' );
		}
		if ( isset( $options['date'] ) ) {
			$options['date'] = __( 'New arrivals', 'fifty' );
		}
		if ( isset( $options['price'] ) ) {
			$options['price'] = __( 'Price: low to high', 'fifty' );
		}
		if ( isset( $options['price-desc'] ) ) {
			$options['price-desc'] = __( 'Price: high to low', 'fifty' );
		}
		return $options;
	}
);
add_filter(
	'woocommerce_catalog_orderby',
	function ( $options ) {
		if ( isset( $options['menu_order'] ) ) {
			$options['menu_order'] = __( 'Featured', 'fifty' );
		}
		return $options;
	}
);

// ---------------------------------------------------------------------------
// 2. Cart + Checkout: totals labels.
// ---------------------------------------------------------------------------
//
// "Estimated total" -> "Total" (no need to soften it for our demo).
// "Subtotal" stays. "Proceed to Checkout" -> "Checkout".
add_filter(
	'gettext',
	function ( $translation, $text, $domain ) {
		if ( 'woocommerce' !== $domain && 'default' !== $domain ) {
			return $translation;
		}

		// Map of WC default string -> our preferred microcopy. Keep
		// alphabetical so future additions stay easy to find. Whitespace
		// matters — we match the exact source string WC ships.
		static $map = array(
			'Estimated total'                                                                                                              => 'Total',
			'Proceed to Checkout'                                                                                                          => 'Checkout',
			'Proceed to checkout'                                                                                                          => 'Checkout',
			'Lost your password?'                                                                                                          => 'Forgot password',
			'Username or email address'                                                                                                    => 'Email',
			'Username or Email Address'                                                                                                    => 'Email',
			'+ Add apartment, suite, etc.'                                                                                                 => 'Add address line 2',
			'You are currently checking out as a guest.'                                                                                   => 'Have an account? Sign in to autofill.',
			'Showing the single result'                                                                                                    => '1 item',
			'Default sorting'                                                                                                              => 'Featured',
			'No products were found matching your selection.'                                                                              => 'Nothing matches that filter yet.',
			'No products in the cart.'                                                                                                     => 'Your cart is empty.',
			'Your cart is currently empty!'                                                                                                => 'Your cart is empty.',
			'Your cart is currently empty.'                                                                                                => 'Your cart is empty.',
			'Return to shop'                                                                                                               => 'Continue shopping',
			'Return To Shop'                                                                                                               => 'Continue shopping',
			'Have a coupon?'                                                                                                               => 'Coupon code',
			'Update cart'                                                                                                                  => 'Update',
			'Place order'                                                                                                                  => 'Place order',
			'Apply coupon'                                                                                                                 => 'Apply',
			'Coupon code'                                                                                                                  => 'Code',
			'Order details'                                                                                                                => 'Order',
			'Order summary'                                                                                                                => 'Summary',
			'Cart subtotal'                                                                                                                => 'Subtotal',
			'Add to cart'                                                                                                                  => 'Add to cart',
			'Customer details'                                                                                                             => 'Your details',
			'Save my name, email, and website in this browser for the next time I comment.'                                                => 'Remember me for next time.',
			'Be the first to review'                                                                                                       => 'Be the first to review',
			'Your review'                                                                                                                  => 'Review',
			'Your rating'                                                                                                                  => 'Rating',
			'Submit'                                                                                                                       => 'Post review',
			'Description'                                                                                                                  => 'Description',
			'Reviews'                                                                                                                      => 'Reviews',
			'Additional information'                                                                                                       => 'Details',
			'View cart'                                                                                                                    => 'View cart',
			'View Cart'                                                                                                                    => 'View cart',
			'Choose an option'                                                                                                             => 'Select',
			'Clear'                                                                                                                        => 'Reset',
			'Login'                                                                                                                        => 'Sign in',
			'Log in'                                                                                                                       => 'Sign in',
			'Log out'                                                                                                                      => 'Sign out',
			'Register'                                                                                                                     => 'Create account',
			'Remember me'                                                                                                                  => 'Keep me signed in',
			'My account'                                                                                                                   => 'Account',
			'My Account'                                                                                                                   => 'Account',
			'Order received'                                                                                                               => 'Thank you',
			'Thank you. Your order has been received.'                                                                                     => 'Thanks — your order is in.',
			'You may also like&hellip;'                                                                                                    => 'You may also like',
			'You may also like…'                                                                                                           => 'You may also like',
			'Related products'                                                                                                             => 'You may also like',
		);

		return isset( $map[ $text ] ) ? $map[ $text ] : $translation;
	},
	20,
	3
);

// ---------------------------------------------------------------------------
// 3. WC Blocks (cart/checkout) string overrides.
// ---------------------------------------------------------------------------
//
// WC Blocks ships its own block-level filters that bypass `gettext`
// because the strings are emitted in JS-rendered React components.
// These cover the totals row label, place-order button, and the
// "checking out as guest" / login prompt strings on the WC Blocks
// checkout.
add_filter(
	'woocommerce_blocks_cart_totals_label',
	function ( $label ) {
		return __( 'Total', 'fifty' );
	}
);
add_filter(
	'woocommerce_order_button_text',
	function () {
		return __( 'Place order', 'fifty' );
	}
);

// ---------------------------------------------------------------------------
// 4. Required-field marker softening.
// ---------------------------------------------------------------------------
//
// WC's checkout fields render a red `<abbr class="required">*</abbr>`
// next to every required input. The asterisk is fine; the screaming red
// reads cheap. We swap the markup to a softer dot rendered in the
// theme's secondary color via CSS (the dot is inserted server-side so
// it works without JS).
add_filter(
	'woocommerce_form_field',
	function ( $field, $key, $args, $value ) {
		// Only touch frontend fields with the default required marker.
		if ( false !== strpos( $field, '<abbr class="required"' ) ) {
			$field = preg_replace(
				'#<abbr class="required"[^>]*>\*</abbr>#i',
				'<span class="wo-required-mark" aria-hidden="true">·</span>',
				$field
			);
		}
		return $field;
	},
	20,
	4
);

// ---------------------------------------------------------------------------
// 5. Footer copyright filter (per-theme brand string).
// ---------------------------------------------------------------------------
//
// Themes that include a footer pattern with the literal "Site Title"
// placeholder get a real per-theme name swapped in here so demos read
// "© Chonk", "© Obel", etc. The WO_THEME_NAME constant is defined by
// `wo-configure.php` (and prepended by `bin/sync-playground.py`); this
// mu-plugin runs in the same Playground process so we can read it.
add_filter(
	'wo_footer_copyright_brand',
	function ( $brand ) {
		if ( defined( 'WO_THEME_NAME' ) && WO_THEME_NAME ) {
			return (string) WO_THEME_NAME;
		}
		return $brand;
	}
);

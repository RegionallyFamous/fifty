<?php
/**
 * Wonders & Oddities demo configurator for WordPress Playground.
 *
 * Run via `wp eval-file /wordpress/wo-configure.php` after wo-import.php
 * and the WXR import have completed.
 *
 * WO_THEME_NAME must be defined before this script is included. The
 * sync-playground.py script prepends
 *   define('WO_THEME_NAME', '<theme>');
 * to the inlined data field so each theme gets its own value without
 * this source file needing to know about it.
 *
 * The script is idempotent: it stores a timestamp in the _wo_configured
 * option and returns early if that option already exists. Re-running the
 * blueprint will not create duplicates.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

if ( ! class_exists( 'WooCommerce' ) ) {
	WP_CLI::error( 'WooCommerce is not active. Aborting W&O configure.' );
}

if ( get_option( '_wo_configured' ) ) {
	WP_CLI::success( 'W&O already configured. Skipping.' );
	return;
}

$theme_name = defined( 'WO_THEME_NAME' ) ? WO_THEME_NAME : 'Demo';

// ---------------------------------------------------------------------------
// 1. Permalinks
// ---------------------------------------------------------------------------
//
// Subtle but critical: just calling
//     update_option( 'permalink_structure', '/%postname%/' );
//     flush_rewrite_rules( true );
// does NOT work in a `wp eval-file` context. The global $wp_rewrite was
// constructed at WP boot using the previous (default = empty) structure, so
// $wp_rewrite->permalink_structure is still ''. flush_rewrite_rules() then
// regenerates the `rewrite_rules` option from that stale property, producing
// rules for the default permalink structure. Result: requests to
// /welcome-to-wonders-and-oddities/, /product/foo/, /journal/, etc. all
// 404 inside Playground.
//
// The fix is to use WP_Rewrite::set_permalink_structure(), which updates
// both the option and the in-memory $wp_rewrite state (via init()), then
// flush. The trailing delete_option() is belt + suspenders so any next
// frontend request will lazily rebuild the rules even if the in-process
// flush misses a permastruct registered by a plugin loaded after $wp_rewrite.
global $wp_rewrite;
$wp_rewrite->set_permalink_structure( '/%postname%/' );
$wp_rewrite->set_category_base( '' );
$wp_rewrite->set_tag_base( '' );
$wp_rewrite->flush_rules( true );
delete_option( 'rewrite_rules' );
WP_CLI::log( 'Permalinks: set to /%postname%/ and flushed.' );

// ---------------------------------------------------------------------------
// 2. Site identity
// ---------------------------------------------------------------------------
update_option( 'blogdescription', $theme_name . ' demo storefront' );
WP_CLI::log( 'Tagline: set.' );

// ---------------------------------------------------------------------------
// 3. WooCommerce store config
// ---------------------------------------------------------------------------
update_option( 'woocommerce_default_country', 'US:CA' );
update_option( 'woocommerce_currency', 'USD' );
update_option( 'woocommerce_currency_pos', 'left' );
update_option( 'woocommerce_price_thousand_sep', ',' );
update_option( 'woocommerce_price_decimal_sep', '.' );
update_option( 'woocommerce_price_num_decimals', '2' );
update_option( 'woocommerce_weight_unit', 'kg' );
update_option( 'woocommerce_dimension_unit', 'cm' );
update_option( 'woocommerce_calc_taxes', 'no' );
update_option( 'woocommerce_ship_to_countries', '' );
update_option( 'woocommerce_store_address', '123 Curiosity Lane' );
update_option( 'woocommerce_store_city', 'Los Angeles' );
update_option( 'woocommerce_store_postcode', '90001' );

// Product image sizes: 800px single (matches source resolution), 600px thumbnails.
update_option( 'woocommerce_single_image_width', 800 );
update_option( 'woocommerce_thumbnail_image_width', 600 );
update_option( 'woocommerce_thumbnail_cropping', '1:1' );
WP_CLI::log( 'WC store options: set.' );

// ---------------------------------------------------------------------------
// 4. Suppress WC onboarding notices + disable "Coming soon" site visibility
// ---------------------------------------------------------------------------
update_option( 'woocommerce_show_marketplace_suggestions', 'no' );
update_option( 'woocommerce_task_list_complete', 'yes' );
update_option( 'woocommerce_task_list_hidden', 'yes' );
update_option( 'woocommerce_extended_task_list_hidden', 'yes' );
update_option( 'woocommerce_setup_wizard_complete', 'yes' );
update_option( 'woocommerce_admin_notices', array() );
delete_transient( 'woocommerce_activation_redirect' );
delete_option( 'woocommerce_queue_flush_rewrite_rules' );

// WC 8.4+ ships with a "Coming soon" site-visibility mode that redirects every
// non-shop frontend URL to /shop/ for logged-out visitors. Disable it so the
// homepage and all other pages are publicly visible on first load.
update_option( 'woocommerce_coming_soon', 'no' );
update_option( 'woocommerce_store_pages_only', 'no' );

// Mark all known WC onboarding note actions as actioned so the inbox is quiet.
if ( class_exists( '\Automattic\WooCommerce\Admin\Notes\Notes' ) ) {
	global $wpdb;
	$wpdb->query(
		"UPDATE {$wpdb->prefix}wc_admin_notes SET status = 'actioned' WHERE status = 'unactioned'"
	);
}
WP_CLI::log( 'WC onboarding: suppressed.' );

// ---------------------------------------------------------------------------
// 5. Payment gateways (enable cod + bacs; no credentials required)
// ---------------------------------------------------------------------------
$gateway_settings = array(
	'woocommerce_cod_settings'  => array(
		'enabled'            => 'yes',
		'title'              => 'Cash on Delivery',
		'description'        => 'Pay with cash upon delivery.',
		'instructions'       => 'Pay with cash upon delivery.',
		'enable_for_methods' => array(),
		'enable_for_virtual' => 'yes',
	),
	'woocommerce_bacs_settings' => array(
		'enabled'      => 'yes',
		'title'        => 'Direct Bank Transfer',
		'description'  => 'Make your payment directly into our bank account.',
		'instructions' => 'Make your payment directly into our bank account. Please use your Order ID as the payment reference.',
		'account_name'    => 'Wonders & Oddities',
		'account_number'  => '0000000',
		'sort_code'       => '000000',
		'bank_name'       => 'Curiosity Bank',
		'iban'            => '',
		'bic'             => '',
	),
);
foreach ( $gateway_settings as $key => $value ) {
	update_option( $key, $value );
}
WP_CLI::log( 'Payment gateways: COD and BACS enabled.' );

// ---------------------------------------------------------------------------
// 6. Shipping zones + methods
// ---------------------------------------------------------------------------

// Remove any existing zones except the "Rest of the World" catch-all (id=0).
global $wpdb;
$existing_zone_ids = $wpdb->get_col(
	"SELECT zone_id FROM {$wpdb->prefix}woocommerce_shipping_zones WHERE zone_id != 0"
);
foreach ( $existing_zone_ids as $zid ) {
	$zone = new WC_Shipping_Zone( (int) $zid );
	$zone->delete();
}

$zone = new WC_Shipping_Zone();
$zone->set_zone_name( 'Default' );
$zone->set_zone_order( 1 );
$zone->save();
$zone->add_location( 'US', 'country' );

// Flat Rate: $5.
$flat_id = $zone->add_shipping_method( 'flat_rate' );
update_option(
	'woocommerce_flat_rate_' . $flat_id . '_settings',
	array(
		'enabled'      => 'yes',
		'title'        => 'Flat Rate',
		'tax_status'   => 'taxable',
		'cost'         => '5',
		'class_costs'  => '',
		'no_class_cost'=> '',
		'type'         => 'class',
	)
);

// Free Shipping: no min order (straightforward for demos).
$free_id = $zone->add_shipping_method( 'free_shipping' );
update_option(
	'woocommerce_free_shipping_' . $free_id . '_settings',
	array(
		'enabled'      => 'yes',
		'title'        => 'Free Shipping',
		'requires'     => '',
		'min_amount'   => '',
		'ignore_discounts' => 'no',
	)
);

// Also enable free shipping on the "Rest of the World" zone (id=0).
$row_zone = new WC_Shipping_Zone( 0 );
$row_free_id = $row_zone->add_shipping_method( 'free_shipping' );
update_option(
	'woocommerce_free_shipping_' . $row_free_id . '_settings',
	array(
		'enabled' => 'yes',
		'title'   => 'Free Shipping',
		'requires' => '',
	)
);

WC_Cache_Helper::invalidate_cache_group( 'shipping_zones' );
WP_CLI::log( 'Shipping zones: Default zone with Flat Rate + Free Shipping added.' );

// ---------------------------------------------------------------------------
// 7. Customer account
// ---------------------------------------------------------------------------
$customer_id = username_exists( 'customer' );
if ( ! $customer_id ) {
	$customer_id = wp_insert_user(
		array(
			'user_login' => 'customer',
			'user_email' => 'customer@example.com',
			'user_pass'  => 'customer',
			'first_name' => 'Alex',
			'last_name'  => 'Curiosity',
			'role'       => 'customer',
		)
	);
	if ( is_wp_error( $customer_id ) ) {
		WP_CLI::warning( 'Customer creation failed: ' . $customer_id->get_error_message() );
		$customer_id = 0;
	}
}

if ( $customer_id ) {
	$addr = array(
		'billing_first_name' => 'Alex',
		'billing_last_name'  => 'Curiosity',
		'billing_email'      => 'customer@example.com',
		'billing_phone'      => '555-0100',
		'billing_address_1'  => '42 Wonder Way',
		'billing_city'       => 'Los Angeles',
		'billing_state'      => 'CA',
		'billing_postcode'   => '90001',
		'billing_country'    => 'US',
		'shipping_first_name'=> 'Alex',
		'shipping_last_name' => 'Curiosity',
		'shipping_address_1' => '42 Wonder Way',
		'shipping_city'      => 'Los Angeles',
		'shipping_state'     => 'CA',
		'shipping_postcode'  => '90001',
		'shipping_country'   => 'US',
	);
	foreach ( $addr as $key => $value ) {
		update_user_meta( $customer_id, $key, $value );
	}
	WP_CLI::log( "Customer: ID {$customer_id} (login: customer / customer)." );
}

// ---------------------------------------------------------------------------
// 8. Sample orders
// ---------------------------------------------------------------------------
if ( $customer_id && ! get_option( '_wo_orders_seeded' ) ) {

	// Grab a handful of real product IDs to use as line items.
	$order_products = array();
	foreach ( array( 'WO-BOTTLED-MORNING', 'WO-CHAOS-SEASONING', 'WO-POCKET-THUNDER', 'WO-SILENCE-JAR', 'WO-MOON-DUST' ) as $sku ) {
		$pid = wc_get_product_id_by_sku( $sku );
		if ( $pid ) {
			$order_products[] = $pid;
		}
	}
	// Fall back to any published simple products if the SKUs aren't there yet.
	if ( count( $order_products ) < 3 ) {
		$fallback = wc_get_products(
			array(
				'type'   => 'simple',
				'status' => 'publish',
				'limit'  => 5,
				'return' => 'ids',
			)
		);
		$order_products = array_values( array_unique( array_merge( $order_products, $fallback ) ) );
	}

	$statuses = array( 'wc-completed', 'wc-processing', 'wc-on-hold', 'wc-cancelled', 'wc-refunded' );
	$billing  = array(
		'first_name' => 'Alex',
		'last_name'  => 'Curiosity',
		'email'      => 'customer@example.com',
		'phone'      => '555-0100',
		'address_1'  => '42 Wonder Way',
		'city'       => 'Los Angeles',
		'state'      => 'CA',
		'postcode'   => '90001',
		'country'    => 'US',
	);

	foreach ( $statuses as $i => $status ) {
		try {
			$order = wc_create_order( array( 'customer_id' => $customer_id ) );
			$order->set_status( $status );
			$order->set_billing_address( $billing );
			$order->set_shipping_address( $billing );
			$order->set_payment_method( 'cod' );
			$order->set_payment_method_title( 'Cash on Delivery' );

			// Add 1–3 products cycling through the list.
			$count = ( $i % 3 ) + 1;
			for ( $j = 0; $j < $count; $j++ ) {
				$pid = $order_products[ ( $i + $j ) % count( $order_products ) ] ?? 0;
				if ( $pid ) {
					$product = wc_get_product( $pid );
					$order->add_product( $product, 1 );
				}
			}

			$order->calculate_totals();
			$order->add_meta_data( '_wo_seed_order', '1', true );
			$order->set_date_created( time() - ( ( 5 - $i ) * DAY_IN_SECONDS * 3 ) );
			$order->save();
		} catch ( Exception $e ) {
			WP_CLI::warning( "Order {$status}: " . $e->getMessage() );
		}
	}

	update_option( '_wo_orders_seeded', '1' );
	WP_CLI::log( 'Orders: 5 sample orders created.' );
}

// ---------------------------------------------------------------------------
// 9. Stock-state variety
// ---------------------------------------------------------------------------
// Put a couple of existing products on-sale and mark one out-of-stock.
$sale_skus = array( 'WO-CHAOS-SEASONING', 'WO-MOON-DUST', 'WO-SILENCE-JAR' );
foreach ( $sale_skus as $sku ) {
	$pid = wc_get_product_id_by_sku( $sku );
	if ( ! $pid ) {
		continue;
	}
	$p = wc_get_product( $pid );
	if ( ! $p || ! $p->is_type( 'simple' ) ) {
		continue;
	}
	$reg = (float) $p->get_regular_price();
	if ( $reg > 0 ) {
		$p->set_sale_price( number_format( $reg * 0.7, 2, '.', '' ) );
		$p->save();
	}
}

$oos_pid = wc_get_product_id_by_sku( 'WO-VOID-SAMPLER' );
if ( $oos_pid ) {
	$oos = wc_get_product( $oos_pid );
	if ( $oos ) {
		$oos->set_stock_status( 'outofstock' );
		$oos->save();
	}
}

$backorder_pid = wc_get_product_id_by_sku( 'WO-DISCOUNT-GRAVITY' );
if ( $backorder_pid ) {
	$bop = wc_get_product( $backorder_pid );
	if ( $bop && $bop->is_type( 'simple' ) ) {
		$bop->set_manage_stock( true );
		$bop->set_stock_quantity( 0 );
		$bop->set_backorders( 'notify' );
		$bop->save();
	}
}
WP_CLI::log( 'Stock states: sale prices, OOS, and backorder set.' );

// ---------------------------------------------------------------------------
// 9b. Featured products — mark 4 hero SKUs so the homepage hero grid fills.
// ---------------------------------------------------------------------------
// The front-page hero collection uses collection="woocommerce/product-collection/featured"
// which only surfaces products with is_featured = true. Without this step the
// hero's right column renders empty because the CSV import sets featured = false
// on all rows by default.
foreach ( array( 'WO-BOTTLED-MORNING', 'WO-POCKET-THUNDER', 'WO-MOON-DUST', 'WO-SILENCE-JAR' ) as $sku ) {
	$pid = wc_get_product_id_by_sku( $sku );
	if ( ! $pid ) {
		continue;
	}
	$p = wc_get_product( $pid );
	if ( $p ) {
		$p->set_featured( true );
		$p->save();
	}
}
WP_CLI::log( 'Featured: 4 hero products flagged.' );

// ---------------------------------------------------------------------------
// 10. Variable products
// ---------------------------------------------------------------------------
if ( ! wc_get_product_id_by_sku( 'WO-BOTL-S-AMB' ) ) {
	try {
		$variable = new WC_Product_Variable();
		$variable->set_name( 'Bottled Morning (Variants)' );
		$variable->set_status( 'publish' );
		$variable->set_sku( 'WO-BOTL-VAR' );
		$variable->set_description( 'Bottled Morning in multiple sizes and finishes. Each bottle is guaranteed to contain exactly one morning.' );
		$variable->set_short_description( 'Your morning, your way.' );
		$variable->set_featured( false );

		// Inherit the featured image from the matching simple product.
		$botl_simple_id = wc_get_product_id_by_sku( 'WO-BOTTLED-MORNING' );
		if ( $botl_simple_id ) {
			$botl_img_id = get_post_thumbnail_id( $botl_simple_id );
			if ( $botl_img_id ) {
				$variable->set_image_id( $botl_img_id );
			}
		}

		$attr_size = new WC_Product_Attribute();
		$attr_size->set_name( 'Size' );
		$attr_size->set_options( array( 'Small', 'Medium', 'Large' ) );
		$attr_size->set_position( 0 );
		$attr_size->set_visible( true );
		$attr_size->set_variation( true );

		$attr_finish = new WC_Product_Attribute();
		$attr_finish->set_name( 'Finish' );
		$attr_finish->set_options( array( 'Amber', 'Clear' ) );
		$attr_finish->set_position( 1 );
		$attr_finish->set_visible( true );
		$attr_finish->set_variation( true );

		$variable->set_attributes( array( $attr_size, $attr_finish ) );
		$variable_id = $variable->save();

		$variations = array(
			array( 'Size' => 'Small',  'Finish' => 'Amber', 'sku' => 'WO-BOTL-S-AMB', 'price' => '9.00',  'stock' => 20 ),
			array( 'Size' => 'Small',  'Finish' => 'Clear', 'sku' => 'WO-BOTL-S-CLR', 'price' => '9.00',  'stock' => 15 ),
			array( 'Size' => 'Medium', 'Finish' => 'Amber', 'sku' => 'WO-BOTL-M-AMB', 'price' => '14.00', 'stock' => 10 ),
			array( 'Size' => 'Medium', 'Finish' => 'Clear', 'sku' => 'WO-BOTL-M-CLR', 'price' => '14.00', 'stock' => 8  ),
			array( 'Size' => 'Large',  'Finish' => 'Amber', 'sku' => 'WO-BOTL-L-AMB', 'price' => '22.00', 'stock' => 5  ),
			array( 'Size' => 'Large',  'Finish' => 'Clear', 'sku' => 'WO-BOTL-L-CLR', 'price' => '22.00', 'stock' => 3  ),
		);

		foreach ( $variations as $vdata ) {
			$variation = new WC_Product_Variation();
			$variation->set_parent_id( $variable_id );
			$variation->set_attributes(
				array(
					'attribute_size'   => $vdata['Size'],
					'attribute_finish' => $vdata['Finish'],
				)
			);
			$variation->set_sku( $vdata['sku'] );
			$variation->set_regular_price( $vdata['price'] );
			$variation->set_status( 'publish' );
			$variation->set_manage_stock( true );
			$variation->set_stock_quantity( $vdata['stock'] );
			$variation->save();
		}

		WC_Product_Variable::sync( $variable_id );
		WP_CLI::log( "Variable product: Bottled Morning (Variants) created (ID {$variable_id})." );

	} catch ( Exception $e ) {
		WP_CLI::warning( 'Bottled Morning variable: ' . $e->getMessage() );
	}
}

if ( ! wc_get_product_id_by_sku( 'WO-THUN-SOFT' ) ) {
	try {
		$thunder = new WC_Product_Variable();
		$thunder->set_name( 'Pocket Thunder (Variants)' );
		$thunder->set_status( 'publish' );
		$thunder->set_sku( 'WO-THUN-VAR' );
		$thunder->set_description( 'A compact thunderstorm, available in two intensities.' );
		$thunder->set_short_description( 'The storm that fits in your pocket.' );

		// Inherit the featured image from the matching simple product.
		$thun_simple_id = wc_get_product_id_by_sku( 'WO-POCKET-THUNDER' );
		if ( $thun_simple_id ) {
			$thun_img_id = get_post_thumbnail_id( $thun_simple_id );
			if ( $thun_img_id ) {
				$thunder->set_image_id( $thun_img_id );
			}
		}

		$attr_int = new WC_Product_Attribute();
		$attr_int->set_name( 'Intensity' );
		$attr_int->set_options( array( 'Soft', 'Loud' ) );
		$attr_int->set_position( 0 );
		$attr_int->set_visible( true );
		$attr_int->set_variation( true );

		$thunder->set_attributes( array( $attr_int ) );
		$thunder_id = $thunder->save();

		foreach ( array( 'Soft' => array( 'sku' => 'WO-THUN-SOFT', 'price' => '18.00', 'stock' => 12 ), 'Loud' => array( 'sku' => 'WO-THUN-LOUD', 'price' => '24.00', 'stock' => 6 ) ) as $intensity => $vdata ) {
			$v = new WC_Product_Variation();
			$v->set_parent_id( $thunder_id );
			$v->set_attributes( array( 'attribute_intensity' => $intensity ) );
			$v->set_sku( $vdata['sku'] );
			$v->set_regular_price( $vdata['price'] );
			$v->set_status( 'publish' );
			$v->set_manage_stock( true );
			$v->set_stock_quantity( $vdata['stock'] );
			$v->save();
		}

		WC_Product_Variable::sync( $thunder_id );
		WP_CLI::log( "Variable product: Pocket Thunder (Variants) created (ID {$thunder_id})." );

	} catch ( Exception $e ) {
		WP_CLI::warning( 'Pocket Thunder variable: ' . $e->getMessage() );
	}
}

// ---------------------------------------------------------------------------
// 11. Product reviews
// ---------------------------------------------------------------------------
if ( ! get_option( '_wo_reviews_seeded' ) ) {
	$review_data = array(
		array( 'sku' => 'WO-BOTTLED-MORNING',  'author' => 'Priya S.',    'rating' => 5, 'comment' => 'Genuinely changed my mornings. Worth every penny.' ),
		array( 'sku' => 'WO-BOTTLED-MORNING',  'author' => 'James W.',    'rating' => 4, 'comment' => 'Tastes like optimism with a faint hint of regret.' ),
		array( 'sku' => 'WO-CHAOS-SEASONING',  'author' => 'Dana K.',     'rating' => 5, 'comment' => 'Transformed my bland meals into something unpredictable. 10/10.' ),
		array( 'sku' => 'WO-CHAOS-SEASONING',  'author' => 'Mikael R.',   'rating' => 3, 'comment' => 'Exciting, but I wish there was a mild setting.' ),
		array( 'sku' => 'WO-POCKET-THUNDER',   'author' => 'Leila M.',    'rating' => 5, 'comment' => 'Perfect for dramatic emphasis in presentations.' ),
		array( 'sku' => 'WO-SILENCE-JAR',      'author' => 'Tom B.',      'rating' => 4, 'comment' => 'My family has never been quieter. Miraculous.' ),
		array( 'sku' => 'WO-SILENCE-JAR',      'author' => 'Carmen O.',   'rating' => 5, 'comment' => 'Works as described. No complaints -- literally.' ),
		array( 'sku' => 'WO-MOON-DUST',        'author' => 'Noah F.',     'rating' => 4, 'comment' => 'Smells exactly like you would expect the moon to smell.' ),
		array( 'sku' => 'WO-MOON-DUST',        'author' => 'Aiko T.',     'rating' => 5, 'comment' => 'Bought three jars. Planning to buy more.' ),
		array( 'sku' => 'WO-VOID-SAMPLER',     'author' => 'Remy D.',     'rating' => 3, 'comment' => 'The void is real. Not sure I was ready for that.' ),
		array( 'sku' => 'WO-DISCOUNT-GRAVITY', 'author' => 'Fatima A.',   'rating' => 5, 'comment' => 'Finally, a discount that is tangible in every sense.' ),
		array( 'sku' => 'WO-DISCOUNT-GRAVITY', 'author' => 'Carlos N.',   'rating' => 4, 'comment' => 'Applied it to my grocery bill. Neighbours are concerned.' ),
	);

	$review_count = 0;
	foreach ( $review_data as $idx => $rd ) {
		$pid = wc_get_product_id_by_sku( $rd['sku'] );
		if ( ! $pid ) {
			continue;
		}
		$existing = get_comments(
			array(
				'post_id'  => $pid,
				'type'     => 'review',
				'author'   => $rd['author'],
				'count'    => true,
			)
		);
		if ( $existing ) {
			continue;
		}
		$comment_id = wp_insert_comment(
			array(
				'comment_post_ID'      => $pid,
				'comment_author'       => $rd['author'],
				'comment_author_email' => 'reviewer' . $idx . '@example.com',
				'comment_content'      => $rd['comment'],
				'comment_type'         => 'review',
				'comment_approved'     => 1,
				'comment_date'         => date( 'Y-m-d H:i:s', time() - ( $idx * DAY_IN_SECONDS * 2 ) ),
			)
		);
		if ( $comment_id ) {
			update_comment_meta( $comment_id, 'rating', (int) $rd['rating'] );
			update_comment_meta( $comment_id, 'verified', 0 );
			++$review_count;
		}
	}

	// Refresh average ratings for all reviewed products.
	foreach ( array_unique( array_column( $review_data, 'sku' ) ) as $sku ) {
		$pid = wc_get_product_id_by_sku( $sku );
		if ( $pid ) {
			WC_Comments::get_average_rating_for_product( wc_get_product( $pid ) );
		}
	}

	update_option( '_wo_reviews_seeded', '1' );
	WP_CLI::log( "Reviews: {$review_count} inserted." );
}

// ---------------------------------------------------------------------------
// 11b. Category cover images
// ---------------------------------------------------------------------------
//
// Both the image base URL and the cat-name -> filename map are pulled from
// the per-theme content/ folder so every theme can ship its own category
// cover artwork without touching this shared script. The map lives at
// `<theme>/playground/content/category-images.json` and looks like:
//
//     { "Curiosities": "cat-curiosities.jpg", ... }
//
// Image files themselves live at `<theme>/playground/images/<filename>`.
//
// If the JSON file is missing or unreachable (e.g. a theme that doesn't
// ship category covers), the step quietly no-ops -- it isn't a hard
// dependency for a working storefront.
if ( ! get_option( '_wo_cat_images_seeded' ) ) {
	require_once ABSPATH . 'wp-admin/includes/media.php';
	require_once ABSPATH . 'wp-admin/includes/file.php';
	require_once ABSPATH . 'wp-admin/includes/image.php';

	$wo_content_base = defined( 'WO_CONTENT_BASE_URL' )
		? WO_CONTENT_BASE_URL
		: 'https://raw.githubusercontent.com/RegionallyFamous/fifty/main/playground/';
	$raw_base = rtrim( $wo_content_base, '/' ) . '/images/';
	$map_url  = rtrim( $wo_content_base, '/' ) . '/content/category-images.json';

	$cat_images   = array();
	$map_response = wp_remote_get( $map_url, array( 'timeout' => 30 ) );
	if ( ! is_wp_error( $map_response ) && 200 === wp_remote_retrieve_response_code( $map_response ) ) {
		$decoded = json_decode( wp_remote_retrieve_body( $map_response ), true );
		if ( is_array( $decoded ) ) {
			$cat_images = $decoded;
		}
	}
	if ( empty( $cat_images ) ) {
		WP_CLI::log( "Category images: no map found at {$map_url}, skipping." );
		// The trailing update_option('_wo_cat_images_seeded', ...) below
		// fires regardless, so the empty-map branch is idempotent on its
		// own without an early return here.
	}

	$img_count = 0;
	foreach ( $cat_images as $cat_name => $filename ) {
		$term = get_term_by( 'name', $cat_name, 'product_cat' );
		if ( ! $term ) {
			WP_CLI::log( "Category image: term not found for '{$cat_name}', skipping." );
			continue;
		}
		if ( get_term_meta( $term->term_id, 'thumbnail_id', true ) ) {
			WP_CLI::log( "Category image: '{$cat_name}' already has a thumbnail, skipping." );
			continue;
		}

		$url = $raw_base . $filename;
		$tmp = download_url( $url );
		if ( is_wp_error( $tmp ) ) {
			WP_CLI::warning( "Category image: failed to download {$url} — " . $tmp->get_error_message() );
			continue;
		}

		$file_array = array(
			'name'     => $filename,
			'tmp_name' => $tmp,
		);
		$attachment_id = media_handle_sideload( $file_array, 0, $cat_name );
		if ( is_wp_error( $attachment_id ) ) {
			@unlink( $tmp );
			WP_CLI::warning( "Category image: sideload failed for '{$cat_name}' — " . $attachment_id->get_error_message() );
			continue;
		}

		update_term_meta( $term->term_id, 'thumbnail_id', $attachment_id );
		++$img_count;
		WP_CLI::log( "Category image: assigned to '{$cat_name}' (attachment {$attachment_id})." );
	}

	update_option( '_wo_cat_images_seeded', '1' );
	WP_CLI::log( "Category images: {$img_count} assigned." );
}

// ---------------------------------------------------------------------------
// 11c. Product featured images
// ---------------------------------------------------------------------------
//
// Loads a JSON map of { "SKU": "filename.jpg" } from the per-theme content/
// folder (product-images.json) and sideloads each image as a media attachment,
// then sets it as the product's featured image.  Like the category cover step,
// the source images live in <theme>/playground/images/  and the map is fetched
// from <theme>/playground/content/product-images.json.
//
// This step runs after the WXR import so it replaces any placeholder images
// that the import may have sideloaded from the CSV.  It is idempotent because
// it checks whether the product already has a thumbnail whose _wo_product_image
// post meta flag is set before sideloading again.
if ( ! get_option( '_wo_product_images_seeded' ) ) {
	require_once ABSPATH . 'wp-admin/includes/media.php';
	require_once ABSPATH . 'wp-admin/includes/file.php';
	require_once ABSPATH . 'wp-admin/includes/image.php';

	$wo_content_base = defined( 'WO_CONTENT_BASE_URL' )
		? WO_CONTENT_BASE_URL
		: 'https://raw.githubusercontent.com/RegionallyFamous/fifty/main/playground/';
	$prod_raw_base = rtrim( $wo_content_base, '/' ) . '/images/';
	$prod_map_url  = rtrim( $wo_content_base, '/' ) . '/content/product-images.json';

	$prod_images   = array();
	$prod_response = wp_remote_get( $prod_map_url, array( 'timeout' => 30 ) );
	if ( ! is_wp_error( $prod_response ) && 200 === wp_remote_retrieve_response_code( $prod_response ) ) {
		$decoded = json_decode( wp_remote_retrieve_body( $prod_response ), true );
		if ( is_array( $decoded ) ) {
			$prod_images = $decoded;
		}
	}
	if ( empty( $prod_images ) ) {
		WP_CLI::log( "Product images: no map found at {$prod_map_url}, skipping." );
	}

	$pi_count = 0;
	foreach ( $prod_images as $sku => $filename ) {
		$pid = wc_get_product_id_by_sku( $sku );
		if ( ! $pid ) {
			WP_CLI::log( "Product image: SKU '{$sku}' not found, skipping." );
			continue;
		}

		// Skip if we already seeded this product's image in a prior run.
		if ( get_post_meta( $pid, '_wo_product_image', true ) ) {
			continue;
		}

		$url = $prod_raw_base . $filename;
		$tmp = download_url( $url );
		if ( is_wp_error( $tmp ) ) {
			WP_CLI::warning( "Product image: failed to download {$url} — " . $tmp->get_error_message() );
			continue;
		}

		$file_array = array(
			'name'     => $filename,
			'tmp_name' => $tmp,
		);
		$attachment_id = media_handle_sideload( $file_array, $pid, $sku );
		if ( is_wp_error( $attachment_id ) ) {
			@unlink( $tmp );
			WP_CLI::warning( "Product image: sideload failed for SKU '{$sku}' — " . $attachment_id->get_error_message() );
			continue;
		}

		set_post_thumbnail( $pid, $attachment_id );
		update_post_meta( $pid, '_wo_product_image', $attachment_id );
		++$pi_count;
		WP_CLI::log( "Product image: assigned to '{$sku}' (attachment {$attachment_id})." );
	}

	update_option( '_wo_product_images_seeded', '1' );
	WP_CLI::log( "Product images: {$pi_count} assigned." );
}

// ---------------------------------------------------------------------------
// 12. Auto-update suppression
// ---------------------------------------------------------------------------
update_option( 'auto_update_core_major', 'disabled' );
update_option( 'auto_update_core_minor', 'disabled' );
update_option( 'auto_updater.lock', time() );
WP_CLI::log( 'Auto-updates: disabled.' );

// ---------------------------------------------------------------------------
// Done.
// ---------------------------------------------------------------------------
update_option( '_wo_configured', time() );
WP_CLI::success( 'W&O configure done.' );

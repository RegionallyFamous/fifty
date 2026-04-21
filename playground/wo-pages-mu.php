<?php
/**
 * Wonders & Oddities branded WC pages mu-plugin.
 *
 * Bundles the four "page-level" Phase D deliverables that all share the
 * same shape (filter a WC hook, inject a branded wrapper or replace
 * markup):
 *
 *   1. My Account login: split layout with brand-intro panel on the
 *      left, form on the right. Uses `woocommerce_before_customer_login_form`
 *      / `_after_customer_login_form` to wrap the form in branded markup.
 *      Same approach for the registration column on the right.
 *
 *   2. Empty cart message: `woocommerce_cart_is_empty` action emits a
 *      branded heading + 2 CTA buttons. The default WC empty-cart text
 *      ("Your cart is currently empty!") and the bare "Return to shop"
 *      link both get suppressed via gettext (handled in the microcopy
 *      mu-plugin) so this branded version is the only thing visible.
 *
 *   3. Empty search results / no products: filter
 *      `woocommerce_no_products_found` to print a branded empty state
 *      with a "Browse all products" CTA + recently-viewed prompt.
 *
 *   4. Editorial archive header: `woocommerce_before_main_content` hook
 *      injects a hero strip at the top of category / tag / shop archives
 *      that pulls the term cover image (sideloaded by wo-configure 11b)
 *      + term name + term description into a hero banner. Falls through
 *      to a clean text-only banner if the term has no cover image.
 *
 * All hooks are frontend-only and short-circuit on `is_admin()`. No DB
 * writes, no options, no admin UI. Works with both block themes and
 * legacy-PHP WC templates because every hook used here exists in both.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

// ---------------------------------------------------------------------------
// 1. Branded My Account login screen — moved to <theme>/functions.php.
// ---------------------------------------------------------------------------
//
// HISTORICAL NOTE. Earlier passes of this mu-plugin emitted shopper-
// facing markup on the logged-out My Account page from `playground/`:
// first a generic `<aside class="wo-account-intro">` + `<p class="wo-
// account-help">` (cycle 1), then four structural `<div>` wrappers
// (`wo-account-login-grid` / `wo-account-login-form`) that paired the
// intro and the login form into a two-column layout (cycle 2).
//
// Both violated the root rule "Shopper-facing brand lives in the
// theme, not in playground/" — anything that affects what a real
// shopper sees on a released theme has to ship in the theme directory
// so a Proprietor who downloads the theme and drops it into
// `wp-content/themes/` gets the same login chrome as the Playground
// demo. The cycle-1 generics were superseded by per-theme branded
// versions in each `<theme>/functions.php` (between the
// `// === BEGIN my-account ===` sentinels). The cycle-2 structural
// wrappers were caught by `bin/check.py`'s
// `check_no_brand_filters_in_playground` gate (the
// `woocommerce_before_customer_login_form` /
// `woocommerce_after_customer_login_form` hooks are on its denylist
// for exactly this reason) and moved into the same per-theme block at
// priorities 4 / 6 / 19 / 25, sandwiching the intro (5) and help (20)
// callbacks the themes already register. The resulting DOM on /my-
// account/ when logged out is now:
//
//   <div class="wo-account-login-grid">                          ← prio 4 (theme)
//     <aside class="wo-account-intro">…brand intro…</aside>      ← prio 5 (theme)
//     <div class="wo-account-login-form">                        ← prio 6 (theme)
//       …WC's <h2>Sign in</h2> + <form>…
//     </div>                                                     ← after-prio 19 (theme)
//     <p class="wo-account-help">…</p>                           ← after-prio 20 (theme)
//   </div>                                                       ← after-prio 25 (theme)
//
// styled by `.wo-account-login-grid` / `.wo-account-login-form` rules
// in each theme's `theme.json`. Nothing about the My Account login
// surface lives in `playground/` any more.

// ---------------------------------------------------------------------------
// 2. Branded empty cart.
// ---------------------------------------------------------------------------
//
// When the cart is empty WC fires `woocommerce_cart_is_empty`. Default
// behavior is a small "Your cart is currently empty!" banner + a
// "Return to shop" link. We replace the whole region with a branded
// empty state (eyebrow + display-font heading + 2 CTAs).
add_action(
	'woocommerce_cart_is_empty',
	function () {
		if ( is_admin() ) {
			return;
		}
		?>
<div class="wo-empty wo-empty--cart">
	<p class="wo-empty__eyebrow">Cart</p>
	<h1 class="wo-empty__title">Your cart is empty.</h1>
	<p class="wo-empty__lede">Browse the shop or pick up where you left off.</p>
	<p class="wo-empty__ctas">
		<a class="wo-empty__cta wo-empty__cta--primary" href="/shop/">Continue shopping</a>
		<a class="wo-empty__cta wo-empty__cta--secondary" href="/journal/">Read the journal</a>
	</p>
</div>
		<?php
	},
	5
);

// ---------------------------------------------------------------------------
// 3. Branded "no products found" empty state.
// ---------------------------------------------------------------------------
//
// Triggered from the legacy WC archive loop (and from the WC Blocks
// product collection's empty-results inner block). Replaces WC's
// "No products were found matching your selection." paragraph with
// the same branded empty-state shape used for the cart.
//
// `remove_action` first to clear WC's default; then `add_action` to
// re-add the branded version at the same priority so it appears in
// the same template slot.
add_action(
	'init',
	function () {
		if ( ! function_exists( 'wc_no_products_found' ) ) {
			return;
		}
		remove_action( 'woocommerce_no_products_found', 'wc_no_products_found' );
		add_action(
			'woocommerce_no_products_found',
			function () {
				if ( is_admin() ) {
					return;
				}
				?>
<div class="wo-empty wo-empty--shop">
	<p class="wo-empty__eyebrow">Shop</p>
	<h2 class="wo-empty__title">Nothing matches that filter yet.</h2>
	<p class="wo-empty__lede">Try a different category — or see everything we currently have in stock.</p>
	<p class="wo-empty__ctas">
		<a class="wo-empty__cta wo-empty__cta--primary" href="/shop/">Browse all products</a>
		<a class="wo-empty__cta wo-empty__cta--secondary" href="/journal/">Read the journal</a>
	</p>
</div>
				<?php
			},
			10
		);
	},
	20
);

// ---------------------------------------------------------------------------
// 4. Editorial archive header (category / tag / shop).
// ---------------------------------------------------------------------------
//
// On product category and tag archives, prepend a hero strip that uses
// the term's cover image (sideloaded by wo-configure section 11b) as a
// background image with the term name + description overlay. On the
// generic shop archive (no term), a leaner H1+lede strip prints
// instead. The strip is dropped before WC's `woocommerce_before_main_content`
// hook so the existing block-theme markup is unaffected.
add_action(
	'woocommerce_before_main_content',
	function () {
		if ( is_admin() ) {
			return;
		}
		if ( ! function_exists( 'is_product_category' ) || ! ( is_product_category() || is_product_tag() || is_shop() ) ) {
			return;
		}

		$term      = get_queried_object();
		$has_term  = ( $term && isset( $term->term_id ) );
		$cover_url = '';
		$title     = '';
		$desc      = '';
		$eyebrow   = '';

		if ( $has_term ) {
			$thumb_id = (int) get_term_meta( $term->term_id, 'thumbnail_id', true );
			if ( $thumb_id ) {
				$cover_url = wp_get_attachment_image_url( $thumb_id, 'large' );
			}
			$title   = $term->name;
			$desc    = term_description( $term->term_id, $term->taxonomy );
			$eyebrow = ( 'product_cat' === $term->taxonomy ) ? 'Collection' : 'Tag';
		} elseif ( function_exists( 'is_shop' ) && is_shop() ) {
			$shop_page_id = wc_get_page_id( 'shop' );
			if ( $shop_page_id > 0 ) {
				$cover_url = get_the_post_thumbnail_url( $shop_page_id, 'large' );
				$title     = get_the_title( $shop_page_id );
			}
			if ( ! $title ) {
				$title = __( 'Shop', 'fifty' );
			}
			$eyebrow = 'Shop';
		}

		if ( ! $title ) {
			return;
		}

		$style = '';
		$mod   = '';
		if ( $cover_url ) {
			$style = sprintf( ' style="background-image:url(%s);"', esc_url( $cover_url ) );
			$mod   = ' wo-archive-hero--has-cover';
		}
		?>
<header class="wo-archive-hero<?php echo esc_attr( $mod ); ?>"<?php echo $style; ?>>
	<div class="wo-archive-hero__inner">
		<p class="wo-archive-hero__eyebrow"><?php echo esc_html( $eyebrow ); ?></p>
		<h1 class="wo-archive-hero__title"><?php echo esc_html( $title ); ?></h1>
		<?php if ( $desc ) : ?>
			<div class="wo-archive-hero__lede"><?php echo wp_kses_post( $desc ); ?></div>
		<?php endif; ?>
	</div>
</header>
		<?php
	},
	5
);

// ---------------------------------------------------------------------------
// 5. Per-theme body class for distinctive Phase E polish.
// ---------------------------------------------------------------------------
//
// Block themes don't expose a per-theme body class on the frontend by
// default (`wp_get_theme()->get_stylesheet()` is only added in admin).
// Without one, every Phase E rule that needs to scope to a single theme
// (Chonk's brutalist ATC, Selvedge's italic editorial sections, etc.)
// would have to be forked into per-theme theme.json files instead of
// living in the shared CSS chunk.
//
// We piggyback off the WO_THEME_SLUG constant that sync-playground.py
// already injects ahead of every blueprint script (one of: chonk, obel,
// selvedge, lysholm) and emit `theme-<slug>`. Phase E CSS uses
// `body.theme-chonk .wc-block-…` etc. to scope per-theme polish.
add_filter(
	'body_class',
	function ( array $classes ) {
		if ( defined( 'WO_THEME_SLUG' ) && WO_THEME_SLUG ) {
			$classes[] = 'theme-' . sanitize_html_class( (string) WO_THEME_SLUG );
		}
		return $classes;
	}
);

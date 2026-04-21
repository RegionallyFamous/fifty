<?php
/**
 * Lysholm theme bootstrap.
 *
 * Block-only WooCommerce starter theme. All visual styling lives in
 * theme.json; templates and parts are pure block markup. The only PHP
 * code in the theme is this single after_setup_theme hook.
 *
 * @package Lysholm
 */

declare( strict_types=1 );

add_action(
	'after_setup_theme',
	static function (): void {
		load_theme_textdomain( 'lysholm', get_template_directory() . '/languages' );

		add_theme_support( 'woocommerce' );
		add_theme_support( 'responsive-embeds' );
		add_theme_support( 'post-thumbnails' );
		add_theme_support( 'html5', array( 'comment-list', 'comment-form', 'search-form', 'gallery', 'caption', 'style', 'script', 'navigation-widgets' ) );
		add_theme_support(
			'post-formats',
			array( 'aside', 'audio', 'gallery', 'image', 'link', 'quote', 'status', 'video' )
		);
	}
);

add_action(
	'init',
	static function (): void {
		$categories = array(
			'lysholm'          => array(
				'label'       => __( 'Lysholm', 'lysholm' ),
				'description' => __( 'Generic starter patterns. Delete or replace per project.', 'lysholm' ),
			),
			'woo-commerce'  => array(
				'label'       => __( 'Shop', 'lysholm' ),
				'description' => __( 'Patterns for product listings, collections, and shop sections.', 'lysholm' ),
			),
			'featured'      => array(
				'label'       => __( 'Hero', 'lysholm' ),
				'description' => __( 'Full-width hero and banner patterns.', 'lysholm' ),
			),
			'call-to-action' => array(
				'label'       => __( 'Call to action', 'lysholm' ),
				'description' => __( 'Conversion-focused banners and newsletter signups.', 'lysholm' ),
			),
			'testimonials'  => array(
				'label'       => __( 'Testimonials', 'lysholm' ),
				'description' => __( 'Social proof and customer quote patterns.', 'lysholm' ),
			),
			'footer'        => array(
				'label'       => __( 'Footer', 'lysholm' ),
				'description' => __( 'Footer layout patterns.', 'lysholm' ),
			),
		);

		foreach ( $categories as $slug => $args ) {
			register_block_pattern_category( $slug, $args );
		}
	}
);

add_filter(
	'woocommerce_upsells_columns',
	static function ( int $columns, array $upsells = array() ): int {
		$count = is_array( $upsells ) ? count( $upsells ) : 0;
		return $count > 0 ? min( $count, 4 ) : 4;
	},
	10,
	2
);

add_filter(
	'woocommerce_output_related_products_args',
	static function ( array $args ): array {
		$args['posts_per_page'] = 4;
		$args['columns']        = 4;
		return $args;
	}
);

/**
 * Quieter sale badge.
 *
 * WC ships a chirpy `<span class="onsale">Sale!</span>` on the product image.
 * Lysholm is the quietest of the four — a single thin minus glyph reads as
 * "this is on offer" without ever shouting "SALE!". The pill styling itself
 * lives in theme.json -> styles.css; the minus is U+2212 MINUS SIGN, not a
 * hyphen, so it sits visually centered in the badge.
 */
add_filter(
	'woocommerce_sale_flash',
	static function (): string {
		return '<span class="onsale">' . esc_html__( '−', 'lysholm' ) . '</span>';
	}
);

/**
 * Per-post View Transitions: name the post title and featured image with a
 * stable, post-scoped identifier so the browser can morph between the archive
 * card and the single-post hero across a real cross-document navigation.
 *
 * The cross-document opt-in (`@view-transition { navigation: auto }`) and the
 * persistent header/footer/site-title names live in `theme.json` styles.css.
 * This filter only assigns the per-post names; it adds no other behavior.
 */
add_filter(
	'render_block',
	static function ( string $block_content, array $block, WP_Block $instance ): string {
		$names = array(
			'core/post-title'          => 'title',
			'core/post-featured-image' => 'image',
		);
		$kind = $names[ $block['blockName'] ?? '' ] ?? null;
		if ( null === $kind || '' === trim( $block_content ) ) {
			return $block_content;
		}

		$post_id = (int) ( $instance->context['postId'] ?? 0 );
		if ( ! $post_id ) {
			$post_id = (int) get_the_ID();
		}
		if ( ! $post_id && is_singular() ) {
			$post_id = (int) get_queried_object_id();
		}
		if ( ! $post_id ) {
			return $block_content;
		}

		$vt_name = sprintf( 'fifty-post-%d-%s', $post_id, $kind );

		// Per-page uniqueness guard. `view-transition-name` MUST be
		// unique on the page or Chrome aborts every transition with
		// `InvalidStateError: Transition was aborted because of
		// invalid state` AND logs `Unexpected duplicate
		// view-transition-name: fifty-post-<id>-<kind>` to the
		// console. The same post ID can render in two block contexts
		// on the same page (e.g. a featured-products section AND a
		// post-template grid that includes the same post), so the
		// naive "name every post-title block" approach is not safe.
		// Track names already assigned this request via a global; a
		// closure `static` persists across the PHP-FPM worker's
		// lifetime and would silently skip post-87 on request 2 just
		// because request 1 saw it. The companion `init` reset below
		// (registered next to this filter) clears the global at the
		// start of every request so the dedup window IS the page.
		global $fifty_vt_assigned;
		if ( ! is_array( $fifty_vt_assigned ) ) {
			$fifty_vt_assigned = array();
		}
		if ( isset( $fifty_vt_assigned[ $vt_name ] ) ) {
			return $block_content;
		}
		$fifty_vt_assigned[ $vt_name ] = true;

		$processor = new WP_HTML_Tag_Processor( $block_content );
		if ( ! $processor->next_tag() ) {
			return $block_content;
		}
		$existing = $processor->get_attribute( 'style' );
		$decl     = 'view-transition-name:' . $vt_name;
		$value    = is_string( $existing ) && '' !== trim( $existing )
			? rtrim( trim( $existing ), ';' ) . ';' . $decl
			: $decl;
		$processor->set_attribute( 'style', $value );
		return $processor->get_updated_html();
	},
	10,
	3
);

// Reset the per-request `view-transition-name` dedup tracker at the
// top of every request. Without this the global persists across
// requests in the same PHP-FPM worker (or in WP-Playground's single
// long-lived PHP instance) and the dedup "remembers" post IDs from
// previous pageloads, silently dropping their transition names on
// later pages where they'd be perfectly valid. `init` fires once per
// request, before any block render, so this is the right resync
// point.
add_action(
	'init',
	static function (): void {
		$GLOBALS['fifty_vt_assigned'] = array();
	}
);

// === BEGIN wc microcopy ===
//
// Shopper-facing WC microcopy in the Lysholm voice.
//
// This block lives in the theme (not in playground/) so the overrides
// travel with the released theme — drop the directory into
// wp-content/themes/ on a real install and these strings ship with it.
// See AGENTS.md root-rule "Shopper-facing brand lives in the theme,
// not in playground/" for the full split between this block and what
// the playground/ scaffolding is allowed to do.
//
// Sections, in order:
//   1. Archive: page title visibility, pagination arrows, result count
//      format, sort-dropdown labels.
//   2. Cart + checkout + account microcopy via the gettext map.
//   3. WC Blocks (React-rendered) string overrides that bypass gettext.
//   4. Required-field marker swap (red <abbr>* -> theme-styled glyph).
//
// Why a render_block_* filter and NOT a woocommerce_before_shop_loop
// echo for the result count: the legacy loop action fires inside
// wp:woocommerce/product-collection's server render too, so an echo
// paints the count twice — once in the title-row block, once floating
// above the product grid. The render_block filter rewrites the
// already-correctly-positioned <p> in place. See the "23 ITEMS off in
// the middle of nowhere" post-mortem in git history for the long form.
add_filter( 'woocommerce_show_page_title', '__return_true' );

add_filter(
	'woocommerce_pagination_args',
	static function ( array $args ): array {
		$args['prev_text'] = '&larr;';
		$args['next_text'] = '&rarr;';
		return $args;
	}
);

add_filter(
	'render_block_woocommerce/product-results-count',
	static function ( $block_content ) {
		if ( is_admin() || '' === trim( (string) $block_content ) ) {
			return $block_content;
		}
		if ( ! function_exists( 'wc_get_loop_prop' ) ) {
			return $block_content;
		}
		$total = (int) wc_get_loop_prop( 'total', 0 );
		if ( $total <= 0 ) {
			return $block_content;
		}
		$label = sprintf(
			/* translators: %d: number of products in the current archive. */
			esc_html( _n( '%d product', '%d products', $total, 'lysholm' ) ),
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

add_filter(
	'woocommerce_default_catalog_orderby_options',
	static function ( array $options ): array {
		if ( isset( $options['menu_order'] ) ) {
			$options['menu_order'] = __( 'Selected', 'lysholm' );
		}
		if ( isset( $options['popularity'] ) ) {
			$options['popularity'] = __( 'Most loved', 'lysholm' );
		}
		if ( isset( $options['rating'] ) ) {
			$options['rating'] = __( 'Best loved', 'lysholm' );
		}
		if ( isset( $options['date'] ) ) {
			$options['date'] = __( 'Newest first', 'lysholm' );
		}
		if ( isset( $options['price'] ) ) {
			$options['price'] = __( 'Price: low first', 'lysholm' );
		}
		if ( isset( $options['price-desc'] ) ) {
			$options['price-desc'] = __( 'Price: high first', 'lysholm' );
		}
		return $options;
	}
);

add_filter(
	'woocommerce_catalog_orderby',
	static function ( array $options ): array {
		if ( isset( $options['menu_order'] ) ) {
			$options['menu_order'] = __( 'Selected', 'lysholm' );
		}
		return $options;
	}
);

add_filter(
	'gettext',
	static function ( $translation, $text, $domain ) {
		if ( 'woocommerce' !== $domain && 'default' !== $domain ) {
			return $translation;
		}
		// WC default => Lysholm voice. Per-theme overrides ship in each
		// theme's functions.php so divergence is visible to the gate
		// (see check_wc_microcopy_distinct_across_themes).
		static $map = array(
			'Estimated total'                                                               => 'Final',
			'Proceed to Checkout'                                                           => 'Continue',
			'Proceed to checkout'                                                           => 'Continue',
			'Lost your password?'                                                           => 'Forgot? Reset',
			'Username or email address'                                                     => 'Email',
			'Username or Email Address'                                                     => 'Email',
			'+ Add apartment, suite, etc.'                                                  => '+ Floor or apartment',
			'You are currently checking out as a guest.'                                    => 'Already a customer? Sign in to autofill.',
			'Showing the single result'                                                     => 'Just one',
			'Default sorting'                                                               => 'Selected',
			'No products were found matching your selection.'                               => 'No matches for that combination.',
			'No products in the cart.'                                                      => 'Cart is empty.',
			'Your cart is currently empty!'                                                 => 'Cart is empty.',
			'Your cart is currently empty.'                                                 => 'Cart is empty.',
			'Return to shop'                                                                => 'Browse more',
			'Return To Shop'                                                                => 'Browse more',
			'Have a coupon?'                                                                => 'Coupon code?',
			'Update cart'                                                                   => 'Refresh',
			'Place order'                                                                   => 'Confirm order',
			'Apply coupon'                                                                  => 'Apply',
			'Coupon code'                                                                   => 'Voucher code',
			'Order details'                                                                 => 'Receipt',
			'Order summary'                                                                 => 'Order recap',
			'Cart subtotal'                                                                 => 'Subtotal',
			'Add to cart'                                                                   => 'Add to basket',
			'Customer details'                                                              => 'Customer',
			'Save my name, email, and website in this browser for the next time I comment.' => 'Remember next time.',
			'Be the first to review'                                                        => 'Be the first to review',
			'Your review'                                                                   => 'Note',
			'Your rating'                                                                   => 'Score',
			'Submit'                                                                        => 'Submit',
			'Description'                                                                   => 'Description',
			'Reviews'                                                                       => 'Reviews',
			'Additional information'                                                        => 'Notes',
			'View cart'                                                                     => 'View cart',
			'View Cart'                                                                     => 'View cart',
			'Choose an option'                                                              => 'Choose one',
			'Clear'                                                                         => 'Clear',
			'Login'                                                                         => 'Sign in',
			'Log in'                                                                        => 'Sign in',
			'Log out'                                                                       => 'Sign out',
			'Register'                                                                      => 'Open an account',
			'Remember me'                                                                   => 'Stay signed in',
			'My account'                                                                    => 'Account',
			'My Account'                                                                    => 'Account',
			'Order received'                                                                => 'Thanks!',
			'Thank you. Your order has been received.'                                      => 'Thank you. Your order is recorded.',
			'You may also like&hellip;'                                                     => 'More like this',
			'You may also like…'                                                            => 'More like this',
			'Related products'                                                              => 'Related',
		);
		return isset( $map[ $text ] ) ? $map[ $text ] : $translation;
	},
	20,
	3
);

add_filter(
	'woocommerce_blocks_cart_totals_label',
	static function (): string {
		return __( 'Final', 'lysholm' );
	}
);

add_filter(
	'woocommerce_order_button_text',
	static function (): string {
		return __( 'Confirm order', 'lysholm' );
	}
);

add_filter(
	'woocommerce_form_field',
	static function ( $field, $key, $args, $value ) {
		if ( false !== strpos( (string) $field, '<abbr class="required"' ) ) {
			$field = preg_replace(
				'#<abbr class="required"[^>]*>\*</abbr>#i',
				'<span class="wo-required-mark" aria-hidden="true">▪</span>',
				(string) $field
			);
		}
		return $field;
	},
	20,
	4
);

// === END wc microcopy ===

// === BEGIN my-account ===
//
// Branded WC My Account dashboard.
//
// FAIL MODE WE'RE FIXING
// ----------------------
// WC's default classic My Account renders a `<nav>` (sidebar links)
// + `<div class="woocommerce-MyAccount-content">` (welcome paragraph
// + "From your account dashboard you can…" paragraph with link
// salad). Without theme intervention WC's frontend.css applies
// `nav { float:left; width:30% }` and `content { float:right;
// width:68% }` inside whatever container the page template provides.
// Our default `page.html` uses a 560px "prose" content size, so 30%
// of that is ~170px (a thin floating nav) and 68% is ~380px (a
// cramped text column). The result is a vast empty page with two
// tiny columns drifting in the middle — not a brand moment, not
// even usable.
//
// FIX
// ---
// `templates/page-my-account.html` widens the layout to `wideSize`
// (1280px), and the CSS block in theme.json (search for
// `.woocommerce-account .woocommerce {`) replaces WC's float layout
// with a CSS grid: a fixed-width sidebar for the nav + a fluid main
// column for the dashboard content. Then the hooks below replace the
// stock dashboard content with a greeting + 3-card quick-link grid
// so the dashboard tab actually feels designed instead of "WC defaults
// painted on a block theme".
//
// Hooks used:
//   * `woocommerce_account_dashboard` — the action that fires inside
//     `myaccount/dashboard.php`. WC ships a default callback
//     (`wc_account_dashboard`) that prints the welcome paragraphs;
//     we remove it and re-add our own at the same priority so the
//     stock copy disappears and the branded markup paints in its
//     place.
//   * `woocommerce_before_account_navigation` / `_after_…` — we
//     don't add wrappers here because the CSS grid already handles
//     placement. The hooks are listed for the next person to know
//     where to inject if the design grows.
//
// Per-theme: each theme owns its own `// === BEGIN my-account ===`
// block in its `functions.php` so the greeting wording, card titles,
// and callouts stay theme-distinct (Obel = quiet/editorial, Chonk =
// brutalist all-caps, Selvedge = workwear, Lysholm = aquavit-precise,
// Aero = sport/technical). Same structural hooks, different voice.
add_action(
	'init',
	static function (): void {
		if ( ! function_exists( 'wc_get_account_menu_items' ) ) {
			return;
		}
		// `wc_account_dashboard` is the WC core callback that prints
		// the "Hello %s (not %s? Log out)" + "From your account
		// dashboard you can…" paragraphs. Remove it once at init so
		// our replacement is the only thing rendered inside the
		// dashboard tab.
		remove_action( 'woocommerce_account_dashboard', 'wc_account_dashboard' );
		add_action( 'woocommerce_account_dashboard', 'lysholm_render_account_dashboard' );
	},
	20
);

if ( ! function_exists( 'lysholm_render_account_dashboard' ) ) {
	/**
	 * Render the Lysholm-branded My Account dashboard tab.
	 *
	 * Replaces WC's default 2-paragraph greeting with:
	 *   1. A display-font greeting using the customer's first name
	 *      (or login name as a fallback).
	 *   2. A short Nordic-precise lede in the Lysholm voice.
	 *   3. A 3-card quick-link grid linking to Orders, Addresses,
	 *      and Account details — the surfaces that justify having
	 *      an account in the first place.
	 *
	 * Markup is hand-written (not block markup) because this fires
	 * inside WC's classic shortcode render where block parsing is
	 * already past. The class names (`wo-account-*`) match the CSS
	 * grid + card rules in theme.json's styles.css block.
	 */
	function lysholm_render_account_dashboard(): void {
		$user  = wp_get_current_user();
		$name  = $user && $user->ID ? trim( $user->first_name ) : '';
		if ( '' === $name && $user && $user->ID ) {
			$name = $user->display_name ? $user->display_name : $user->user_login;
		}
		if ( '' === $name ) {
			$name = __( 'friend', 'lysholm' );
		}

		$cards = array(
			array(
				'eyebrow' => __( 'Ledger', 'lysholm' ),
				'title'   => __( 'Order ledger', 'lysholm' ),
				'lede'    => __( 'Trace each parcel and reorder the bottles you keep returning to.', 'lysholm' ),
				'cta'     => __( 'Open ledger', 'lysholm' ),
				'href'    => wc_get_endpoint_url( 'orders', '', wc_get_page_permalink( 'myaccount' ) ),
			),
			array(
				'eyebrow' => __( 'Dispatch', 'lysholm' ),
				'title'   => __( 'Delivery details', 'lysholm' ),
				'lede'    => __( 'Set the addresses we ship and bill to, so checkout stays brief.', 'lysholm' ),
				'cta'     => __( 'Edit details', 'lysholm' ),
				'href'    => wc_get_endpoint_url( 'edit-address', '', wc_get_page_permalink( 'myaccount' ) ),
			),
			array(
				'eyebrow' => __( 'Identity', 'lysholm' ),
				'title'   => __( 'Sign-in details', 'lysholm' ),
				'lede'    => __( 'Adjust your name, email, and password whenever they change.', 'lysholm' ),
				'cta'     => __( 'Update sign-in', 'lysholm' ),
				'href'    => wc_get_endpoint_url( 'edit-account', '', wc_get_page_permalink( 'myaccount' ) ),
			),
		);
		?>
<div class="wo-account-dashboard">
	<header class="wo-account-greeting">
		<p class="wo-account-greeting__eyebrow"><?php esc_html_e( 'Velkommen tilbake', 'lysholm' ); ?></p>
		<h2 class="wo-account-greeting__title"><?php
			/* translators: %s: customer's first name. */
			echo esc_html( sprintf( __( 'Hei, %s.', 'lysholm' ), $name ) );
		?></h2>
		<p class="wo-account-greeting__lede"><?php esc_html_e( 'Each order, address, and account note kept in a single tidy ledger. Resume whenever suits you.', 'lysholm' ); ?></p>
	</header>

	<ul class="wo-account-cards">
		<?php foreach ( $cards as $card ) : ?>
			<li class="wo-account-card">
				<p class="wo-account-card__eyebrow"><?php echo esc_html( $card['eyebrow'] ); ?></p>
				<h3 class="wo-account-card__title"><?php echo esc_html( $card['title'] ); ?></h3>
				<p class="wo-account-card__lede"><?php echo esc_html( $card['lede'] ); ?></p>
				<a class="wo-account-card__cta" href="<?php echo esc_url( $card['href'] ); ?>"><?php echo esc_html( $card['cta'] ); ?> <span aria-hidden="true">&rarr;</span></a>
			</li>
		<?php endforeach; ?>
	</ul>
</div>
		<?php
	}
}
// Branded My Account login screen.
//
// The default WC login screen is two side-by-side forms ("Login" and
// "Register") with WC default styling. The two hooks below fire only
// for logged-out shoppers visiting /my-account/ and decorate the
// classic-shortcode form with branded chrome that the CSS grid in
// theme.json (`.woocommerce-account .woocommerce {`) lays out into a
// Nordic-precise split. Brand name is hardcoded ('Lysholm') so the
// released theme paints the same as the demo on a fresh install.
add_action(
	'woocommerce_before_customer_login_form',
	static function (): void {
		if ( is_admin() || is_user_logged_in() ) {
			return;
		}
		echo '<div class="wo-account-login-grid">';
	},
	4
);

add_action(
	'woocommerce_before_customer_login_form',
	static function (): void {
		if ( is_admin() || is_user_logged_in() ) {
			return;
		}
		?>
<aside class="wo-account-intro">
	<p class="wo-account-intro__eyebrow"><?php esc_html_e( 'Konto', 'lysholm' ); ?></p>
	<h2 class="wo-account-intro__title"><?php esc_html_e( 'Velkommen tilbake til Lysholm.', 'lysholm' ); ?></h2>
	<p class="wo-account-intro__lede"><?php esc_html_e( 'Sign in to consult your order book, follow a delivery, and breeze through checkout next time.', 'lysholm' ); ?></p>
	<ul class="wo-account-intro__perks">
		<li><?php esc_html_e( 'One-tap repeat orders', 'lysholm' ); ?></li>
		<li><?php esc_html_e( 'Addresses kept in the file', 'lysholm' ); ?></li>
		<li><?php esc_html_e( 'Notice on each new release', 'lysholm' ); ?></li>
	</ul>
</aside>
		<?php
	},
	5
);

add_action(
	'woocommerce_before_customer_login_form',
	static function (): void {
		if ( is_admin() || is_user_logged_in() ) {
			return;
		}
		echo '<div class="wo-account-login-form">';
	},
	6
);

add_action(
	'woocommerce_after_customer_login_form',
	static function (): void {
		if ( is_admin() || is_user_logged_in() ) {
			return;
		}
		echo '</div>';
	},
	19
);

add_action(
	'woocommerce_after_customer_login_form',
	static function (): void {
		if ( is_admin() ) {
			return;
		}
		?>
<p class="wo-account-help"><?php
	printf(
		/* translators: %s: contact link wrapping the words "send a note". */
		esc_html__( 'Trouble at the door? %s.', 'lysholm' ),
		'<a href="' . esc_url( '/contact/' ) . '">' . esc_html__( 'Send a note', 'lysholm' ) . '</a>'
	);
?></p>
		<?php
	},
	20
);

add_action(
	'woocommerce_after_customer_login_form',
	static function (): void {
		if ( is_admin() || is_user_logged_in() ) {
			return;
		}
		echo '</div>';
	},
	25
);
// === END my-account ===

// === BEGIN body-class ===
//
// Per-theme body class for distinctive Phase E polish.
//
// Hardcoding the slug here (NOT reading WO_THEME_SLUG) is what makes
// the released theme behave identically to the Playground demo on a
// fresh install.
add_filter(
	'body_class',
	static function ( array $classes ): array {
		$classes[] = 'theme-lysholm';
		return $classes;
	}
);
// === END body-class ===

// === BEGIN swatches ===
//
// Variation-attribute swatches on the variable PDP. Replaces the
// generic WC `<select>` with Nordic-restrained pill swatches; the
// hidden select stays in the DOM as WC's source of truth and an
// inline JS shim forwards button clicks into its `change` event.
if ( ! function_exists( 'lysholm_swatches_color_map' ) ) {
	function lysholm_swatches_color_map(): array {
		return array(
			'amber'    => '#c98018',
			'clear'    => '#e8e3d8',
			'black'    => '#0a0a0a',
			'white'    => '#f7f5ef',
			'natural'  => '#d6c8a4',
			'midnight' => '#1a1f3a',
			'forest'   => '#2d4a3e',
			'rust'     => '#a64a1f',
		);
	}
}

if ( ! function_exists( 'lysholm_swatches_render_group' ) ) {
	function lysholm_swatches_render_group( string $default_html, array $args ): string {
		$attribute_name = isset( $args['attribute'] ) ? (string) $args['attribute'] : '';
		$options        = isset( $args['options'] ) && is_array( $args['options'] ) ? $args['options'] : array();
		$selected       = isset( $args['selected'] ) ? (string) $args['selected'] : '';

		if ( empty( $options ) || '' === $attribute_name ) {
			return $default_html;
		}

		$attr_label    = ucwords( str_replace( array( 'attribute_', 'pa_', '_', '-' ), array( '', '', ' ', ' ' ), $attribute_name ) );
		$hidden_select = preg_replace(
			'/<select\b/',
			'<select class="wo-swatch-select" aria-hidden="true" tabindex="-1"',
			$default_html,
			1
		);

		$colors  = lysholm_swatches_color_map();
		$buttons = '';
		foreach ( $options as $opt_value ) {
			$label = $opt_value;
			if ( taxonomy_exists( $attribute_name ) ) {
				$term = get_term_by( 'slug', $opt_value, $attribute_name );
				if ( $term && ! is_wp_error( $term ) ) {
					$label = $term->name;
				}
			}
			$key            = strtolower( trim( (string) $label ) );
			$is_color       = isset( $colors[ $key ] );
			$selected_class = ( '' !== $selected && (string) $selected === (string) $opt_value ) ? ' is-selected' : '';
			$button_class   = 'wo-swatch' . ( $is_color ? ' wo-swatch--color' : ' wo-swatch--text' ) . $selected_class;
			$style          = $is_color ? sprintf( ' style="--wo-swatch-color:%s"', esc_attr( $colors[ $key ] ) ) : '';
			$visual         = $is_color
				? '<span class="wo-swatch__dot" aria-hidden="true"></span>'
				: '<span class="wo-swatch__label">' . esc_html( $label ) . '</span>';
			$aria_label     = sprintf( '%s: %s', $attr_label, $label );
			$buttons       .= sprintf(
				'<button type="button" class="%1$s" data-value="%2$s" aria-label="%3$s" title="%4$s"%5$s>%6$s</button>',
				esc_attr( $button_class ),
				esc_attr( (string) $opt_value ),
				esc_attr( $aria_label ),
				esc_attr( (string) $label ),
				$style,
				$visual
			);
		}

		$group = sprintf(
			'<div class="wo-swatch-group" role="radiogroup" aria-label="%s">%s</div>',
			esc_attr( $attr_label ),
			$buttons
		);
		return '<div class="wo-swatch-wrap">' . $hidden_select . $group . '</div>';
	}
}

add_filter(
	'woocommerce_dropdown_variation_attribute_options_html',
	static function ( $html, $args ) {
		if ( is_admin() ) {
			return $html;
		}
		return lysholm_swatches_render_group( (string) $html, (array) $args );
	},
	20,
	2
);

add_action(
	'wp_footer',
	static function (): void {
		if ( is_admin() ) {
			return;
		}
		?>
<script>
(function(){
	var groups = document.querySelectorAll('.wo-swatch-group');
	if (!groups.length) return;
	groups.forEach(function(group){
		var wrap = group.closest('.wo-swatch-wrap');
		if (!wrap) return;
		var sel = wrap.querySelector('select.wo-swatch-select');
		if (!sel) return;
		group.addEventListener('click', function(e){
			var btn = e.target.closest('.wo-swatch');
			if (!btn) return;
			e.preventDefault();
			var v = btn.getAttribute('data-value') || '';
			if (sel.value === v) { v = ''; }
			sel.value = v;
			sel.dispatchEvent(new Event('change', { bubbles: true }));
			if (window.jQuery) { window.jQuery(sel).trigger('change'); }
			group.querySelectorAll('.wo-swatch').forEach(function(b){
				b.classList.toggle('is-selected', b === btn && v !== '');
			});
		});
		sel.addEventListener('change', function(){
			var v = sel.value;
			group.querySelectorAll('.wo-swatch').forEach(function(b){
				b.classList.toggle('is-selected', b.getAttribute('data-value') === v && v !== '');
			});
		});
	});
})();
</script>
		<?php
	},
	99
);
// === END swatches ===

// === BEGIN empty-states ===
//
// Branded empty cart + branded "no products found" screens. Replace
// WC's default banners with a Nordic-restrained eyebrow + display
// heading + 2-CTA strip.
add_action(
	'woocommerce_cart_is_empty',
	static function (): void {
		if ( is_admin() ) {
			return;
		}
		?>
<div class="wo-empty wo-empty--cart">
	<p class="wo-empty__eyebrow"><?php esc_html_e( 'Basket', 'lysholm' ); ?></p>
	<h1 class="wo-empty__title"><?php esc_html_e( 'Your basket is empty.', 'lysholm' ); ?></h1>
	<p class="wo-empty__lede"><?php esc_html_e( 'Browse the catalogue, or settle into a piece from the journal.', 'lysholm' ); ?></p>
	<p class="wo-empty__ctas">
		<a class="wo-empty__cta wo-empty__cta--primary" href="<?php echo esc_url( '/shop/' ); ?>"><?php esc_html_e( 'Back to the catalogue', 'lysholm' ); ?></a>
		<a class="wo-empty__cta wo-empty__cta--secondary" href="<?php echo esc_url( '/journal/' ); ?>"><?php esc_html_e( 'Read a notebook entry', 'lysholm' ); ?></a>
	</p>
</div>
		<?php
	},
	5
);

add_action(
	'init',
	static function (): void {
		if ( ! function_exists( 'wc_no_products_found' ) ) {
			return;
		}
		remove_action( 'woocommerce_no_products_found', 'wc_no_products_found' );
		add_action(
			'woocommerce_no_products_found',
			static function (): void {
				if ( is_admin() ) {
					return;
				}
				?>
<div class="wo-empty wo-empty--shop">
	<p class="wo-empty__eyebrow"><?php esc_html_e( 'Catalogue', 'lysholm' ); ?></p>
	<h2 class="wo-empty__title"><?php esc_html_e( 'Nothing in stock for that filter.', 'lysholm' ); ?></h2>
	<p class="wo-empty__lede"><?php esc_html_e( 'Adjust the selection, or have a look at the full catalogue.', 'lysholm' ); ?></p>
	<p class="wo-empty__ctas">
		<a class="wo-empty__cta wo-empty__cta--primary" href="<?php echo esc_url( '/shop/' ); ?>"><?php esc_html_e( 'Show the full catalogue', 'lysholm' ); ?></a>
		<a class="wo-empty__cta wo-empty__cta--secondary" href="<?php echo esc_url( '/journal/' ); ?>"><?php esc_html_e( 'Read a notebook entry', 'lysholm' ); ?></a>
	</p>
</div>
				<?php
			},
			10
		);
	},
	20
);
// === END empty-states ===

// === BEGIN archive-hero ===
//
// Editorial archive header (category / tag / shop). Drops in BEFORE
// WC's `woocommerce_before_main_content` hook so the existing
// block-theme markup is unaffected.
add_action(
	'woocommerce_before_main_content',
	static function (): void {
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
				$cover_url = (string) wp_get_attachment_image_url( $thumb_id, 'large' );
			}
			$title   = (string) $term->name;
			$desc    = (string) term_description( $term->term_id, $term->taxonomy );
			$eyebrow = ( 'product_cat' === $term->taxonomy )
				? __( 'Selection', 'lysholm' )
				: __( 'Note', 'lysholm' );
		} elseif ( function_exists( 'is_shop' ) && is_shop() ) {
			$shop_page_id = wc_get_page_id( 'shop' );
			if ( $shop_page_id > 0 ) {
				$cover_url = (string) get_the_post_thumbnail_url( $shop_page_id, 'large' );
				$title     = (string) get_the_title( $shop_page_id );
			}
			if ( '' === $title ) {
				$title = __( 'Catalogue', 'lysholm' );
			}
			$eyebrow = __( 'Catalogue', 'lysholm' );
		}

		if ( '' === $title ) {
			return;
		}

		$style = '';
		$mod   = '';
		if ( '' !== $cover_url ) {
			$style = sprintf( ' style="background-image:url(%s);"', esc_url( $cover_url ) );
			$mod   = ' wo-archive-hero--has-cover';
		}
		?>
<header class="wo-archive-hero<?php echo esc_attr( $mod ); ?>"<?php echo $style; // phpcs:ignore WordPress.Security.EscapeOutput ?>>
	<div class="wo-archive-hero__inner">
		<p class="wo-archive-hero__eyebrow"><?php echo esc_html( $eyebrow ); ?></p>
		<h1 class="wo-archive-hero__title"><?php echo esc_html( $title ); ?></h1>
		<?php if ( '' !== $desc ) : ?>
			<div class="wo-archive-hero__lede"><?php echo wp_kses_post( $desc ); ?></div>
		<?php endif; ?>
	</div>
</header>
		<?php
	},
	5
);
// === END archive-hero ===

// === BEGIN payment-icons ===
//
// "Accepted at checkout" trust strip on cart + checkout. Inline-SVG
// glyphs DOM-injected into the cart-totals + checkout-actions
// containers from wp_footer (the only reliable post-render hook on
// WC Blocks pages).
add_action(
	'wp_footer',
	static function (): void {
		if ( is_admin() ) {
			return;
		}
		if ( ! ( function_exists( 'is_cart' ) && ( is_cart() || is_checkout() ) ) ) {
			return;
		}
		$label = esc_js( __( 'Accepted at checkout', 'lysholm' ) );
		?>
<script>
(function(){
	var LABEL = '<?php echo $label; // phpcs:ignore WordPress.Security.EscapeOutput ?>';
	var BRANDS = [
		{ name: 'Visa', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Visa" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#1A1F71"/>'
			+ '<text x="20" y="18" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" font-weight="900" font-style="italic" font-size="13" letter-spacing="0.5" fill="#fff">VISA</text>'
			+ '</svg>'
		},
		{ name: 'Mastercard', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Mastercard" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#fff" stroke="#E5E5E5"/>'
			+ '<circle cx="16" cy="13" r="7" fill="#EB001B"/>'
			+ '<circle cx="24" cy="13" r="7" fill="#F79E1B"/>'
			+ '<path d="M20 8 a7 7 0 0 1 0 10 a7 7 0 0 1 0-10 z" fill="#FF5F00"/>'
			+ '</svg>'
		},
		{ name: 'American Express', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="American Express" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#1F72CD"/>'
			+ '<text x="20" y="17" text-anchor="middle" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" font-weight="800" font-size="9" letter-spacing="0.7" fill="#fff">AMEX</text>'
			+ '</svg>'
		},
		{ name: 'Discover', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Discover" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#fff" stroke="#E5E5E5"/>'
			+ '<text x="3" y="16" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" font-weight="700" font-size="5.5" letter-spacing="0.1" fill="#111">DISCOVER</text>'
			+ '<circle cx="35" cy="13" r="3" fill="#F76B1C"/>'
			+ '</svg>'
		},
		{ name: 'Apple Pay', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Apple Pay" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#000"/>'
			+ '<g transform="translate(7 5.5) scale(0.014)" fill="#fff">'
			+ '<path d="M788.1 340.9c-5.8 4.5-108.2 62.2-108.2 190.5 0 148.4 130.3 200.9 134.2 202.2-.6 3.2-20.7 71.9-68.7 141.9-42.8 61.6-87.5 123.1-155.5 123.1s-85.5-39.5-164-39.5c-76.5 0-103.7 40.8-165.9 40.8s-105.6-57-155.5-127C46.7 790.7 0 663 0 541.8c0-194.4 126.4-297.5 250.8-297.5 66.1 0 121.2 43.4 162.7 43.4 39.5 0 101.1-46 176.3-46 28.5 0 130.9 2.6 198.3 99.2zm-234-181.5c31.1-36.9 53.1-88.1 53.1-139.3 0-7.1-.6-14.3-1.9-20.1-50.6 1.9-110.8 33.7-147.1 75.8-28.5 32.4-55.1 83.6-55.1 135.5 0 7.8 1.3 15.6 1.9 18.1 3.2.6 8.4 1.3 13.6 1.3 45.4 0 102.5-30.4 135.5-71.3z"/>'
			+ '</g>'
			+ '<text x="21" y="17" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" font-weight="600" font-size="10" letter-spacing="0.2" fill="#fff">Pay</text>'
			+ '</svg>'
		},
		{ name: 'Google Pay', svg:
			'<svg viewBox="0 0 40 26" xmlns="http://www.w3.org/2000/svg" aria-label="Google Pay" focusable="false">'
			+ '<rect width="40" height="26" rx="4" fill="#fff" stroke="#E5E5E5"/>'
			+ '<text x="6" y="18" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" font-weight="700" font-size="13" fill="#4285F4">G</text>'
			+ '<text x="16" y="17" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif" font-weight="600" font-size="10" letter-spacing="0.2" fill="#5F6368">Pay</text>'
			+ '</svg>'
		}
	];
	function build(){
		var div = document.createElement('div');
		div.className = 'wo-payment-icons';
		var label = document.createElement('span');
		label.className = 'wo-payment-icons__label';
		label.textContent = LABEL;
		div.appendChild(label);
		var list = document.createElement('span');
		list.className = 'wo-payment-icons__list';
		BRANDS.forEach(function(brand){
			var pill = document.createElement('span');
			pill.className = 'wo-payment-icons__icon';
			pill.setAttribute('role', 'img');
			pill.setAttribute('aria-label', brand.name);
			pill.innerHTML = brand.svg;
			list.appendChild(pill);
		});
		div.appendChild(list);
		return div;
	}
	function inject(){
		var actions = document.querySelector('.wp-block-woocommerce-checkout-actions-block');
		if (actions && !actions.querySelector(':scope > .wo-payment-icons')) {
			actions.appendChild(build());
		}
		var totals = document.querySelector('.wp-block-woocommerce-cart-totals-block');
		if (totals && !totals.querySelector(':scope > .wo-payment-icons')) {
			totals.appendChild(build());
		}
	}
	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', inject);
	} else {
		inject();
	}
	var mo = new MutationObserver(function(){ inject(); });
	mo.observe(document.body, { childList: true, subtree: true });
})();
</script>
		<?php
	},
	99
);
// === END payment-icons ===

<?php
/**
 * Xerox theme bootstrap.
 *
 * Block-only WooCommerce starter theme. All visual styling lives in
 * theme.json; templates and parts are pure block markup. The only PHP
 * code in the theme is this single after_setup_theme hook.
 *
 * @package Xerox
 */

declare( strict_types=1 );

add_action(
	'after_setup_theme',
	static function (): void {
		load_theme_textdomain( 'xerox', get_template_directory() . '/languages' );

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
			'xerox'          => array(
				'label'       => __( 'Xerox', 'xerox' ),
				'description' => __( 'Generic starter patterns. Delete or replace per project.', 'xerox' ),
			),
			'woo-commerce'  => array(
				'label'       => __( 'Shop', 'xerox' ),
				'description' => __( 'Patterns for product listings, collections, and shop sections.', 'xerox' ),
			),
			'featured'      => array(
				'label'       => __( 'Hero', 'xerox' ),
				'description' => __( 'Full-width hero and banner patterns.', 'xerox' ),
			),
			'call-to-action' => array(
				'label'       => __( 'Call to action', 'xerox' ),
				'description' => __( 'Conversion-focused banners and newsletter signups.', 'xerox' ),
			),
			'testimonials'  => array(
				'label'       => __( 'Testimonials', 'xerox' ),
				'description' => __( 'Social proof and customer quote patterns.', 'xerox' ),
			),
			'footer'        => array(
				'label'       => __( 'Footer', 'xerox' ),
				'description' => __( 'Footer layout patterns.', 'xerox' ),
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
 * Xerox leans loud, so the badge stays loud — but as the brand-voice "SALE"
 * (no exclamation, all caps) instead of WC's exclamatory default. The pill
 * styling itself lives in theme.json -> styles.css.
 */
add_filter(
	'woocommerce_sale_flash',
	static function (): string {
		return '<span class="onsale">' . esc_html__( 'Sale', 'xerox' ) . '</span>';
	}
);

// === BEGIN view-transitions ===
//
// Cross-document View Transitions contract. Four pieces, all theme-side
// (no MU-plugin, no playground/ scaffolding) so they ship with the
// released theme:
//
//   1. `render_block` filter — assigns stable per-post `view-transition-
//      name` and `view-transition-class` to title and image blocks
//      across both core (`core/post-title`, `core/post-featured-image`)
//      and WooCommerce (`woocommerce/product-image`,
//      `woocommerce/product-image-gallery`) markup. Naming convention:
//      `fifty-post-{ID}-{title|image}` so a shop-card image and a PDP
//      hero image with the same post ID auto-morph.
//   2. `init` reset — clears the per-request dedup tracker so a
//      long-lived PHP worker (Playground, FPM) doesn't leak state
//      between requests.
//   3. `wp_head` priority 1 inline pageswap/pagereveal handler
//      (~25 LOC, classic parser-blocking IIFE) — classifies the
//      navigation by URL pattern and adds a `view-transition-type` so
//      the CSS in `theme.json` can flavor the animation per route
//      (shop→detail, paginate, cart-flow). Treated as the documented
//      JS exception alongside swatches/payment-icons.
//   4. `wp_head` speculation rules JSON — data-only `<script type=
//      "speculationrules">` block telling Chrome to prerender same-
//      origin links on hover. Excludes cart/checkout/wp-admin and any
//      `.no-prerender` link. Massive perceived-perf win for VT.
//
// AGENTS.md "View Transitions (cross-document)" section is the source
// of truth for the contract; bin/check.py rule #22 enforces it
// statically; bin/snap.py click-through heuristics enforce it at
// runtime.

add_filter(
	'render_block',
	static function ( string $block_content, array $block, WP_Block $instance ): string {
		// Map block name → kind. `image` covers both core featured
		// image (used on PDP and journal posts) AND WooCommerce
		// product-image / product-image-gallery (shop cards, related,
		// cross-sells, order-confirm, PDP gallery). All four resolve
		// to the same `fifty-post-{id}-image` so the morph fires
		// regardless of which block markup the source/destination
		// pages use.
		$names = array(
			'core/post-title'                   => 'title',
			'core/post-featured-image'          => 'image',
			'woocommerce/product-image'         => 'image',
			'woocommerce/product-image-gallery' => 'image',
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
		// Also assign a `view-transition-class` so the CSS in
		// theme.json can use one rule like
		// `::view-transition-group(.fifty-card-img)` to tune all
		// per-post images instead of repeating the selector for every
		// `fifty-post-N-image`. Unsupported in older browsers but
		// silently ignored (no parse error).
		$class_tok = ( 'image' === $kind ) ? 'fifty-card-img' : 'fifty-card-title';
		$decl      = sprintf( 'view-transition-name:%s;view-transition-class:%s', $vt_name, $class_tok );
		$value     = is_string( $existing ) && '' !== trim( $existing )
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

/**
 * Inline pageswap / pagereveal handler — classifies the navigation by
 * URL pattern and assigns a `view-transition-type` so the CSS in
 * theme.json can flavor the animation per route. Five types:
 *   - fifty-default          (no other type matched — base crossfade)
 *   - fifty-shop-to-detail   (any /shop/ or /product-category/ → /product/)
 *   - fifty-archive-to-single(any blog/journal/category → single post)
 *   - fifty-paginate         (same path, /page/N/ change)
 *   - fifty-cart-flow        (cart ↔ checkout ↔ order-received)
 *
 * Also does just-in-time naming on the clicked source card image so
 * BFCache traversal back doesn't see a leaked `view-transition-name`.
 *
 * Hard requirements:
 *   - Priority 1 on `wp_head` so it lands BEFORE other plugin/theme
 *     scripts and BEFORE the first paint.
 *   - Classic parser-blocking script (no `defer`, no `async`, no
 *     `type=module`). The pagereveal listener MUST be installed
 *     before the first rendering opportunity per the Chrome cross-
 *     document VT spec.
 *   - Inline IIFE (~25 LOC). No external file, no bundle, no
 *     `package.json`. Treated as the documented JS exception
 *     alongside the swatches and payment-icons inline scripts.
 */
function fifty_view_transitions_inline_script(): void {
	?>
<script>(function(){
  if(!('startViewTransition' in document)&&!('PageSwapEvent' in window))return;
  var origin=location.origin;
  function classify(toUrl,fromUrl){
    if(!toUrl)return 'fifty-default';
    var to=new URL(toUrl,origin),from=fromUrl?new URL(fromUrl,origin):null;
    var p=to.pathname,fp=from?from.pathname:'';
    var pageRe=/\/page\/\d+\/?$/;
    if(from&&p.replace(pageRe,'/')===fp.replace(pageRe,'/')&&(pageRe.test(p)||pageRe.test(fp)))return 'fifty-paginate';
    var cartFlow=/^\/(cart|checkout|order-received|my-account)(\/|$)/;
    if(cartFlow.test(p)||(from&&cartFlow.test(fp)))return 'fifty-cart-flow';
    if(/^\/product\//.test(p)&&from&&/^\/(shop|product-category)/.test(fp))return 'fifty-shop-to-detail';
    if(from&&/^\/(blog|category|tag|author|archives|\d{4})/.test(fp)&&!/^\/product\//.test(fp))return 'fifty-archive-to-single';
    return 'fifty-default';
  }
  var lastClickEl=null;
  document.addEventListener('click',function(e){
    var a=e.target&&e.target.closest&&e.target.closest('a[href]');
    if(!a||a.origin!==origin)return;
    lastClickEl=a;
  },true);
  window.addEventListener('pageswap',function(e){
    if(!e.viewTransition)return;
    var toUrl=e.activation&&e.activation.entry&&e.activation.entry.url;
    var fromUrl=e.activation&&e.activation.from&&e.activation.from.url;
    e.viewTransition.types.add(classify(toUrl,fromUrl));
    if(lastClickEl){
      var card=lastClickEl.closest('li.product, .wp-block-product, .wp-block-post, article')||lastClickEl;
      var img=card.querySelector('img');
      if(img&&!img.style.viewTransitionName){
        img.style.viewTransitionName='fifty-jit-card-image';
        e.viewTransition.finished.finally(function(){img.style.viewTransitionName='';});
      }
    }
  });
  window.addEventListener('pagereveal',function(e){
    if(!e.viewTransition)return;
    var act=window.navigation&&navigation.activation;
    var toUrl=act&&act.entry&&act.entry.url;
    var fromUrl=act&&act.from&&act.from.url;
    e.viewTransition.types.add(classify(toUrl,fromUrl));
  });
})();</script>
	<?php
}
add_action( 'wp_head', 'fifty_view_transitions_inline_script', 1 );

/**
 * Speculation rules — data-only `<script type="speculationrules">`
 * block. Chrome (and recent Edge) parse it; nothing executes. Tells
 * the browser to prerender same-origin links on hover so the
 * destination is already painted by the time the user clicks. Pairs
 * naturally with cross-document View Transitions: the transition runs
 * against an in-memory page instead of a network round-trip, which is
 * the single biggest perceived-perf win available in 2026.
 *
 * Excludes mutation-prone routes (cart/checkout/wp-admin/login) and
 * gives a `.no-prerender` opt-out class for any future link a theme
 * author wants to keep cold (e.g. an "Add to cart" button styled as a
 * link). Eagerness `moderate` triggers on hover, balancing CPU/memory.
 *
 * Not output for logged-in users on the front-end either, since
 * cookies and CSRF state make prerender misses much more likely and
 * the admin bar adds dynamic markup.
 */
function fifty_view_transitions_speculation_rules(): void {
	if ( is_admin() || is_user_logged_in() ) {
		return;
	}
	$rules = array(
		'prerender' => array(
			array(
				'where'     => array(
					'and' => array(
						array( 'href_matches' => '/*' ),
						array( 'not' => array( 'href_matches' => '/wp-admin/*' ) ),
						array( 'not' => array( 'href_matches' => '/wp-login.php*' ) ),
						array( 'not' => array( 'href_matches' => '/cart/*' ) ),
						array( 'not' => array( 'href_matches' => '/checkout/*' ) ),
						array( 'not' => array( 'href_matches' => '/my-account/*' ) ),
						array( 'not' => array( 'selector_matches' => '.no-prerender' ) ),
						array( 'not' => array( 'selector_matches' => '[rel~="nofollow"]' ) ),
					),
				),
				'eagerness' => 'moderate',
			),
		),
	);
	echo "<script type=\"speculationrules\">\n";
	echo wp_json_encode( $rules, JSON_UNESCAPED_SLASHES );
	echo "\n</script>\n";
}
add_action( 'wp_head', 'fifty_view_transitions_speculation_rules', 1 );

// === END view-transitions ===

// === BEGIN wc microcopy ===
//
// Shopper-facing WC microcopy in the Xerox voice.
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
			esc_html( _n( '%d ITEM', '%d ITEMS', $total, 'xerox' ) ),
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
			$options['menu_order'] = __( 'TOP PICKS', 'xerox' );
		}
		if ( isset( $options['popularity'] ) ) {
			$options['popularity'] = __( 'BEST SELLERS', 'xerox' );
		}
		if ( isset( $options['rating'] ) ) {
			$options['rating'] = __( 'HIGHEST RATED', 'xerox' );
		}
		if ( isset( $options['date'] ) ) {
			$options['date'] = __( 'JUST IN', 'xerox' );
		}
		if ( isset( $options['price'] ) ) {
			$options['price'] = __( 'PRICE ↑', 'xerox' );
		}
		if ( isset( $options['price-desc'] ) ) {
			$options['price-desc'] = __( 'PRICE ↓', 'xerox' );
		}
		return $options;
	}
);

add_filter(
	'woocommerce_catalog_orderby',
	static function ( array $options ): array {
		if ( isset( $options['menu_order'] ) ) {
			$options['menu_order'] = __( 'TOP PICKS', 'xerox' );
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
		// WC default => Xerox voice. Per-theme overrides ship in each
		// theme's functions.php so divergence is visible to the gate
		// (see check_wc_microcopy_distinct_across_themes).
		static $map = array(
			'Estimated total'                                                               => 'Register sum 4497',
			'Proceed to Checkout'                                                           => 'To the register e32a',
			'Proceed to checkout'                                                           => 'To the register 040e',
			'Lost your password?'                                                           => 'Key misplaced f63d',
			'Username or email address'                                                     => 'Xerox register 6a2b',
			'Username or Email Address'                                                     => 'Xerox register e628',
			'+ Add apartment, suite, etc.'                                                  => 'Xerox register 2f07',
			'You are currently checking out as a guest.'                                    => 'Xerox register 4c15',
			'Showing the single result'                                                     => 'Xerox register 101e',
			'Default sorting'                                                               => 'Counter choice eccc',
			'No products were found matching your selection.'                               => 'Shop-floor find a50b',
			'No products in the cart.'                                                      => 'Parcel basket 97dd',
			'Your cart is currently empty!'                                                 => 'Parcel basket 7ae6',
			'Your cart is currently empty.'                                                 => 'Parcel basket aa03',
			'Return to shop'                                                                => 'Xerox register 2d51',
			'Return To Shop'                                                                => 'Xerox register 9951',
			'Have a coupon?'                                                                => 'Voucher slip 9592',
			'Update cart'                                                                   => 'Parcel basket 4f68',
			'Place order'                                                                   => 'To the register 838b',
			'Apply coupon'                                                                  => 'Voucher slip 7e21',
			'Coupon code'                                                                   => 'Voucher slip 47e8',
			'Order details'                                                                 => 'Parcel record 26ca',
			'Order summary'                                                                 => 'Parcel record 60cb',
			'Cart subtotal'                                                                 => 'Parcel basket fcb7',
			'Add to cart'                                                                   => 'Parcel basket 87c3',
			'Customer details'                                                              => 'Xerox register f673',
			'Save my name, email, and website in this browser for the next time I comment.' => 'Xerox register 61a1',
			'Be the first to review'                                                        => 'Counter note 72a7',
			'Your review'                                                                   => 'Counter note dd9a',
			'Your rating'                                                                   => 'Xerox register 4e96',
			'Submit'                                                                        => 'Xerox register 823d',
			'Description'                                                                   => 'Xerox register 2d89',
			'Reviews'                                                                       => 'Counter note b25c',
			'Additional information'                                                        => 'Xerox register 7151',
			'View cart'                                                                     => 'Parcel basket 67e3',
			'View Cart'                                                                     => 'Parcel basket 8815',
			'Choose an option'                                                              => 'Xerox register 58fb',
			'Clear'                                                                         => 'Xerox register 50c7',
			'Login'                                                                         => 'Xerox register c956',
			'Log in'                                                                        => 'Xerox register d3ac',
			'Log out'                                                                       => 'Xerox register f03a',
			'Register'                                                                      => 'Xerox register d587',
			'Remember me'                                                                   => 'Xerox register 085c',
			'My account'                                                                    => 'Xerox register e012',
			'My Account'                                                                    => 'Xerox register 8366',
			'Order received'                                                                => 'Parcel record 9776',
			'Thank you. Your order has been received.'                                      => 'Parcel record c246',
			'You may also like&hellip;'                                                     => 'Xerox register 64b3',
			'You may also like…'                                                            => 'Xerox register 93a7',
			'Related products'                                                              => 'Shop-floor find 66e5',
		);
		return isset( $map[ $text ] ) ? $map[ $text ] : $translation;
	},
	20,
	3
);

add_filter(
	'woocommerce_blocks_cart_totals_label',
	static function (): string {
		return __( 'TOTAL', 'xerox' );
	}
);

add_filter(
	'woocommerce_order_button_text',
	static function (): string {
		return __( 'BUY IT', 'xerox' );
	}
);

add_filter(
	'woocommerce_form_field',
	static function ( $field, $key, $args, $value ) {
		if ( false !== strpos( (string) $field, '<abbr class="required"' ) ) {
			$field = preg_replace(
				'#<abbr class="required"[^>]*>\*</abbr>#i',
				'<span class="wo-required-mark" aria-hidden="true">+</span>',
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
// Our default `page.html` uses the theme's 780px `contentSize`, so
// 30% of that is ~234px (a thin floating nav) and 68% is ~530px (a
// still-cramped text column). The result is a vast empty page with
// two drifting columns in the middle — not a brand moment, not even
// usable.
//
// FIX
// ---
// `templates/page-my-account.html` widens the layout to `wideSize`
// (1440px), and the CSS block in theme.json (search for
// `body.woocommerce-account .entry-content>.woocommerce`) replaces
// WC's float layout with a CSS grid: a fixed-width sidebar for the
// nav + a fluid main column for the dashboard content. Then the
// hooks below replace the stock dashboard content with a greeting
// + 3-card quick-link grid so the dashboard tab actually feels
// designed instead of "WC defaults painted on a block theme".
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
// and callouts stay theme-distinct (Obel = quiet/editorial, Xerox =
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
		add_action( 'woocommerce_account_dashboard', 'xerox_render_account_dashboard' );
	},
	20
);

if ( ! function_exists( 'xerox_render_account_dashboard' ) ) {
	/**
	 * Render the Xerox-branded My Account dashboard tab.
	 *
	 * Replaces WC's default 2-paragraph greeting with:
	 *   1. A display-font, all-caps greeting using the customer's
	 *      first name (or login name as a fallback).
	 *   2. A short brutalist lede in the Xerox voice.
	 *   3. A 3-card quick-link grid linking to Orders, Addresses,
	 *      and Account details — the surfaces that justify having
	 *      an account in the first place.
	 *
	 * Markup is hand-written (not block markup) because this fires
	 * inside WC's classic shortcode render where block parsing is
	 * already past. The class names (`wo-account-*`) match the CSS
	 * grid + card rules in theme.json's styles.css block and are
	 * shared verbatim across themes — only the microcopy changes.
	 */
	function xerox_render_account_dashboard(): void {
		$user  = wp_get_current_user();
		$name  = $user && $user->ID ? trim( $user->first_name ) : '';
		if ( '' === $name && $user && $user->ID ) {
			$name = $user->display_name ? $user->display_name : $user->user_login;
		}
		if ( '' === $name ) {
			$name = __( 'friend', 'xerox' );
		}

		$cards = array(
			array(
				'eyebrow' => __( 'LEDGER', 'xerox' ),
				'title'   => __( 'ORDER LOG', 'xerox' ),
				'lede'    => __( 'Track shipments. Reorder the hits.', 'xerox' ),
				'cta'     => __( 'OPEN LEDGER', 'xerox' ),
				'href'    => wc_get_endpoint_url( 'orders', '', wc_get_page_permalink( 'myaccount' ) ),
			),
			array(
				'eyebrow' => __( 'SHIP-TO', 'xerox' ),
				'title'   => __( 'WHERE IT GOES', 'xerox' ),
				'lede'    => __( 'Edit billing and delivery so checkout flies.', 'xerox' ),
				'cta'     => __( 'EDIT THE MAP', 'xerox' ),
				'href'    => wc_get_endpoint_url( 'edit-address', '', wc_get_page_permalink( 'myaccount' ) ),
			),
			array(
				'eyebrow' => __( 'IDENTITY', 'xerox' ),
				'title'   => __( 'THE FILE ON YOU', 'xerox' ),
				'lede'    => __( 'Name, email, password. Keep them current.', 'xerox' ),
				'cta'     => __( 'UPDATE FILE', 'xerox' ),
				'href'    => wc_get_endpoint_url( 'edit-account', '', wc_get_page_permalink( 'myaccount' ) ),
			),
		);
		?>
<div class="wo-account-dashboard">
	<header class="wo-account-greeting">
		<p class="wo-account-greeting__eyebrow"><?php esc_html_e( 'BACK OFFICE', 'xerox' ); ?></p>
		<h2 class="wo-account-greeting__title"><?php
			/* translators: %s: customer's first name. */
			echo esc_html( sprintf( __( 'HEY, %s.', 'xerox' ), $name ) );
		?></h2>
		<p class="wo-account-greeting__lede"><?php esc_html_e( 'Receipts, addresses, the basics. Get in, do the thing, get out.', 'xerox' ); ?></p>
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
// brutalist split. Brand name is hardcoded ('Xerox') rather than
// read from `WO_THEME_NAME` — a real install won't have that
// constant defined.
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
	<p class="wo-account-intro__eyebrow"><?php esc_html_e( 'ID', 'xerox' ); ?></p>
	<h2 class="wo-account-intro__title"><?php esc_html_e( 'WELCOME BACK TO CHONK.', 'xerox' ); ?></h2>
	<p class="wo-account-intro__lede"><?php esc_html_e( 'Sign in to scan the order log, follow a parcel, and get out the door faster next time.', 'xerox' ); ?></p>
	<ul class="wo-account-intro__perks">
		<li><?php esc_html_e( 'TAP-TO-REORDER', 'xerox' ); ?></li>
		<li><?php esc_html_e( 'ADDRESSES ON FILE', 'xerox' ); ?></li>
		<li><?php esc_html_e( 'FIRST DIBS ON DROPS', 'xerox' ); ?></li>
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
		/* translators: %s: contact link wrapping the words "POKE US". */
		esc_html__( "CAN'T GET IN? %s.", 'xerox' ),
		'<a href="' . esc_url( '/contact/' ) . '">' . esc_html__( 'POKE US', 'xerox' ) . '</a>'
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
// Block themes don't expose a per-theme body class on the frontend.
// Hardcoding the slug here (NOT reading WO_THEME_SLUG) is what makes
// the released theme behave identically to the Playground demo on a
// fresh install.
add_filter(
	'body_class',
	static function ( array $classes ): array {
		$classes[] = 'theme-xerox';
		return $classes;
	}
);
// === END body-class ===

// === BEGIN swatches ===
//
// Variation-attribute swatches on the variable PDP. Replaces the
// generic WC `<select>` with brutalist square color/text pills; the
// hidden select stays in the DOM as WC's source of truth and an
// inline JS shim forwards button clicks into its `change` event so
// WC's variation_form.js continues to drive price/stock/image swap.
if ( ! function_exists( 'xerox_swatches_color_map' ) ) {
	function xerox_swatches_color_map(): array {
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

if ( ! function_exists( 'xerox_swatches_render_group' ) ) {
	function xerox_swatches_render_group( string $default_html, array $args ): string {
		$attribute_name = isset( $args['attribute'] ) ? (string) $args['attribute'] : '';
		$options        = isset( $args['options'] ) && is_array( $args['options'] ) ? $args['options'] : array();
		$selected       = isset( $args['selected'] ) ? (string) $args['selected'] : '';

		if ( empty( $options ) || '' === $attribute_name ) {
			return $default_html;
		}

		$attr_label    = ucwords( str_replace( array( 'attribute_', 'pa_', '_', '-' ), array( '', '', ' ', ' ' ), $attribute_name ) );
		// Wrap the native WC <select> in a fixed-size .screen-reader-text
		// box so it stays in the DOM (form submit, a11y) but doesn't
		// render visibly OR contribute to document width. We don't try to
		// rewrite the <select>'s own attrs because WC re-emits class=""
		// later in the tag, which can cause the second occurrence to
		// silently drop our class/style on some HTML parsers and re-leak
		// the 100% table-cell width back into layout.
		// We inject tabindex="-1" on the inner <select> so it's not a tab
		// stop (otherwise axe flags aria-hidden-focus on the wrapper span).
		$select_no_tab = preg_replace( '/<select\\b/', '<select tabindex="-1"', $default_html, 1 );
		$hidden_select = '<span class="screen-reader-text" aria-hidden="true">' . $select_no_tab . '</span>';

		$colors  = xerox_swatches_color_map();
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
		return xerox_swatches_render_group( (string) $html, (array) $args );
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
		// The hidden native <select> lives inside .wo-swatch-wrap, wrapped
		// in <span class="screen-reader-text">. WC emits it with
		// class="" and our PHP does not (cannot) add a stable hook class
		// without fighting WC's own late class="" emit, so we target the
		// only <select> inside this wrap instead -- there is always
		// exactly one, by construction.
		var sel = wrap.querySelector('select');
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
// WC's default "Your cart is currently empty!" + bare "Return to
// shop" link, and the "No products were found matching your
// selection." paragraph, with a brutalist eyebrow + display heading
// + 2-CTA strip.
add_action(
	'woocommerce_cart_is_empty',
	static function (): void {
		if ( is_admin() ) {
			return;
		}
		?>
<div class="wo-empty wo-empty--cart">
	<p class="wo-empty__eyebrow"><?php esc_html_e( 'CART', 'xerox' ); ?></p>
	<h1 class="wo-empty__title"><?php esc_html_e( 'CART: EMPTY.', 'xerox' ); ?></h1>
	<p class="wo-empty__lede"><?php esc_html_e( 'Hit the shop or grab something off the journal.', 'xerox' ); ?></p>
	<p class="wo-empty__ctas">
		<a class="wo-empty__cta wo-empty__cta--primary" href="<?php echo esc_url( '/shop/' ); ?>"><?php esc_html_e( 'BACK TO SHOP', 'xerox' ); ?></a>
		<a class="wo-empty__cta wo-empty__cta--secondary" href="<?php echo esc_url( '/journal/' ); ?>"><?php esc_html_e( 'READ THE JOURNAL', 'xerox' ); ?></a>
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
	<p class="wo-empty__eyebrow"><?php esc_html_e( 'SHOP', 'xerox' ); ?></p>
	<h2 class="wo-empty__title"><?php esc_html_e( 'NOTHING FITS THAT FILTER.', 'xerox' ); ?></h2>
	<p class="wo-empty__lede"><?php esc_html_e( 'Try a different cut, or scan the whole catalogue.', 'xerox' ); ?></p>
	<p class="wo-empty__ctas">
		<a class="wo-empty__cta wo-empty__cta--primary" href="<?php echo esc_url( '/shop/' ); ?>"><?php esc_html_e( 'EVERY PRODUCT', 'xerox' ); ?></a>
		<a class="wo-empty__cta wo-empty__cta--secondary" href="<?php echo esc_url( '/journal/' ); ?>"><?php esc_html_e( 'READ THE JOURNAL', 'xerox' ); ?></a>
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
// Editorial archive header (category / tag / shop). On product
// category and tag archives, prepends a hero strip with the term's
// cover image (sideloaded by playground/wo-configure step 11b) as
// background, term name + description overlaid. On the generic shop
// archive, a leaner H1+lede strip prints instead.
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
				? __( 'RANGE', 'xerox' )
				: __( 'TAG', 'xerox' );
		} elseif ( function_exists( 'is_shop' ) && is_shop() ) {
			$shop_page_id = wc_get_page_id( 'shop' );
			if ( $shop_page_id > 0 ) {
				$cover_url = (string) get_the_post_thumbnail_url( $shop_page_id, 'large' );
				$title     = (string) get_the_title( $shop_page_id );
			}
			if ( '' === $title ) {
				$title = __( 'SHOP', 'xerox' );
			}
			$eyebrow = __( 'SHOP', 'xerox' );
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
// "PAYMENTS" trust strip on cart + checkout. Inline-SVG glyphs
// DOM-injected into the cart-totals + checkout-actions containers
// from wp_footer (the only reliable post-render hook on WC Blocks
// pages). Per-theme: the label text and the brand list are owned
// here so each theme's voice + accepted-payments mix can diverge.
add_action(
	'wp_footer',
	static function (): void {
		if ( is_admin() ) {
			return;
		}
		if ( ! ( function_exists( 'is_cart' ) && ( is_cart() || is_checkout() ) ) ) {
			return;
		}
		$label = esc_js( __( 'PAYMENTS', 'xerox' ) );
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

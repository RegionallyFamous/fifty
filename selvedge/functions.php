<?php
/**
 * Selvedge theme bootstrap.
 *
 * Block-only WooCommerce starter theme. All visual styling lives in
 * theme.json; templates and parts are pure block markup. The only PHP
 * code in the theme is this single after_setup_theme hook.
 *
 * @package Selvedge
 */

declare( strict_types=1 );

add_action(
	'after_setup_theme',
	static function (): void {
		load_theme_textdomain( 'selvedge', get_template_directory() . '/languages' );

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
			'selvedge'          => array(
				'label'       => __( 'Selvedge', 'selvedge' ),
				'description' => __( 'Generic starter patterns. Delete or replace per project.', 'selvedge' ),
			),
			'woo-commerce'  => array(
				'label'       => __( 'Shop', 'selvedge' ),
				'description' => __( 'Patterns for product listings, collections, and shop sections.', 'selvedge' ),
			),
			'featured'      => array(
				'label'       => __( 'Hero', 'selvedge' ),
				'description' => __( 'Full-width hero and banner patterns.', 'selvedge' ),
			),
			'call-to-action' => array(
				'label'       => __( 'Call to action', 'selvedge' ),
				'description' => __( 'Conversion-focused banners and newsletter signups.', 'selvedge' ),
			),
			'testimonials'  => array(
				'label'       => __( 'Testimonials', 'selvedge' ),
				'description' => __( 'Social proof and customer quote patterns.', 'selvedge' ),
			),
			'footer'        => array(
				'label'       => __( 'Footer', 'selvedge' ),
				'description' => __( 'Footer layout patterns.', 'selvedge' ),
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
 * Selvedge is dark editorial; "Reduced" reads as a price tag at a quiet
 * boutique rather than a flash sale shout. The pill styling itself lives in
 * theme.json -> styles.css.
 */
add_filter(
	'woocommerce_sale_flash',
	static function (): string {
		return '<span class="onsale">' . esc_html__( 'Reduced', 'selvedge' ) . '</span>';
	}
);

/**
 * Shop-by-category cover tiles get the first product's featured image.
 *
 * Why this filter exists
 * ----------------------
 * `wp:terms-query` doesn't ship a "term thumbnail" core block, and
 * WC's `product_cat` taxonomy ships an empty `thumbnail_id` term-meta
 * for every category created by a CSV import (`wo-import.php` doesn't
 * sideload category art -- only product art). So the front-page
 * "Shop by Category" terms-query renders a `wp:cover` block with no
 * image source and the cover paints the contrast color flat -- a giant
 * brown box with the term name floating in it. Two failure modes
 * compound: (a) no image, and (b) the cover's `aspect-ratio:portrait`
 * makes each tile occupy a 4:5 slice of the column, so any responsive
 * stacking turns it into a viewport-tall block.
 *
 * The fix here is content-driven: pick the first published product in
 * the category that has a featured image, and inject that image into
 * the cover as `<img class="wp-block-cover__image-background">` (the
 * exact element WP emits for cover blocks given a `url` attribute).
 * That keeps the cover's overlay + dim + content positioning exactly
 * as the editor configured them; we're only filling in the missing
 * background image.
 *
 * Marker className
 * ----------------
 * The filter only fires on `core/cover` blocks whose className includes
 * `selvedge-cat-cover`. Without the marker we'd touch every cover on
 * the site and waste a `wc_get_products` call per render.
 *
 * Caching
 * -------
 * One `wc_get_products(['category'=>$slug,'limit'=>1])` per render.
 * That's 5 queries on the front page (one per category tile) and zero
 * elsewhere. WP object cache hits subsequent renders during the same
 * request. Not memoizing across requests because the "first product"
 * legitimately changes when the catalogue is edited and the cost is
 * trivial. If perf ever becomes a concern, wrap the lookup in a
 * `wp_cache_get` keyed on `selvedge:cat-img:<term_id>` with a short
 * TTL.
 *
 * Failure modes (handled silently)
 * --------------------------------
 *   * No termId in context (the cover wasn't actually inside a
 *     term-template) -> return original markup unchanged.
 *   * Term has zero products / no published products with images ->
 *     return original markup; the cover paints the contrast color
 *     (the original behaviour, but now an explicit fallback rather
 *     than the default state).
 *   * WC isn't active -> return original markup. The check.py gate
 *     guarantees WC is present in every theme that ships this code,
 *     but the runtime guard is cheap insurance for non-Playground
 *     installs.
 */
add_filter(
	'render_block',
	static function ( string $block_content, array $block, WP_Block $instance ): string {
		if ( 'core/cover' !== ( $block['blockName'] ?? '' ) ) {
			return $block_content;
		}
		$class_name = (string) ( $block['attrs']['className'] ?? '' );
		if ( false === strpos( $class_name, 'selvedge-cat-cover' ) ) {
			return $block_content;
		}
		$term_id = (int) ( $instance->context['termId'] ?? 0 );
		if ( ! $term_id || ! function_exists( 'wc_get_products' ) ) {
			return $block_content;
		}
		$term = get_term( $term_id, 'product_cat' );
		if ( ! $term || is_wp_error( $term ) ) {
			return $block_content;
		}

		// First, honour an explicit category thumbnail if WC ever
		// gets one set (some themes / importers do attach term meta).
		$image_id  = (int) get_term_meta( $term_id, 'thumbnail_id', true );
		$image_url = $image_id ? wp_get_attachment_image_url( $image_id, 'large' ) : '';

		// Fallback: pull the first product in the category that has
		// a featured image. WC's `product_cat` IDs and the underlying
		// term IDs are the same, so we can pass the term_id directly.
		if ( ! $image_url ) {
			$products = wc_get_products(
				array(
					'category' => array( $term->slug ),
					'status'   => 'publish',
					'limit'    => 5,
					'orderby'  => 'date',
					'order'    => 'DESC',
					'return'   => 'ids',
				)
			);
			foreach ( (array) $products as $pid ) {
				$tid = get_post_thumbnail_id( $pid );
				if ( $tid ) {
					$image_url = wp_get_attachment_image_url( $tid, 'large' );
					if ( $image_url ) {
						break;
					}
				}
			}
		}

		if ( ! $image_url ) {
			return $block_content;
		}

		// Inject `<img class="wp-block-cover__image-background">` as
		// the first child of `.wp-block-cover` -- exactly where core
		// puts it when the cover block has a `url` attribute. The
		// dim-overlay span and inner-container come AFTER the img,
		// which lets the existing CSS layering paint the dim on top
		// of the photo and the term-name + count on top of both.
		$img = sprintf(
			'<img class="wp-block-cover__image-background selvedge-cat-cover__img" alt="%s" src="%s" loading="lazy" decoding="async" />',
			esc_attr( $term->name ),
			esc_url( $image_url )
		);

		// Splice the img right after the opening <div class="wp-block-cover ...">.
		// Using a simple regex against the cover's leading tag is
		// safe here because the block's render output always starts
		// with that single <div ...> (see core/cover/render.php).
		$updated = preg_replace(
			'/(<div\s+class="[^"]*wp-block-cover[^"]*"[^>]*>)/',
			'$1' . $img,
			$block_content,
			1
		);
		return is_string( $updated ) ? $updated : $block_content;
	},
	10,
	3
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

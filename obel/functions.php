<?php
/**
 * Obel theme bootstrap.
 *
 * Block-only WooCommerce starter theme. All visual styling lives in
 * theme.json; templates and parts are pure block markup. The only PHP
 * code in the theme is this single after_setup_theme hook.
 *
 * @package Obel
 */

declare( strict_types=1 );

add_action(
	'after_setup_theme',
	static function (): void {
		load_theme_textdomain( 'obel', get_template_directory() . '/languages' );

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
			'obel'          => array(
				'label'       => __( 'Obel', 'obel' ),
				'description' => __( 'Generic starter patterns. Delete or replace per project.', 'obel' ),
			),
			'woo-commerce'  => array(
				'label'       => __( 'Shop', 'obel' ),
				'description' => __( 'Patterns for product listings, collections, and shop sections.', 'obel' ),
			),
			'featured'      => array(
				'label'       => __( 'Hero', 'obel' ),
				'description' => __( 'Full-width hero and banner patterns.', 'obel' ),
			),
			'call-to-action' => array(
				'label'       => __( 'Call to action', 'obel' ),
				'description' => __( 'Conversion-focused banners and newsletter signups.', 'obel' ),
			),
			'testimonials'  => array(
				'label'       => __( 'Testimonials', 'obel' ),
				'description' => __( 'Social proof and customer quote patterns.', 'obel' ),
			),
			'footer'        => array(
				'label'       => __( 'Footer', 'obel' ),
				'description' => __( 'Footer layout patterns.', 'obel' ),
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
 * The exclamation point and the literal word "Sale!" are an immediate "this
 * is a stock WooCommerce store" tell. The wrapper styling lives in
 * theme.json -> styles.css (`.products li.product .onsale, span.onsale`),
 * which already turns the badge into an editorial uppercase pill; here we
 * just swap the copy so each theme has its own brand voice.
 */
add_filter(
	'woocommerce_sale_flash',
	static function (): string {
		return '<span class="onsale">' . esc_html__( 'On sale', 'obel' ) . '</span>';
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

		$vt_name   = sprintf( 'fifty-post-%d-%s', $post_id, $kind );
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

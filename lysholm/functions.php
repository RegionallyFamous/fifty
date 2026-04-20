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

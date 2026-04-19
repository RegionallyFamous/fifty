<?php
/**
 * Chonk theme bootstrap.
 *
 * Block-only WooCommerce starter theme. All visual styling lives in
 * theme.json; templates and parts are pure block markup. The only PHP
 * code in the theme is this single after_setup_theme hook.
 *
 * @package Chonk
 */

declare( strict_types=1 );

add_action(
	'after_setup_theme',
	static function (): void {
		load_theme_textdomain( 'chonk', get_template_directory() . '/languages' );

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
			'chonk'          => array(
				'label'       => __( 'Chonk', 'chonk' ),
				'description' => __( 'Generic starter patterns. Delete or replace per project.', 'chonk' ),
			),
			'woo-commerce'  => array(
				'label'       => __( 'Shop', 'chonk' ),
				'description' => __( 'Patterns for product listings, collections, and shop sections.', 'chonk' ),
			),
			'featured'      => array(
				'label'       => __( 'Hero', 'chonk' ),
				'description' => __( 'Full-width hero and banner patterns.', 'chonk' ),
			),
			'call-to-action' => array(
				'label'       => __( 'Call to action', 'chonk' ),
				'description' => __( 'Conversion-focused banners and newsletter signups.', 'chonk' ),
			),
			'testimonials'  => array(
				'label'       => __( 'Testimonials', 'chonk' ),
				'description' => __( 'Social proof and customer quote patterns.', 'chonk' ),
			),
			'footer'        => array(
				'label'       => __( 'Footer', 'chonk' ),
				'description' => __( 'Footer layout patterns.', 'chonk' ),
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

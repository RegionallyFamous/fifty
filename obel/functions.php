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

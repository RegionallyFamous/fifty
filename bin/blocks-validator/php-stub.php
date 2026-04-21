<?php
/**
 * Pattern-rendering stub for the blocks validator.
 *
 * Patterns rely on a tiny pocket of WordPress globals — translation helpers,
 * `wp_json_encode()`, a few `*_url()` functions. We provide minimal versions
 * so each `patterns/*.php` file can be `include`d in a vanilla PHP CLI run
 * and produce the same HTML/block-comment markup the editor would receive.
 *
 * Usage: php php-stub.php <path/to/pattern.php>
 *   stdout = rendered pattern markup
 */

if ( $argc < 2 ) {
	fwrite( STDERR, "Usage: php php-stub.php <pattern.php>\n" );
	exit( 2 );
}

function __( $s, $domain = '' ) { return $s; }
function _e( $s, $domain = '' ) { echo $s; }
function _x( $s, $context = '', $domain = '' ) { return $s; }
function _ex( $s, $context = '', $domain = '' ) { echo $s; }
function _n( $s, $p, $n, $domain = '' ) { return $n === 1 ? $s : $p; }
function _nx( $s, $p, $n, $context = '', $domain = '' ) { return $n === 1 ? $s : $p; }
function esc_html__( $s, $domain = '' ) { return htmlspecialchars( $s, ENT_QUOTES, 'UTF-8' ); }
function esc_html_e( $s, $domain = '' ) { echo htmlspecialchars( $s, ENT_QUOTES, 'UTF-8' ); }
function esc_html_x( $s, $context = '', $domain = '' ) { return htmlspecialchars( $s, ENT_QUOTES, 'UTF-8' ); }
function esc_attr__( $s, $domain = '' ) { return htmlspecialchars( $s, ENT_QUOTES, 'UTF-8' ); }
function esc_attr_e( $s, $domain = '' ) { echo htmlspecialchars( $s, ENT_QUOTES, 'UTF-8' ); }
function esc_attr_x( $s, $context = '', $domain = '' ) { return htmlspecialchars( $s, ENT_QUOTES, 'UTF-8' ); }
function esc_html( $s ) { return htmlspecialchars( $s, ENT_QUOTES, 'UTF-8' ); }
function esc_attr( $s ) { return htmlspecialchars( $s, ENT_QUOTES, 'UTF-8' ); }
function esc_url( $s ) { return $s; }
function esc_url_raw( $s ) { return $s; }
function wp_json_encode( $v, $options = 0, $depth = 512 ) {
	return json_encode( $v, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | $options, $depth );
}
function get_template_directory_uri() { return ''; }
function get_stylesheet_directory_uri() { return ''; }
function get_template_directory() { return ''; }
function get_stylesheet_directory() { return ''; }
function get_theme_file_uri( $f = '' ) { return $f; }
function get_theme_file_path( $f = '' ) { return $f; }
function get_parent_theme_file_uri( $f = '' ) { return $f; }
function get_parent_theme_file_path( $f = '' ) { return $f; }
function includes_url( $p = '' ) { return $p; }
function content_url( $p = '' ) { return $p; }
function home_url( $p = '' ) { return $p; }
function site_url( $p = '' ) { return $p; }
function admin_url( $p = '' ) { return $p; }
function plugins_url( $p = '' ) { return $p; }
function rest_url( $p = '' ) { return '/wp-json/' . ltrim( $p, '/' ); }
function get_bloginfo( $k = '' ) { return ''; }
function bloginfo( $k = '' ) { echo ''; }
function wp_get_attachment_image( $id, $size = 'thumbnail', $icon = false, $attr = '' ) { return ''; }
function wp_get_attachment_image_url( $id, $size = 'thumbnail' ) { return ''; }
function wp_get_attachment_url( $id ) { return ''; }
function wp_kses_post( $s ) { return $s; }
function wp_strip_all_tags( $s ) { return strip_tags( $s ); }
function wp_unique_id( $prefix = '' ) {
	static $n = 0;
	return $prefix . ( ++$n );
}
function get_locale() { return 'en_US'; }
function is_rtl() { return false; }
function apply_filters( $hook, $value ) { return $value; }
function do_action( $hook ) {}

ob_start();
include $argv[1];
echo ob_get_clean();

<?php
/**
 * Title: Hero, text only
 * Slug: agave/hero-text
 * Categories: agave, featured
 * Block Types: core/post-content
 * Description: Centered text-only hero with headline, subhead, and CTA. Use when imagery would distract.
 * Keywords: hero, banner, header
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","backgroundColor":"accent-soft","style":{"spacing":{"padding":{"top":"var:preset|spacing|3-xl","bottom":"var:preset|spacing|3-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull has-accent-soft-background-color has-background" style="padding-top:var(--wp--preset--spacing--3-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--3-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:paragraph {"align":"center","fontSize":"xs","style":{"typography":{"letterSpacing":"var:custom|letter-spacing|wider","textTransform":"uppercase"}},"textColor":"tertiary"} -->
	<p class="has-text-align-center has-tertiary-color has-text-color has-xs-font-size" style="letter-spacing:var(--wp--custom--letter-spacing--wider);text-transform:uppercase"><?php esc_html_e( 'Fresh arrivals', 'agave' ); ?></p>
	<!-- /wp:paragraph -->

	<!-- wp:heading {"level":1,"textAlign":"center","fontSize":"4xl"} -->
	<h1 class="wp-block-heading has-text-align-center has-4-xl-font-size"><?php esc_html_e( 'A sun-warmed, considered headline.', 'agave' ); ?></h1>
	<!-- /wp:heading -->

	<!-- wp:paragraph {"align":"center","fontSize":"md","style":{"spacing":{"margin":{"top":"var:preset|spacing|md","bottom":"var:preset|spacing|lg"}}},"textColor":"secondary"} -->
	<p class="has-text-align-center has-secondary-color has-text-color has-md-font-size" style="margin-top:var(--wp--preset--spacing--md);margin-bottom:var(--wp--preset--spacing--lg)"><?php esc_html_e( 'One honest line that earns the next step.', 'agave' ); ?></p>
	<!-- /wp:paragraph -->

	<!-- wp:buttons {"layout":{"type":"flex","justifyContent":"center"}} -->
	<div class="wp-block-buttons">
		<!-- wp:button -->
		<div class="wp-block-button"><a class="wp-block-button__link wp-element-button"><?php esc_html_e( 'Shop now', 'agave' ); ?></a></div>
		<!-- /wp:button -->
	</div>
	<!-- /wp:buttons -->
</div>
<!-- /wp:group -->

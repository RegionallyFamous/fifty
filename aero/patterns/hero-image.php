<?php
/**
 * Title: Hero with image background
 * Slug: aero/hero-image
 * Categories: aero, featured
 * Block Types: core/post-content
 * Description: Full-width cover image with headline, subhead, and primary CTA. Replace the placeholder image.
 * Keywords: hero, banner, header, cover
 * Viewport Width: 1280
 */
?>
<!-- wp:cover {"minHeight":640,"minHeightUnit":"px","overlayColor":"contrast","dimRatio":40,"contentPosition":"center center","align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|3-xl","bottom":"var:preset|spacing|3-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}}} -->
<div class="wp-block-cover alignfull" style="padding-top:var(--wp--preset--spacing--3-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--3-xl);padding-left:var(--wp--preset--spacing--lg);min-height:640px"><span aria-hidden="true" class="wp-block-cover__background has-contrast-background-color has-background-dim-40 has-background-dim"></span><div class="wp-block-cover__inner-container">
	<!-- wp:group {"layout":{"type":"constrained"}} -->
	<div class="wp-block-group">
		<!-- wp:heading {"level":1,"textAlign":"center","textColor":"base","fontSize":"5xl"} -->
		<h1 class="wp-block-heading has-text-align-center has-base-color has-text-color has-5-xl-font-size"><?php esc_html_e( 'Holographic, on purpose.', 'aero' ); ?></h1>
		<!-- /wp:heading -->

		<!-- wp:paragraph {"align":"center","textColor":"base","fontSize":"md","style":{"spacing":{"margin":{"top":"var:preset|spacing|md","bottom":"var:preset|spacing|lg"}},"typography":{"lineHeight":"var(--wp--custom--line-height--normal)"}}} -->
		<p class="has-text-align-center has-base-color has-text-color has-md-font-size" style="margin-top:var(--wp--preset--spacing--md);margin-bottom:var(--wp--preset--spacing--lg);line-height:var(--wp--custom--line-height--normal)"><?php esc_html_e( 'A small studio for soft-future objects — the kind that catch the light, the eye, and occasionally the conversation.', 'aero' ); ?></p>
		<!-- /wp:paragraph -->

		<!-- wp:buttons {"layout":{"type":"flex","justifyContent":"center"}} -->
		<div class="wp-block-buttons">
			<!-- wp:button -->
			<div class="wp-block-button"><a class="wp-block-button__link wp-element-button"><?php esc_html_e( 'Browse the collection ✦', 'aero' ); ?></a></div>
			<!-- /wp:button -->

			<!-- wp:button {"className":"is-style-outline","textColor":"base"} -->
			<div class="wp-block-button is-style-outline"><a class="wp-block-button__link has-base-color has-text-color wp-element-button"><?php esc_html_e( 'Read the journal', 'aero' ); ?></a></div>
			<!-- /wp:button -->
		</div>
		<!-- /wp:buttons -->
	</div>
	<!-- /wp:group -->
</div></div>
<!-- /wp:cover -->

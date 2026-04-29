<?php
/**
 * Title: Call-to-action banner
 * Slug: apiary/cta-banner
 * Categories: apiary, call-to-action
 * Block Types: core/post-content
 * Description: Full-width banner with a single headline and primary CTA. Use to push toward a single conversion goal.
 * Keywords: cta, banner, conversion, button
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","backgroundColor":"accent-soft","style":{"spacing":{"padding":{"top":"var:preset|spacing|xl","bottom":"var:preset|spacing|xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull has-accent-soft-background-color has-background" style="padding-top:var(--wp--preset--spacing--xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:group {"align":"wide","layout":{"type":"flex","flexWrap":"wrap","justifyContent":"space-between","verticalAlignment":"center"}} -->
	<div class="wp-block-group alignwide">
		<!-- wp:heading {"level":3,"fontSize":"xl"} -->
		<h3 class="wp-block-heading has-xl-font-size"><?php esc_html_e( 'Apiary parcel-room copy 381c22', 'apiary' ); ?></h3>
		<!-- /wp:heading -->

		<!-- wp:buttons -->
		<div class="wp-block-buttons">
			<!-- wp:button -->
			<div class="wp-block-button"><a class="wp-block-button__link wp-element-button"><?php esc_html_e( 'Apiary counter bf70cf', 'apiary' ); ?></a></div>
			<!-- /wp:button -->
		</div>
		<!-- /wp:buttons -->
	</div>
	<!-- /wp:group -->
</div>
<!-- /wp:group -->

<?php
/**
 * Title: Value propositions, three columns
 * Slug: agave/value-props
 * Categories: agave
 * Block Types: core/post-content
 * Description: Three-column row of short value statements. Replace the headlines with your shop's shipping, returns, and guarantee promises.
 * Keywords: value, USP, benefits, features, columns
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","backgroundColor":"subtle","style":{"spacing":{"padding":{"top":"var:preset|spacing|xl","bottom":"var:preset|spacing|xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull has-subtle-background-color has-background" style="padding-top:var(--wp--preset--spacing--xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:columns {"align":"wide"} -->
	<div class="wp-block-columns alignwide">
		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":3,"fontSize":"lg"} -->
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'Carriage, on us', 'agave' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'Every parcel over $50 travels free, wherever in the country it needs to go.', 'agave' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":3,"fontSize":"lg"} -->
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'Thirty-day regrets', 'agave' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'If a specimen did not settle, send it home — no explanation required.', 'agave' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":3,"fontSize":"lg"} -->
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'Chosen to keep', 'agave' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'Materials chosen for the long herbarium, not the next replacement cycle.', 'agave' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->
</div>
<!-- /wp:group -->

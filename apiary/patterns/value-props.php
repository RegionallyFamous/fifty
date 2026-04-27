<?php
/**
 * Title: Value propositions, three columns
 * Slug: apiary/value-props
 * Categories: apiary
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
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'Shipping on every batch over $50', 'apiary' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'Shipping is on us over $50. Every batch travels wrapped in wool and kraft, sealed with a paper-bee sticker.', 'apiary' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":3,"fontSize":"lg"} -->
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'Replacements by the next batch', 'apiary' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'Every jar carries its batch number, forage log, and the date it left the comb. If a jar ever turns up sour, write and we\'ll replace it from the next batch.', 'apiary' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":3,"fontSize":"lg"} -->
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'Traceable by the jar', 'apiary' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'Honeycomb, beeswax, untreated pine lids — chosen because they age down into the pantry like they were always there.', 'apiary' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->
</div>
<!-- /wp:group -->

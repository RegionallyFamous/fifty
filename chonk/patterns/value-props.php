<?php
/**
 * Title: Value propositions, three columns
 * Slug: chonk/value-props
 * Categories: chonk
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
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'FREE SHIPPING', 'chonk' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'Free over $50, anywhere in the lower 48. Boxed heavy, taped twice.', 'chonk' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":3,"fontSize":"lg"} -->
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( '30-DAY RETURNS', 'chonk' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'Send it back inside 30 days. Free, fast, no awkward questionnaire.', 'chonk' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":3,"fontSize":"lg"} -->
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'MADE TO LAST', 'chonk' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'Built from materials we\'d put in our own kitchens. Outlives the trend cycle on principle.', 'chonk' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->
</div>
<!-- /wp:group -->

<?php
/**
 * Title: Value propositions, three columns
 * Slug: azulejo/value-props
 * Categories: azulejo
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
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'Carriage from the oficina', 'azulejo' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'On commissions above fifty, carriage is folded into the price and the parcel leaves the oficina wrapped in tissue, pine shavings and a jute tie.', 'azulejo' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":3,"fontSize":"lg"} -->
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'Thirty days to unhang', 'azulejo' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'If the pattern does not find its place in the room, return it unhung within thirty days and the atelier will cover the carriage and see it placed in a home that suits it better.', 'azulejo' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:heading {"level":3,"fontSize":"lg"} -->
			<h3 class="wp-block-heading has-lg-font-size"><?php esc_html_e( 'Painted to last a century', 'azulejo' ); ?></h3>
			<!-- /wp:heading -->
			<!-- wp:paragraph {"textColor":"secondary"} -->
			<p class="has-secondary-color has-text-color"><?php esc_html_e( 'Cobalt oxide, tin glaze, and a kiln fired on Tuesdays: the pattern on the wall in 2126 will be the pattern you hang this afternoon, dulled only by the morning light that crosses it.', 'azulejo' ); ?></p>
			<!-- /wp:paragraph -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->
</div>
<!-- /wp:group -->

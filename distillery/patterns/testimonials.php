<?php
/**
 * Title: Customer testimonials
 * Slug: distillery/testimonials
 * Categories: distillery, testimonials
 * Block Types: core/post-content
 * Description: Three short customer quotes with attribution. Replace with your own.
 * Keywords: testimonials, reviews, social proof, quotes
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:heading {"textAlign":"center"} -->
	<h2 class="wp-block-heading has-text-align-center"><?php esc_html_e( 'Notes from our patrons', 'distillery' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:columns {"align":"wide","style":{"spacing":{"margin":{"top":"var:preset|spacing|xl"}}}} -->
	<div class="wp-block-columns alignwide" style="margin-top:var(--wp--preset--spacing--xl)">
		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:group {"className":"is-style-panel","style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
			<div class="wp-block-group is-style-panel">
				<!-- wp:quote -->
				<blockquote class="wp-block-quote">
					<!-- wp:paragraph -->
					<p><?php esc_html_e( 'The quality matched every word on the label. I shall return without hesitation.', 'distillery' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Alex M.', 'distillery' ); ?></cite>
				</blockquote>
				<!-- /wp:quote -->
			</div>
			<!-- /wp:group -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:group {"className":"is-style-panel","style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
			<div class="wp-block-group is-style-panel">
				<!-- wp:quote -->
				<blockquote class="wp-block-quote">
					<!-- wp:paragraph -->
					<p><?php esc_html_e( 'Dispatched promptly and arrived dressed impeccably. Every detail attended to.', 'distillery' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Sam P.', 'distillery' ); ?></cite>
				</blockquote>
				<!-- /wp:quote -->
			</div>
			<!-- /wp:group -->
		</div>
		<!-- /wp:column -->

		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:group {"className":"is-style-panel","style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
			<div class="wp-block-group is-style-panel">
				<!-- wp:quote -->
				<blockquote class="wp-block-quote">
					<!-- wp:paragraph -->
					<p><?php esc_html_e( 'Twelve months in my possession and it shows not a mark. A testament to the craft.', 'distillery' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Jordan K.', 'distillery' ); ?></cite>
				</blockquote>
				<!-- /wp:quote -->
			</div>
			<!-- /wp:group -->
		</div>
		<!-- /wp:column -->
	</div>
	<!-- /wp:columns -->
</div>
<!-- /wp:group -->

<?php
/**
 * Title: Customer testimonials
 * Slug: atomic/testimonials
 * Categories: atomic, testimonials
 * Block Types: core/post-content
 * Description: Three short customer quotes with attribution. Replace with your own.
 * Keywords: testimonials, reviews, social proof, quotes
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:heading {"textAlign":"center"} -->
	<h2 class="wp-block-heading has-text-align-center"><?php esc_html_e( 'Transmissions from the deck', 'atomic' ); ?></h2>
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
					<p><?php esc_html_e( 'The capsule arrived on a grey Tuesday &mdash; suddenly the Tuesday was not grey.', 'atomic' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Alex M.', 'atomic' ); ?></cite>
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
					<p><?php esc_html_e( 'Launch was on time, payload packed with care, gold capsule unbroken.', 'atomic' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Sam P.', 'atomic' ); ?></cite>
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
					<p><?php esc_html_e( 'Three years on the console, still reads like it left the pad this morning.', 'atomic' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Jordan K.', 'atomic' ); ?></cite>
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

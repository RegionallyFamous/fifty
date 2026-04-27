<?php
/**
 * Title: Customer testimonials
 * Slug: agave/testimonials
 * Categories: agave, testimonials
 * Block Types: core/post-content
 * Description: Three short customer quotes with attribution. Replace with your own.
 * Keywords: testimonials, reviews, social proof, quotes
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:heading {"textAlign":"center"} -->
	<h2 class="wp-block-heading has-text-align-center"><?php esc_html_e( 'What people say', 'agave' ); ?></h2>
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
					<p><?php esc_html_e( 'Exactly what I hoped for. Already back for more.', 'agave' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Alex M.', 'agave' ); ?></cite>
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
					<p><?php esc_html_e( 'Arrived quickly and packed with genuine care.', 'agave' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Sam P.', 'agave' ); ?></cite>
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
					<p><?php esc_html_e( 'A year in and it still looks as good as the day it arrived.', 'agave' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Jordan K.', 'agave' ); ?></cite>
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

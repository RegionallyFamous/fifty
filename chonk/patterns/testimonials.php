<?php
/**
 * Title: Customer testimonials
 * Slug: chonk/testimonials
 * Categories: chonk, testimonials
 * Block Types: core/post-content
 * Description: Three short customer quotes with attribution. Replace with your own.
 * Keywords: testimonials, reviews, social proof, quotes
 * Viewport Width: 1280
 */
?>
<!-- wp:group {"align":"full","style":{"spacing":{"padding":{"top":"var:preset|spacing|2-xl","bottom":"var:preset|spacing|2-xl","left":"var:preset|spacing|lg","right":"var:preset|spacing|lg"}}},"layout":{"type":"constrained"}} -->
<div class="wp-block-group alignfull" style="padding-top:var(--wp--preset--spacing--2-xl);padding-right:var(--wp--preset--spacing--lg);padding-bottom:var(--wp--preset--spacing--2-xl);padding-left:var(--wp--preset--spacing--lg)">
	<!-- wp:heading {"textAlign":"center"} -->
	<h2 class="wp-block-heading has-text-align-center"><?php esc_html_e( 'WHAT FOLKS SAY', 'chonk' ); ?></h2>
	<!-- /wp:heading -->

	<!-- wp:columns {"align":"wide","style":{"spacing":{"margin":{"top":"var:preset|spacing|xl"}}}} -->
	<div class="wp-block-columns alignwide" style="margin-top:var(--wp--preset--spacing--xl)">
		<!-- wp:column -->
		<div class="wp-block-column">
			<!-- wp:group {"className":"is-style-panel","style":{"spacing":{"blockGap":"var:preset|spacing|sm"}}} -->
			<div class="wp-block-group is-style-panel">
				<!-- wp:quote <?php echo wp_json_encode( array( 'citation' => __( 'Alex M.', 'chonk' ) ) ); ?> -->
				<blockquote class="wp-block-quote">
					<!-- wp:paragraph -->
					<p><?php esc_html_e( 'Heavier than I expected. In the best way. Already eyeing my next one.', 'chonk' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Alex M.', 'chonk' ); ?></cite>
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
				<!-- wp:quote <?php echo wp_json_encode( array( 'citation' => __( 'Sam P.', 'chonk' ) ) ); ?> -->
				<blockquote class="wp-block-quote">
					<!-- wp:paragraph -->
					<p><?php esc_html_e( 'Box arrived in two days, wrapped like a piece of industrial equipment. Solid.', 'chonk' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Sam P.', 'chonk' ); ?></cite>
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
				<!-- wp:quote <?php echo wp_json_encode( array( 'citation' => __( 'Jordan K.', 'chonk' ) ) ); ?> -->
				<blockquote class="wp-block-quote">
					<!-- wp:paragraph -->
					<p><?php esc_html_e( 'A year of daily abuse and the thing still looks like the day I unboxed it.', 'chonk' ); ?></p>
					<!-- /wp:paragraph -->
					<cite><?php esc_html_e( 'Jordan K.', 'chonk' ); ?></cite>
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
